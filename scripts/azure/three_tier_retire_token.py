#!/usr/bin/env python3
"""Retire the exact bootstrap PAT after all three connection states are empty."""
from __future__ import annotations
import argparse
import base64
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
    def request(method, target=url):
        try:
            with urllib.request.urlopen(urllib.request.Request(target, headers=headers, method=method), timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return 404, {}
            raise ValueError("Bootstrap PAT owner operation failed with HTTP " + str(error.code)) from None
    def listed_as_revoked():
        continuation = None
        seen = set()
        for _ in range(100):
            query = {"displayFilterOption": "revoked", "$top": 100, "api-version": "7.1-preview.1"}
            if continuation: query["continuationToken"] = continuation
            status, page = request("GET", url.split("?")[0] + "?" + urllib.parse.urlencode(query))
            tf.require(status == 200 and isinstance(page.get("patTokens"), list), "Cannot verify revoked-token inventory")
            for item in page["patTokens"]:
                if item.get("authorizationId") == a.authorization_id:
                    tf.require(item.get("displayName") == a.display_name, "Revoked token name mismatch")
                    return True
            continuation = page.get("continuationToken")
            if not continuation: return False
            tf.require(continuation not in seen, "Repeated token inventory page")
            seen.add(continuation)
        raise ValueError("Token inventory pagination exceeded its review bound")
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
        already_revoked = listed_as_revoked()
        if not already_revoked:
            status, _ = request("DELETE")
            tf.require(status in (200, 204), "PAT revocation did not succeed")
            tf.write_private(a.output / "revocation-response.json", json.dumps({"authorization_id": a.authorization_id, "http_status": status}))
        after_status, after = request("GET")
        tf.require(listed_as_revoked(), "Owner inventory does not yet confirm revocation; retain the local token and retry in a new output directory")
        tf.private_path(tf.PAT_FILE)
        pat = tf.regular(tf.PAT_FILE).decode().strip()
        tf.require(pat and not re.search(r"\s", pat), "Malformed local bootstrap credential")
        # The owner API can retain revoked-token metadata. Verify authentication
        # fails against this private project; never follow a credential redirect.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        probe_url = tf.ORGANIZATION.rstrip("/") + "/" + tf.PROJECT + "/_apis/serviceendpoint/endpoints?api-version=7.1"
        probe_headers = {"Authorization": "Basic " + base64.b64encode((":" + pat).encode()).decode(),
                         "X-TFS-FedAuthRedirect": "Suppress", "X-VSS-ForceMsaPassThrough": "true"}
        try:
            with urllib.request.build_opener(NoRedirect).open(
                    urllib.request.Request(probe_url, headers=probe_headers), timeout=30) as probe:
                probe_status = probe.status
        except urllib.error.HTTPError as error:
            probe_status = error.code
        tf.require(probe_status == 401, "PAT still authenticates or revocation is inconclusive; retain the local file")
        tf.PAT_FILE.unlink()
        result.update(status="revoked", local_token_file_removed=True, owner_lookup_status=after_status,
                      owner_metadata_retained=bool(after.get("patToken")), authentication_probe_status=probe_status,
                      already_revoked=already_revoked, revoked_inventory_confirmed=True)
    tf.write_private(a.output / "result.json", json.dumps(result, indent=2))
    print(json.dumps({"status": result["status"], "local_token_file_removed": result.get("local_token_file_removed", False)}))

if __name__ == "__main__":
    main()
