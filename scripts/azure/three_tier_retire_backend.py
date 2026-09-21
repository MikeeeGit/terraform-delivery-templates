#!/usr/bin/env python3
"""Migrate the disposable lab's own backend state locally, then retire its storage."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import three_tier_teardown as tf

def validate_bootstrap(state):
    tf.require(state.get("version") == 4 and state.get("lineage") and isinstance(state.get("serial"), int), "Missing original backend state identity")
    allowed = {"azurerm_resource_group", "azurerm_storage_account", "azurerm_storage_container", "azurerm_role_assignment"}
    groups = {f"uks-{e}-aks-lab-tfstate-rsg" for e in ("hub", "pprd", "prd")}
    count = 0
    for resource in state.get("resources", []):
        if resource.get("mode") != "managed": continue
        tf.require(resource["type"] in allowed, "Unexpected managed backend resource")
        for instance in resource.get("instances", []):
            a = instance["attributes"]
            scope = a.get("scope") if resource["type"] == "azurerm_role_assignment" else a.get("id")
            # Storage container IDs include a data-plane separator after the ARM account ID.
            match = re.match(r"/subscriptions/([^/]+)/resourcegroups/([^/|]+)", str(scope).lower())
            tf.require(match and match[1] == tf.SUBSCRIPTION and match[2] in groups, "Backend object escapes the isolated storage groups")
            tf.require(a.get("principal_id") != tf.PROTECTED_ADMIN_GROUP, "Existing administrator group is outside backend cleanup")
            count += 1
    return count

def blob_download(backend, output, env):
    tf.run(["az", "storage", "blob", "download", "--account-name", backend["storage_account_name"],
            "--container-name", backend["container_name"], "--name", backend["key"],
            "--file", str(output), "--auth-mode", "login", "--subscription", tf.SUBSCRIPTION,
            "--only-show-errors", "--output", "none"], output.parent, env, "Read remaining component state")
    output.chmod(0o600)
    return json.loads(tf.regular(output))

def source_files(root):
    paths = [p for p in root.iterdir() if p.name.endswith(".tf") or p.name in (".terraform.lock.hcl", "terraform.tfvars")]
    tf.require(any(p.name == "remote-backend.tf" for p in paths), "Expected the bootstrap migration's explicit remote-backend.tf")
    return {p.name: tf.digest(tf.regular(p)) for p in paths}

def plan(output):
    tf.create_output(output)
    work = output / "source"; work.mkdir(mode=0o700)
    env = tf.child_environment(output)
    account = json.loads(tf.run(["az", "account", "show", "--subscription", tf.SUBSCRIPTION, "-o", "json"], work, env, "Operator check"))
    tf.require(account["id"] == tf.SUBSCRIPTION and account["tenantId"] == tf.TENANT
               and account.get("user", {}).get("type") == "user", "Unexpected retained operator account")
    # Read every declared state again; successful earlier destroy logs alone are insufficient.
    states = output / "component-states"; states.mkdir(mode=0o700)
    for component, environments in tf.TARGETS.items():
        for environment in environments:
            backend = tf.expected_backend(component, environment)
            state = blob_download(backend, states / (component + "-" + environment + ".tfstate"), env)
            info = tf.validate_state(state, component, environment)
            tf.require(info["managed_instances"] == 0, "Component resources remain: " + component + "/" + environment)
    root = tf.BASE / "bootstrap-state"
    files = source_files(root)
    for name in files: tf.write_private(work / name, tf.regular(root / name))
    backend = dict(tf.expected_backend("aks-lab-delivery-identities", "hub"), key="terraform-delivery-bootstrap.tfstate")
    # Match the real bootstrap file, including the actual account and operator-only container.
    tf.require(tf.read_simple_backend(root / ".backend.generated.hcl") == backend, "Bootstrap backend differs from this lab")
    hcl = output / "backend.hcl"
    tf.write_private(hcl, "".join(f"{k} = {json.dumps(v)}\n" for k,v in dict(backend, use_cli=True, use_oidc=False, use_msi=False).items()))
    tf.run([str(tf.TERRAFORM), "init", "-input=false", "-lockfile=readonly", "-no-color", "-backend-config="+str(hcl)], work, env, "Initialize existing bootstrap backend")
    tf.validate_backend_cache(json.loads(tf.regular(Path(env["TF_DATA_DIR"]) / "terraform.tfstate")), backend)
    before = tf.run([str(tf.TERRAFORM), "state", "pull"], work, env, "Capture bootstrap state")
    original = json.loads(before)
    count = validate_bootstrap(original)
    tf.require(count > 0, "No bootstrap resources remain")
    tf.write_private(output / "remote-before.tfstate", before)
    remote = work / "remote-backend.tf"
    tf.require(re.fullmatch(r'\s*terraform\s*\{\s*backend\s+"azurerm"\s*\{\s*\}\s*\}\s*', remote.read_text()), "Unexpected bootstrap backend declaration")
    recovery = output / "bootstrap-recovery.tfstate"
    remote.write_text('terraform {\n  backend "local" { path = '+json.dumps(str(recovery))+' }\n}\n')
    tf.run([str(tf.TERRAFORM), "init", "-migrate-state", "-force-copy", "-input=false", "-lockfile=readonly", "-no-color"], work, env, "Migrate the existing bootstrap state to private local recovery")
    cache = json.loads(tf.regular(Path(env["TF_DATA_DIR"]) / "terraform.tfstate"))["backend"]
    tf.require(cache["type"] == "local" and cache["config"]["path"] == str(recovery), "Bootstrap backend migration did not select protected local recovery")
    migrated = json.loads(tf.run([str(tf.TERRAFORM), "state", "pull"], work, env, "Verify migrated state"))
    tf.require(migrated["lineage"] == original["lineage"] and migrated["serial"] >= original["serial"]
               and migrated["resources"] == original["resources"], "Migrated state identity/resources differ")
    recovery.chmod(0o600)
    saved = output / "destroy.tfplan"
    tf.run([str(tf.TERRAFORM), "plan", "-destroy", "-input=false", "-lock=true", "-lock-timeout=60s", "-no-color",
            "-out="+str(saved), "-var-file=terraform.tfvars"], work, env, "Plan backend retirement")
    saved.chmod(0o600)
    rendered = tf.run([str(tf.TERRAFORM), "show", "-json", str(saved)], work, env, "Review backend retirement")
    parsed = json.loads(rendered)
    values = {k:v["value"] for k,v in parsed["variables"].items()}
    tf.require(values["subscription_id"] == tf.SUBSCRIPTION and values["tenant_id"] == tf.TENANT
               and values["prefix"] == tf.STORAGE_PREFIX and values["resource_group_name_prefix"] == "aks-lab"
               and set(values["backend_environments"]) == {"hub","pprd","prd"}, "Backend plan inputs differ")
    changes = [r for r in parsed.get("resource_changes", []) if r["change"]["actions"] != ["no-op"] and r["mode"] == "managed"]
    tf.require(len(changes) == count and all(r["change"]["actions"] == ["delete"] for r in changes), "Backend plan is not exact full removal")
    tf.write_private(output / "destroy-plan.json", rendered)
    tf.write_private(output / "destroy-plan.txt", tf.run([str(tf.TERRAFORM), "show", "-no-color", str(saved)], work, env, "Write private backend plan"))
    receipt = {"status":"backend-removal-plan-ready", "files":files, "plan_sha256":tf.digest(tf.regular(saved)),
               "lineage":original["lineage"], "managed_count":count, "local_backend_path":str(recovery),
               "migration_performed":True, "resource_apply_performed":False,
               "work_files":source_files(work)}
    tf.write_private(output / "receipt.json", json.dumps(receipt, indent=2))
    print(json.dumps({"status":receipt["status"], "plan_sha256":receipt["plan_sha256"], "delete_count":count}))

def apply(output, expected):
    tf.require(output.resolve().is_relative_to(tf.PRIVATE.resolve()), "Output escapes private recovery directory")
    tf.private_path(output, directory=True)
    receipt = json.loads(tf.regular(output / "receipt.json"))
    saved = output / "destroy.tfplan"; work = output / "source"; env = tf.child_environment(output)
    tf.require(receipt["status"] == "backend-removal-plan-ready" and expected == receipt["plan_sha256"]
               and tf.digest(tf.regular(saved)) == expected, "Reviewed backend plan digest mismatch")
    tf.require(not (output / "apply-result.json").exists(), "Retain prior result and create a fresh recovery plan before retry")
    tf.require(source_files(work) == receipt["work_files"] and source_files(tf.BASE / "bootstrap-state") == receipt["files"],
               "Bootstrap source changed after planning")
    cache = json.loads(tf.regular(Path(env["TF_DATA_DIR"]) / "terraform.tfstate"))["backend"]
    tf.require(cache["type"] == "local" and cache["config"]["path"] == receipt["local_backend_path"], "Do not delete the active remote backend")
    before = json.loads(tf.run([str(tf.TERRAFORM), "state", "pull"], work, env, "Local recovery check"))
    tf.require(before["lineage"] == receipt["lineage"] and validate_bootstrap(before) == receipt["managed_count"], "Local recovery changed")
    result = subprocess.run([str(tf.TERRAFORM), "apply", "-input=false", "-lock=true", "-lock-timeout=60s", "-no-color", str(saved)],
                            cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tf.write_private(output / "apply.log", result.stdout)
    after = tf.run([str(tf.TERRAFORM), "state", "pull"], work, env, "Final local recovery snapshot")
    tf.write_private(output / "state-final.tfstate", after)
    remaining = validate_bootstrap(json.loads(after))
    record = {"status":"removed" if result.returncode == 0 and remaining == 0 else "failed",
              "remaining_managed_instances":remaining, "returncode":result.returncode, "plan_sha256":expected}
    tf.write_private(output / "apply-result.json", json.dumps(record, indent=2))
    tf.require(record["status"] == "removed", "Backend removal incomplete; private local recovery state remains authoritative")
    print(json.dumps(record))

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--mode", choices=["plan","apply"], required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--expected-plan-sha256")
    a=p.parse_args(argv);os.umask(0o077);tf.configure(a.config)
    if a.mode == "plan":
        tf.require(a.expected_plan_sha256 is None, "Plan does not accept a previous plan digest")
        plan(a.output)
    else: apply(a.output,a.expected_plan_sha256)

if __name__ == "__main__":
    try: main()
    except (ValueError,OSError,KeyError,json.JSONDecodeError) as error:
        raise SystemExit("Backend retirement stopped: "+str(error))
