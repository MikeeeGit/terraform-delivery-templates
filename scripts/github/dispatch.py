#!/usr/bin/env python3
"""GitHub helpers with per-checkout context and exact dispatched-run tracking."""
import argparse, json, re, subprocess, sys, time, uuid
from pathlib import Path


def gh(args, json_output=False):
    result = subprocess.run(
        ["gh", *args], text=True, capture_output=json_output, check=True
    )
    return json.loads(result.stdout) if json_output else None


def valid(value, pattern, name):
    if not re.fullmatch(pattern, value):
        raise ValueError("invalid " + name)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "setup",
            "run",
            "plan",
            "apply",
            "runs",
            "watch",
            "view",
            "latest",
            "open",
            "plan-watch",
        ],
    )
    parser.add_argument("arguments", nargs="*")
    a = parser.parse_args()
    path = Path.cwd() / ".terraform-delivery" / "github.json"
    context = json.loads(path.read_text()) if path.exists() else {}

    def save():
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(context, indent=2) + "\n")

    if a.command == "setup":
        values = a.arguments + ["", "", ""]
        repository, workflow, branch = values[:3]
        repository = (
            repository
            or gh(["repo", "view", "--json", "nameWithOwner"], True)["nameWithOwner"]
        )
        context = {
            "repository": valid(
                repository, r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", "repository"
            ),
            "workflow": valid(
                workflow or "tf-validate.yml", r"[A-Za-z0-9][A-Za-z0-9_.-]*", "workflow"
            ),
            "branch": valid(branch or "main", r"[A-Za-z0-9][A-Za-z0-9_./-]*", "branch"),
        }
        save()
        print(
            "Selected {repository}, {workflow}, {branch}; prior run selection cleared.".format(
                **context
            )
        )
        return
    if not context:
        raise ValueError("run gha_setup from this checkout first")
    repository = context["repository"]
    branch = context["branch"]
    workflow = context["workflow"]
    if a.command in ("run", "plan", "apply", "plan-watch"):
        values = a.arguments + ["hub", "uks", ""]
        environment = values[0] if a.arguments else "hub"
        region = values[1] if len(a.arguments) > 1 else "uks"
        valid(environment, r"[A-Za-z0-9][A-Za-z0-9_.-]*", "environment")
        valid(region, r"[A-Za-z0-9][A-Za-z0-9_.-]*", "region")
        workflow = {
            "plan": "tf-validate.yml",
            "plan-watch": "tf-validate.yml",
            "apply": "tf-apply.yml",
        }.get(a.command, a.arguments[2] if len(a.arguments) > 2 else workflow)
        valid(workflow, r"[A-Za-z0-9][A-Za-z0-9_.-]*", "workflow")
        if "apply" in workflow.lower() or "destroy" in workflow.lower():
            if (
                not sys.stdin.isatty()
                or input(
                    f"Dispatch {workflow} for {repository}/{environment}/{region}? Type yes: "
                )
                != "yes"
            ):
                raise ValueError("dispatch cancelled")
        request = str(uuid.uuid4())
        context.update(workflow=workflow, request_id=request)
        context.pop("run_id", None)
        save()
        gh(
            [
                "workflow",
                "run",
                workflow,
                "--repo",
                repository,
                "--ref",
                branch,
                "-f",
                "environment=" + environment,
                "-f",
                "location=" + region,
                "-f",
                "request_id=" + request,
            ]
        )
        for attempt in range(30):
            runs = gh(
                [
                    "run",
                    "list",
                    "--repo",
                    repository,
                    "--workflow",
                    workflow,
                    "--branch",
                    branch,
                    "--event",
                    "workflow_dispatch",
                    "--limit",
                    "30",
                    "--json",
                    "databaseId,displayTitle,url",
                ],
                True,
            )
            matches = [item for item in runs if request in item["displayTitle"]]
            if len(matches) == 1:
                context["run_id"] = str(matches[0]["databaseId"])
                save()
                print(matches[0]["url"])
                break
            if len(matches) > 1:
                raise ValueError(
                    "ambiguous dispatch result; inspect request_id manually"
                )
            time.sleep(2)
        else:
            raise ValueError(
                "dispatch sent but run not located; use saved request_id to find the run, do not blindly dispatch again"
            )
        if a.command == "plan-watch":
            gh(
                [
                    "run",
                    "watch",
                    context["run_id"],
                    "--repo",
                    repository,
                    "--exit-status",
                ]
            )
    elif a.command == "runs":
        limit = valid(
            a.arguments[0] if a.arguments else "10", r"[1-9][0-9]{0,2}", "limit"
        )
        gh(
            [
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                workflow,
                "--branch",
                branch,
                "--limit",
                limit,
            ]
        )
    elif a.command in ("watch", "view"):
        run_id = valid(
            a.arguments[0] if a.arguments else context.get("run_id", ""),
            r"[1-9][0-9]*",
            "run ID (dispatch first or pass an exact run ID)",
        )
        gh(
            [
                "run",
                a.command,
                run_id,
                "--repo",
                repository,
                "--exit-status" if a.command == "watch" else "--log-failed",
            ]
        )
    elif a.command == "latest":
        print(
            json.dumps(
                gh(
                    [
                        "run",
                        "list",
                        "--repo",
                        repository,
                        "--workflow",
                        workflow,
                        "--branch",
                        branch,
                        "--limit",
                        "1",
                        "--json",
                        "databaseId,status,conclusion,displayTitle,url,headSha,createdAt",
                    ],
                    True,
                ),
                indent=2,
            )
        )
    else:
        gh(["repo", "view", repository, "--web"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("GitHub helper stopped: " + str(error))
