#!/usr/bin/env python3
"""Run backend-free Terraform checks in an isolated data directory."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
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



def contained_var_files(source_root: Path, working: Path, relative_paths: list[str]) -> list[str]:
    """Require regular, non-symlink files included in the committed Git archive."""
    paths = []
    for relative in relative_paths:
        candidate = Path(relative)
        if not relative or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("var-file must be a non-empty relative path without '..'")
        path = working / candidate
        # Check every component before resolve(), including symlinks that point
        # back inside the permitted tree. No file content is printed or extracted.
        cursor = source_root
        for part in path.relative_to(source_root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("var-file must not use symlinks")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(working) or not resolved.is_file():
            raise ValueError("var-file must resolve to a regular file inside the Terraform directory")
        paths.append(resolved)

    if paths:
        names = [path.relative_to(source_root).as_posix() for path in paths]
        try:
            archive = subprocess.run(
                ["git", "--literal-pathspecs", "-C", str(source_root), "archive", "--format=tar", "HEAD", "--", *names],
                check=True, capture_output=True,
            )
            with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as contents:
                included = {member.name for member in contents.getmembers() if member.isfile()}
        except (subprocess.CalledProcessError, tarfile.TarError):
            raise ValueError("var-files must be committed files included in git archive HEAD") from None
        if any(name not in included for name in names):
            raise ValueError("var-files must be committed files included in git archive HEAD; export-ignore files are not supported")
    return [path.relative_to(working).as_posix() for path in paths]

def validate(source_root: Path, directory: str, test_directory: str = "", var_files: list[str] | None = None) -> None:
    source_root = source_root.resolve(strict=True)
    working = contained_directory(source_root, directory)
    if not any(working.glob("*.tf")) and not any(working.glob("*.tf.json")):
        raise ValueError("working directory contains no Terraform configuration")
    if test_directory:
        tests = contained_directory(working, test_directory)
        if not any(tests.glob("*.tftest.hcl")) and not any(tests.glob("*.tftest.json")):
            raise ValueError("test directory contains no Terraform tests")

    if var_files and not test_directory:
        raise ValueError("var-files require a test-directory; they are used only by terraform test")
    if var_files:
        cursor = source_root
        for part in Path(directory).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("var-file working directory must not use symlinks")
    test_var_files = contained_var_files(source_root, working, var_files or [])

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
            commands.append(["terraform", "test", "-no-color", f"-test-directory={test_directory}", *[f"-var-file={path}" for path in test_var_files]])
        for command in commands:
            print("Running " + " ".join(command[:2]), flush=True)
            subprocess.run(command, cwd=working, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--directory", default=".")
    parser.add_argument("--test-directory", default="", help="Opt in to known credential-free tests")
    parser.add_argument("--var-file", action="append", default=[], help="Repeatable committed variable file relative to directory; passed only to terraform test")
    args = parser.parse_args()
    try:
        validate(args.source_root, args.directory, args.test_directory, args.var_file)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Validation configuration error: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        print(f"Terraform command failed with exit code {error.returncode}", file=sys.stderr)
        return error.returncode if error.returncode > 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
