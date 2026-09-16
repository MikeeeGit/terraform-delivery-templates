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
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"terraform_version": validator.TESTED_TERRAFORM_VERSION}))
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
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"terraform_version": validator.TESTED_TERRAFORM_VERSION}))
        with patch.object(validator.subprocess, "run", return_value=completed) as runner:
            validator.validate(self.root, strange.name)
        for call in runner.call_args_list:
            self.assertEqual(call.kwargs["cwd"], strange)
            self.assertIsInstance(call.args[0], list)
            self.assertNotIn("shell", call.kwargs)

    def test_failing_command_stops_later_validation(self):
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"terraform_version": validator.TESTED_TERRAFORM_VERSION}))
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


class ValidationVariableFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "main.tf").write_text("terraform {}\n")
        (self.root / "tests").mkdir()
        (self.root / "tests/basic.tftest.hcl").write_text('run "basic" { command = plan }\n')
        self.git("init", "--quiet")
        self.commit()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), "-c", "core.hooksPath=/dev/null",
             "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
            check=True, capture_output=True,
        )

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "fixture")

    def test_multiple_committed_files_only_reach_test_as_literal_arguments(self):
        names = ["base.tfvars", "region [dev]; echo harmless.tfvars"]
        for name in names:
            (self.root / name).write_text('environment = "dev"\n')
        self.commit()
        real_run = subprocess.run
        calls = []
        def run(command, **kwargs):
            if command[0] == "git":
                return real_run(command, **kwargs)
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"terraform_version": validator.TESTED_TERRAFORM_VERSION}))
        with patch.object(validator.subprocess, "run", side_effect=run):
            validator.validate(self.root, ".", "tests", names)
        test = next(command for command, _ in calls if command[1] == "test")
        self.assertEqual(test[-2:], [f"-var-file={name}" for name in names])
        for command, kwargs in calls:
            self.assertNotIn("shell", kwargs)
            if command[1] != "test":
                self.assertFalse(any(arg.startswith("-var-file") for arg in command))

    def test_traversal_absolute_empty_and_outside_paths_are_rejected(self):
        for name in ("../outside.tfvars", str(self.root / "absolute.tfvars"), "", "child/../../outside.tfvars"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validator.contained_var_files(self.root, self.root, [name])

    def test_untracked_and_staged_only_files_are_rejected(self):
        (self.root / "untracked.tfvars").write_text("value = 1\n")
        with self.assertRaisesRegex(ValueError, "committed"):
            validator.contained_var_files(self.root, self.root, ["untracked.tfvars"])
        self.git("add", "untracked.tfvars")
        with self.assertRaisesRegex(ValueError, "committed"):
            validator.contained_var_files(self.root, self.root, ["untracked.tfvars"])

    def test_symlink_files_and_directories_are_rejected_even_inside_source(self):
        (self.root / "real").mkdir()
        (self.root / "real/vars.tfvars").write_text("value = 1\n")
        (self.root / "link.tfvars").symlink_to("real/vars.tfvars")
        (self.root / "linked-directory").symlink_to("real", target_is_directory=True)
        for name in ("link.tfvars", "linked-directory/vars.tfvars"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "symlink"):
                validator.contained_var_files(self.root, self.root, [name])

    def test_outside_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / "outside.tfvars"
            path.write_text("value = 1\n")
            (self.root / "escape.tfvars").symlink_to(path)
            with self.assertRaisesRegex(ValueError, "symlink"):
                validator.contained_var_files(self.root, self.root, ["escape.tfvars"])

    def test_export_ignored_committed_file_is_rejected(self):
        (self.root / "ignored.tfvars").write_text("value = 1\n")
        (self.root / ".gitattributes").write_text("ignored.tfvars export-ignore\n")
        self.commit()
        with self.assertRaisesRegex(ValueError, "archive"):
            validator.contained_var_files(self.root, self.root, ["ignored.tfvars"])

    def test_nested_working_directory_uses_its_own_relative_files(self):
        working = self.root / "configuration"
        working.mkdir()
        (working / "target.tfvars").write_text("value = 1\n")
        self.commit()
        self.assertEqual(validator.contained_var_files(self.root, working, ["target.tfvars"]), ["target.tfvars"])
        with self.assertRaises(ValueError):
            validator.contained_var_files(self.root, working, ["../main.tf"])

    def test_directories_and_missing_files_are_rejected(self):
        with self.assertRaises(ValueError):
            validator.contained_var_files(self.root, self.root, ["tests"])
        with self.assertRaises(FileNotFoundError):
            validator.contained_var_files(self.root, self.root, ["missing.tfvars"])

    def test_var_files_without_tests_are_rejected_before_commands(self):
        with patch.object(validator.subprocess, "run") as runner:
            with self.assertRaisesRegex(ValueError, "test-directory"):
                validator.validate(self.root, ".", var_files=["anything.tfvars"])
        runner.assert_not_called()

    def test_cli_accepts_repeatable_var_file_flags(self):
        with patch.object(validator.sys, "argv", ["validate.py", "--source-root", str(self.root), "--test-directory", "tests", "--var-file=one.tfvars", "--var-file=two.tfvars"]), patch.object(validator, "validate") as checked:
            self.assertEqual(validator.main(), 0)
        checked.assert_called_once_with(self.root, ".", "tests", ["one.tfvars", "two.tfvars"])


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
