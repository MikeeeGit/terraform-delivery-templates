# Authentication

Azure is the only implemented deployment adapter. Use [the bootstrap guide](azure/bootstrap.md) for first-time identity setup and [GitHub](azure/github-actions.md) / [Azure DevOps](azure/azure-devops.md) for platform configuration.

Local helpers use an explicit Azure CLI login and verify the selected tenant and both accessible subscription IDs. Terraform receives explicit workload/tenant IDs and Azure AD backend settings. Azure DevOps uses separate backend and workload WIF service connections with TerraformTask v5 token refresh. GitHub uses separate OIDC plan/apply identities, each authorized for its intended workload and state scope.

Federation must use the actual platform issuer/subject/audience and the private caller repository/environment. GitHub's immutable subject format applies to newly created or renamed/transferred repositories; [check the official format](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/). The discovery helper prints only non-secret claims, never the token. Azure DevOps service-connection screens provide their current federation values; do not reuse a legacy issuer from an unrelated connection.

Do not create a client secret for these paths. Do not place PATs, Azure access keys or tokens in tfvars, backend HCL, saved helper context or global Git configuration. Optional private Git module access must be installed in isolated job-scoped configuration with narrowly scoped credentials and cleanup; public module sources need no extra token.

Authoritative references: [Azure AD Terraform backend authentication](https://developer.hashicorp.com/terraform/language/backend/azurerm), [Microsoft TerraformTask](https://github.com/microsoft/azure-pipelines-terraform/blob/main/overview.md), [GitHub Azure OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure).
