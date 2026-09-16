"""Verify plan integrity without any cloud requests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import deploy_azure as delivery


class SavedPlanContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.bundle = self.base / "bundle"
        self.bundle.mkdir()
        self.plan = self.bundle / "tfplan"
        self.plan.write_bytes(b"synthetic saved plan; never executed")
        self.expected = {
            "context": {"commit": "a" * 40, "key": "sandbox.tfstate", "run": "123:1"},
            "lockfile_sha256": "reviewed-lock-digest",
            "terraform_version": delivery.TESTED_TERRAFORM_VERSION,
        }
        self.write_manifest()
        self.env = patch.dict(os.environ, {"TD_MANIFEST_SHA256": delivery.digest(self.bundle / "manifest.json")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write_manifest(self, age=0):
        (self.bundle / "manifest.json").write_text(json.dumps({
            "binding": self.expected,
            "created_at": time.time() - age,
            "plan_sha256": delivery.digest(self.plan),
        }))

    def test_valid_bound_plan_is_accepted(self):
        delivery.verify_plan(self.bundle, self.expected)

    def test_modified_plan_is_rejected(self):
        self.plan.write_bytes(b"different plan")
        with self.assertRaisesRegex(ValueError, "checksum"):
            delivery.verify_plan(self.bundle, self.expected)

    def test_replaced_plan_and_manifest_cannot_replace_trusted_job_digest(self):
        self.plan.write_bytes(b"attacker plan")
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "trusted plan-job"):
            delivery.verify_plan(self.bundle, self.expected)

    def test_changed_commit_state_run_or_lockfile_is_rejected(self):
        for key, value in (("commit", "b" * 40), ("key", "production.tfstate"), ("run", "123:2")):
            changed = json.loads(json.dumps(self.expected))
            changed["context"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "context"):
                delivery.verify_plan(self.bundle, changed)
        with self.assertRaisesRegex(ValueError, "context"):
            delivery.verify_plan(self.bundle, dict(self.expected, lockfile_sha256="unreviewed"))

    def test_expired_and_future_dated_plans_are_rejected(self):
        for age in (delivery.MAX_PLAN_AGE_SECONDS + 1, -60):
            self.write_manifest(age)
            with patch.dict(os.environ, {"TD_MANIFEST_SHA256": delivery.digest(self.bundle / "manifest.json")}):
                with self.subTest(age=age), self.assertRaisesRegex(ValueError, "expired"):
                    delivery.verify_plan(self.bundle, self.expected)

    def test_symlinked_plan_is_rejected(self):
        target = self.base / "other-plan"
        target.write_bytes(self.plan.read_bytes())
        self.plan.unlink()
        self.plan.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "checksum"):
            delivery.verify_plan(self.bundle, self.expected)

    def test_failed_verification_never_initializes_or_applies(self):
        self.plan.write_bytes(b"tampered")
        with patch.object(delivery, "context_from_environment", return_value={}), patch.object(delivery, "binding", return_value=self.expected), patch.object(delivery, "initialise") as init, patch.object(delivery.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                delivery.execute("apply", self.source, ".", self.bundle)
        init.assert_not_called()
        run.assert_not_called()

    def test_apply_uses_only_verified_binary_plan_with_locking(self):
        with patch.object(delivery, "context_from_environment", return_value={}), patch.object(delivery, "binding", return_value=self.expected), patch.object(delivery, "environment", return_value={}), patch.object(delivery, "initialise"), patch.object(delivery.subprocess, "run") as run:
            delivery.execute("apply", self.source, ".", self.bundle)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["terraform", "apply"])
        self.assertEqual(command[-1], str(self.plan))
        self.assertIn("-lock-timeout=5m", command)
        self.assertNotIn("-lock=false", command)
        self.assertEqual(run.call_count, 1)

    def test_plan_exit_code_two_records_plan_and_separate_manifest_digest(self):
        fresh = self.base / "fresh-bundle"
        output = self.base / "job-output"
        def fake_plan(command, **kwargs):
            plan_path = next(arg.split("=", 1)[1] for arg in command if arg.startswith("-out="))
            Path(plan_path).write_bytes(b"mock plan with changes")
            return subprocess.CompletedProcess(command, 2)
        with patch.object(delivery, "context_from_environment", return_value={}), patch.object(delivery, "binding", return_value=self.expected), patch.object(delivery, "environment", return_value={}), patch.object(delivery, "initialise"), patch.object(delivery.subprocess, "run", side_effect=fake_plan), patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
            delivery.execute("plan", self.source, ".", fresh)
        trusted_digest = output.read_text().strip().split("=", 1)[1]
        with patch.dict(os.environ, {"TD_MANIFEST_SHA256": trusted_digest}):
            delivery.verify_plan(fresh, self.expected)

    def test_plan_failure_does_not_produce_an_approvable_manifest(self):
        fresh = self.base / "failed-bundle"
        with patch.object(delivery, "context_from_environment", return_value={}), patch.object(delivery, "binding", return_value=self.expected), patch.object(delivery, "environment", return_value={}), patch.object(delivery, "initialise"), patch.object(delivery.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(subprocess.CalledProcessError):
                delivery.execute("plan", self.source, ".", fresh)
        self.assertFalse((fresh / "manifest.json").exists())

    def test_extra_flags_removed_workspace_forced_and_identity_checked(self):
        context = {"plan_client_id": "plan-id", "apply_client_id": "apply-id", "tenant_id": "tenant", "subscription_id": "subscription"}
        env = {"ARM_CLIENT_ID": "apply-id", "ARM_TENANT_ID": "tenant", "ARM_SUBSCRIPTION_ID": "subscription", "ARM_USE_OIDC": "true", "ARM_USE_AZUREAD": "true", "TF_CLI_ARGS_apply": "-lock=false", "TF_WORKSPACE": "production", "TF_VAR_unbound": "unreviewed"}
        with patch.dict(os.environ, env):
            cleaned = delivery.environment(self.source, context, "apply")
            self.assertNotIn("TF_CLI_ARGS_apply", cleaned)
            self.assertEqual(cleaned["TF_WORKSPACE"], "default")
            self.assertNotIn("TF_VAR_unbound", cleaned)
            with self.assertRaisesRegex(ValueError, "ARM_CLIENT_ID"):
                delivery.environment(self.source, context, "plan")

    def test_backend_metadata_must_match_target(self):
        metadata = self.source / ".terraform"
        metadata.mkdir()
        (metadata / "terraform.tfstate").write_text(json.dumps({"backend": {"type": "local", "config": {}}}))
        context = {"storage_account": "examplestate", "container": "state", "key": "sandbox.tfstate"}
        version = subprocess.CompletedProcess([], 0, stdout=json.dumps({"terraform_version": delivery.TESTED_TERRAFORM_VERSION}))
        with patch.object(delivery.subprocess, "run", return_value=version):
            with self.assertRaisesRegex(ValueError, "backend"):
                delivery.initialise(self.source, context, {})

    def test_untracked_and_ignored_inputs_are_rejected(self):
        for ignored in (False, True):
            def git(command, **kwargs):
                result = ""
                if "rev-parse" in command:
                    result = "a" * 40
                if "--others" in command and ("--ignored" in command) == ignored:
                    result = "unreviewed.auto.tfvars\0"
                return subprocess.CompletedProcess(command, 0, stdout=result)
            with self.subTest(ignored=ignored), patch.object(delivery.subprocess, "run", side_effect=git):
                with self.assertRaisesRegex(ValueError, "untracked or ignored"):
                    delivery.require_source(self.source, "a" * 40, self.source)

    def test_tracked_symlinks_are_rejected(self):
        (self.source / "linked.tf").symlink_to(self.base / "external.tf")
        def git(command, **kwargs):
            output = "a" * 40 if "rev-parse" in command else "linked.tf\0" if "ls-files" in command else ""
            return subprocess.CompletedProcess(command, 0, stdout=output)
        with patch.object(delivery.subprocess, "run", side_effect=git):
            with self.assertRaisesRegex(ValueError, "symlinks"):
                delivery.require_source(self.source, "a" * 40, self.source)


if __name__ == "__main__":
    unittest.main()
