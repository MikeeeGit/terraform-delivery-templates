#!/usr/bin/env python3
"""Private Azure delivery: bind an approved binary plan to its exact context."""
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

from validate import contained_directory, TESTED_TERRAFORM_VERSION

MAX_PLAN_AGE_SECONDS = 7200


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def context_from_environment() -> dict:
    patterns = {
        "commit": r"[0-9a-f]{40}",
        "run": r"[0-9]+:[0-9]+",
        "tenant_id": r"[0-9a-fA-F-]{36}",
        "subscription_id": r"[0-9a-fA-F-]{36}",
        "plan_client_id": r"[0-9a-fA-F-]{36}",
        "apply_client_id": r"[0-9a-fA-F-]{36}",
        "storage_account": r"[a-z0-9]{3,24}",
        "container": r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]",
        "key": r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}",
        "environment": r"[A-Za-z0-9_.-]{1,64}",
    }
    context = {}
    for key, pattern in patterns.items():
        value = os.environ.get("TD_" + key.upper(), "")
        if not re.fullmatch(pattern, value):
            raise ValueError(f"TD_{key.upper()} is missing or invalid")
        context[key] = value
    if ".." in context["key"].split("/"):
        raise ValueError("state key must not contain '..' segments")
    if context["plan_client_id"].lower() == context["apply_client_id"].lower():
        raise ValueError("plan and apply must use different workload identities")
    return context


def environment(working: Path, context: dict, operation: str) -> dict:
    env = os.environ.copy()
    for name in list(env):
        if name == "TF_CLI_ARGS" or name.startswith(("TF_CLI_ARGS_", "TF_VAR_")):
            del env[name]
    env.update(TF_IN_AUTOMATION="true", TF_INPUT="false", TF_DATA_DIR=str(working / ".terraform"), TF_WORKSPACE="default")
    required = {
        "ARM_CLIENT_ID": context["plan_client_id" if operation == "plan" else "apply_client_id"],
        "ARM_TENANT_ID": context["tenant_id"],
        "ARM_SUBSCRIPTION_ID": context["subscription_id"],
        "ARM_USE_OIDC": "true",
        "ARM_USE_AZUREAD": "true",
    }
    for key, value in required.items():
        if env.get(key, "").lower() != value.lower():
            raise ValueError(f"{key} does not match the approved delivery context")
    return env


def require_source(source: Path, commit: str, working: Path) -> None:
    actual = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if actual != commit:
        raise ValueError("checked-out commit does not match the delivery context")
    subprocess.run(["git", "-C", str(source), "diff", "--quiet", "HEAD", "--"], check=True)
    tracked = subprocess.run(["git", "-C", str(source), "ls-files", "-z"], check=True, capture_output=True, text=True).stdout
    for name in filter(None, tracked.split("\0")):
        if (source / name).is_symlink():
            raise ValueError("deployment source must not contain tracked symlinks")
    # Only Terraform's own managed data directory may contain untracked files.
    # This catches ignored auto-tfvars/overrides and generated local inputs too.
    for extra_flags in ([], ["--ignored"]):
        output = subprocess.run(["git", "-C", str(source), "ls-files", "-z", "--others", "--exclude-standard", *extra_flags], check=True, capture_output=True, text=True).stdout
        for name in filter(None, output.split("\0")):
            candidate = source / name
            managed_data = working / ".terraform"
            if not candidate.is_relative_to(managed_data) or not candidate.resolve().is_relative_to(managed_data):
                raise ValueError("untracked or ignored source files are not allowed in delivery")


def binding(source: Path, working: Path, context: dict, var_file: str) -> dict:
    require_source(source, context["commit"], working)
    lockfile = working / ".terraform.lock.hcl"
    if not lockfile.is_file() or lockfile.is_symlink():
        raise ValueError("a committed provider lockfile is required")
    # Ensure the lock and selected variable file are tracked at the approved commit.
    tracked = [lockfile]
    variables = None
    if var_file:
        relative = Path(var_file)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("var-file must be relative and inside the Terraform directory")
        path = (working / relative).resolve(strict=True)
        if not path.is_relative_to(working) or not path.is_file():
            raise ValueError("var-file must resolve inside the Terraform directory")
        tracked.append(path)
        variables = {"path": var_file, "sha256": digest(path)}
    for path in tracked:
        subprocess.run(["git", "-C", str(source), "ls-files", "--error-unmatch", "--", str(path.relative_to(source))], check=True, capture_output=True)
    return {
        "schema": 1,
        "workspace": "default",
        "context": context,
        "terraform_version": TESTED_TERRAFORM_VERSION,
        "working_directory": str(working),
        "lockfile_sha256": digest(lockfile),
        "variables": variables,
    }


def verify_plan(bundle: Path, expected: dict) -> None:
    manifest_path = bundle / "manifest.json"
    trusted_digest = os.environ.get("TD_MANIFEST_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", trusted_digest) or manifest_path.is_symlink() or digest(manifest_path) != trusted_digest:
        raise ValueError("manifest checksum differs from the trusted plan-job output")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("binding") != expected:
        raise ValueError("saved plan context differs from this commit, run, identity, state, path or lockfile")
    created = manifest.get("created_at")
    if not isinstance(created, (int, float)) or not 0 <= time.time() - created <= MAX_PLAN_AGE_SECONDS:
        raise ValueError("saved plan is expired or has an invalid creation time; generate a new plan")
    plan = bundle / "tfplan"
    if plan.is_symlink() or not plan.is_file() or digest(plan) != manifest.get("plan_sha256"):
        raise ValueError("saved plan checksum mismatch")


def initialise(working: Path, context: dict, env: dict) -> None:
    version = subprocess.run(["terraform", "version", "-json"], check=True, capture_output=True, text=True, env=env, cwd=working)
    if json.loads(version.stdout).get("terraform_version") != TESTED_TERRAFORM_VERSION:
        raise ValueError("Terraform version differs from the tested plan/apply version")
    subprocess.run([
        "terraform", "init", "-input=false", "-no-color", "-lockfile=readonly", "-reconfigure",
        "-backend-config=use_oidc=true", "-backend-config=use_azuread_auth=true",
        f"-backend-config=storage_account_name={context['storage_account']}",
        f"-backend-config=container_name={context['container']}",
        f"-backend-config=key={context['key']}",
    ], check=True, env=env, cwd=working)
    metadata = json.loads((working / ".terraform" / "terraform.tfstate").read_text())
    backend = metadata.get("backend", {})
    configuration = backend.get("config", {})
    if backend.get("type") != "azurerm" or any(
        configuration.get(field) != context[key]
        for field, key in [("storage_account_name", "storage_account"), ("container_name", "container"), ("key", "key")]
    ):
        raise ValueError("initialized backend does not match the Azure state binding")
    workspace = subprocess.run(["terraform", "workspace", "show"], check=True, capture_output=True, text=True, env=env, cwd=working).stdout.strip()
    if workspace != "default":
        raise ValueError("delivery supports only the default Terraform workspace")


def execute(operation: str, source: Path, directory: str, bundle: Path, var_file: str = "") -> None:
    source = source.resolve(strict=True)
    working = contained_directory(source, directory)
    context = context_from_environment()
    expected = binding(source, working, context, var_file)
    bundle = bundle.resolve()
    if bundle == working or bundle.is_relative_to(working):
        raise ValueError("plan bundle must be outside the Terraform configuration")
    if operation in ("verify", "apply"):
        # Verify BEFORE cloud initialization or Terraform execution.
        verify_plan(bundle, expected)
    if operation == "verify":
        print("Saved plan context and checksum verified.")
        return
    env = environment(working, context, operation)
    initialise(working, context, env)
    if binding(source, working, context, var_file) != expected:
        raise ValueError("configuration changed during initialization")
    if operation == "plan":
        bundle.mkdir(parents=True, exist_ok=True)
        if any(bundle.iterdir()):
            raise ValueError("plan bundle must be empty; refusing to overwrite another plan")
        command = ["terraform", "plan", "-input=false", "-no-color", "-lock-timeout=5m", "-detailed-exitcode", f"-out={bundle / 'tfplan'}"]
        if var_file:
            command.append(f"-var-file={var_file}")
        result = subprocess.run(command, env=env, cwd=working)
        if result.returncode not in (0, 2):
            raise subprocess.CalledProcessError(result.returncode, command)
        manifest = {"binding": expected, "created_at": time.time(), "plan_sha256": digest(bundle / "tfplan")}
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        manifest_digest = digest(bundle / "manifest.json")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.write(f"manifest-sha256={manifest_digest}\n")
        print("Private plan bundle prepared. Review the plan log before approving apply.")
    elif operation == "apply":
        # Recheck immediately before apply, including the two-hour expiry.
        verify_plan(bundle, expected)
        subprocess.run(["terraform", "apply", "-input=false", "-no-color", "-lock-timeout=5m", str(bundle / "tfplan")], check=True, env=env, cwd=working)
    else:
        raise ValueError("unknown operation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["plan", "verify", "apply"])
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--directory", default=".")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--var-file", default="")
    args = parser.parse_args()
    try:
        execute(args.operation, args.source_root, args.directory, args.bundle, args.var_file)
    except (ValueError, OSError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        # Never echo subprocess output, environment values or plan contents here.
        print(f"Delivery rejected: {type(error).__name__}: {str(error) if not isinstance(error, subprocess.CalledProcessError) else 'required command failed'}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
