import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts/azure"
sys.path.insert(0, str(SCRIPTS))
import three_tier_cleanup as cleanup
import three_tier_retire_backend as backend


class CleanupGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.manifest = b"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: platform-demo\n  namespace: platform-demo\n"
        self.receipt = {
            "source_commit": "a" * 40,
            "manifest_sha256": hashlib.sha256(self.manifest).hexdigest(),
            "target": {"slot": "aks01", "namespace": "platform-demo",
                       "verification": {"ingress": {"gateway": "platform-demo-private"}}},
        }
        self.write_bundle()

    def write_bundle(self):
        (self.bundle / "manifest.yaml").write_bytes(self.manifest)
        (self.bundle / "release.json").write_text(json.dumps(self.receipt))

    def test_tampered_bundle_stops_before_cloud_access(self):
        (self.bundle / "manifest.yaml").write_bytes(self.manifest + b"# changed\n")
        with patch.object(cleanup, "kube_context") as context:
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                cleanup.services(self.bundle, self.root / "out", None, True)
        context.assert_not_called()

    def test_secret_and_cross_namespace_bundles_are_rejected(self):
        for manifest in (
            self.manifest.replace(b"Deployment", b"Secret"),
            self.manifest.replace(b"namespace: platform-demo", b"namespace: kube-system"),
            self.manifest.replace(b"name: platform-demo", b"name: another-app"),
        ):
            self.manifest = manifest
            self.receipt["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
            self.write_bundle()
            with self.assertRaisesRegex(ValueError, "unexpected cleanup objects"):
                cleanup.validate_bundle(self.bundle)

    def run_cleanup(self, execute, *, remaining_frontend=False):
        calls = []
        service = {"metadata": {"name": "envoy-owned", "namespace": "envoy-gateway-system",
                               "labels": {"gateway.envoyproxy.io/owning-gateway-name": "platform-demo-private",
                                          "gateway.envoyproxy.io/owning-gateway-namespace": "platform-demo"}},
                   "status": {"loadBalancer": {"ingress": [{"ip": "10.1.0.20"}]}}}
        reads = 0
        def read(args, *unused, **kwargs):
            nonlocal reads
            calls.append(args)
            if "services" in args:
                reads += 1
                return {"items": [service] if reads == 1 else []}
            if args[:3] == ["az", "network", "lb"]:
                return [{"frontendIPConfigurations": [{"privateIPAddress": "10.1.0.20"}]}] if remaining_frontend else []
            if args[0] == "helm":
                return [{"name": "envoy-gateway", "chart": "gateway-helm-v1.9.1"}]
            raise AssertionError(args)
        context = (self.receipt["target"], {"id": "owned-cluster", "nodeResourceGroup": "owned-nodes"},
                   self.root / "kubeconfig", ["kubectl", "--kubeconfig", "owned-context"], {})
        with patch.object(cleanup.tf, "PRIVATE", self.root), patch.object(cleanup, "kube_context", return_value=context), \
             patch.object(cleanup, "data", side_effect=read), patch.object(cleanup, "command", side_effect=lambda args, *a, **k: calls.append(args) or b""), \
             patch.object(cleanup.time, "monotonic", side_effect=[0, 400]):
            if remaining_frontend:
                with self.assertRaisesRegex(ValueError, "frontends remain"):
                    cleanup.services(self.bundle, self.root / "out", None, execute)
            else:
                cleanup.services(self.bundle, self.root / "out", None, execute)
        return calls

    def test_inventory_makes_no_removal_calls(self):
        calls = self.run_cleanup(False)
        self.assertFalse(any("delete" in c or "uninstall" in c for c in calls))
        self.assertFalse((self.root / "out/result.json").exists())

    def test_cloud_frontend_must_be_released_before_helm_uninstall(self):
        calls = self.run_cleanup(True)
        gateway = next(i for i,c in enumerate(calls) if "delete" in c and "gateway" in c)
        service_wait = next(i for i,c in enumerate(calls) if "wait" in c and "service/envoy-owned" in c)
        cloud = next(i for i,c in enumerate(calls) if c[:3] == ["az","network","lb"])
        helm = next(i for i,c in enumerate(calls) if "uninstall" in c)
        self.assertLess(gateway, service_wait)
        self.assertLess(service_wait, cloud)
        self.assertLess(cloud, helm)
        self.assertEqual(json.loads((self.root / "out/result.json").read_text())["status"], "removed")

    def test_stuck_cloud_frontend_preserves_controller(self):
        calls = self.run_cleanup(True, remaining_frontend=True)
        self.assertFalse(any("uninstall" in c for c in calls))
        self.assertFalse((self.root / "out/result.json").exists())

    def test_retry_checks_original_cloud_address_after_service_disappears(self):
        previous = self.root / "previous.json"
        previous.write_text(json.dumps({
            "slot": "aks01", "cluster_id": "owned-cluster", "node_resource_group": "owned-nodes",
            "source_commit": self.receipt["source_commit"], "manifest_sha256": self.receipt["manifest_sha256"],
            "gateway": "platform-demo-private", "frontend_addresses": ["10.81.0.20"],
        }))
        previous.chmod(0o600)
        context = (self.receipt["target"], {"id": "owned-cluster", "nodeResourceGroup": "owned-nodes"},
                   self.root / "kubeconfig", ["kubectl"], {})
        calls = []
        def read(args, *unused):
            calls.append(args)
            if "services" in args: return {"items": []}
            if args[:3] == ["az", "network", "lb"]:
                return [{"frontendIPConfigurations": [{"privateIPAddress": "10.81.0.20"}]}]
            raise AssertionError(args)
        with patch.object(cleanup.tf, "PRIVATE", self.root), patch.object(cleanup, "kube_context", return_value=context), \
             patch.object(cleanup, "data", side_effect=read), patch.object(cleanup, "command", return_value=b""), \
             patch.object(cleanup.time, "monotonic", side_effect=[0, 400]):
            with self.assertRaisesRegex(ValueError, "frontends remain"):
                cleanup.services(self.bundle, self.root / "retry", None, True, previous)
        self.assertTrue(any(c[:3] == ["az", "network", "lb"] for c in calls))
        self.assertFalse(any(c[0] == "helm" for c in calls))

    def test_retry_rejects_previous_inventory_from_another_release(self):
        previous = self.root / "previous.json"
        previous.write_text(json.dumps({"slot": "aks02"}))
        previous.chmod(0o600)
        context = (self.receipt["target"], {"id": "owned-cluster", "nodeResourceGroup": "owned-nodes"},
                   self.root / "kubeconfig", ["kubectl"], {})
        with patch.object(cleanup.tf, "PRIVATE", self.root), patch.object(cleanup, "kube_context", return_value=context), \
             patch.object(cleanup, "data", return_value={"items": []}), patch.object(cleanup, "command") as command:
            with self.assertRaisesRegex(ValueError, "another release or cluster"):
                cleanup.services(self.bundle, self.root / "retry", None, True, previous)
        command.assert_not_called()

    def test_live_argo_application_blocks_workload_removal(self):
        app = {"spec": {"destination": {"namespace": "platform-demo"}}}
        with patch.object(cleanup, "command", return_value=b"customresourcedefinition/applications.argoproj.io"), \
             patch.object(cleanup, "data", return_value={"items": [app]}):
            with self.assertRaisesRegex(ValueError, "Retire Argo"):
                cleanup.assert_argocd_retired(["kubectl"], {}, "platform-demo")

    def test_other_namespace_application_does_not_block_exact_lab_cleanup(self):
        app = {"spec": {"destination": {"namespace": "another-app"}}}
        with patch.object(cleanup, "command", return_value=b"customresourcedefinition/applications.argoproj.io"), \
             patch.object(cleanup, "data", return_value={"items": [app]}):
            cleanup.assert_argocd_retired(["kubectl"], {}, "platform-demo")

    def test_no_argo_crd_needs_no_application_read(self):
        with patch.object(cleanup, "command", return_value=b""), patch.object(cleanup, "data") as read:
            cleanup.assert_argocd_retired(["kubectl"], {}, "platform-demo")
        read.assert_not_called()

    def test_backend_refuses_foreign_subscription_or_unrelated_group(self):
        def state(resource_id, kind="azurerm_storage_account"):
            return {"version":4, "lineage":"original", "serial":2, "resources":[
                {"mode":"managed", "type":kind, "instances":[{"attributes":{"id":resource_id}}]}]}
        owned = f"/subscriptions/{backend.tf.SUBSCRIPTION}/resourceGroups/uks-hub-aks-lab-tfstate-rsg/providers/Microsoft.Storage/storageAccounts/example"
        self.assertEqual(backend.validate_bootstrap(state(owned)), 1)
        for value in (state(owned.replace(backend.tf.SUBSCRIPTION, "other")),
                      state(owned.replace("uks-hub-aks-lab-tfstate-rsg", "existing-shared")),
                      state(owned, "azuread_group")):
            with self.assertRaises(ValueError):
                backend.validate_bootstrap(value)

    def test_backend_apply_requires_matching_reviewed_plan_before_cloud_access(self):
        output = self.root / "recovery"; output.mkdir(mode=0o700)
        (output / "destroy.tfplan").write_bytes(b"new-plan")
        (output / "receipt.json").write_text(json.dumps({"status":"backend-removal-plan-ready", "plan_sha256":"a"*64}))
        with patch.object(backend.tf, "PRIVATE", self.root), patch.object(backend.tf, "run") as run:
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                backend.apply(output, "a"*64)
        run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
