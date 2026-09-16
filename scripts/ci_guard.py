#!/usr/bin/env python3
"""Fail closed before authenticated/persistent CI; recheck branch before apply."""
import argparse, base64, json, os, re, urllib.parse, urllib.request


def get(url, token, basic=False):
    auth = (
        "Basic " + base64.b64encode((":" + token).encode()).decode()
        if basic
        else "Bearer " + token
    )
    request = urllib.request.Request(
        url, headers={"Authorization": auth, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def check(platform, latest=False):
    branch = os.environ.get("DEPLOYMENT_BRANCH", "main")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,100}", branch) or ".." in branch:
        raise ValueError("invalid deployment branch")
    if platform == "github":
        if (
            os.environ.get("PRIVATE_REPOSITORY") != "true"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.environ.get("GITHUB_REF") != "refs/heads/" + branch
        ):
            raise ValueError(
                "delivery requires workflow_dispatch of the protected branch in a PRIVATE consumer repository"
            )
        if not re.fullmatch(r"[0-9a-f]{40}", os.environ.get("TEMPLATE_REF", "")):
            raise ValueError("template-ref must be a full commit SHA")
        labels = json.loads(os.environ.get("RUNNER_LABELS", '["ubuntu-24.04"]'))
        if (
            not isinstance(labels, list)
            or not labels
            or any(
                not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", x)
                for x in labels
            )
        ):
            raise ValueError("runs-on must be a JSON array of runner labels")
        if latest:
            ref = urllib.parse.quote("heads/" + branch, safe="/")
            data = get(
                f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/git/ref/{ref}",
                os.environ["GH_TOKEN"],
            )
            if data["object"]["sha"] != os.environ["GITHUB_SHA"]:
                raise ValueError("branch changed; create and approve a new plan")
    else:
        if (
            os.environ.get("BUILD_REASON") == "PullRequest"
            or os.environ.get("BUILD_SOURCEBRANCH") != "refs/heads/" + branch
            or os.environ.get("BUILD_REPOSITORY_PROVIDER") != "TfsGit"
        ):
            raise ValueError(
                "delivery requires the protected Azure Repos branch; pull requests are rejected"
            )
        base = os.environ["SYSTEM_COLLECTIONURI"] + urllib.parse.quote(
            os.environ["SYSTEM_TEAMPROJECTID"], safe=""
        )
        token = os.environ["SYSTEM_ACCESSTOKEN"]
        project = get(
            os.environ["SYSTEM_COLLECTIONURI"]
            + "_apis/projects/"
            + os.environ["SYSTEM_TEAMPROJECTID"]
            + "?api-version=7.1",
            token,
            True,
        )
        if project.get("visibility") != "private":
            raise ValueError(
                "authenticated delivery requires a PRIVATE Azure DevOps project"
            )
        if latest:
            query = urllib.parse.urlencode(
                {"filter": "heads/" + branch, "api-version": "7.1"}
            )
            refs = get(
                base
                + "/_apis/git/repositories/"
                + os.environ["BUILD_REPOSITORY_ID"]
                + "/refs?"
                + query,
                token,
                True,
            )["value"]
            matches = [
                x["objectId"] for x in refs if x["name"] == "refs/heads/" + branch
            ]
            if matches != [os.environ["BUILD_SOURCEVERSION"]]:
                raise ValueError("branch changed; create and approve a new plan")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=["github", "azure-devops"])
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    try:
        check(args.platform, args.latest)
    except Exception as error:
        raise SystemExit("Delivery guard stopped: " + str(error))
