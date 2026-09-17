#!/usr/bin/env python3
"""Export selected non-secret Terraform outputs into reviewed app delivery targets."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
RESOURCE = re.compile(
    rf"^/subscriptions/({UUID})/resourceGroups/([^/]+)/providers/"
    r"(Microsoft.ContainerService/managedClusters|Microsoft.ContainerRegistry/registries|Microsoft.ManagedIdentity/userAssignedIdentities)/([^/]+)$",
    re.IGNORECASE,
)


def output(snapshot: dict, name: str):
    entry = snapshot.get(name)
    if not isinstance(entry, dict) or entry.get("sensitive") is not False or "value" not in entry:
        raise ValueError(f"Required non-sensitive Terraform output is missing: {name}")
    return entry["value"]


def resource(value: str, kind: str) -> tuple[str, str, str]:
    match = RESOURCE.fullmatch(value) if isinstance(value, str) else None
    if not match or match[3].lower() != kind.lower():
        raise ValueError("Terraform output contains an unexpected Azure resource type")
    return match[1].lower(), match[2], match[4]


def export_config(template: dict, aks: dict, registry: dict, delivery: dict,
                  environment: str, region: str) -> dict:
    if template.get("schema_version") != 1 or delivery.get("schema_version") != 1:
        raise ValueError("Only schema_version 1 is supported")
    context = output(aks, "deployment_context")
    clusters = output(aks, "clusters")
    expected_subscription = delivery["subscriptions"][
        delivery["environments"][environment]["subscription_alias"]
    ]
    if (context["environment"] != environment or context["region"] != region
            or region not in delivery["regions"]
            or context["tenant_id"].lower() != delivery["tenant_id"].lower()
            or context["subscription_id"].lower() != expected_subscription.lower()):
        raise ValueError("AKS output target does not match the selected delivery environment")
    if not re.fullmatch(UUID, context["tenant_id"]):
        raise ValueError("Expected a tenant UUID")
    selected = [copy.deepcopy(t) for t in template["targets"]
                if t["environment"] == environment and t["region"] == region]
    if not selected or len({t["slot"] for t in selected}) != len(selected):
        raise ValueError("Template must contain unique targets for the selected environment/region")
    for target in selected:
        slot = target["slot"]
        if slot not in ("aks01", "aks02") or slot not in clusters:
            raise ValueError("A requested cluster slot is missing from applied AKS outputs")
        cluster = clusters[slot]
        subscription, group, name = resource(cluster["id"], "Microsoft.ContainerService/managedClusters")
        if (subscription != expected_subscription.lower()
                or cluster["name"] != name or cluster["resource_group_name"] != group):
            raise ValueError("AKS resource ID disagrees with the target or cluster metadata")
        target.update(subscription_id=subscription, resource_group=group, cluster_name=name)
    registry_id = output(registry, "acr_id")
    registry_subscription, _, registry_name = resource(
        registry_id, "Microsoft.ContainerRegistry/registries"
    )
    if registry_subscription not in {v.lower() for v in delivery["subscriptions"].values()}:
        raise ValueError("Registry subscription is outside the reviewed delivery aliases")
    login_server = output(registry, "acr_login_server")
    if (output(registry, "acr_name") != registry_name
            or login_server.lower() != f"{registry_name}.azurecr.io".lower()):
        raise ValueError("Registry outputs disagree or are outside the Azure public cloud contract")
    result = copy.deepcopy(template)
    result.pop("subscription_id", None)
    result["tenant_id"] = context["tenant_id"]
    result["registry"].update(subscription_id=registry_subscription,
                              name=registry_name.lower(), login_server=login_server.lower())
    result["targets"] = selected
    return result


def export_workload(config: dict, aks: dict, identity_key: str,
                    service_account_key: str) -> dict:
    """Export an exact applied federation binding; never obtain a token or a secret."""
    context = output(aks, "deployment_context")
    clusters = output(aks, "clusters")
    identity = output(aks, "workload_identities")[identity_key]
    subscription, _, _ = resource(
        identity["id"], "Microsoft.ManagedIdentity/userAssignedIdentities"
    )
    if (subscription != context["subscription_id"].lower()
            or identity["tenant_id"].lower() != config["tenant_id"].lower()
            or not re.fullmatch(UUID, identity["client_id"])
            or not re.fullmatch(UUID, identity["tenant_id"])):
        raise ValueError("Workload identity does not match the applied AKS target")
    account = identity["service_accounts"][service_account_key]
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if (not re.fullmatch(label, account["namespace"])
            or not re.fullmatch(label, account["service_account"])):
        raise ValueError("Invalid workload namespace or service account")
    subject = f"system:serviceaccount:{account['namespace']}:{account['service_account']}"
    credentials = identity["federated_credentials"]
    selected = []
    for target in config["targets"]:
        slot = target["slot"]
        if (target["namespace"] != account["namespace"]
                or slot not in account["clusters"]):
            raise ValueError("Workload federation does not cover the selected namespace and slots")
        issuer = clusters[slot]["oidc_issuer_url"]
        url = urlparse(issuer)
        if (url.scheme != "https" or not url.hostname or url.username
                or url.password or url.query or url.fragment):
            raise ValueError("Invalid applied OIDC issuer URL")
        matches = [entry for entry in credentials.values()
                   if entry["cluster"] == slot and entry["issuer"] == issuer
                   and entry["subject"] == subject
                   and entry["audience"] == ["api://AzureADTokenExchange"]]
        if len(matches) != 1:
            raise ValueError("Applied federated credential is missing or disagrees with the target")
        selected.append({"slot": slot, "cluster_id": clusters[slot]["id"],
                         "issuer": issuer, "subject": subject})
    return {
        "schema_version": 1,
        "tenant_id": identity["tenant_id"],
        "identity_id": identity["id"],
        "client_id": identity["client_id"],
        "namespace": account["namespace"],
        "service_account": account["service_account"],
        "targets": selected,
        "service_account_manifest": {
            "apiVersion": "v1", "kind": "ServiceAccount",
            "metadata": {"name": account["service_account"], "namespace": account["namespace"],
                         "annotations": {"azure.workload.identity/client-id": identity["client_id"],
                                         "azure.workload.identity/tenant-id": identity["tenant_id"]}},
        },
        "secret_provider_parameters": {"usePodIdentity": "false",
                                       "clientID": identity["client_id"],
                                       "tenantId": identity["tenant_id"]},
    }


def write_new_jsons(items: list[tuple[Path, dict]]) -> None:
    """Create review outputs exclusively, and remove only our new files on failure."""
    if len({path.resolve() for path, _ in items}) != len(items):
        raise ValueError("Each handoff output must use a different path")
    created = []
    try:
        for path, value in items:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created.append(path)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2)
                stream.write("\n")
    except Exception:
        for path in created:
            path.unlink()
        raise


def load(path: Path) -> dict:
    if path.stat().st_size > 2_000_000:
        raise ValueError("Expected compact Terraform output/configuration JSON, not state")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("template", "aks-outputs", "registry-outputs", "delivery-config", "output"):
        parser.add_argument("--" + flag, required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--workload-identity", help="Applied workload identity map key")
    parser.add_argument("--service-account-key", help="Service account map key within that identity")
    parser.add_argument("--workload-output", type=Path, help="New private review JSON for identity/ServiceAccount binding")
    args = parser.parse_args()
    try:
        aks = load(args.aks_outputs)
        result = export_config(load(args.template), aks,
                               load(args.registry_outputs), load(args.delivery_config),
                               args.environment, args.region)
        workload_options = [args.workload_identity, args.service_account_key, args.workload_output]
        if any(workload_options) and not all(workload_options):
            raise ValueError("Workload export requires identity, service-account key and output path together")
        items = [(args.output, result)]
        if all(workload_options):
            binding = export_workload(result, aks, args.workload_identity, args.service_account_key)
            items.append((args.workload_output, binding))
        write_new_jsons(items)
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, FileExistsError):
            print("Output already exists; choose a new review file.")
        elif isinstance(error, ValueError):
            print(f"Handoff rejected: {error}")
        else:
            print("Handoff rejected: missing or invalid input files/fields.")
        return 2
    print(f"Created app configuration for {len(result['targets'])} selected cluster slots.")
    print("Review it and run the AKS delivery validator before use. No cloud changes were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
