#!/usr/bin/env python3
"""Optional installed-tool checks; no curl-to-shell or unpinned downloads."""
import argparse, shutil, subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--directory", default=".")
p.add_argument("--enforce", action="store_true")
a = p.parse_args()
commands = [
    ["tflint", "--recursive"],
    ["checkov", "-d", ".", "--compact"],
    ["trivy", "config", ".", "--exit-code", "1"],
]
failed = False
for command in commands:
    if not shutil.which(command[0]):
        print("Unavailable optional scanner:", command[0])
        failed = True
        continue
    if subprocess.run(command, cwd=a.directory).returncode:
        failed = True
if failed and a.enforce:
    raise SystemExit(1)
if failed:
    print("Scans were incomplete or found issues (advisory mode).")
