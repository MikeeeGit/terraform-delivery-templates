import copy
import importlib.util
from pathlib import Path
import unittest
import json
import tempfile

spec = importlib.util.spec_from_file_location(
    "platform_handoff", Path(__file__).resolve().parents[1] / "scripts/azure/platform_handoff.py"
)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tenant = "00000000-0000-0000-0000-000000000001"
        self.hub = "00000000-0000-0000-0000-000000000002"
        self.workload = "00000000-0000-0000-0000-000000000003"
        self.delivery = {"schema_version": 1, "tenant_id": self.tenant,
                         "subscriptions": {"hub": self.hub, "pprd": self.workload},
                         "environments": {"pprd": {"subscription_alias": "pprd"}},
                         "regions": ["uks", "ukw"]}
        wrap = lambda value: {"sensitive": False, "value": value}
        self.aks = {
            "deployment_context": wrap({"tenant_id": self.tenant, "subscription_id": self.workload,
                                         "environment": "pprd", "region": "uks"}),
            "clusters": wrap({
                slot: {"id": f"/subscriptions/{self.workload}/resourceGroups/actual-aks-rg/providers/Microsoft.ContainerService/managedClusters/actual-{slot}",
                       "name": f"actual-{slot}", "resource_group_name": "actual-aks-rg"}
                for slot in ("aks01", "aks02")
            }),
        }
        self.registry = {
            "acr_id": wrap(f"/subscriptions/{self.hub}/resourceGroups/actual-hub-rg/providers/Microsoft.ContainerRegistry/registries/actualexampleacr"),
            "acr_name": wrap("actualexampleacr"),
            "acr_login_server": wrap("actualexampleacr.azurecr.io"),
        }
        self.template = {
            "schema_version": 1, "tenant_id": self.tenant,
            "registry": {"subscription_id": self.hub, "name": "placeholder", "login_server": "placeholder.azurecr.io", "repository": "aks-platform-demo"},
            "build": {"context": ".", "dockerfile": "Dockerfile", "image_name": "aks-platform-demo"},
            "targets": [{"environment": "pprd", "region": "uks", "slot": slot,
                         "subscription_id": self.workload, "namespace": "platform-demo",
                         "deployment": "platform-demo", "resource_group": "placeholder", "cluster_name": "placeholder",
                         "overlay": f"deploy/overlays/pprd/uks/{slot}", "approval_environment": f"pprd-uks-{slot}"}
                        for slot in ("aks01", "aks02")],
        }

    def export(self):
        return handoff.export_config(self.template, self.aks, self.registry, self.delivery, "pprd", "uks")

    def test_uses_actual_cluster_metadata_and_separate_registry_subscription(self):
        original = copy.deepcopy(self.template)
        result = self.export()
        self.assertEqual(self.template, original)
        self.assertEqual(result["targets"][1]["cluster_name"], "actual-aks02")
        self.assertEqual(result["targets"][1]["subscription_id"], self.workload)
        self.assertEqual(result["registry"]["subscription_id"], self.hub)
        self.assertEqual(result["registry"]["login_server"], "actualexampleacr.azurecr.io")
        self.assertEqual(result["targets"][0]["overlay"], "deploy/overlays/pprd/uks/aks01")

    def test_rejects_snapshot_from_another_target(self):
        for field, value in (("environment", "prd"), ("region", "ukw"), ("tenant_id", self.hub),
                             ("subscription_id", self.hub)):
            with self.subTest(field=field):
                original = self.aks["deployment_context"]["value"][field]
                self.aks["deployment_context"]["value"][field] = value
                with self.assertRaises(ValueError): self.export()
                self.aks["deployment_context"]["value"][field] = original

    def test_rejects_sensitive_outputs(self):
        self.aks["clusters"]["sensitive"] = True
        with self.assertRaises(ValueError): self.export()

    def test_rejects_missing_or_duplicate_slots(self):
        del self.aks["clusters"]["value"]["aks02"]
        with self.assertRaises(ValueError): self.export()
        self.template["targets"][1]["slot"] = "aks01"
        with self.assertRaises(ValueError): self.export()

    def test_rejects_resource_id_metadata_disagreement(self):
        self.aks["clusters"]["value"]["aks01"]["resource_group_name"] = "wrong-group"
        with self.assertRaises(ValueError): self.export()

    def test_rejects_unrelated_registry_subscription(self):
        self.registry["acr_id"]["value"] = self.registry["acr_id"]["value"].replace(
            self.hub, "00000000-0000-0000-0000-000000000099")
        with self.assertRaises(ValueError): self.export()

    def test_rejects_registry_login_server_disagreement(self):
        self.registry["acr_login_server"]["value"] = "different.azurecr.io"
        with self.assertRaises(ValueError): self.export()

    def test_does_not_export_unselected_environments_or_private_metadata(self):
        self.template["targets"].append(dict(self.template["targets"][0], environment="prd"))
        self.aks["unrelated_secret"] = {"sensitive": True, "value": "do-not-copy"}
        result = self.export()
        self.assertEqual(len(result["targets"]), 2)
        self.assertNotIn("unrelated_secret", result)


class WorkloadHandoffTests(unittest.TestCase):
    def setUp(self):
        HandoffTests.setUp(self)
        self.client = "00000000-0000-0000-0000-000000000009"
        for slot, cluster in self.aks["clusters"]["value"].items():
            cluster["oidc_issuer_url"] = f"https://uksouth.oic.prod-aks.azure.com/example/{slot}/"
        self.aks["workload_identities"] = {"sensitive": False, "value": {
            "platform-demo": {
                "id": f"/subscriptions/{self.workload}/resourceGroups/actual-aks-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/app",
                "client_id": self.client, "tenant_id": self.tenant,
                "service_accounts": {"app": {"namespace": "platform-demo", "service_account": "platform-demo",
                                               "clusters": ["aks01", "aks02"]}},
                "federated_credentials": {
                    slot: {"cluster": slot, "issuer": cluster["oidc_issuer_url"],
                           "subject": "system:serviceaccount:platform-demo:platform-demo",
                           "audience": ["api://AzureADTokenExchange"]}
                    for slot, cluster in self.aks["clusters"]["value"].items()
                },
            }
        }}

    def export(self):
        return HandoffTests.export(self)

    def workload_export(self):
        return handoff.export_workload(self.export(), self.aks, "platform-demo", "app")

    def identity(self):
        return self.aks["workload_identities"]["value"]["platform-demo"]

    def test_exports_actual_service_account_and_both_issuers(self):
        value = self.workload_export()
        self.assertEqual(value["service_account_manifest"]["metadata"]["annotations"]["azure.workload.identity/client-id"], self.client)
        self.assertEqual(value["secret_provider_parameters"]["clientID"], self.client)
        self.assertEqual({t["slot"] for t in value["targets"]}, {"aks01", "aks02"})
        self.assertEqual(len({t["issuer"] for t in value["targets"]}), 2)
        self.assertNotIn("principal_id", value)

    def test_rejects_identity_from_wrong_tenant_or_subscription(self):
        original = copy.deepcopy(self.identity())
        self.identity()["tenant_id"] = self.hub
        with self.assertRaises(ValueError): self.workload_export()
        self.aks["workload_identities"]["value"]["platform-demo"] = copy.deepcopy(original)
        self.identity()["id"] = self.identity()["id"].replace(self.workload, self.hub)
        with self.assertRaises(ValueError): self.workload_export()

    def test_rejects_control_plane_identity_type(self):
        self.identity()["id"] = self.aks["clusters"]["value"]["aks01"]["id"]
        with self.assertRaises(ValueError): self.workload_export()

    def test_rejects_namespace_or_missing_slot_federation(self):
        self.identity()["service_accounts"]["app"]["namespace"] = "other-app"
        with self.assertRaises(ValueError): self.workload_export()
        self.identity()["service_accounts"]["app"]["namespace"] = "platform-demo"
        self.identity()["service_accounts"]["app"]["clusters"] = ["aks01"]
        with self.assertRaises(ValueError): self.workload_export()

    def test_rejects_missing_or_wrong_applied_federation(self):
        for field, bad in (("issuer", "https://another.example/"), ("subject", "system:serviceaccount:other:other"),
                           ("audience", ["another-audience"]), ("cluster", "aks01")):
            with self.subTest(field=field):
                original = copy.deepcopy(self.identity()["federated_credentials"])
                self.identity()["federated_credentials"]["aks02"][field] = bad
                with self.assertRaises(ValueError): self.workload_export()
                self.identity()["federated_credentials"] = original
        del self.identity()["federated_credentials"]["aks02"]
        with self.assertRaises(ValueError): self.workload_export()

    def test_does_not_require_unused_slot(self):
        self.template["targets"] = self.template["targets"][:1]
        self.identity()["service_accounts"]["app"]["clusters"] = ["aks01"]
        del self.identity()["federated_credentials"]["aks02"]
        self.assertEqual(len(self.workload_export()["targets"]), 1)

    def test_workload_sensitive_output_rejected(self):
        self.aks["workload_identities"]["sensitive"] = True
        with self.assertRaises(ValueError): self.workload_export()

    def test_review_outputs_never_replace_existing_or_leave_partial_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, workload = root / "app.json", root / "workload.json"
            workload.write_text("existing-review")
            with self.assertRaises(FileExistsError):
                handoff.write_new_jsons([(app, {"app": True}), (workload, {"identity": True})])
            self.assertFalse(app.exists())
            self.assertEqual(workload.read_text(), "existing-review")
            with self.assertRaises(ValueError):
                handoff.write_new_jsons([(app, {}), (app, {})])
            handoff.write_new_jsons([(app, {"app": True})])
            self.assertEqual(json.loads(app.read_text()), {"app": True})
