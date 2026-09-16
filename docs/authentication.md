# Workload identity federation

Provision identities and state storage separately from public PR validation.
The preflight examples only test identity; they do not configure trust or approvals.

## GitHub to Azure

Create separate plan and apply service principals or supported managed identities.
Each federated subject identifies the **private caller repository** and its exact
plan/apply environment, not the public template repository. Use the Azure audience
`api://AzureADTokenExchange`. Because environment subjects replace ref subjects,
also restrict each environment's allowed deployment branch to protected `main`.

Plan needs infrastructure read permissions and the narrowly scoped backend data
permissions needed for blob leases. Apply needs only its deployment scope plus
required backend operations. Pre-register resource providers and configure AzureRM
registration appropriately so a read-only plan identity is not asked to register
them. Provider authentication must come from the environment; explicit credentials
or alternate subscription aliases in Terraform override this adapter's contract.

Set consumer variables `AZURE_PLAN_CLIENT_ID`, `AZURE_APPLY_CLIENT_ID`,
`AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `TF_STATE_STORAGE_ACCOUNT`, and
`TF_STATE_CONTAINER`. These identifiers are not tokens; keep actual credentials
out of source and logs. The single-identity preflight uses `AZURE_CLIENT_ID`.

Repositories created after 15 July 2026 use GitHub OIDC subjects containing
immutable owner/repository IDs. Existing repositories may retain legacy subjects
unless opted in or affected by rename/transfer. Obtain the expected subject from
the current setup flow; do not blindly use `repo:owner/name:environment:...` from
older examples. Never print live JWTs to logs.

## GitHub to AWS

Use an IAM OIDC provider and scoped role, audience `sts.amazonaws.com`, and exact
subject conditions for the trusted caller/environment. The newer immutable GitHub
subject format also applies. Preflight variables are `AWS_ROLE_ARN`, `AWS_REGION`
and `AWS_ACCOUNT_ID`; the action checks the allowed account. AWS saved-plan
delivery is future work.

## Azure Pipelines

Use an Azure Resource Manager workload identity federation service connection,
authorized to individual pipelines. Configure environment and service-connection
approvals/branch checks outside YAML. New applicable Azure connections use the
Microsoft Entra issuer; the old Azure DevOps issuer retires on 1 July 2027 for the
documented public-cloud single-tenant/managed-identity scope. Use the connection's
actual issuer and subject.

AWS preflight requires AWS Toolkit 1.15+ and its AWS OIDC service connection with
constrained trust. Do not assume ARM issuer changes apply identically to the AWS
connection; verify the current token metadata and AWS guidance.

Sources: [GitHub Azure OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure),
[GitHub AWS OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws),
[Azure service connections](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/connect-to-azure?view=azure-devops),
[AWS Toolkit federation](https://aws.amazon.com/blogs/modernizing-with-aws/how-to-federate-into-aws-from-azure-devops-using-openid-connect/).
