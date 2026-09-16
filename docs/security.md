# Security model

## Public contributions

Fork PRs are untrusted executable input: Terraform providers and tests can run
code. Use disposable hosted runners, a read-only repository token and no cloud
credentials. Public validation never requests OIDC tokens or a remote backend.
Do not add secrets, credential-bearing caches, private-module PATs, self-hosted
runners or `pull_request_target` execution of PR content.

Provider installation accesses public registries. This is credential-free CI,
not a network-isolated sandbox. Tests are opt-in and must be mocked or otherwise
credential-free. Existing local user credentials are outside the CI isolation
boundary. The scripts reject traversal and symlink escapes, use argument lists,
clear `TF_CLI_ARGS*` and isolate validation data. They do not sandbox malicious
Terraform executed with deployment permissions.

## Privileged delivery

Deploy reviewed protected-branch code from a private repository. Protect workflow,
provider, lockfile and module changes through review. Use constrained OIDC trust
and separate plan/apply identities. OIDC authenticates; it does not approve a plan.

Azure delivery rejects public, PR, non-main and non-manual callers before cloud
login. Apply defaults off. Create and configure the apply environment beforehand:
GitHub can create a named environment without protections. YAML alone cannot
create or prove reviewer policies. Approval features for private repositories
are plan-dependent; keep apply disabled if the documented gate is unavailable.

State, binary plans and plan JSON are confidential. Public workflow artifacts
are downloadable by signed-in readers. The Azure adapter only uploads from private
callers, retains the plan for one day and downloads the exact same-run artifact
ID. Review private plan logs before approving. Never post raw plans publicly.

The manifest binds plan hash, source commit, run/attempt, CLI version, lockfile,
tenant/subscription, plan/apply IDs, state location, default workspace, working
path and optional tracked variable-file digest. Its SHA-256 is transmitted as a
separate job output, so replacing both plan and manifest fails verification.
Plans expire after two hours. This is not protection against a malicious maintainer
who controls the trusted workflow; source review and external approvals supply
that trust boundary.

Delivery rejects tracked symlinks and all untracked/ignored inputs outside the
managed `.terraform` directory. It forces and verifies the default workspace,
keeps state locking enabled and refuses superseded main commits before apply.
GitHub concurrency is per repository; backend blob leases remain necessary for
other callers. Do not override stale-plan failures or automatically force-unlock.

## Operations

Bootstrap state separately with encryption, restricted data permissions, network
controls, recovery/versioning and retention. Templates do not open storage or
Key Vault firewalls or create persistent secrets. Audit cloud/identity and
artifact access in their hosting platforms.

References: [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use),
[artifact access](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts),
[Terraform sensitive data](https://developer.hashicorp.com/terraform/language/manage-sensitive-data),
[Azure fork builds](https://learn.microsoft.com/en-us/azure/devops/pipelines/security/secure-access-to-repos?view=azure-devops).
