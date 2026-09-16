"""Exercise path, execution, failure and download-integrity boundaries."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load("validate")
installer = load("install_terraform")


class ValidationBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "main.tf").write_text("terraform {}\n")

    def test_traversal_and_absolute_paths_are_rejected(self):
        for path in ("../outside", str(self.root), "child/../../outside", ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validator.contained_directory(self.root, path)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                validator.contained_directory(self.root, "escape")

    def test_backend_is_disabled_lockfile_is_readonly_and_flags_are_isolated(self):
        (self.root / ".terraform.lock.hcl").touch()
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"terraform_version": "1.16.3"}))
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            return completed
        with patch.object(validator.subprocess, "run", side_effect=run), patch.dict(os.environ, {"TF_CLI_ARGS_init": "-backend=true"}):
            validator.validate(self.root, ".")
        init, options = next(c for c in calls if c[0][1] == "init")
        self.assertIn("-backend=false", init)
        self.assertIn("-lockfile=readonly", init)
        self.assertNotIn("TF_CLI_ARGS_init", options["env"])
        self.assertFalse(Path(options["env"]["TF_DATA_DIR"]).exists())
        self.assertFalse(any(c[0][1] in ("plan", "apply", "test") for c in calls))

    def test_shell_metacharacters_remain_a_single_literal_path(self):
        strange = self.root / "config; echo UNTRUSTED"
        strange.mkdir()
        (strange / "main.tf").write_text("terraform {}\n")
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"terraform_version": "1.16.3"}))
        with patch.object(validator.subprocess, "run", return_value=completed) as runner:
            validator.validate(self.root, strange.name)
        for call in runner.call_args_list:
            self.assertEqual(call.kwargs["cwd"], strange)
            self.assertIsInstance(call.args[0], list)
            self.assertNotIn("shell", call.kwargs)

    def test_failing_command_stops_later_validation(self):
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"terraform_version": "1.16.3"}))
        with patch.object(validator.subprocess, "run", side_effect=[completed, subprocess.CalledProcessError(7, ["terraform", "fmt"])]) as runner:
            with self.assertRaises(subprocess.CalledProcessError):
                validator.validate(self.root, ".")
        self.assertEqual(runner.call_count, 2)

    def test_wrong_terraform_version_fails_before_init(self):
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"terraform_version": "0.12.0"}))
        with patch.object(validator.subprocess, "run", return_value=completed) as runner:
            with self.assertRaises(ValueError):
                validator.validate(self.root, ".")
        self.assertEqual(runner.call_count, 1)

    def test_test_directory_escape_is_rejected_before_terraform_runs(self):
        with patch.object(validator.subprocess, "run") as runner:
            with self.assertRaises(ValueError):
                validator.validate(self.root, ".", "../outside")
        runner.assert_not_called()


class InstallerIntegrity(unittest.TestCase):
    def test_untrusted_archive_is_rejected_before_reading_zip(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            installer.verified_binary(b"tampered download")

    def test_only_terraform_member_is_read_from_verified_archive(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("terraform", b"expected binary")
            zipped.writestr("../../escape", b"must never be extracted")
        payload = archive.getvalue()
        with patch.object(installer, "SHA256", installer.hashlib.sha256(payload).hexdigest()):
            self.assertEqual(installer.verified_binary(payload), b"expected binary")


if __name__ == "__main__":
    unittest.main()
