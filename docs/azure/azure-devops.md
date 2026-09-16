# Azure DevOps Azure delivery

The public framework is consumed by a **private Azure DevOps project**. Start from `starter-templates/azure/azure-pipelines-plan.yml` / `azure-pipelines-apply.yml`; both have triggers disabled. Use a repository resource alias named `deliveryTemplates`, pinned to the reviewed `v0.2.0` release (or its full commit SHA).

When sourcing from GitHub, configure the repository connection named by the caller. With an Azure Repos mirror, set `type: git`, the actual private project/repository name, and the matching ref. Authorize the build identity to read only required template/module repositories. Do not print Git configuration or tokens, or enable permanent machine-wide credential rewrites.

Install Microsoft's Terraform extension that provides `TerraformTask@5`. Create workload-identity-federated ARM service connections for the backend and workload plan/apply scopes. Use current service-connection issuer/subject values from Azure DevOps, not a guessed legacy issuer. Do not grant every pipeline access to these connections. [Microsoft's task documentation](https://github.com/microsoft/azure-pipelines-terraform/blob/main/overview.md) describes the independent identity/ID-token-refresh configuration used here.

The wrapper `multi-env-region-terraform-deploy.yml` preserves the original structure: one environment, an object list of locations, and optional shared variable group. Include it once per environment when composing several environments. It calls `terraform-deployment-stages.yml`, which uses `terraform-setup-validate-pipeline.yml` for checkout, context, installation, optional scans/access, backend init and validation.

## Configuration

| Parameter | Use |
|---|---|
| `environment`, `locations` | Explicit selectors matching config files |
| `planServiceConnection`, `applyServiceConnection` | Workload identities; apply can explicitly reuse plan only when its permissions are appropriate |
| `backendServiceConnection` | Independent state identity/subscription |
| `variableGroup` | Optional private group, forwarded to both stages |
| `useHostedAgents`, `hostedVmImage` | Set true for hosted Linux validation/deployment access |
| `selfHostedAgentPool` | Trusted private pool; default `terraform-trusted` |
| `deploymentBranch` | Protected source branch, default `main` |
| `enableApply` | False until external approval controls are verified |
| `configuration`, `prefix`, `repositoryName` | Explicit delivery file/backend prefix/state-key repository overrides |
| `whitelistRunnerIp`, `keyVault` | Optional dedicated-IP storage/vault access |
| `enableSecurityScans`, `enforceSecurityScans` | Forwarded optional installed-tool scans, advisory by default |

The initial guard uses a hosted agent and the build token to verify private project visibility and the expected Azure Repos branch. PR builds are rejected. This delivery adapter currently supports Azure Repos consumers (`TfsGit`); the public validation adapter also serves other repository types.

The source is checked out separately from the shared templates. Context resolves backend coordinates and workload IDs from the JSON contract. Task v5 initializes with Azure AD auth and backend CLI identity flags, using refresh rather than the legacy one-token fallback. The workload subscription override is set explicitly. Keep a reviewed provider lockfile; init does not upgrade it.

Plan captures its source binding before execution, creates a locked binary plan, then verifies inputs stayed unchanged and emits a separate output digest. Apply downloads only the current run's artifact, verifies it before authentication, checks the protected branch still points to the same commit, reinitializes/validates the same backend and rechecks the receipt immediately before applying the saved plan. State locking uses a five-minute timeout.

## Required external controls

Create `<environment>-<region>-apply` environments with required approvals, protected-branch checks and an exclusive-lock check. The apply stage sets sequential lock behavior; YAML cannot create the actual check. Configure environment and service-connection permissions so pipeline authors cannot bypass deployment review. Keep `enableApply: false` until these settings are verified.

Set an appropriately short private run/artifact retention policy; the reusable template cannot enforce an artifact-specific Azure DevOps retention period. Never publish plan artifacts from a public project. The plan receipt itself expires after two hours; approve promptly or generate a fresh plan.

State access requires Blob Data permissions even for a workload Reader plan identity. Backend network access must exist before init. Optional hosted-IP rules use the backend service connection and recorded ownership; cleanup runs with `always()` after plan/apply. A failed/cancelled machine can leave rules for operator reconciliation. Do not run independent firewall users concurrently behind a shared egress IP without external serialization.

Validation evidence for this repository covers YAML structure, shell syntax, mock Terraform and mocked command contracts. Actual service-connection authorization, extension task execution, runner networking and approvals need a configured private sandbox run.

Register the required Azure resource-provider namespaces using the operator/bootstrap identity before a Reader-only plan. The starter sets `resource_provider_registrations = "none"` so plan does not attempt subscription-level registration. Match this setting across all provider aliases.
