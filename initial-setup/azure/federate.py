#!/usr/bin/env python3
"""Review or create new secretless OIDC identities; never modify existing apps."""
import argparse, json, re, subprocess, sys, tempfile, uuid
from pathlib import Path


def az(args):
    result = subprocess.run(
        ["az", *args, "--only-show-errors", "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def credentials(app):
    if "federations" in app and "federation" in app:
        raise ValueError("choose federations or the legacy single federation")
    source = app.get("federations") or (
        [app["federation"]] if "federation" in app else []
    )
    if not source:
        raise ValueError("configure at least one federated credential")
    result = []
    names = set()
    for item in source:
        name = item.get("name", "terraform-delivery")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,119}", name) or name in names:
            raise ValueError(
                "federated credential names must be safe and unique within each application"
            )
        if not item["issuer"].startswith("https://") or not item["subject"]:
            raise ValueError("copy the exact issuer and subject from the platform")
        names.add(name)
        result.append(
            {
                "name": name,
                "issuer": item["issuer"],
                "subject": item["subject"],
                "audiences": ["api://AzureADTokenExchange"],
            }
        )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("configuration", type=Path)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    configuration = json.loads(a.configuration.read_text())
    apps = configuration["applications"]
    tenant = str(uuid.UUID(configuration["tenant_id"]))
    allowed_roles = {
        "Reader",
        "Contributor",
        "Storage Blob Data Contributor",
        "Storage Account Contributor",
    }
    if not apps:
        raise ValueError("configure at least one identity")
    names = set()
    for app in apps:
        name = app["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,79}", name) or name in names:
            raise ValueError("use unique safe application names")
        names.add(name)
        federations = credentials(app)
        for assignment in app["roles"]:
            if assignment["role"] not in allowed_roles or not re.fullmatch(
                r"/subscriptions/[0-9a-fA-F-]{36}(?:/[A-Za-z0-9._/-]+)?",
                assignment["scope"],
            ):
                raise ValueError("invalid least-privilege role assignment")
        print(
            name
            + ": "
            + str(len(federations))
            + " federated credentials, "
            + str(len(app["roles"]))
            + " scoped role assignments"
        )
    if not a.apply:
        print("Review only. --apply prompts before creating any identity.")
        return
    current = az(["account", "show"])
    if current.get("tenantId", "").lower() != tenant:
        raise ValueError("Azure CLI is in the wrong tenant")
    subscriptions = {
        assignment["scope"].split("/")[2].lower()
        for app in apps
        for assignment in app["roles"]
    }
    for subscription in subscriptions:
        account = az(["account", "show", "--subscription", subscription])
        if (
            account.get("id", "").lower() != subscription
            or account.get("tenantId", "").lower() != tenant
        ):
            raise ValueError(
                "role scope subscription does not belong to the expected accessible tenant"
            )
    if (
        not sys.stdin.isatty()
        or input("Create these NEW Azure identities and scoped roles? Type create: ")
        != "create"
    ):
        raise ValueError("creation cancelled")
    # Check all names before the first mutation; repeated use never silently binds a foreign app.
    for app in apps:
        if az(["ad", "app", "list", "--display-name", app["name"]]):
            raise ValueError(
                "an application with a selected name already exists; inspect/reconcile explicitly"
            )
    receipt = Path.cwd() / ".terraform-delivery" / "identity-receipt.json"
    receipt.parent.mkdir(exist_ok=True)
    created = []
    for app in apps:
        application = az(
            [
                "ad",
                "app",
                "create",
                "--display-name",
                app["name"],
                "--sign-in-audience",
                "AzureADMyOrg",
            ]
        )
        row = {
            "name": app["name"],
            "client_id": application["appId"],
            "application_object_id": application["id"],
        }
        created.append(row)
        receipt.write_text(json.dumps(created, indent=2) + "\n")
        principal = az(["ad", "sp", "create", "--id", application["appId"]])
        row["principal_object_id"] = principal["id"]
        receipt.write_text(json.dumps(created, indent=2) + "\n")
        for credential in credentials(app):
            with tempfile.TemporaryDirectory(
                prefix="terraform-federation-"
            ) as directory:
                path = Path(directory) / "federation.json"
                path.write_text(json.dumps(credential))
                az(
                    [
                        "ad",
                        "app",
                        "federated-credential",
                        "create",
                        "--id",
                        application["id"],
                        "--parameters",
                        str(path),
                    ]
                )
        for role in app["roles"]:
            az(
                [
                    "role",
                    "assignment",
                    "create",
                    "--assignee-object-id",
                    principal["id"],
                    "--assignee-principal-type",
                    "ServicePrincipal",
                    "--role",
                    role["role"],
                    "--scope",
                    role["scope"],
                ]
            )
        row["complete"] = True
        receipt.write_text(json.dumps(created, indent=2) + "\n")
    print(
        "Created secretless identities. Client IDs and progress are in the ignored local receipt; no token or client secret was printed."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(
            "Identity setup stopped: "
            + type(error).__name__
            + ". Inspect the local receipt before retrying; existing apps are never modified."
        )
