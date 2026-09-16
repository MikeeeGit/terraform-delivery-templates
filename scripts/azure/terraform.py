#!/usr/bin/env python3
"""Shared Azure context, saved-plan contract and confirmed local operations."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ALIASES = {"dev": "pprd", "shr": "hub", "bcdr": "prd"}
LOCK_TIMEOUT = "5m"
PLAN_AGE = 7200
LOCAL = ".terraform-delivery"


def run(args, *, cwd=None, capture=False, env=None, allowed=(0,)):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=capture)
    if result.returncode not in allowed:
        raise RuntimeError(
            f"{Path(args[0]).name} {args[1] if len(args)>1 else ''} failed (exit {result.returncode})"
        )
    return result.stdout.strip() if capture else result.returncode


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def label(value, name):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value
    ):
        raise ValueError(f"invalid {name}")
    return value


def identifier(value, name):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{name} must be a UUID") from None


def resolve(
    root,
    repository,
    environment,
    region,
    config_file="delivery.azure.json",
    prefix=None,
):
    root = Path(root).resolve(strict=True)
    for value, name in [
        (repository, "repository"),
        (environment, "environment"),
        (region, "region"),
    ]:
        label(value, name)
    reject_symlink_components(root, root / config_file)
    path = (root / config_file).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("configuration must be inside the repository")
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1:
        raise ValueError("deployment config schema_version must be 1")
    if region not in data["regions"]:
        raise ValueError("region is not configured")
    selection = data["environments"].get(environment)
    if selection is None:
        raise ValueError("environment is not configured")
    backend = dict(data["backend"], **selection.get("backend", {}))
    work_alias = selection["subscription_alias"]
    backend_alias = backend["subscription_alias"]
    variables = {
        "repository": repository,
        "environment": environment,
        "region": region,
        "secondary_region": data["secondary_region"],
        "prefix": prefix or data["prefix"],
        "backend_environment": selection.get(
            "backend_environment", ALIASES.get(environment, environment)
        ),
    }
    for key, value in variables.items():
        label(value, key)
    rendered = {
        key: backend[key].format_map(variables)
        for key in ["resource_group", "storage_account", "container", "key"]
    }
    if not re.fullmatch(r"[a-z0-9]{3,24}", rendered["storage_account"]):
        raise ValueError("storage account must contain 3-24 lowercase letters/digits")
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", rendered["container"])
        or "--" in rendered["container"]
    ):
        raise ValueError("invalid backend container")
    if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", rendered["resource_group"]):
        raise ValueError("invalid backend resource group")
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}", rendered["key"]
    ) or ".." in rendered["key"].split("/"):
        raise ValueError("invalid backend key")
    return {
        "repository": repository,
        "environment": environment,
        "region": region,
        "config_file": str(path.relative_to(root)),
        "config_sha256": sha(path),
        "tenant_id": identifier(data["tenant_id"], "tenant_id"),
        "subscription_alias": work_alias,
        "subscription_id": identifier(
            data["subscriptions"][work_alias], "workload subscription"
        ),
        "backend_subscription_alias": backend_alias,
        "backend_subscription_id": identifier(
            data["subscriptions"][backend_alias], "backend subscription"
        ),
        "backend_environment": variables["backend_environment"],
        "prefix": variables["prefix"],
        "backend": rendered,
        "workspace": "default",
    }


def reject_symlink_components(root, path):
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("source symlinks are unsupported")


def var_files(root, context):
    paths = [
        "config/global.tfvars",
        f"config/{context['region']}/{context['environment']}/{context['environment']}.tfvars",
    ]
    for value in paths:
        reject_symlink_components(root, root / value)
        p = (root / value).resolve(strict=True)
        if not p.is_relative_to(root) or not p.is_file():
            raise ValueError("variable files must be regular files inside the root")
    return paths


def environment(context=None):
    result = os.environ.copy()
    for key in list(result):
        if key in ("TF_CLI_ARGS", "TF_DATA_DIR") or key.startswith(
            ("TF_CLI_ARGS_", "TF_VAR_")
        ):
            del result[key]
    result.update(TF_INPUT="false", TF_WORKSPACE="default", ARM_USE_AZUREAD="true")
    if context:
        result.update(
            ARM_SUBSCRIPTION_ID=context["subscription_id"],
            ARM_TENANT_ID=context["tenant_id"],
        )
    return result


def version():
    value = json.loads(run(["terraform", "version", "-json"], capture=True))[
        "terraform_version"
    ]
    parts = tuple(int(x) for x in value.split(".")[:2])
    if not (parts >= (1, 9) and parts < (2, 0)):
        raise ValueError("Terraform >=1.9,<2 is required")
    return value


def source_fingerprint(root, strict=False):
    files = []
    if strict:
        run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--"])
        for flags in ([], ["--ignored"]):
            extra = run(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-files",
                    "-z",
                    "--others",
                    "--exclude-standard",
                    *flags,
                ],
                capture=True,
            )
            for name in filter(None, extra.split("\0")):
                p = root / name
                allowed = root / ".terraform"
                if not p.is_relative_to(allowed) or not p.resolve().is_relative_to(
                    allowed
                ):
                    raise ValueError("CI source contains uncommitted inputs")
        names = run(["git", "-C", str(root), "ls-files", "-z"], capture=True).split(
            "\0"
        )
        files = [root / name for name in names if name]
    else:
        for candidate in root.rglob("*"):
            if (
                not any(
                    x in candidate.relative_to(root).parts
                    for x in (".git", ".terraform", LOCAL, "__pycache__")
                )
                and candidate.is_symlink()
            ):
                raise ValueError("source symlinks are unsupported")
        files = [
            p
            for p in root.rglob("*")
            if p.is_file()
            and not any(
                x in p.relative_to(root).parts
                for x in (".git", ".terraform", LOCAL, "__pycache__")
            )
            and (
                p.suffix in (".tf", ".tfvars", ".json", ".csv", ".hcl")
                or p.name == ".terraform-version"
            )
        ]
    digests = {}
    for p in files:
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            raise ValueError("source symlinks are unsupported")
        if p.is_file():
            digests[str(p.relative_to(root))] = sha(p)
    return hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest()


def reject_ambient_variables():
    if any(key.startswith("TF_VAR_") and value for key, value in os.environ.items()):
        raise ValueError(
            "strict delivery rejects inherited TF_VAR_* inputs; use reviewed variable files"
        )


def binding(root, context, run_id="local", strict=False):
    if strict:
        reject_ambient_variables()
    lock = root / ".terraform.lock.hcl"
    if not lock.is_file():
        raise ValueError("initialize and review a provider lockfile first")
    var_files(root, context)
    commit = (
        run(["git", "-C", str(root), "rev-parse", "HEAD"], capture=True)
        if strict
        else "local"
    )
    return {
        "schema_version": 1,
        "context": context,
        "working_directory": ".",
        "terraform_version": version(),
        "identity_policy": {
            k: os.environ.get(k, "")
            for k in (
                "TD_PLAN_CLIENT_ID",
                "TD_APPLY_CLIENT_ID",
                "TD_PLAN_CONNECTION",
                "TD_APPLY_CONNECTION",
                "TD_BACKEND_CONNECTION",
            )
        },
        "source_sha256": source_fingerprint(root, strict),
        "lockfile_sha256": sha(lock),
        "commit": commit,
        "run_id": run_id,
    }


def record(
    root, context, bundle, run_id="local", strict=False, platform="local", before=None
):
    current = binding(root, context, run_id, strict)
    pending = bundle / "pending-binding.json"
    if before is None and pending.exists():
        before = json.loads(pending.read_text())
    if before is None:
        raise ValueError("capture the source binding before creating a plan")
    if before != current:
        raise ValueError("source or context changed while planning; create a new plan")
    manifest = {
        "binding": before,
        "created_at": time.time(),
        "plan_sha256": sha(bundle / "tfplan"),
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    if pending.exists():
        pending.unlink()
    digest = sha(bundle / "manifest.json")
    if platform == "github":
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"manifest-sha256={digest}\n")
    elif platform == "azure-devops":
        print(f"##vso[task.setvariable variable=manifestSha;isOutput=true]{digest}")
    else:
        # Independent local receipt is deliberately outside the transferable bundle.
        (root / LOCAL / "plan-receipt").write_text(digest + "\n")
    return digest


def verify(root, context, bundle, run_id="local", strict=False, expected=None):
    if not expected:
        expected = (root / LOCAL / "plan-receipt").read_text().strip()
    manifest_path = bundle / "manifest.json"
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected)
        or manifest_path.is_symlink()
        or sha(manifest_path) != expected
    ):
        raise ValueError("manifest does not match the separate trusted receipt")
    saved = json.loads(manifest_path.read_text())
    if saved["binding"] != binding(root, context, run_id, strict):
        raise ValueError("saved plan source, context, run or toolchain changed")
    if not 0 <= time.time() - saved["created_at"] <= PLAN_AGE:
        raise ValueError("plan expired; create and review a new plan")
    plan = bundle / "tfplan"
    if plan.is_symlink() or sha(plan) != saved["plan_sha256"]:
        raise ValueError("saved plan changed")


def select_account(context, backend=False):
    target = context["backend_subscription_id" if backend else "subscription_id"]
    info = json.loads(
        run(
            [
                "az",
                "account",
                "show",
                "--subscription",
                target,
                "--query",
                "{id:id,tenantId:tenantId}",
                "-o",
                "json",
            ],
            capture=True,
        )
    )
    if (
        info.get("id", "").lower() != target
        or info.get("tenantId", "").lower() != context["tenant_id"]
    ):
        raise ValueError(
            "Azure CLI account or tenant does not match the selected target"
        )
    run(["az", "account", "set", "--subscription", target])


def initialize(root, context, upgrade=False, persist=True):
    select_account(context, backend=True)
    b = context["backend"]
    command = [
        "terraform",
        "init",
        "-reconfigure",
        "-input=false",
        "-backend-config=use_azuread_auth=true",
        f"-backend-config=subscription_id={context['backend_subscription_id']}",
        f"-backend-config=tenant_id={context['tenant_id']}",
        f"-backend-config=resource_group_name={b['resource_group']}",
        f"-backend-config=storage_account_name={b['storage_account']}",
        f"-backend-config=container_name={b['container']}",
        f"-backend-config=key={b['key']}",
    ]
    if upgrade:
        command.append("-upgrade")
    elif (root / ".terraform.lock.hcl").exists():
        command.append("-lockfile=readonly")
    run(command, cwd=root, env=environment(context))
    if persist:
        (root / LOCAL / "backend-signature.json").write_text(
            json.dumps(context, sort_keys=True)
        )
    verify_backend(root, context)
    select_account(context)


def verify_backend(root, context):
    metadata = json.loads((root / ".terraform" / "terraform.tfstate").read_text())
    backend = metadata.get("backend", {})
    actual = backend.get("config", {})
    expected = context["backend"]
    if backend.get("type") != "azurerm" or any(
        actual.get(k) != expected[v]
        for k, v in (
            ("storage_account_name", "storage_account"),
            ("container_name", "container"),
            ("key", "key"),
        )
    ):
        raise ValueError("initialized backend does not match the selected state target")
    if actual.get("use_azuread_auth") is not True:
        raise ValueError("backend must use Azure AD authentication")
    if (
        run(
            ["terraform", "workspace", "show"],
            cwd=root,
            capture=True,
            env=environment(context),
        )
        != "default"
    ):
        raise ValueError(
            "only the default workspace is supported; environments have separate state keys"
        )


def ensure_initialized(root, context):
    # The local receipt is not authoritative: raw terraform init can change the cache.
    initialize(root, context)


def confirm(message, yes):
    if yes:
        return
    if not sys.stdin.isatty():
        raise ValueError(
            "confirmation requires a terminal; --yes is explicit automation opt-in"
        )
    if input(message + " Type yes to continue: ") != "yes":
        raise ValueError("operation cancelled")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "setup",
            "context",
            "init",
            "plan",
            "apply",
            "destroy",
            "import",
            "env",
            "record",
            "verify",
            "verify-backend",
            "prepare",
        ],
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--repository")
    parser.add_argument("--environment")
    parser.add_argument("--region")
    parser.add_argument("--config", default="delivery.azure.json")
    parser.add_argument("--prefix")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--run-id", default="local")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--platform", choices=["local", "github", "azure-devops"], default="local"
    )
    parser.add_argument("--expected-digest")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("operands", nargs="*")
    args = parser.parse_intermixed_args()
    selected = [args.repository, args.environment, args.region]
    if any(selected) and not all(selected):
        raise ValueError(
            "provide repository, environment and region together; partial target overrides are rejected"
        )
    if args.upgrade and args.command != "init":
        raise ValueError("upgrades require the explicit init --upgrade command")
    root = args.root.resolve(strict=True)
    session = root / LOCAL / "context.json"
    if args.repository and args.environment and args.region:
        context = resolve(
            root,
            args.repository,
            args.environment,
            args.region,
            args.config,
            args.prefix,
        )
    elif session.exists():
        previous = json.loads(session.read_text())
        context = resolve(
            root,
            previous["repository"],
            previous["environment"],
            previous["region"],
            previous["config_file"],
            previous["prefix"],
        )
    else:
        raise ValueError(
            "select --repository, --environment and --region or run tf_setup"
        )
    if (
        args.command in ("setup", "init", "plan", "apply", "destroy", "import")
        and not args.strict
    ):
        (root / LOCAL).mkdir(exist_ok=True)
    bundle = (args.bundle or root / LOCAL / "plan").resolve()
    if args.strict and bundle.is_relative_to(root):
        raise ValueError("CI bundles must be outside the source checkout")
    if args.command == "context":
        if (
            args.platform == "azure-devops"
            or os.environ.get("GITHUB_ACTIONS") == "true"
        ):
            reject_ambient_variables()
        var_files(root, context)
        if args.platform == "azure-devops":
            flat = {
                "tenant_id": context["tenant_id"],
                "subscription_id": context["subscription_id"],
                "backend_subscription_id": context["backend_subscription_id"],
                **{"backend_" + k: v for k, v in context["backend"].items()},
            }
            for key, value in flat.items():
                print(f"##vso[task.setvariable variable={key}]{value}")
        else:
            print(json.dumps(context, indent=2))
    elif args.command == "setup":
        if root.name != context["repository"]:
            raise ValueError("current directory must match the selected repository")
        select_account(context, backend=True)
        select_account(context)
        session.write_text(json.dumps(context, indent=2) + "\n")
        print(
            f"Selected {context['repository']} / {context['environment']} / {context['region']}. Run tf_init next."
        )
    elif args.command == "env":
        print(
            f"Repository: {context['repository']}\nEnvironment: {context['environment']}\nRegion: {context['region']}\nWorkload alias: {context['subscription_alias']}\nBackend alias: {context['backend_subscription_alias']}\nState key: {context['backend']['key']}"
        )
    elif args.command == "init":
        initialize(root, context, args.upgrade, persist=not args.strict)
    elif args.command == "plan":
        if args.strict:
            source_fingerprint(root, True)
            initialize(root, context, persist=False)
        else:
            ensure_initialized(root, context)
        run(
            ["terraform", "fmt", *(["-check"] if args.strict else []), "-recursive"],
            cwd=root,
            env=environment(context),
        )
        run(["terraform", "validate"], cwd=root, env=environment(context))
        bundle.mkdir(parents=True, exist_ok=True)
        for name in ["tfplan", "manifest.json"]:
            p = bundle / name
            if p.is_symlink():
                raise ValueError("plan path must not be a symlink")
            if p.exists():
                p.unlink()
        before = binding(root, context, args.run_id, args.strict)
        run(
            [
                "terraform",
                "plan",
                "-input=false",
                f"-lock-timeout={LOCK_TIMEOUT}",
                "-detailed-exitcode",
                f"-out={bundle/'tfplan'}",
                *[f"-var-file={p}" for p in var_files(root, context)],
            ],
            cwd=root,
            env=environment(context),
            allowed=(0, 2),
        )
        record(root, context, bundle, args.run_id, args.strict, args.platform, before)
        print(
            "Plan saved locally. tf_apply applies this reviewed plan for up to two hours."
        )
    elif args.command == "apply":
        verify(root, context, bundle, args.run_id, args.strict, args.expected_digest)
        if args.strict:
            initialize(root, context, persist=False)
        else:
            ensure_initialized(root, context)
        confirm(
            f"Apply saved plan for {context['repository']}/{context['environment']}/{context['region']}?",
            args.yes,
        )
        verify(root, context, bundle, args.run_id, args.strict, args.expected_digest)
        run(
            [
                "terraform",
                "apply",
                "-input=false",
                f"-lock-timeout={LOCK_TIMEOUT}",
                str(bundle / "tfplan"),
            ],
            cwd=root,
            env=environment(context),
        )
    elif args.command == "destroy":
        ensure_initialized(root, context)
        confirm(
            f"Destroy {context['repository']}/{context['environment']}/{context['region']}?",
            args.yes,
        )
        run(
            [
                "terraform",
                "destroy",
                "-auto-approve",
                "-input=false",
                f"-lock-timeout={LOCK_TIMEOUT}",
                *[f"-var-file={p}" for p in var_files(root, context)],
            ],
            cwd=root,
            env=environment(context),
        )
    elif args.command == "import":
        if (
            len(args.operands) != 2
            or args.operands[0].startswith("-")
            or args.operands[1].startswith("-")
        ):
            raise ValueError("import requires a resource address and resource ID")
        ensure_initialized(root, context)
        confirm(
            f"Import resource into {context['repository']}/{context['environment']}/{context['region']}?",
            args.yes,
        )
        run(
            [
                "terraform",
                "import",
                "-input=false",
                f"-lock-timeout={LOCK_TIMEOUT}",
                *[f"-var-file={p}" for p in var_files(root, context)],
                *args.operands,
            ],
            cwd=root,
            env=environment(context),
        )
    elif args.command == "prepare":
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "pending-binding.json").write_text(
            json.dumps(binding(root, context, args.run_id, args.strict), sort_keys=True)
        )
    elif args.command == "verify-backend":
        verify_backend(root, context)
    elif args.command == "record":
        record(root, context, bundle, args.run_id, args.strict, args.platform)
    elif args.command == "verify":
        verify(root, context, bundle, args.run_id, args.strict, args.expected_digest)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Operation stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
