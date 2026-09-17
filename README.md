# Terraform delivery templates

Reusable Azure DevOps and GitHub Actions validation, Azure delivery, and local Bash/PowerShell helpers. This public framework carries forward the environment/region and backend-alias model of AZDO-TF-Templates, with organization-specific settings replaced by explicit configuration.

**Start with [getting started](docs/getting-started.md)**. An empty Azure environment starts with the [backend and identity bootstrap](docs/azure/bootstrap.md). A complete network consumer is [azure-network-foundation](https://github.com/MikeeeGit/azure-network-foundation).

| Capability | Included |
|---|---|
| Public pull-request checks | Hosted, credential-free formatting, backend-free initialization, validation and opt-in mocked tests on both platforms |
| Azure DevOps delivery | Environment/region expansion, variable groups, independent backend/plan/apply OIDC service connections, saved plan and deployment environment |
| GitHub delivery | Region matrix, separate plan/apply OIDC identities, isolated credential files, saved plan and deployment environment |
| Local Azure operations | Matching Bash/PowerShell `tf_setup`, init, plan, apply, destroy, import and GitHub dispatch helpers |
| Initial setup | Local-state backend bootstrap, explicit remote migration, new secretless identity helper and private-consumer starters |
| AWS / GCP | [AWS architecture roadmap](docs/aws/architecture.md); no AWS deployment implementation. GCP is future scope. |

Authenticated templates require **trusted private consumers**. Public pull requests never use cloud identities, state access or persistent deployment runners. Apply is disabled by default until the operator configures and verifies the approval controls described in [security](docs/security.md).

Terraform **1.16.3** is the tested CLI pin. Terraform configurations retain `>= 1.9, < 2.0`; the Azure DevOps delivery adapter uses the current TerraformTask v5 OIDC refresh path. Bootstrap/starter AzureRM supports `>= 4.33, < 5.0` and commits its reviewed provider lockfile.

## Find the implementation

- [Architecture and runtime flow](docs/architecture.md)
- [Naming, aliases and delivery.azure.json](docs/conventions.md)
- [Local helpers](docs/azure/local-helpers.md)
- [GitHub Actions delivery](docs/azure/github-actions.md)
- [Azure DevOps delivery](docs/azure/azure-devops.md)
- [Validation consumers](docs/consuming.md), [testing](docs/testing.md), [releases](docs/releases.md)
- [Reviewed changes from the originals](CHANGELOG.md)

The public source is hosted on GitHub. Azure DevOps no longer permits new public projects; Azure mirrors and authenticated consumers are private. See [Microsoft's public-project retirement notice](https://learn.microsoft.com/en-us/azure/devops/organizations/projects/public-projects-retirement?view=azure-devops).

Apache-2.0 licensed. See [LICENSE](LICENSE), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Complete Azure platform example

Follow the [hub/spoke, dual-AKS and WAF gateway scenario](docs/azure/hub-spoke-platform.md) for cross-repository deployment order, state ownership and blue/green operation. [Private network caller examples](examples/azure/hub-spoke/README.md) cover both CI platforms.
