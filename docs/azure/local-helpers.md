# Local Bash and PowerShell helpers

Source/dot-source `scripts/azure/terraform-functions.sh` or `.ps1`. Python 3.10+, Terraform, Azure CLI and Git must be on PATH. Login explicitly to the expected tenant before setup. Both shells use the same Python engine and return failures to the caller.

| Command | Behavior |
|---|---|
| `tf_setup <repo> <env> <region> [prefix]` | Validate configuration, current directory and accessible tenant/subscriptions; persist this checkout's selection |
| `tf_env` | Show selected aliases and state key without dumping credentials |
| `tf_init` | Reconfigure the selected Azure AD backend; retain an existing provider lockfile |
| `tf_upgrade` | Explicit init with provider/module upgrade; review the lockfile/source changes |
| `tf_plan` | Reconfigure, format local files, validate, and save a locked binary plan plus receipt |
| `tf_apply` | Verify and apply that saved plan after confirmation; no fresh implicit plan |
| `tf_destroy` | Confirm, then destroy the selected target with reviewed varfiles and state locking |
| `tf_import <address> <resource-id>` | Confirm and import into the selected state with the same varfiles |
| `tf_deploy <repo> <env> <region> [prefix]` | Setup → init → saved plan → confirmed apply |
| `az_sub` | Show the current Azure CLI account name/default flag |

Stateful commands reconfigure and inspect the real initialized backend every time. A stale local receipt cannot cause a raw `terraform init` to silently change their target. Backend account/container/key and the default workspace are verified. Azure CLI tenant/subscription checks fail closed, and Terraform receives the selected workload/tenant IDs explicitly.

The saved plan lives in `.terraform-delivery/plan/`; its separate local receipt stays outside that bundle. Apply rejects changed inputs/toolchain/context, replaced plans, or plans older than two hours. A local receipt protects against mistakes and transferred bundles; it is not a tamper-proof approval system against an operator who controls the checkout and receipt. Lock timeout is five minutes; locking stays enabled. If a failed run leaves an orphaned Azure Blob lease, follow the [state-lock recovery procedure](state-lock-recovery.md) before planning again.

Inherited `TF_CLI_ARGS*`, `TF_DATA_DIR` and `TF_VAR_*` are cleared for helper-run Terraform. Inputs belong in the explicit variable files (and carefully reviewed local Terraform configuration). CI rejects ambient `TF_VAR_*` rather than accepting hidden persistent-runner inputs. No secret values are stored in the context receipt. Plans themselves may contain sensitive data and remain ignored/private.

`tf_apply --yes`, `tf_destroy --yes` and `tf_import --yes <address> <id>` are explicit automation opt-ins. Normal interactive helpers ask for confirmation; non-interactive sessions fail without that opt-in. CI exposes saved-plan apply only; destruction/import stay deliberate local operations.

## GitHub dispatch helpers

Source/dot-source `scripts/github/github-functions.sh` or `.ps1` and authenticate GitHub CLI. Run from the desired consumer checkout:

```bash
gha_setup owner/private-network tf-validate.yml main
gha_plan pprd uks
gha_watch
gha_apply pprd uks
gha_watch
```

`gha_setup [repository] [workflow] [branch]` resets old context/run selection. Omitted repository is inferred using `gh repo view`; workflow defaults to `tf-validate.yml`, branch to `main`. `gha_run [environment] [region] [workflow]`, `gha_runs [limit]`, `gha_view [run-id]`, `gha_latest`, `gha_open` and `gha_plan_watch` preserve the original names.

The starter dispatch workflows accept `request_id` and include it in `run-name`. Helpers correlate that unique value to the actual dispatched run; `gha_watch` follows that exact run, including after apply. It never guesses whichever unrelated run happens to be newest. If dispatch succeeds but correlation times out, inspect the saved request ID before sending another dispatch. Apply dispatch prompts for confirmation and still requires CI environment approval. `gha_latest` is read-only inspection and does not change the selected run.
