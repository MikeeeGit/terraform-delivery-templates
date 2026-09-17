import copy
import importlib.util
from pathlib import Path
import unittest

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
