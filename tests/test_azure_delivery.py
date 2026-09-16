"""Cloud-free regression tests for reviewed local/CI safety boundaries."""

import contextlib, importlib.util, io, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


azure = module("azure_delivery", "scripts/azure/terraform.py")
guard = module("delivery_guard", "scripts/ci_guard.py")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "consumer"
        self.root.mkdir()
        self.bundle = Path(self.temp.name) / "bundle"
        self.bundle.mkdir()
        (self.root / "delivery.azure.json").write_text(
            (ROOT / "starter-templates/azure/delivery.azure.json").read_text()
        )
        (self.root / "main.tf").write_text("terraform {}\n")
        (self.root / ".terraform.lock.hcl").write_text("# reviewed lock\n")
        (self.root / "config/uks/pprd").mkdir(parents=True)
        (self.root / "config/global.tfvars").write_text('prefix = "example"\n')
        (self.root / "config/uks/pprd/pprd.tfvars").write_text('environment = "pprd"\n')
        (self.root / ".terraform-delivery").mkdir()
        (self.bundle / "tfplan").write_bytes(b"reviewed-plan")
        self.context = azure.resolve(self.root, "consumer", "pprd", "uks")
        patcher = patch.object(azure, "version", return_value="1.16.3")
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self):
        before = azure.binding(self.root, self.context)
        return azure.record(self.root, self.context, self.bundle, before=before)

    def git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True
        )

    def tracked(self):
        (self.root / ".gitignore").write_text(
            ".terraform/\n.terraform-delivery/\n*.auto.tfvars\n"
        )
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )

    def test_import_operands_after_options_are_literal_arguments(self):
        argv = [
            "terraform.py",
            "import",
            "--root",
            str(self.root),
            "--repository",
            "consumer",
            "--environment",
            "pprd",
            "--region",
            "uks",
            "--yes",
            'module.example["one"].resource.item',
            "/synthetic/resource-id",
        ]
        with patch.object(azure.sys, "argv", argv), patch.object(
            azure, "ensure_initialized"
        ), patch.object(azure, "run") as run:
            azure.main()
        self.assertEqual(
            run.call_args.args[0][-2:],
            ['module.example["one"].resource.item', "/synthetic/resource-id"],
        )

    def test_partial_selection_cannot_reuse_an_old_target(self):
        argv = [
            "terraform.py",
            "init",
            "--root",
            str(self.root),
            "--repository",
            "another",
        ]
        with patch.object(azure.sys, "argv", argv), self.assertRaises(ValueError):
            azure.main()

    def test_aliases_and_backend_are_independent(self):
        context = azure.resolve(self.root, "consumer", "bcdr", "ukw")
        self.assertEqual(context["subscription_alias"], "prd")
        self.assertEqual(context["backend_subscription_alias"], "hub")
        self.assertEqual(context["backend"]["key"], "consumer-bcdr-ukw.tfstate")
        self.assertEqual(
            context["backend"]["storage_account"], "ukwprdexampletfstatesa"
        )

    def test_override_backend_names(self):
        data = json.loads((self.root / "delivery.azure.json").read_text())
        data["environments"]["pprd"]["backend"] = {"key": "custom/pprd.tfstate"}
        (self.root / "delivery.azure.json").write_text(json.dumps(data))
        self.assertEqual(
            azure.resolve(self.root, "consumer", "pprd", "uks")["backend"]["key"],
            "custom/pprd.tfstate",
        )

    def test_unknown_selector_rejected(self):
        for env, region in [("qa", "uks"), ("pprd", "none")]:
            with self.assertRaises(ValueError):
                azure.resolve(self.root, "consumer", env, region)

    def test_shell_metacharacters_rejected(self):
        with self.assertRaises(ValueError):
            azure.resolve(self.root, "consumer;touch", "pprd", "uks")

    def test_config_cannot_escape_root(self):
        external = Path(self.temp.name) / "external.json"
        external.write_text((self.root / "delivery.azure.json").read_text())
        with self.assertRaises(ValueError):
            azure.resolve(self.root, "consumer", "pprd", "uks", "../external.json")

    def test_generated_storage_name_length_rejected(self):
        with self.assertRaises(ValueError):
            azure.resolve(self.root, "consumer", "pprd", "uks", prefix="toolongprefix")

    def test_varfiles_order(self):
        self.assertEqual(
            azure.var_files(self.root, self.context),
            ["config/global.tfvars", "config/uks/pprd/pprd.tfvars"],
        )

    def test_missing_target_variables_rejected(self):
        with self.assertRaises(FileNotFoundError):
            azure.var_files(
                self.root, azure.resolve(self.root, "consumer", "prd", "uks")
            )

    def test_environment_removes_cli_injection_and_stale_target(self):
        with patch.dict(
            os.environ,
            {
                "TF_CLI_ARGS_plan": "-lock=false",
                "TF_DATA_DIR": "/wrong",
                "TF_WORKSPACE": "wrong",
                "ARM_SUBSCRIPTION_ID": "wrong",
                "ARM_TENANT_ID": "wrong",
                "TF_VAR_unreviewed": "hidden",
            },
        ):
            env = azure.environment(self.context)
        self.assertNotIn("TF_VAR_unreviewed", env)
        self.assertNotIn("TF_CLI_ARGS_plan", env)
        self.assertNotIn("TF_DATA_DIR", env)
        self.assertEqual(env["TF_WORKSPACE"], "default")
        self.assertEqual(env["ARM_SUBSCRIPTION_ID"], self.context["subscription_id"])
        self.assertEqual(env["ARM_TENANT_ID"], self.context["tenant_id"])

    def test_strict_ci_rejects_ambient_terraform_variables(self):
        with patch.dict(os.environ, {"TF_VAR_unreviewed": "hidden"}), self.assertRaises(
            ValueError
        ):
            azure.reject_ambient_variables()

    def test_symlinked_variable_directory_rejected(self):
        original = self.root / "config/uks/pprd"
        renamed = self.root / "config/uks/real"
        original.rename(renamed)
        original.symlink_to(renamed, target_is_directory=True)
        with self.assertRaises(ValueError):
            azure.var_files(self.root, self.context)

    def test_stateful_operations_always_reconfigure(self):
        with patch.object(azure, "initialize") as initialize:
            azure.ensure_initialized(self.root, self.context)
            azure.ensure_initialized(self.root, self.context)
        self.assertEqual(initialize.call_count, 2)

    def test_init_has_lockfile_and_no_upgrade(self):
        with patch.object(azure, "select_account"), patch.object(
            azure, "verify_backend"
        ), patch.object(azure, "run") as run:
            azure.initialize(self.root, self.context)
        args = run.call_args.args[0]
        self.assertIn("-lockfile=readonly", args)
        self.assertNotIn("-upgrade", args)
        self.assertIn(
            "-backend-config=subscription_id="
            + self.context["backend_subscription_id"],
            args,
        )

    def test_upgrade_requires_explicit_argument(self):
        with patch.object(azure, "select_account"), patch.object(
            azure, "verify_backend"
        ), patch.object(azure, "run") as run:
            azure.initialize(self.root, self.context, True)
        self.assertIn("-upgrade", run.call_args.args[0])

    def test_backend_mismatch_rejected(self):
        (self.root / ".terraform").mkdir()
        (self.root / ".terraform/terraform.tfstate").write_text(
            json.dumps(
                {
                    "backend": {
                        "type": "azurerm",
                        "config": {"storage_account_name": "wrong"},
                    }
                }
            )
        )
        with self.assertRaises(ValueError):
            azure.verify_backend(self.root, self.context)

    def test_workspace_rejected(self):
        (self.root / ".terraform").mkdir()
        b = self.context["backend"]
        (self.root / ".terraform/terraform.tfstate").write_text(
            json.dumps(
                {
                    "backend": {
                        "type": "azurerm",
                        "config": {
                            "storage_account_name": b["storage_account"],
                            "container_name": b["container"],
                            "key": b["key"],
                            "use_azuread_auth": True,
                        },
                    }
                }
            )
        )
        with patch.object(azure, "run", return_value="unexpected"), self.assertRaises(
            ValueError
        ):
            azure.verify_backend(self.root, self.context)

    def test_bound_plan_is_accepted(self):
        digest = self.record()
        azure.verify(self.root, self.context, self.bundle, expected=digest)

    def test_changed_tfvars_are_rejected(self):
        digest = self.record()
        (self.root / "config/global.tfvars").write_text("changed=true")
        with self.assertRaises(ValueError):
            azure.verify(self.root, self.context, self.bundle, expected=digest)

    def test_replaced_plan_and_manifest_fail_separate_receipt(self):
        digest = self.record()
        (self.bundle / "tfplan").write_bytes(b"new")
        manifest = json.loads((self.bundle / "manifest.json").read_text())
        manifest["plan_sha256"] = azure.sha(self.bundle / "tfplan")
        (self.bundle / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            azure.verify(self.root, self.context, self.bundle, expected=digest)

    def test_plan_without_before_binding_rejected(self):
        with self.assertRaises(ValueError):
            azure.record(self.root, self.context, self.bundle)

    def test_source_mutation_during_plan_rejected(self):
        before = azure.binding(self.root, self.context)
        (self.root / "main.tf").write_text("changed")
        with self.assertRaises(ValueError):
            azure.record(self.root, self.context, self.bundle, before=before)

    def test_wrong_run_rejected(self):
        digest = self.record()
        with self.assertRaises(ValueError):
            azure.verify(
                self.root,
                self.context,
                self.bundle,
                run_id="different",
                expected=digest,
            )

    def test_expired_plan_rejected(self):
        with patch.object(azure.time, "time", return_value=1):
            digest = self.record()
        with self.assertRaises(ValueError):
            azure.verify(self.root, self.context, self.bundle, expected=digest)

    def test_symlink_source_rejected(self):
        (self.root / "override.tf").symlink_to(self.root / "main.tf")
        with self.assertRaises(ValueError):
            azure.source_fingerprint(self.root)

    def test_clean_git_source_and_managed_cache_accepted(self):
        self.tracked()
        (self.root / ".terraform").mkdir()
        (self.root / ".terraform/metadata.json").write_text("{}")
        azure.source_fingerprint(self.root, True)

    def test_untracked_override_rejected(self):
        self.tracked()
        (self.root / "override.tf").write_text("changed")
        with self.assertRaises(ValueError):
            azure.source_fingerprint(self.root, True)

    def test_ignored_tfvars_rejected(self):
        self.tracked()
        (self.root / "credentials.auto.tfvars").write_text("synthetic=true")
        with self.assertRaises(ValueError):
            azure.source_fingerprint(self.root, True)

    def test_untracked_symlink_into_cache_rejected(self):
        self.tracked()
        (self.root / ".terraform").mkdir()
        (self.root / ".terraform/payload.tf").write_text("changed")
        (self.root / "injected_override.tf").symlink_to(
            self.root / ".terraform/payload.tf"
        )
        with self.assertRaises(ValueError):
            azure.source_fingerprint(self.root, True)

    def test_confirmation_is_required_noninteractive(self):
        with patch.object(
            azure.sys.stdin, "isatty", return_value=False
        ), self.assertRaises(ValueError):
            azure.confirm("Confirm?", False)

    def test_explicit_yes_supported(self):
        azure.confirm("Confirm?", True)


class GuardTests(unittest.TestCase):
    def test_github_public_and_pr_calls_rejected(self):
        base = {
            "PRIVATE_REPOSITORY": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "TEMPLATE_REF": "a" * 40,
            "RUNNER_LABELS": '["ubuntu-24.04"]',
        }
        for extra in [
            {"PRIVATE_REPOSITORY": "false"},
            {"GITHUB_EVENT_NAME": "pull_request"},
            {"GITHUB_REF": "refs/heads/feature"},
        ]:
            with patch.dict(
                os.environ, {**base, **extra}, clear=True
            ), self.assertRaises(ValueError):
                guard.check("github")

    def test_github_superseded_commit_rejected(self):
        base = {
            "PRIVATE_REPOSITORY": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "TEMPLATE_REF": "a" * 40,
            "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_REPOSITORY": "example/private",
            "GH_TOKEN": "synthetic",
            "GITHUB_SHA": "b" * 40,
        }
        with patch.dict(os.environ, base, clear=True), patch.object(
            guard, "get", return_value={"object": {"sha": "c" * 40}}
        ), self.assertRaises(ValueError):
            guard.check("github", True)

    def test_azure_project_api_is_collection_scoped(self):
        base = {
            "BUILD_SOURCEBRANCH": "refs/heads/main",
            "BUILD_REPOSITORY_PROVIDER": "TfsGit",
            "SYSTEM_COLLECTIONURI": "https://dev.azure.com/example/",
            "SYSTEM_TEAMPROJECTID": "synthetic-project",
            "SYSTEM_ACCESSTOKEN": "synthetic",
        }
        with patch.dict(os.environ, base, clear=True), patch.object(
            guard, "get", return_value={"visibility": "private"}
        ) as get:
            guard.check("azure-devops")
        self.assertEqual(
            get.call_args.args[0],
            "https://dev.azure.com/example/_apis/projects/synthetic-project?api-version=7.1",
        )

    def test_azure_public_project_rejected(self):
        base = {
            "BUILD_SOURCEBRANCH": "refs/heads/main",
            "BUILD_REPOSITORY_PROVIDER": "TfsGit",
            "SYSTEM_COLLECTIONURI": "https://dev.azure.com/example/",
            "SYSTEM_TEAMPROJECTID": "synthetic-project",
            "SYSTEM_ACCESSTOKEN": "synthetic",
        }
        with patch.dict(os.environ, base, clear=True), patch.object(
            guard, "get", return_value={"visibility": "public"}
        ), self.assertRaises(ValueError):
            guard.check("azure-devops")


if __name__ == "__main__":
    unittest.main()
