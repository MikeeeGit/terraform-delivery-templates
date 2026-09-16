#!/usr/bin/env python3
"""Run backend-free Terraform checks in an isolated data directory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

TESTED_TERRAFORM_VERSION = (Path(__file__).resolve().parents[1] / ".terraform-version").read_text().strip()


def contained_directory(root: Path, relative: str) -> Path:
    """Resolve a caller path without allowing traversal or symlink escapes."""
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("directory must be a non-empty relative path without '..'")
    resolved = (root / candidate).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ValueError("directory must resolve inside the source root")
    return resolved


def validate(source_root: Path, directory: str, test_directory: str = "") -> None:
    source_root = source_root.resolve(strict=True)
    working = contained_directory(source_root, directory)
    if not any(working.glob("*.tf")) and not any(working.glob("*.tf.json")):
        raise ValueError("working directory contains no Terraform configuration")
    if test_directory:
        tests = contained_directory(working, test_directory)
        if not any(tests.glob("*.tftest.hcl")) and not any(tests.glob("*.tftest.json")):
            raise ValueError("test directory contains no Terraform tests")

    env = os.environ.copy()
    # Caller-supplied default flags could override the fixed command contract.
    for name in list(env):
        if name == "TF_CLI_ARGS" or name.startswith("TF_CLI_ARGS_"):
            del env[name]
    env.update(TF_IN_AUTOMATION="true", TF_INPUT="false")
    version = subprocess.run(
        ["terraform", "version", "-json"], check=True, capture_output=True,
        text=True, env=env, cwd=working,
    )
    if json.loads(version.stdout).get("terraform_version") != TESTED_TERRAFORM_VERSION:
        raise ValueError(f"Terraform {TESTED_TERRAFORM_VERSION} is required; install the tested version")

    with tempfile.TemporaryDirectory(prefix="terraform-validation-") as data_dir:
        env["TF_DATA_DIR"] = data_dir
        commands = [
            ["terraform", "fmt", "-check", "-recursive", "-diff"],
            ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
            ["terraform", "validate", "-no-color"],
        ]
        if (working / ".terraform.lock.hcl").exists():
            commands[1].append("-lockfile=readonly")
        if test_directory:
            commands.append(["terraform", "test", "-no-color", f"-test-directory={test_directory}"])
        for command in commands:
            print("Running " + " ".join(command[:2]), flush=True)
            subprocess.run(command, cwd=working, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--directory", default=".")
    parser.add_argument("--test-directory", default="", help="Opt in to known credential-free tests")
    args = parser.parse_args()
    try:
        validate(args.source_root, args.directory, args.test_directory)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Validation configuration error: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        print(f"Terraform command failed with exit code {error.returncode}", file=sys.stderr)
        return error.returncode if error.returncode > 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
