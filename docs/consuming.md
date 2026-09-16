# Consuming the templates

## GitHub Actions validation

Copy `examples/github-actions/validate.yml` into `.github/workflows/` in the
consuming repository. Replace both `REPLACE_WITH_40_CHARACTER_COMMIT_SHA` values
with the same reviewed template commit. The workflow reference fixes the YAML;
`template-ref` fixes the implementation scripts. For a fork of this repository,
change `uses` and pass `template-repository` too.

`directory` is relative to the caller repository. `test-directory` is relative to
that Terraform directory. Absolute paths, parent traversal and escaping symlinks
are rejected. Inputs become environment values and literal subprocess arguments,
never executable shell text.

The caller checkout is under `source`; template scripts are separately checked
out under `delivery-templates`. Reusable workflows otherwise run in the caller
repository context. Checkout uses the PR merge commit for validation and does not
persist repository credentials.

Validation runs `fmt -check -recursive`, `init -backend=false` and `validate`, using
an isolated temporary Terraform data directory. Existing backend metadata is not
reused. Existing lockfiles are protected with `-lockfile=readonly`; deployable root
modules and examples should commit them. Libraries without a lockfile can resolve
dependencies and create one locally; review that selection for releases.

Only set `test-directory` for known mocked or credential-free tests. Native
`terraform test` can create resources when a test uses real providers; this
workflow does not rewrite tests to make them safe.

## Azure Pipelines validation

Copy `examples/azure-pipelines/validate.yml`. Configure a repository-scoped GitHub
Azure Pipelines app connection named `github-public-template-read`, or update the
endpoint. The repository alias must be `deliveryTemplates`; the job checks out its
implementation using that resource and its pinned full commit SHA.

Parameters are `directory`, optional `testDirectory`, and optional `jobName`
(default `TerraformValidation`). Set unique `jobName` values to validate several
roots/examples in one pipeline. Use a Microsoft-hosted `ubuntu-24.04` agent.

Enable safe fork-PR handling with no secrets or normal-build permissions. For
Azure Repos, configure PR build validation through branch policies; YAML `pr`
triggers apply to GitHub repositories. Authorize connections per pipeline.

## Deployment

`examples/github-actions/azure-private-delivery.yml` consumes the implemented
Azure adapter. Read `azure-delivery.md` before enabling apply. Other Azure/AWS
examples are explicitly identity preflights, not complete delivery pipelines.
None runs automatically as a workflow in this templates repository.

Example SHA placeholders must be replaced with an actual reviewed published
commit. Branches, movable tags and invented SHAs are not substitutes.
