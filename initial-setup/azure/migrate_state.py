#!/usr/bin/env python3
"""Migrate the bootstrap's existing local state after explicit confirmation."""
import argparse, json, os, subprocess, sys
from pathlib import Path


def tf(root, *args):
    return subprocess.check_output(["terraform", *args], cwd=root, text=True)


def verify_states(before, after):
    # Backend migration can write a new state snapshot and increment its serial.
    # Resource values, outputs and lineage must remain byte-for-byte equivalent
    # as JSON values; a larger jump is unexpected and requires investigation.
    for key in ("lineage", "resources", "outputs"):
        if before.get(key) != after.get(key):
            raise ValueError("migration changed " + key + "; preserve both states and investigate")
    old, new = before.get("serial"), after.get("serial")
    if (type(old) is not int or type(new) is not int or old < 0
            or new not in (old, old + 1)):
        raise ValueError("unexpected migration state serial; preserve both states and investigate")


def private_json(path, value):
    with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, default=Path(__file__).parent / "backend")
    p.add_argument("--environment", default="hub")
    p.add_argument("--operator-state", action="store_true",
                   help="Use the separate operator-only container declared by the bootstrap root")
    a = p.parse_args()
    root = a.directory.resolve(strict=True)
    if not (root / "terraform.tfstate").is_file():
        raise ValueError("an existing local bootstrap state is required")
    if (root / "remote-backend.tf").exists():
        raise ValueError(
            "remote-backend.tf exists; inspect current initialization before retrying"
        )
    before = json.loads(tf(root, "state", "pull"))
    settings = (json.loads(tf(root, "output", "-json", "operator_backend"))
                if a.operator_state else json.loads(tf(root, "output", "-json", "backends"))[a.environment])
    if not isinstance(settings, dict) or not settings:
        raise ValueError("selected backend is not configured; review the bootstrap outputs")
    settings["key"] = "terraform-delivery-bootstrap.tfstate"
    print(
        "Migrate bootstrap state to the selected existing backend. Keep the local backup until verification and recovery testing are complete."
    )
    if not sys.stdin.isatty() or input("Type migrate to continue: ") != "migrate":
        raise ValueError("migration cancelled")
    private_json(root / ".migration-before.tfstate", before)
    config = root / ".backend.generated.hcl"
    config.write_text(
        "\n".join(f"{key} = {json.dumps(value)}" for key, value in settings.items())
        + "\n"
    )
    config.chmod(0o600)
    (root / "remote-backend.tf").write_text('terraform {\n  backend "azurerm" {}\n}\n')
    subprocess.run(
        ["terraform", "init", "-migrate-state", "-backend-config=" + str(config)],
        cwd=root,
        check=True,
    )
    after = json.loads(tf(root, "state", "pull"))
    private_json(root / ".migration-after.tfstate", after)
    verify_states(before, after)
    print(
        "Remote state lineage, resource data and outputs match. Serial is unchanged "
        "or incremented once. Private recovery snapshots and local backups were retained."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("Migration stopped: " + str(error))
