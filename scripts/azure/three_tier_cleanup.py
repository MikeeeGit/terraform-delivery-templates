#!/usr/bin/env python3
"""Remove Kubernetes services and retire the backend for the disposable Azure profile.

Use alongside three_tier_teardown.py. Every write requires --execute; read-only
service inventory is the default. Real settings, states and reports stay private.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.parse
import three_tier_teardown as tf

def command(args, env, *, cwd=None, allowed=(0,)):
    result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tf.require(result.returncode in allowed, "Command failed: " + " ".join(args[:3]) + "; inspect the selected target and credentials")
    return result.stdout

def data(args, env, **kwargs):
    return json.loads(command(args, env, **kwargs))

def kube_context(receipt, output, proxy):
    target = receipt["target"]
    tf.require(target["subscription_id"] == tf.SUBSCRIPTION and target["environment"] == "pprd"
               and target["region"] == "uks" and target["slot"] in ("aks01", "aks02")
               and target["resource_group"] == "uks-pprd-akslab-aks-rg"
               and target["cluster_name"] == "uks-pprd-akslab-" + target["slot"]
               and target["namespace"] == "platform-demo", "Receipt escapes the isolated disposable profile")
    env = tf.child_environment(output)
    cluster = data(["az", "aks", "show", "--subscription", tf.SUBSCRIPTION,
                    "--resource-group", target["resource_group"], "--name", target["cluster_name"], "-o", "json"], env)
    expected = f"/subscriptions/{tf.SUBSCRIPTION}/resourceGroups/{target['resource_group']}/providers/Microsoft.ContainerService/managedClusters/{target['cluster_name']}"
    tf.require(cluster["id"].lower() == expected.lower()
               and cluster.get("disableLocalAccounts") is True
               and cluster.get("apiServerAccessProfile", {}).get("enablePrivateCluster") is True,
               "Expected this trial's private AKS cluster with local accounts disabled")
    kubeconfig = output / "kubeconfig"
    command(["az", "aks", "get-credentials", "--subscription", tf.SUBSCRIPTION,
             "--resource-group", target["resource_group"], "--name", target["cluster_name"],
             "--file", str(kubeconfig), "--format", "exec"], env)
    kubeconfig.chmod(0o600)
    command(["kubelogin", "convert-kubeconfig", "--login", "azurecli", "--kubeconfig", str(kubeconfig)], env)
    base = ["kubectl", "--kubeconfig", str(kubeconfig), "--request-timeout=30s"]
    if proxy:
        url = urllib.parse.urlsplit(proxy)
        tf.require(url.scheme == "socks5" and url.hostname in ("127.0.0.1", "::1")
                   and url.port and not url.username and not url.password and not url.path
                   and not url.query and not url.fragment, "Use only an explicit loopback SOCKS5 tunnel")
        names = data(base + ["config", "view", "-o", "json"], env)["clusters"]
        tf.require(len(names) == 1, "Expected one isolated Kubernetes context")
        command(base + ["config", "set-cluster", names[0]["name"], "--proxy-url", proxy], env)
    user = data(base + ["auth", "whoami", "-o", "json"], env)["status"]["userInfo"]
    tf.require(tf.PROTECTED_ADMIN_GROUP in user.get("groups", []),
               "The retained cleanup operator must belong to the configured existing administrator group")
    return target, cluster, kubeconfig, base, env

def validate_bundle(bundle):
    import yaml
    receipt = json.loads(tf.regular(bundle / "release.json"))
    manifest = tf.regular(bundle / "manifest.yaml")
    tf.require(hashlib.sha256(manifest).hexdigest() == receipt["manifest_sha256"], "Application manifest digest mismatch")
    objects = [x for x in yaml.safe_load_all(manifest) if x]
    allowed = {"Deployment", "Service", "ServiceAccount", "ConfigMap", "HorizontalPodAutoscaler",
               "PodDisruptionBudget", "NetworkPolicy", "HTTPRoute", "SecretProviderClass"}
    tf.require(objects and all(isinstance(x, dict) and x.get("kind") in allowed
               and x.get("metadata", {}).get("namespace") == "platform-demo"
               and re.fullmatch(r"platform-demo(?:-[a-z0-9-]+)?", x["metadata"].get("name", ""))
               for x in objects), "Bundle contains unexpected cleanup objects")
    return receipt, objects

def services(bundle, output, proxy, execute):
    receipt, objects = validate_bundle(bundle)
    tf.create_output(output)
    target, cluster, kubeconfig, base, env = kube_context(receipt, output, proxy)
    gateway = target["verification"]["ingress"]["gateway"]
    tf.require(gateway == "platform-demo-private", "Unexpected Gateway ownership")
    def owned_services():
        all_services = data(base + ["get", "services", "--all-namespaces", "-o", "json"], env)["items"]
        return [x for x in all_services
                if x["metadata"].get("labels", {}).get("gateway.envoyproxy.io/owning-gateway-name") == gateway
                and x["metadata"].get("labels", {}).get("gateway.envoyproxy.io/owning-gateway-namespace") == target["namespace"]]
    before = owned_services()
    addresses = sorted({x["ip"] for svc in before for x in svc.get("status", {}).get("loadBalancer", {}).get("ingress", []) if "ip" in x})
    inventory = {"slot": target["slot"], "cluster_id": cluster["id"], "node_resource_group": cluster["nodeResourceGroup"],
                 "source_commit": receipt["source_commit"], "manifest_sha256": receipt["manifest_sha256"],
                 "objects": [{"kind": x["kind"], "name": x["metadata"]["name"]} for x in objects],
                 "gateway": gateway, "services": [{"namespace": x["metadata"]["namespace"], "name": x["metadata"]["name"]} for x in before],
                 "frontend_addresses": addresses, "resource_apply_performed": False}
    tf.write_private(output / "inventory.json", json.dumps(inventory, indent=2))
    if not execute:
        print(json.dumps({"status": "inventory-only", "slot": target["slot"], "output": str(output)}))
        return
    command(base + ["delete", "-f", str(bundle / "manifest.yaml"), "--ignore-not-found=true", "--wait=true", "--timeout=300s"], env)
    command(base + ["-n", target["namespace"], "delete", "gateway", gateway,
                    "--ignore-not-found=true", "--wait=true", "--timeout=300s"], env)
    for svc in before:
        command(base + ["-n", svc["metadata"]["namespace"], "wait", "--for=delete",
                       "service/" + svc["metadata"]["name"], "--timeout=300s"], env)
    tf.require(not owned_services(), "Owned Gateway Services remain; retain controllers and cloud dependencies")
    deadline = time.monotonic() + 300
    while True:
        lbs = data(["az", "network", "lb", "list", "--subscription", tf.SUBSCRIPTION,
                    "--resource-group", cluster["nodeResourceGroup"], "-o", "json"], env)
        remaining = [ip for lb in lbs for ip in lb.get("frontendIPConfigurations", [])
                     if ip.get("privateIPAddress") in addresses]
        if not remaining: break
        tf.require(time.monotonic() < deadline, "Azure LoadBalancer frontends remain; do not destroy controllers/network")
        time.sleep(5)
    for kind, name in [("clienttrafficpolicy", "application-gateway-client-ip"), ("envoyproxy", "private-proxy")]:
        command(base + ["-n", target["namespace"], "delete", kind, name,
                        "--ignore-not-found=true", "--wait=true", "--timeout=180s"], env)
    releases = data(["helm", "--kubeconfig", str(kubeconfig), "list", "-n", "envoy-gateway-system", "-a", "-o", "json"], env)
    matches = [x for x in releases if x["name"] == "envoy-gateway"]
    tf.require(len(matches) <= 1, "Ambiguous Helm ownership")
    if matches:
        tf.require(matches[0]["chart"].startswith("gateway-helm-"), "Unexpected controller release chart")
        command(["helm", "--kubeconfig", str(kubeconfig), "uninstall", "envoy-gateway",
                 "-n", "envoy-gateway-system", "--wait", "--timeout", "10m"], env)
    result = dict(inventory, resource_apply_performed=True, status="removed", gateway_services_removed=True,
                  cloud_frontends_released=True, helm_controller_removed=True,
                  retained="Separately owned CRDs, namespace and RBAC remain until the disposable cluster is destroyed.")
    tf.write_private(output / "result.json", json.dumps(result, indent=2))
    print(json.dumps({"status":"removed", "slot":target["slot"], "cloud_frontends_released":True}))

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--phase", required=True, choices=["services"])
    p.add_argument("--bundle", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--proxy-url")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args(argv)
    os.umask(0o077)
    tf.configure(args.config)
    services(args.bundle.resolve(), args.output, args.proxy_url, args.execute)

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit("Cleanup stopped: " + str(error))
