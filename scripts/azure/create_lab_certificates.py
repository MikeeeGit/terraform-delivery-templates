#!/usr/bin/env python3
"""Create short-lived example.test TLS material outside Git for a disposable lab."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

HOSTNAMES = ("web.example.test", "api.example.test", "preview.example.test", "private.example.test")
OUTPUT_FILES = (
    "ca.pem", "ca.key.pem", "backend.crt.pem", "backend.key.pem",
    "backend.chain.pem", "backend.secret.pem", "frontend.crt.pem",
    "frontend.key.pem", "frontend.chain.pem", "frontend.pfx", "manifest.json",
)


def openssl(*arguments, input_data=None):
    """Capture command output; OpenSSL diagnostics/private material never reach logs."""
    try:
        result = subprocess.run(
            ["openssl", *map(str, arguments)], input=input_data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("OpenSSL could not complete the local certificate operation") from None
    if result.returncode:
        raise ValueError("OpenSSL certificate generation or verification failed")
    return result.stdout


def public_key_matches(certificate, key):
    cert_key = openssl("x509", "-in", certificate, "-pubkey", "-noout")
    cert_der = openssl("pkey", "-pubin", "-outform", "DER", input_data=cert_key)
    key_der = openssl("pkey", "-in", key, "-pubout", "-outform", "DER")
    if cert_der != key_der:
        raise ValueError("Certificate and private key do not match")


def certificate_hash(path):
    return hashlib.sha256(openssl("x509", "-in", path, "-outform", "DER")).hexdigest()


def validate_output_path(output):
    output = Path(output).expanduser()
    if not output.is_absolute() or ".." in output.parts:
        raise ValueError("Use a new absolute output directory without parent traversal")
    for parent in (output, *output.parents):
        if parent.is_symlink():
            raise ValueError("Symbolic output paths and ancestors are forbidden")
        if (parent / ".git").exists():
            raise ValueError("Certificate material must be generated outside every Git working tree")
    if output.exists():
        raise FileExistsError("Output directory already exists; existing material is never overwritten")
    if not output.parent.is_dir():
        raise ValueError("Create the private parent directory before generating certificates")
    return output


def generate(output, days=7):
    if os.name != "posix":
        raise ValueError("Run in Linux/WSL so private directory and file modes are enforced")
    if type(days) is not int or not 1 <= days <= 7:
        raise ValueError("Disposable certificates must be valid for 1-7 days")
    output = validate_output_path(output)
    original_umask = os.umask(0o077)
    created = False
    succeeded = False
    try:
        output.mkdir(mode=0o700)
        created = True
        with tempfile.TemporaryDirectory(prefix=".generation-", dir=output) as temporary:
            work = Path(temporary)
            ca, ca_key = work / "ca.pem", work / "ca.key.pem"
            openssl(
                "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256",
                "-days", days, "-subj", "/CN=Disposable example.test lab root",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                "-addext", "subjectKeyIdentifier=hash",
                "-keyout", ca_key, "-out", ca,
            )
            public_key_matches(ca, ca_key)
            openssl("verify", "-CAfile", ca, ca)
            extensions = work / "leaf.extensions"
            extensions.write_text(
                "basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\n"
                "extendedKeyUsage=serverAuth\n"
                "subjectKeyIdentifier=hash\n"
                "authorityKeyIdentifier=keyid,issuer\n"
                "subjectAltName=" + ",".join("DNS:" + host for host in HOSTNAMES) + "\n"
            )
            for name in ("backend", "frontend"):
                key, leaf = work / (name + ".key.pem"), work / (name + ".crt.pem")
                request = work / (name + ".csr.pem")
                openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
                        "-subj", "/CN=web.example.test", "-keyout", key, "-out", request)
                openssl("x509", "-req", "-in", request, "-CA", ca, "-CAkey", ca_key,
                        "-set_serial", hex(secrets.randbits(159) | 1), "-days", days,
                        "-sha256", "-extfile", extensions, "-out", leaf)
                public_key_matches(leaf, key)
                for host in HOSTNAMES:
                    openssl("verify", "-CAfile", ca, "-purpose", "sslserver",
                            "-verify_hostname", host, leaf)
                chain = leaf.read_bytes() + ca.read_bytes()
                (work / (name + ".chain.pem")).write_bytes(chain)
                if name == "backend":
                    (work / "backend.secret.pem").write_bytes(chain + key.read_bytes())
            # Empty password is intentional for disposable lab material. The PFX
            # contains a private key and is protected by private filesystem modes.
            openssl("pkcs12", "-export", "-in", work / "frontend.crt.pem",
                    "-inkey", work / "frontend.key.pem", "-certfile", ca,
                    "-name", "disposable-example-test-frontend", "-passout", "pass:",
                    "-out", work / "frontend.pfx")
            extracted_key, extracted_leaf = work / "checked.key.pem", work / "checked.crt.pem"
            extracted_ca = work / "checked.ca.pem"
            for selection, destination in [
                (["-nocerts", "-nodes"], extracted_key),
                (["-clcerts", "-nokeys"], extracted_leaf),
                (["-cacerts", "-nokeys"], extracted_ca),
            ]:
                openssl("pkcs12", "-in", work / "frontend.pfx", "-passin", "pass:",
                        *selection, "-out", destination)
            public_key_matches(extracted_leaf, extracted_key)
            if certificate_hash(extracted_leaf) != certificate_hash(work / "frontend.crt.pem") \
                    or certificate_hash(extracted_ca) != certificate_hash(ca):
                raise ValueError("PFX must retain the expected frontend leaf and CA")
            manifest = {
                "schema_version": 1, "purpose": "disposable-example-test-lab-only",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "validity_days": days, "hostnames": list(HOSTNAMES),
                "certificate_sha256": {
                    name: certificate_hash(work / filename)
                    for name, filename in [("ca", "ca.pem"), ("backend", "backend.crt.pem"),
                                           ("frontend", "frontend.crt.pem")]
                },
                "public_ca": "ca.pem", "backend_csi_secret": "backend.secret.pem",
                "frontend_key_vault_import": "frontend.pfx", "pfx_password": "empty",
                "validated": ["chain", "server-auth-purpose", "all-four-dns-sans",
                              "certificate-key-match", "pfx-key-leaf-and-ca"],
            }
            (work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            for filename in OUTPUT_FILES:
                path = work / filename
                path.chmod(0o600)
                path.rename(output / filename)
        succeeded = True
        return manifest
    finally:
        # Only a directory exclusively created by this invocation is removed.
        # CSR, extracted PFX keys and other intermediates never leave that tree.
        try:
            if created and not succeeded:
                shutil.rmtree(output)
        finally:
            os.umask(original_umask)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--days", type=int, default=7, choices=range(1, 8))
    args = parser.parse_args()
    generate(args.output_dir, args.days)
    print("Disposable example.test certificates generated and locally verified; keep the output private.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit("Certificate generation failed: " + str(error)) from None
