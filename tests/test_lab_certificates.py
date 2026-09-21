"""Actual OpenSSL checks for the disposable Azure certificate handoff."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/azure/create_lab_certificates.py"
SPEC = importlib.util.spec_from_file_location("lab_certificates", SCRIPT)
certificates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(certificates)


def run_openssl(*args):
    return subprocess.run(["openssl", *map(str, args)], check=False, capture_output=True)


class GeneratedCertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="lab-certificate-tests-")
        cls.root = Path(cls.temporary.name) / "certificates"
        cls.output = io.StringIO()
        with contextlib.redirect_stdout(cls.output), contextlib.redirect_stderr(cls.output):
            cls.manifest = certificates.generate(cls.root, days=2)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_actual_chain_server_purpose_and_each_reserved_hostname(self):
        for name in ("backend", "frontend"):
            for host in certificates.HOSTNAMES:
                result = run_openssl("verify", "-CAfile", self.root / "ca.pem", "-purpose", "sslserver",
                                     "-verify_hostname", host, self.root / (name + ".crt.pem"))
                self.assertEqual(result.returncode, 0, result.stderr.decode())
            for wrong in ("web.example.com", "unlisted.example.test"):
                result = run_openssl("verify", "-CAfile", self.root / "ca.pem",
                                     "-verify_hostname", wrong, self.root / (name + ".crt.pem"))
                self.assertNotEqual(result.returncode, 0)

    def test_certificate_keys_match_and_frontend_backend_keys_are_distinct(self):
        for name in ("ca", "backend", "frontend"):
            cert = self.root / ("ca.pem" if name == "ca" else name + ".crt.pem")
            certificates.public_key_matches(cert, self.root / (name + ".key.pem"))
        with self.assertRaisesRegex(ValueError, "do not match"):
            certificates.public_key_matches(self.root / "backend.crt.pem", self.root / "frontend.key.pem")

    def test_csi_bundle_contains_leaf_chain_and_key_loadable_by_tls(self):
        bundle = self.root / "backend.secret.pem"
        contents = bundle.read_bytes()
        self.assertEqual(contents.count(b"-----BEGIN CERTIFICATE-----"), 2)
        self.assertEqual(contents.count(b"-----BEGIN PRIVATE KEY-----"), 1)
        self.assertTrue(contents.startswith((self.root / "backend.crt.pem").read_bytes()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(bundle))
        certificates.public_key_matches(bundle, bundle)

    def test_frontend_pfx_preserves_leaf_private_key_and_ca(self):
        with tempfile.TemporaryDirectory(dir=self.temporary.name) as temporary:
            root = Path(temporary)
            for name, selection in (("leaf", ["-clcerts", "-nokeys"]),
                                    ("key", ["-nocerts", "-nodes"]), ("ca", ["-cacerts", "-nokeys"])):
                destination = root / (name + ".pem")
                destination.touch(mode=0o600)
                result = run_openssl("pkcs12", "-in", self.root / "frontend.pfx", "-passin", "pass:",
                                     *selection, "-out", destination)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
            certificates.public_key_matches(root / "leaf.pem", root / "key.pem")
            self.assertEqual(certificates.certificate_hash(root / "leaf.pem"),
                             certificates.certificate_hash(self.root / "frontend.crt.pem"))
            self.assertEqual(certificates.certificate_hash(root / "ca.pem"),
                             certificates.certificate_hash(self.root / "ca.pem"))

    def test_short_validity_only_reserved_sans_and_correct_ca_constraints(self):
        for name in ("backend", "frontend"):
            info = ssl._ssl._test_decode_cert(str(self.root / (name + ".crt.pem")))
            self.assertEqual(info["subjectAltName"], tuple(("DNS", host) for host in certificates.HOSTNAMES))
            validity = ssl.cert_time_to_seconds(info["notAfter"]) - ssl.cert_time_to_seconds(info["notBefore"])
            self.assertEqual(validity, 2 * 86400)
        ca_text = run_openssl("x509", "-in", self.root / "ca.pem", "-noout", "-text").stdout
        self.assertIn(b"CA:TRUE, pathlen:0", ca_text)
        leaf_text = run_openssl("x509", "-in", self.root / "backend.crt.pem", "-noout", "-text").stdout
        self.assertIn(b"CA:FALSE", leaf_text)
        self.assertIn(b"TLS Web Server Authentication", leaf_text)

    def test_private_permissions_manifest_and_no_logged_keys_or_intermediates(self):
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual({item.name for item in self.root.iterdir()}, set(certificates.OUTPUT_FILES))
        for path in self.root.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
        manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(manifest, self.manifest)
        self.assertNotIn("PRIVATE KEY", json.dumps(manifest))
        self.assertEqual(self.output.getvalue(), "")


class CertificateBoundaryTests(unittest.TestCase):
    def test_existing_output_is_not_modified_and_openssl_never_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / "keep"
            sentinel.write_text("existing data")
            with patch.object(certificates, "openssl") as openssl:
                with self.assertRaises(FileExistsError):
                    certificates.generate(root)
            openssl.assert_not_called()
            self.assertEqual(sentinel.read_text(), "existing data")

    def test_git_worktree_and_symlink_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for marker_kind in ("directory", "file"):
                git = root / marker_kind
                git.mkdir()
                marker = git / ".git"
                marker.mkdir() if marker_kind == "directory" else marker.write_text("gitdir: elsewhere")
                with self.assertRaisesRegex(ValueError, "outside every Git"):
                    certificates.generate(git / "certificates")
            actual = root / "actual"
            actual.mkdir()
            link = root / "link"
            link.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Symbolic"):
                certificates.generate(link / "certificates")
            self.assertEqual(list(actual.iterdir()), [])

    def test_relative_traversal_and_excessive_validity_are_rejected(self):
        for path in (Path("relative-certificates"), Path("/tmp/example/../certificates")):
            with self.assertRaisesRegex(ValueError, "absolute output"):
                certificates.generate(path)
        for days in (0, 8, 365, True, "7"):
            with self.assertRaisesRegex(ValueError, "1-7 days"):
                certificates.generate(Path("/not-created"), days)

    def test_failed_generation_removes_only_owned_output_and_restores_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / "keep"
            sentinel.write_text("existing data")
            original = os.umask(0o027)
            try:
                with patch.object(certificates, "openssl", side_effect=ValueError("failure")):
                    with self.assertRaisesRegex(ValueError, "failure"):
                        certificates.generate(root / "new")
                observed = os.umask(0o027)
                self.assertEqual(observed, 0o027)
            finally:
                os.umask(original)
            self.assertFalse((root / "new").exists())
            self.assertEqual(sentinel.read_text(), "existing data")

    def test_openssl_failure_does_not_expose_its_output(self):
        result = subprocess.CompletedProcess([], 1, stdout=b"private material", stderr=b"private material")
        with patch.object(certificates.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ValueError, "generation or verification failed") as error:
                certificates.openssl("req")
        self.assertNotIn("private material", str(error.exception))


if __name__ == "__main__":
    unittest.main()
