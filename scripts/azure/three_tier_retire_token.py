#!/usr/bin/env python3
"""Retire the exact bootstrap PAT after all three connection states are empty."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import three_tier_teardown as tf
import three_tier_retire_backend as backend

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--authorization-id", required=True)
    p.add_argument("--display-name", required=True)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args(argv)
    os.umask(0o077)
    tf.configure(a.config)
    tf.require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", a.authorization_id),
               "Expected the exact bootstrap PAT authorization UUID")
    tf.require(a.display_name.startswith("aks-lab-terraform-bootstrap-"),
               "Expected the explicitly named disposable Terraform bootstrap PAT")
    tf.create_output(a.output)
    env = tf.child_environment(a.output)
    for target in ("hub", "prd", "pprd"):
        state = backend.blob_download(tf.expected_backend(tf.CONNECTIONS, target),
                                      a.output / (target + "-connections.tfstate"), env)
        tf.require(tf.validate_state(state, tf.CONNECTIONS, target)["managed_instances"] == 0,
                   "Connection resources remain; retain the bootstrap PAT")
    credentials = json.loads(tf.run(
        ["az", "account", "get-access-token", "--resource", "499b84ac-1321-427f-aa17-267ca6975798",
         "--tenant", tf.TENANT, "--output", "json"], a.output, env, "Obtain delegated owner authentication"))
    organization = urllib.parse.urlsplit(tf.ORGANIZATION).path.strip("/")
    url = "https://vssps.dev.azure.com/" + organization + "/_apis/tokens/pats?" + urllib.parse.urlencode(
        {"authorizationId": a.authorization_id, "api-version": "7.1-preview.1"})
    headers = {"Authorization": "Bearer " + credentials["accessToken"],
               "X-TFS-FedAuthRedirect": "Suppress", "X-VSS-ForceMsaPassThrough": "true"}
    def request(method):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers, method=method), timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return 404, {}
            raise ValueError("Bootstrap PAT owner operation failed with HTTP " + str(error.code)) from None
    status, record = request("GET")
    token = record.get("patToken") or {}
    tf.require(status == 200 and token.get("authorizationId") == a.authorization_id
               and token.get("displayName") == a.display_name,
               "Bootstrap PAT metadata does not match the explicitly reviewed owner record")
    tf.require(set(token.get("scope", "").split()) ==
               {"vso.pipelineresources_manage", "vso.project", "vso.serviceendpoint_manage"},
               "Unexpected bootstrap token scope")
    result = {key: token.get(key) for key in ("authorizationId", "displayName", "scope", "validTo")}
    result["status"] = "inventory-only"
    if a.execute:
        status, _ = request("DELETE")
        tf.require(status in (200, 204), "PAT revocation did not succeed")
        after_status, after = request("GET")
        tf.require(after_status == 404 or (after_status == 200 and not after.get("patToken")),
                   "PAT owner lookup still returns a token; retain the local file and investigate")
        tf.private_path(tf.PAT_FILE)
        tf.PAT_FILE.unlink()
        result.update(status="revoked", local_token_file_removed=True, owner_lookup_status=after_status)
    tf.write_private(a.output / "result.json", json.dumps(result, indent=2))
    print(json.dumps({"status": result["status"], "local_token_file_removed": result.get("local_token_file_removed", False)}))

if __name__ == "__main__":
    main()
