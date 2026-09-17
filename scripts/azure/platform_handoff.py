#!/usr/bin/env python3
"""Export selected non-secret Terraform outputs into reviewed app delivery targets."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re

UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
RESOURCE = re.compile(
    rf"^/subscriptions/({UUID})/resourceGroups/([^/]+)/providers/"
    r"(Microsoft.ContainerService/managedClusters|Microsoft.ContainerRegistry/registries)/([^/]+)$",
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
    args = parser.parse_args()
    try:
        result = export_config(load(args.template), load(args.aks_outputs),
                               load(args.registry_outputs), load(args.delivery_config),
                               args.environment, args.region)
        # Do not overwrite an existing private deployment configuration.
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
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
