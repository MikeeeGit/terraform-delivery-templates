#!/usr/bin/env python3
"""Migrate the bootstrap's existing local state after explicit confirmation."""
import argparse, json, subprocess, sys
from pathlib import Path


def tf(root, *args):
    return subprocess.check_output(["terraform", *args], cwd=root, text=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, default=Path(__file__).parent / "backend")
    p.add_argument("--environment", default="hub")
    a = p.parse_args()
    root = a.directory.resolve(strict=True)
    if not (root / "terraform.tfstate").is_file():
        raise ValueError("an existing local bootstrap state is required")
    if (root / "remote-backend.tf").exists():
        raise ValueError(
            "remote-backend.tf exists; inspect current initialization before retrying"
        )
    before = json.loads(tf(root, "state", "pull"))
    settings = json.loads(tf(root, "output", "-json", "backends"))[a.environment]
    settings["key"] = "terraform-delivery-bootstrap.tfstate"
    print(
        "Migrate bootstrap state to the selected existing backend. Keep the local backup until verification and recovery testing are complete."
    )
    if not sys.stdin.isatty() or input("Type migrate to continue: ") != "migrate":
        raise ValueError("migration cancelled")
    config = root / ".backend.generated.hcl"
    config.write_text(
        "\n".join(f"{key} = {json.dumps(value)}" for key, value in settings.items())
        + "\n"
    )
    (root / "remote-backend.tf").write_text('terraform {\n  backend "azurerm" {}\n}\n')
    subprocess.run(
        ["terraform", "init", "-migrate-state", "-backend-config=" + str(config)],
        cwd=root,
        check=True,
    )
    after = json.loads(tf(root, "state", "pull"))
    for key in ("lineage", "serial", "resources"):
        if before.get(key) != after.get(key):
            raise ValueError(
                "migration verification differs; preserve both states and investigate before applying"
            )
    print(
        "Remote state lineage, serial and resource data match. Local state/backup files were not removed."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("Migration stopped: " + str(error))
