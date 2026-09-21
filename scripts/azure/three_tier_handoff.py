#!/usr/bin/env python3
"""Generate new private consumer files from non-sensitive applied Terraform outputs."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import shutil

from platform_handoff import UUID, export_config, export_workload, output, resource, write_new_jsons


def ci_principals(snapshot, environment, region, tenant_id, platform_key, application_key, namespace, slots):
    identities = output(snapshot, "identities")
    if platform_key == application_key or not slots or not set(slots) <= {"aks01", "aks02"}:
        raise ValueError("Select separate platform/application identities and explicit AKS slots")
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", namespace):
        raise ValueError("Expected a Kubernetes namespace")
    principals = {}
    for key, purpose in [(platform_key, "platform"), (application_key, "application")]:
        identity = identities[key]
        subscription, _, _ = resource(identity["id"], "Microsoft.ManagedIdentity/userAssignedIdentities")
        if (subscription != identity["subscription_id"].lower() or identity["purpose"] != purpose or identity["environment"] != environment
                or identity["region"] != region or identity["tenant_id"].lower() != tenant_id.lower()
                or not re.fullmatch(UUID, identity["client_id"])
                or not re.fullmatch(UUID, identity["principal_id"])):
            raise ValueError("CI identity purpose, target or identifiers disagree")
        principals[key] = {name: identity[name] for name in ["client_id", "principal_id", "purpose"]}
        principals[key].update(clusters=sorted(set(slots)),
                               namespaces=[namespace] if purpose == "application" else [])
    if any(len({p[field].lower() for p in principals.values()}) != 2 for field in ["principal_id", "client_id"]):
        raise ValueError("Platform and application must use separate principals")
    return {"delivery_principals": principals}


def application_files(template, platform, aks, registry, delivery, environment, region,
                      identity_key, account_key, vault_id, certificate_name, secret_name):
    config = export_config(template, aks, registry, delivery, environment, region)
    binding = export_workload(config, aks, identity_key, account_key)
    if binding["namespace"] != "platform-demo" or binding["service_account"] != "platform-demo":
        raise ValueError("This consumer generator targets the platform-demo Azure workload profile")
    if any(t["overlay"] != f"deploy/azure-workload/overlays/{environment}/{region}/{t['slot']}"
           for t in config["targets"]):
        raise ValueError("Select the maintained Azure workload delivery profile")
    vault_match = re.fullmatch(
        rf"/subscriptions/({UUID})/resourceGroups/[^/]+/providers/Microsoft.KeyVault/vaults/([a-zA-Z][a-zA-Z0-9-]{{1,22}}[a-zA-Z0-9])",
        vault_id, re.IGNORECASE)
    if (not vault_match or vault_match[1].lower() not in
            {value.lower() for value in delivery["subscriptions"].values()}):
        raise ValueError("Vault must belong to a declared delivery subscription")
    for name in [certificate_name, secret_name]:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,127}", name):
            raise ValueError("Use Key Vault object names, never secret values or URLs")
    identity = output(aks, "workload_identities")[identity_key]
    roles = identity["role_assignments"]
    if not any(r["scope"].lower() == vault_id.lower() and
               r["role_definition_name"] == "Key Vault Secrets User" and
               r["principal_id"].lower() == identity["principal_id"].lower() for r in roles.values()):
        raise ValueError("Applied workload output must declare Secrets User at this exact vault")
    vault_name = vault_match[2]
    parameters = {**binding["secret_provider_parameters"], "keyvaultName": vault_name}
    secret_class = {
        "apiVersion": "secrets-store.csi.x-k8s.io/v1", "kind": "SecretProviderClass",
        "metadata": {"name": "platform-demo-app-secret"},
        "spec": {"provider": "azure", "parameters": {
            **parameters, "useVMManagedIdentity": "false",
            "objects": "array:\n  - |\n"
                       f"    objectName: {secret_name}\n    objectAlias: qualification\n"
                       '    objectType: secret\n    objectVersion: ""\n    filePermission: "0444"\n'
        }},
    }
    tls_patch = {
        "apiVersion": "secrets-store.csi.x-k8s.io/v1", "kind": "SecretProviderClass",
        "metadata": {"name": "platform-demo-tls"},
        "spec": {"parameters": {
            **parameters,
            "objects": "array:\n  - |\n"
                       f"    objectName: {certificate_name}\n    objectType: secret\n"
                       '    objectFormat: pem\n    objectVersion: ""\n'
        }, "secretObjects": [{
            "secretName": "platform-demo-tls", "type": "kubernetes.io/tls",
            "data": [{"objectName": certificate_name, "key": key} for key in ["tls.key", "tls.crt"]]
        }]},
    }
    account_patch = copy.deepcopy(binding["service_account_manifest"])
    account_patch["metadata"].pop("namespace")
    platform_result = copy.deepcopy(platform)
    if platform_result.get("schema_version") != 1:
        raise ValueError("Unsupported platform schema")
    platform_result["tenant_id"] = config["tenant_id"]
    by_slot = {t["slot"]: t for t in config["targets"]}
    selected = [t for t in platform_result["targets"]
                if t["environment"] == environment and t["region"] == region]
    if {t["slot"] for t in selected} != set(by_slot) or len(selected) != len(by_slot):
        raise ValueError("Platform and application must cover the same selected slots exactly once")
    for target in selected:
        source = by_slot[target["slot"]]
        for key in ["subscription_id", "resource_group", "cluster_name"]:
            target[key] = source[key]
        accounts = [a for a in target["workload_service_accounts"]
                    if a["name"] == binding["service_account"] and a["namespace"] == binding["namespace"]]
        if len(accounts) != 1:
            raise ValueError("Platform must declare the exact workload ServiceAccount once")
        accounts[0]["client_id"] = binding["client_id"]
    platform_result["targets"] = selected
    expected = {"schema_version": 1, "targets": [
        {key: t[key] for key in ["environment", "region", "slot"]} | {
            "client_id": binding["client_id"], "tenant_id": binding["tenant_id"],
            "vault_name": vault_name, "secret_name": secret_name,
            "service_account": binding["service_account"],
            "secret_provider_class": "platform-demo-app-secret",
        } for t in config["targets"]
    ]}
    return {
        "application/delivery.azure-workload.apps.json": config,
        "application/azure.workload.json": expected,
        "application/deploy/azure-workload/base/service-account.patch.yaml": account_patch,
        "application/deploy/azure-workload/base/tls-identity.patch.yaml": tls_patch,
        "application/deploy/azure-workload/base/application-secret-provider-class.yaml": secret_class,
        "platform/platform.services.json": platform_result,
        "workload.private.json": binding,
    }


def write_pack(directory: Path, files):
    # Only a newly created directory is owned by this operation.
    directory = directory.absolute()
    for parent in [directory, *directory.parents]:
        if parent.is_symlink():
            raise ValueError("Output directories must not use symbolic links")
    directory.mkdir(mode=0o700)
    try:
        for name, value in files.items():
            path = directory / name
            if not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError("Output path escapes the new directory")
            path.parent.mkdir(parents=True, exist_ok=True)
            write_new_jsons([(path, value)])
    except Exception:
        shutil.rmtree(directory)
        raise


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ci = commands.add_parser("ci")
    ci.add_argument("--identities", type=Path, required=True)
    ci.add_argument("--tenant-id", required=True)
    ci.add_argument("--platform-key", default="platform")
    ci.add_argument("--application-key", default="application")
    ci.add_argument("--namespace", default="platform-demo")
    ci.add_argument("--slots", nargs="+", choices=["aks01", "aks02"], required=True)
    ci.add_argument("--output", type=Path, required=True)
    app = commands.add_parser("application")
    for flag in ["template", "platform-template", "aks-outputs", "registry-outputs", "delivery-config"]:
        app.add_argument("--" + flag, type=Path, required=True)
    for flag in ["workload-identity", "service-account-key", "vault-id", "certificate-name", "secret-name"]:
        app.add_argument("--" + flag, required=True)
    app.add_argument("--output-directory", type=Path, required=True)
    for command in [ci, app]:
        command.add_argument("--environment", required=True)
        command.add_argument("--region", required=True)
    args = parser.parse_args()
    if args.command == "ci":
        result = ci_principals(read(args.identities), args.environment, args.region, args.tenant_id,
                               args.platform_key, args.application_key, args.namespace, args.slots)
        write_new_jsons([(args.output, result)])
    else:
        files = application_files(
            read(args.template), read(args.platform_template), read(args.aks_outputs),
            read(args.registry_outputs), read(args.delivery_config), args.environment, args.region,
            args.workload_identity, args.service_account_key, args.vault_id,
            args.certificate_name, args.secret_name)
        write_pack(args.output_directory, files)
    print("Created new private review files; no cloud login, secret retrieval or deployment was performed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as error:
        raise SystemExit("Handoff stopped: " + str(error))
