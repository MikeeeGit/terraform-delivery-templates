# Terraform delivery templates

[![Template checks](https://github.com/MikeeeGit/terraform-delivery-templates/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/MikeeeGit/terraform-delivery-templates/actions/workflows/ci.yml)

Reusable Terraform validation for GitHub Actions and Azure Pipelines, plus private
Azure delivery for GitHub Actions. Public contributors validate code without cloud
credentials; trusted deployments use workload identity federation and a reviewed
saved plan.

This repository contains the delivery layer, synthetic tests and consumer
examples. It contains no live environment configuration or Terraform state.

| Capability | GitHub Actions | Azure Pipelines |
| --- | --- | --- |
| Formatting, backend-free initialization and validation | Implemented | Implemented |
| Optional credential-free Terraform tests | Implemented | Implemented |
| Azure workload identity preflight | Starter example | Starter example |
| AWS workload identity preflight | Starter example | Starter example |
| Private Azure saved-plan deployment | Implemented; apply disabled by default | Planned |
| AWS saved-plan deployment | Planned | Planned |
| GCP adapters | Future scope | Future scope |

**Qualification:** local Python tests, Terraform mock tests and workflow linting
validate the implementation. Hosted OIDC, environment approval policies and actual
resource deployment require consumer integration testing. A workflow file is not
proof of a successful cloud deployment.

## Start here

1. Run the local checks below or copy a [validation example](examples/).
2. Follow [consuming templates](docs/consuming.md) and replace both template SHA
   placeholders with the same reviewed published commit.
3. For deployment, use a private deployment repository and follow
   [Azure delivery](docs/azure-delivery.md). `enable-apply` remains `false` until
   the externally configured approval gate is verified.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/install_terraform.py --install-dir .tools/bin
PATH="$PWD/.tools/bin:$PATH" python3 scripts/validate.py \
  --source-root "$PWD" --directory tests/fixtures/mock-module --test-directory tests
```

The Linux amd64 installer verifies the reviewed release checksum.
`.terraform-version` selects Terraform **1.16.3**. The implementation requires that
selected version, so plan and apply cannot accidentally use different CLIs.

## Design

- Shared Python scripts pass literal argument lists and validate paths.
- Public PR jobs have no OIDC permissions, cloud credentials or backend access.
- Private Azure delivery binds plans to source commit, run, backend, identities,
  lockfile and CLI version, then applies the same binary with state locking.
- Plan integrity is checked against a digest carried separately from the artifact.
- Approvals and branch protections are configured outside repository YAML.
- Actions and consuming template references use full upstream commit SHAs.

Read the [security model](docs/security.md), [authentication guide](docs/authentication.md),
[test guide](docs/testing.md) and [release policy](docs/releases.md).

GitHub is the intended public host. Microsoft retired new Azure DevOps public
projects in April 2026 and will convert existing public projects to private in
2027. Azure Pipelines can consume public GitHub source from a private project.
[Microsoft retirement notice](https://learn.microsoft.com/en-us/azure/devops/organizations/projects/public-projects-retirement?view=azure-devops).

Licensed under [Apache-2.0](LICENSE).
