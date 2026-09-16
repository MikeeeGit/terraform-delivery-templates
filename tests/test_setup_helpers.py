"""Cloud commands are mocked; setup review paths cannot mutate Azure."""

import contextlib, importlib.util, io, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


federate = module("federate", "initial-setup/azure/federate.py")
firewall = module("firewall", "scripts/azure/firewall.py")
dispatch = module("dispatch", "scripts/github/dispatch.py")


class FederationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "federation.json"
        self.data = json.loads(
            (ROOT / "initial-setup/azure/federation.json.example").read_text()
        )
        self.path.write_text(json.dumps(self.data))

    def test_review_never_calls_azure(self):
        with patch.object(
            federate.sys, "argv", ["federate", str(self.path)]
        ), patch.object(federate, "az") as az, contextlib.redirect_stdout(
            io.StringIO()
        ):
            federate.main()
        az.assert_not_called()

    def test_multiregion_credentials_are_distinct(self):
        credentials = federate.credentials(self.data["applications"][0])
        self.assertEqual(
            [x["name"] for x in credentials], ["hub-uks-plan", "hub-ukw-plan"]
        )
        self.assertTrue(
            all(x["audiences"] == ["api://AzureADTokenExchange"] for x in credentials)
        )

    def test_legacy_single_credential_supported(self):
        value = self.data["applications"][0]["federations"][0]
        self.assertEqual(len(federate.credentials({"federation": value})), 1)

    def test_duplicate_credential_names_rejected(self):
        value = self.data["applications"][0]["federations"][0]
        with self.assertRaises(ValueError):
            federate.credentials({"federations": [value, value]})

    def test_wrong_cli_tenant_stops_before_mutation(self):
        with patch.object(
            federate.sys, "argv", ["federate", str(self.path), "--apply"]
        ), patch.object(
            federate, "az", return_value={"tenantId": "wrong"}
        ) as az, contextlib.redirect_stdout(
            io.StringIO()
        ), self.assertRaises(
            ValueError
        ):
            federate.main()
        self.assertEqual(az.call_args_list[0].args[0], ["account", "show"])
        self.assertEqual(az.call_count, 1)

    def test_wrong_role_scope_tenant_stops_before_mutation(self):
        with patch.object(
            federate.sys, "argv", ["federate", str(self.path), "--apply"]
        ), patch.object(
            federate,
            "az",
            side_effect=[
                {"tenantId": self.data["tenant_id"]},
                {"tenantId": "wrong", "id": "wrong"},
            ],
        ) as az, contextlib.redirect_stdout(
            io.StringIO()
        ), self.assertRaises(
            ValueError
        ):
            federate.main()
        self.assertTrue(
            all(call.args[0][:2] == ["account", "show"] for call in az.call_args_list)
        )

    def test_existing_application_stops_before_creation(self):
        sub = self.data["applications"][0]["roles"][0]["scope"].split("/")[2]
        responses = [
            {"tenantId": self.data["tenant_id"]},
            {"tenantId": self.data["tenant_id"], "id": sub},
            [{"displayName": "existing"}],
        ]
        with patch.object(
            federate.sys, "argv", ["federate", str(self.path), "--apply"]
        ), patch.object(federate, "az", side_effect=responses) as az, patch.object(
            federate.sys.stdin, "isatty", return_value=True
        ), patch(
            "builtins.input", return_value="create"
        ), contextlib.redirect_stdout(
            io.StringIO()
        ), self.assertRaises(
            ValueError
        ):
            federate.main()
        self.assertFalse(any("create" in call.args[0] for call in az.call_args_list))


class FirewallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.context = root / "context.json"
        self.receipt = root / "receipt.json"
        self.context.write_text(
            json.dumps(
                {
                    "backend_subscription_id": "synthetic",
                    "backend": {
                        "resource_group": "example-rg",
                        "storage_account": "examplestate",
                    },
                }
            )
        )

    def invoke(self, operation, vault=""):
        with patch.object(
            firewall.sys if hasattr(firewall, "sys") else __import__("sys"),
            "argv",
            [
                "firewall",
                operation,
                "--context",
                str(self.context),
                "--receipt",
                str(self.receipt),
                "--ip",
                "203.0.113.10",
                "--key-vault",
                vault,
            ],
        ):
            firewall.main()

    def test_existing_rule_is_never_owned_or_removed(self):
        with patch.object(
            firewall,
            "az",
            return_value={"ipRules": [{"ipAddressOrRange": "203.0.113.10/32"}]},
        ) as az:
            self.invoke("add")
            self.assertEqual(json.loads(self.receipt.read_text()), [])
            self.invoke("cleanup")
        self.assertEqual(az.call_count, 1)

    def test_only_added_storage_and_vault_rules_are_removed(self):
        with patch.object(firewall, "az", return_value={"ipRules": []}) as az:
            self.invoke("add", "example-vault")
            self.assertEqual(len(json.loads(self.receipt.read_text())), 2)
            self.invoke("cleanup")
        commands = [call.args[0] for call in az.call_args_list]
        self.assertEqual(sum("remove" in command for command in commands), 2)
        self.assertFalse(self.receipt.exists())

    def test_failed_cleanup_keeps_recovery_receipt(self):
        self.receipt.write_text(
            json.dumps([["storage", "account", "network-rule", "remove"]])
        )
        with patch.object(
            firewall, "az", side_effect=subprocess.CalledProcessError(1, ["az"])
        ), self.assertRaises(RuntimeError):
            self.invoke("cleanup")
        self.assertTrue(self.receipt.exists())


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".terraform-delivery").mkdir()
        self.path = self.root / ".terraform-delivery/github.json"
        self.path.write_text(
            json.dumps(
                {
                    "repository": "example/private",
                    "workflow": "tf-validate.yml",
                    "branch": "main",
                    "run_id": "111",
                }
            )
        )

    def invoke(self, *args):
        with patch.object(dispatch.sys, "argv", ["dispatch", *args]), patch.object(
            dispatch.Path, "cwd", return_value=self.root
        ), contextlib.redirect_stdout(io.StringIO()):
            dispatch.main()

    def test_setup_resets_stale_repository_and_run(self):
        self.invoke("setup", "example/new-private", "tf-validate.yml", "main")
        data = json.loads(self.path.read_text())
        self.assertEqual(data["repository"], "example/new-private")
        self.assertNotIn("run_id", data)

    def test_apply_then_watch_tracks_exact_dispatched_run(self):
        with patch.object(
            dispatch.uuid, "uuid4", return_value="request-unique"
        ), patch.object(dispatch.sys.stdin, "isatty", return_value=True), patch(
            "builtins.input", return_value="yes"
        ), patch.object(
            dispatch,
            "gh",
            side_effect=[
                None,
                [
                    {
                        "databaseId": 456,
                        "displayTitle": "Apply request-unique",
                        "url": "https://example.invalid/run/456",
                    }
                ],
            ],
        ) as gh:
            self.invoke("apply", "pprd", "uks")
        self.assertEqual(json.loads(self.path.read_text())["workflow"], "tf-apply.yml")
        with patch.object(dispatch, "gh") as gh:
            self.invoke("watch")
        self.assertEqual(
            gh.call_args.args[0],
            ["run", "watch", "456", "--repo", "example/private", "--exit-status"],
        )

    def test_watch_never_guesses_latest(self):
        data = json.loads(self.path.read_text())
        data.pop("run_id")
        self.path.write_text(json.dumps(data))
        with patch.object(dispatch, "gh") as gh, self.assertRaises(ValueError):
            self.invoke("watch")
        gh.assert_not_called()

    def test_noninteractive_apply_requires_confirmation(self):
        with patch.object(
            dispatch.sys.stdin, "isatty", return_value=False
        ), patch.object(dispatch, "gh") as gh, self.assertRaises(ValueError):
            self.invoke("apply")
        gh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
