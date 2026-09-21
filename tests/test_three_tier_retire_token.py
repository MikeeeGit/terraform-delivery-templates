import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/azure"))
import three_tier_retire_token as helper


class TokenRetirementGuards(unittest.TestCase):
    def run_helper(self, *, remaining=0, name=None, execute=False, still_present=False):
        identifier = "00000000-0000-0000-0000-000000000005"
        expected_name = "aks-lab-terraform-bootstrap-test"
        metadata = {"authorizationId": identifier, "displayName": name or expected_name,
                    "scope": "vso.pipelineresources_manage vso.project vso.serviceendpoint_manage"}
        calls = []
        class Response:
            def __init__(self, status, data):
                self.status, self.data = status, data
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(self.data).encode()
        def request(value, timeout):
            calls.append(value.method)
            if value.method == "DELETE": return Response(204, {})
            return Response(200, {"patToken": metadata if len(calls) == 1 or still_present else None})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            token = root / "bootstrap.pat"
            token.write_text("fixture-only")
            token.chmod(0o600)
            args = ["--config", str(root / "config.json"), "--output", str(root),
                    "--authorization-id", identifier, "--display-name", expected_name]
            if execute: args.append("--execute")
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(helper.tf, "configure"))
                stack.enter_context(patch.object(helper.tf, "create_output"))
                stack.enter_context(patch.object(helper.tf, "child_environment", return_value={}))
                stack.enter_context(patch.object(helper.tf, "PAT_FILE", token))
                stack.enter_context(patch.object(helper.backend, "blob_download", return_value={}))
                stack.enter_context(patch.object(helper.tf, "validate_state", return_value={"managed_instances": remaining}))
                stack.enter_context(patch.object(helper.tf, "run", return_value=b'{"accessToken":"fixture-only"}'))
                stack.enter_context(patch.object(helper.urllib.request, "urlopen", side_effect=request))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                try:
                    helper.main(args)
                except ValueError:
                    self.assertTrue(token.exists(), "Failure must preserve the local recovery credential")
                    raise
            return calls, token.exists(), json.loads((root / "result.json").read_text())

    def test_live_connections_stop_before_token_access(self):
        with self.assertRaisesRegex(ValueError, "Connection resources remain"):
            self.run_helper(remaining=1, execute=True)

    def test_other_token_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "metadata does not match"):
            self.run_helper(name="unrelated-token", execute=True)

    def test_default_is_read_only(self):
        calls, exists, result = self.run_helper()
        self.assertEqual(calls, ["GET"])
        self.assertTrue(exists)
        self.assertEqual(result["status"], "inventory-only")

    def test_delete_and_owner_verification_precede_local_removal(self):
        calls, exists, result = self.run_helper(execute=True)
        self.assertEqual(calls, ["GET", "DELETE", "GET"])
        self.assertFalse(exists)
        self.assertEqual(result["status"], "revoked")

    def test_unconfirmed_revocation_preserves_local_evidence(self):
        with self.assertRaisesRegex(ValueError, "still returns a token"):
            self.run_helper(execute=True, still_present=True)
