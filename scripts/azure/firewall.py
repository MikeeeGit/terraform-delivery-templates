#!/usr/bin/env python3
"""Optional dedicated-runner IP rules; remove only rules this invocation added."""
import argparse, ipaddress, json, subprocess, urllib.request
from pathlib import Path


def az(args, capture=False):
    result = subprocess.run(
        ["az", *args, "--only-show-errors", "-o", "json" if capture else "none"],
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout) if capture else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=["add", "cleanup"])
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--key-vault", default="")
    p.add_argument("--ip")
    a = p.parse_args()
    if a.operation == "cleanup":
        if not a.receipt.exists():
            return
        receipt = json.loads(a.receipt.read_text())
        failures = []
        for rule in reversed(receipt):
            try:
                az(rule)
            except subprocess.CalledProcessError:
                failures.append(rule[0])
        if failures:
            raise RuntimeError(
                "Unable to remove recorded firewall rules; inspect the private run receipt"
            )
        a.receipt.unlink()
        return
    if a.receipt.exists():
        raise ValueError("existing receipt must be cleaned before adding new access")
    context = json.loads(a.context.read_text())
    b = context["backend"]
    subscription = context["backend_subscription_id"]
    ip = a.ip
    if not ip:
        with urllib.request.urlopen("https://api.ipify.org", timeout=15) as response:
            ip = response.read(64).decode().strip()
    ip = str(ipaddress.IPv4Address(ip))
    receipt = []

    # Write ownership before each mutation so cleanup can recover uncertain responses.
    def own(remove):
        receipt.append(remove)
        a.receipt.write_text(json.dumps(receipt))

    common = [
        "--subscription",
        subscription,
        "--resource-group",
        b["resource_group"],
        "--account-name",
        b["storage_account"],
    ]
    rules = az(["storage", "account", "network-rule", "list", *common], True)
    if ip not in [
        x["ipAddressOrRange"].removesuffix("/32") for x in rules.get("ipRules", [])
    ]:
        own(
            [
                "storage",
                "account",
                "network-rule",
                "remove",
                *common,
                "--ip-address",
                ip,
            ]
        )
        az(["storage", "account", "network-rule", "add", *common, "--ip-address", ip])
    if a.key_vault:
        common = ["--subscription", subscription, "--name", a.key_vault]
        rules = az(["keyvault", "network-rule", "list", *common], True)
        if ip not in [x["value"].removesuffix("/32") for x in rules.get("ipRules", [])]:
            own(["keyvault", "network-rule", "remove", *common, "--ip-address", ip])
            az(["keyvault", "network-rule", "add", *common, "--ip-address", ip])
    if not a.receipt.exists():
        a.receipt.write_text("[]")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(
            "Firewall operation stopped: "
            + type(error).__name__
            + "; inspect the private runner and receipt"
        )
