# Private Azure saved-plan delivery

`.github/workflows/terraform-azure-private.yml` implements manual Azure plan/apply.
The command contract has local mocked tests; a hosted cloud deployment has not
been performed. Apply is disabled by default (`enable-apply: false`).

## Setup

1. Use a private repository with reviewed Terraform, an `azurerm` backend and a
   committed provider lockfile. Pin remote modules to immutable revisions.
2. Bootstrap blob state storage and separate plan/apply identities. This first
   adapter supports one tenant/subscription for backend and target, env-supplied
   provider authentication, default workspace and a unique state key per target.
   Multiple subscriptions/provider aliases are outside the supported contract.
3. Protect `main` and create `azure-plan`/`azure-apply` environments. Restrict both
   to `main`; configure required apply reviewers and appropriate no-bypass and
   self-review restrictions. Bind each identity to its caller/environment subject.
4. Confirm required reviewers are available for the PRIVATE repository. Current
   GitHub documentation limits reviewers on Free/Pro/Team to public repositories;
   private use needs a supported plan/control, typically Enterprise. If unavailable,
   keep apply disabled and use a deployment platform with the required gate.
5. Copy the private delivery example, replace both template SHA placeholders and
   supply its variables. A manual `main` run creates a plan only. Enable apply
   only after observing that the configured approval gate blocks an unapproved run.

## Contract

The guard rejects public, PR, non-main and non-manual callers. Plan and apply check
out the same source and template revisions at stable paths. They use the selected
CLI, a read-only lockfile and explicit Azure backend coordinates with OIDC/Entra
authentication. The initialized backend and default workspace are checked.

Plan creates a binary and manifest. The manifest binds source SHA, run/attempt,
CLI, lockfile, state coordinates, tenant/subscription, both identity IDs, apply
environment, working path and optional tracked variable-file digest. Plan exit
codes 0/2 are accepted; errors produce no approvable manifest. The manifest hash
is carried separately as a plan-job output and the plan artifact is private with
one-day retention. The approval window is limited to two hours.

Apply downloads the exact same-run artifact ID, checks current `main` still matches
the planned SHA, and verifies the bound manifest/hash before cloud authentication.
It rechecks `main` immediately before execution, initializes the same backend,
revalidates context/expiry, then applies the saved binary with state locking.
It never silently replans. New commits, stale state, altered plans/context or
expired plans require a new plan and approval. The branch check is a point-in-time
check, not an atomic lock on future Git commits.

Reviewers must inspect the private plan job output and bound commit before
approval. Source/workflow permissions and external approval policies protect the
trusted job outputs. Concurrency is per repository; backend locking protects
operations involving other writers.

## Supported configuration boundary

Only static committed configurations are supported. All tracked symlinks and
untracked/ignored files outside `.terraform` are rejected. Providers/modules are
reinitialized at the same absolute checkout path; the whole working directory is
not archived. Do not depend on files generated during plan, mutable modules,
external local files, provisioner artifacts or untracked auto-tfvars. Implicit
`TF_VAR_*` inputs are cleared; use committed variables or an explicit tracked
variable file. Extend the
artifact contract before adopting those patterns.

Provider HCL must use environment-supplied credentials and subscription selection.
The helper checks its expected identity and backend; it does not parse arbitrary
provider HCL or prove the identity of every aliased provider.

There is no automatic destroy, forced unlock, state migration, firewall opening,
subscription vending or provider registration. Cloud permissions, OIDC trust and
hosted approval checks require integration tests before production use.

[Terraform automation](https://developer.hashicorp.com/terraform/tutorials/automation/automate-terraform),
[GitHub environment features and plans](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
