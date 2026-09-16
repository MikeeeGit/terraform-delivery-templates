#!/usr/bin/env python3
"""Install the checksum-pinned Terraform 1.16.3 Linux amd64 release."""
from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path
import platform
import tempfile
import urllib.request
import zipfile

VERSION = (Path(__file__).resolve().parents[1] / ".terraform-version").read_text().strip()
SHA256 = "093b6ae9a2228af5029c41606bc96eb583553528aad1bfe7e0b4d62fc91e25d8"
URL = f"https://releases.hashicorp.com/terraform/{VERSION}/terraform_{VERSION}_linux_amd64.zip"


def verified_binary(archive: bytes) -> bytes:
    if hashlib.sha256(archive).hexdigest() != SHA256:
        raise ValueError("Terraform archive checksum does not match the reviewed release")
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        # Read only the expected file; never extract arbitrary archive paths.
        return zipped.read("terraform")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        parser.error("this installer supports Linux amd64 only")
    with urllib.request.urlopen(URL, timeout=60) as response:
        binary = verified_binary(response.read())
    target = args.install_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target, delete=False) as output:
            temporary = Path(output.name)
            output.write(binary)
        temporary.chmod(0o755)
        os.replace(temporary, target / "terraform")
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    print(f"Installed checksum-verified Terraform {VERSION}")


if __name__ == "__main__":
    main()
