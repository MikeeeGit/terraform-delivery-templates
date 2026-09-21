"""Regression coverage for observed Azure backend state migration behavior."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("migrate_state", ROOT / "initial-setup/azure/migrate_state.py")
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class StateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.before = {"lineage": "synthetic-lineage", "serial": 13,
                       "resources": [{"mode": "managed", "type": "example", "instances": [{"attributes": {"id": "owned"}}]}],
                       "outputs": {"backend": {"value": "owned"}}, "check_results": None}

    def test_backend_can_increment_serial_once_without_changing_owned_state(self):
        for delta in (0, 1):
            after = copy.deepcopy(self.before)
            after.update(serial=13 + delta, check_results=[])
            migration.verify_states(self.before, after)

    def test_changed_resource_output_or_lineage_rejected(self):
        for key, value in (("lineage", "different"), ("resources", []), ("outputs", {})):
            after = copy.deepcopy(self.before)
            after[key] = value
            with self.assertRaises(ValueError):
                migration.verify_states(self.before, after)

    def test_serial_regression_large_jump_and_invalid_type_rejected(self):
        for serial in (12, 15, "14", None, True):
            after = dict(self.before, serial=serial)
            with self.assertRaises(ValueError):
                migration.verify_states(self.before, after)

    def test_recovery_snapshot_is_private_and_never_overwrites_prior_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recovery.tfstate"
            migration.private_json(path, self.before)
            self.assertEqual(json.loads(path.read_text()), self.before)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                migration.private_json(path, {})


if __name__ == "__main__":
    unittest.main()
