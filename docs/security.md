# Security boundaries

Public CI runs on isolated hosted agents with read-only repository permissions. It has no Azure/AWS identity, remote-state access or plan-artifact publishing. Never add a public PR job to a persistent deployment runner, or use `pull_request_target` to execute untrusted Terraform with credentials.

Authenticated workflows require private consumers and a protected source branch. GitHub accepts manual workflow_dispatch; Azure DevOps checks private-project visibility and Azure Repos source metadata. These guards run on hosted agents before trusted deployment runners. Protect the caller, shared-template refs, module sources, provider lockfiles and state configuration through review.

Apply is disabled by default. Environment required reviewers, branch restrictions, service-connection checks, exclusive locks and runner permissions are external platform settings: writing their names in YAML neither creates nor verifies those controls. GitHub private environment review availability depends on the account plan. If an enforceable approval gate is absent, keep CI apply disabled.

Saved plans can contain plaintext sensitive values. GitHub stores them only in private same-run artifacts for one day; Azure retention must be configured on the private project. The independent manifest digest, exact run/commit, checked source inputs, lockfile/tool version, target and two-hour expiry are checked before apply. Plan creation checks that inputs did not change during execution. Do not expose `terraform show -json` or raw plans in public logs/issues.

Use secretless OIDC with least-privilege, narrowly scoped identities. A plan principal still needs state Blob Data permissions for leases. Providers, modules and data sources can perform arbitrary actions; a Reader principal is not a universal sandbox. Cross-subscription provider aliases are supported and must be reviewed/authorized deliberately. Helpers bind intended targeting; they cannot prove that arbitrary Terraform code follows it.

GitHub jobs isolate Azure/Git/Terraform credential files and remove them at completion; Azure tasks use their job-scoped WIF/CLI mechanisms. Use dedicated private self-hosted runner groups, current agents and controlled administration. No global credential URL rewrite or token printing is included. Private module authentication requires an explicit scoped operator adapter.

Inherited Terraform CLI flags, data directories and TF_VAR inputs do not silently change helper execution. Strict source checks reject untracked/ignored inputs outside the managed `.terraform` cache and reject source symlinks. Commit the configuration/lockfile before private CI. Default workspaces and unique state keys avoid implicit workspace targeting.

Optional storage/vault firewall access is opt-in. Only rules recorded as newly added are removed; existing rules remain. Share an egress IP only with external serialization, because independent jobs can observe and depend on the same allow rule. Cleanup handles normal task failures, but power loss/forced runner termination can leave access requiring reconciliation. Private networking avoids these mutations.

Local receipts are accident/integrity checks, not a trust boundary against a malicious local administrator. Local apply/destroy/import require confirmation unless explicitly given `--yes`. Bootstrap identity creation defaults to review-only, checks tenant/subscription access before mutation, refuses existing application names, and writes progress for partial-failure recovery. Migration retains state backups and requires confirmation.

Report suspected vulnerabilities through [SECURITY.md](../SECURITY.md). No cloud deployment, IAM correctness or compliance certification is implied by unit/mock tests.
