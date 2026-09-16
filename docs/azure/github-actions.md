# GitHub Actions Azure delivery

Use `starter-templates/azure/.github/workflows/tf-validate.yml` for a manual authenticated plan and `tf-apply.yml` for plan plus approved apply. These must run in a private consumer. Public validation is the separate `terraform-validate.yml` reusable workflow.

The caller references the `v0.2.0` workflow and supplies a full reviewed template checkout SHA through `TERRAFORM_DELIVERY_SHA`. Keep the two references on the same release. Third-party actions use reviewed full commit SHAs with version comments. The public template repository does not need a PAT.

Required repository variables are `TERRAFORM_DELIVERY_SHA`, `AZURE_PLAN_CLIENT_ID` and `AZURE_APPLY_CLIENT_ID`. The tenant, workload subscription and independent backend subscription/names come from `delivery.azure.json`. Each principal needs its workload scope plus Azure AD state access. Cross-subscription aliases in Terraform need explicit roles as well.

Create `<environment>-<region>-plan` and `<environment>-<region>-apply` environments. Federated credentials must match the **private caller's actual subject** and exact environment. New/renamed/transferred repositories can use immutable owner/repository IDs in OIDC subjects; do not copy a legacy name-only guess. [GitHub's subject format change](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/) explains the rollout. The optional private setup helper prints only the issuer, subject and audience.

Configure apply required reviewers, prevent self-approval/admin bypass as available, restrict both environments to the protected deployment branch, and protect workflow/configuration changes. **Private-repository environment reviewers depend on your GitHub plan; Free/Pro/Team do not provide all required-reviewer protection available for private Enterprise repositories.** Check [GitHub's environment protection availability](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments). If the required gate is unavailable, leave apply disabled and use an approved Azure DevOps environment or confirmed local saved-plan apply. A YAML environment name alone is not approval.

The starter's `ENABLE_TERRAFORM_APPLY` remains false/unset until you verify these settings. The reusable `enable-apply` input also defaults false. Normal GitHub branch `main` is expected; `deployment-branch` can name another deliberately protected branch.

## Inputs and execution

`environment` selects one environment; `locations` is a JSON array, such as `["uks","ukw"]`. Only targets with matching variable files are usable. The outer workflow serializes its region calls; each region owns distinct plan/apply jobs, environment names and output receipts. Call once per environment to create a larger deployment matrix.

`runs-on` is a JSON array of labels. Reusable defaults retain trusted Linux self-hosted agents (`self-hosted`, `Linux`, `X64`, `terraform`); the starter explicitly selects hosted `ubuntu-24.04`. A hosted guard rejects public repositories, pull requests and untrusted branches before persistent runners are scheduled. Use dedicated private runner groups and restrict their repositories. Keep agents current enough for Node24 actions.

Every job isolates `AZURE_CONFIG_DIR`, `GIT_CONFIG_GLOBAL` and `TF_CLI_CONFIG_FILE` in a unique temporary directory. Checkouts do not persist credentials. Public module sources require none; private module authentication is deliberately an operator-specific adapter, never a shared permanent global URL rewrite.

Plan initializes the selected backend with Azure AD/OIDC, checks format/validation, then creates a locked saved plan. Its private artifact is kept one day; the approval receipt expires after two hours. Apply downloads the exact artifact ID from the same run, verifies its separate manifest digest and source binding, rejects a superseded branch commit, and applies the saved binary plan after environment approval. Terraform itself also rejects stale state snapshots.

`whitelist-runner-ip` is opt-in, false by default. Private-network runners normally need no firewall mutation. If enabled, dedicate/serialize the public egress IP, grant narrow backend firewall permissions, and optionally set `key-vault`. Setup records only rules it adds; cleanup removes only those rules on normal success/failure. Abrupt machine loss can interrupt cleanup, so reconcile orphaned access operationally. Shared NAT IPs across independent runs require external serialization; this helper is not a distributed firewall lease manager.

`enable-security-scans` invokes installed TFLint, Checkov and Trivy. Operators pin/install them in their runner image. Scans are advisory unless `enforce-security-scans` is true; missing tools then fail. No unpinned installation script is downloaded at runtime.

Register the required Azure resource-provider namespaces using the operator/bootstrap identity before a Reader-only plan. The starter sets `resource_provider_registrations = "none"` so plan does not attempt subscription-level registration. Match this setting across all provider aliases.
