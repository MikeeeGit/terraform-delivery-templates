#!/usr/bin/env python3
"""Print only the non-secret federation issuer/subject/audience in a private setup job."""
import base64, json, os, urllib.parse, urllib.request

if (
    os.environ.get("PRIVATE_REPOSITORY") != "true"
    or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
):
    raise SystemExit("Use only a manual private repository setup job.")
url = (
    os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    + "&"
    + urllib.parse.urlencode({"audience": "api://AzureADTokenExchange"})
)
request = urllib.request.Request(
    url,
    headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]},
)
with urllib.request.urlopen(request, timeout=30) as response:
    token = json.load(response)["value"]
payload = token.split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
print(json.dumps({key: claims[key] for key in ("iss", "sub", "aud")}, indent=2))
