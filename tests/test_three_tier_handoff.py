import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/azure"))
import three_tier_handoff as handoff
import test_platform_handoff as fixtures


class ThreeTierHandoffTests(unittest.TestCase):
    def setUp(self):
        fixtures.WorkloadHandoffTests.setUp(self)
        for target in self.template["targets"]:
            target["overlay"] = f"deploy/azure-workload/overlays/pprd/uks/{target['slot']}"
        self.aks["workload_identities"]["value"]["platform-demo"]["principal_id"] = self.client
        self.vault = f"/subscriptions/{self.workload}/resourceGroups/vault-rg/providers/Microsoft.KeyVault/vaults/actual-vault"
        self.aks["workload_identities"]["value"]["platform-demo"]["role_assignments"] = {
            "vault": {"scope": self.vault, "role_definition_name": "Key Vault Secrets User", "principal_id": self.client}
        }
        self.platform = {"schema_version": 1, "tenant_id": self.tenant, "targets": [
            {key: t[key] for key in ["environment", "region", "slot", "subscription_id", "resource_group", "cluster_name"]} |
            {"approval_environment": "platform-pprd-uks-" + t["slot"],
             "workload_service_accounts": [{"name": "platform-demo", "namespace": "platform-demo", "client_id": "placeholder"}]}
            for t in self.template["targets"]
        ]}
        self.identities = {"identities": {"sensitive": False, "value": {
            key: {
                "id": f"/subscriptions/{self.workload}/resourceGroups/ci/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{key}",
                "client_id": f"00000000-0000-0000-0000-0000000000{suffix}",
                "principal_id": f"00000000-0000-0000-0000-0000000001{suffix}",
                "subscription_id": self.workload, "purpose": purpose, "environment": "pprd", "region": "uks", "tenant_id": self.tenant,
            } for key, purpose, suffix in [("platform", "platform", "11"), ("application", "application", "12")]
        }}}

    def pack(self):
        return handoff.application_files(self.template, self.platform, self.aks, self.registry,
                                         self.delivery, "pprd", "uks", "platform-demo", "app",
                                         self.vault, "real-tls", "real-qualification")

    def ci(self):
        return handoff.ci_principals(self.identities, "pprd", "uks", self.tenant, "platform",
                                    "application", "platform-demo", ["aks01", "aks02"])

    def test_one_applied_identity_reaches_both_platform_slots_and_app_profiles(self):
        originals = copy.deepcopy((self.template, self.platform))
        files = self.pack()
        self.assertEqual(originals, (self.template, self.platform))
        platform = files["platform/platform.services.json"]
        self.assertEqual([t["cluster_name"] for t in platform["targets"]], ["actual-aks01", "actual-aks02"])
        self.assertTrue(all(t["workload_service_accounts"][0]["client_id"] == self.client
                            for t in platform["targets"]))
        expected = files["application/azure.workload.json"]
        self.assertEqual([t["slot"] for t in expected["targets"]], ["aks01", "aks02"])
        self.assertTrue(all(t["client_id"] == self.client and t["vault_name"] == "actual-vault"
                            for t in expected["targets"]))
        tls = files["application/deploy/azure-workload/base/tls-identity.patch.yaml"]["spec"]
        self.assertEqual(tls["parameters"]["clientID"], self.client)
        self.assertEqual(tls["secretObjects"][0]["data"][0]["objectName"], "real-tls")
        app = files["application/deploy/azure-workload/base/application-secret-provider-class.yaml"]["spec"]
        self.assertNotIn("secretObjects", app)
        self.assertIn("objectName: real-qualification", app["parameters"]["objects"])

    def test_wrong_vault_grant_or_missing_federation_stops_handoff(self):
        roles = self.aks["workload_identities"]["value"]["platform-demo"]["role_assignments"]
        roles["vault"]["scope"] = self.vault + "-different"
        with self.assertRaisesRegex(ValueError, "exact vault"):
            self.pack()
        roles["vault"]["scope"] = self.vault
        del self.aks["workload_identities"]["value"]["platform-demo"]["federated_credentials"]["aks02"]
        with self.assertRaisesRegex(ValueError, "credential"):
            self.pack()

    def test_platform_and_application_slot_set_must_match(self):
        self.platform["targets"].pop()
        with self.assertRaisesRegex(ValueError, "same selected slots"):
            self.pack()

    def test_ci_principals_preserve_distinct_purposes_and_scope(self):
        principals = self.ci()["delivery_principals"]
        self.assertEqual(principals["application"]["namespaces"], ["platform-demo"])
        self.assertEqual(principals["platform"]["namespaces"], [])
        self.assertEqual(principals["application"]["clusters"], ["aks01", "aks02"])

    def test_wrong_environment_or_purpose_cannot_be_reused(self):
        identity = self.identities["identities"]["value"]["application"]
        for key, invalid in [("environment", "prd"), ("region", "ukw"), ("purpose", "build")]:
            value = identity[key]
            identity[key] = invalid
            with self.assertRaisesRegex(ValueError, "purpose, target"):
                self.ci()
            identity[key] = value

    def test_existing_output_and_symlink_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "pack"
            handoff.write_pack(directory, self.pack())
            before = (directory / "workload.private.json").read_bytes()
            with self.assertRaises(FileExistsError):
                handoff.write_pack(directory, self.pack())
            self.assertEqual(before, (directory / "workload.private.json").read_bytes())
            link = Path(temp) / "link"
            link.symlink_to(directory, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic"):
                handoff.write_pack(link / "new", self.pack())
            self.assertFalse((directory / "new").exists())

    def test_sensitive_snapshot_cannot_be_exported(self):
        self.identities["identities"]["sensitive"] = True
        with self.assertRaises(ValueError):
            self.ci()
