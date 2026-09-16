# Credential-free validation consumers

The stable entrypoints remain `.github/workflows/terraform-validate.yml` and `azure-pipelines/jobs/terraform-validate.yml`. Both use hosted Linux agents, read-only checkout credentials, backend-disabled initialization, the tested Terraform version and a reviewed lockfile when present. They need no cloud service connection.

For GitHub, use [the example](../examples/github-actions/validate.yml). Pin the reusable workflow and its `template-ref` checkout to the same reviewed release commit. Inputs are `directory` (default `.`), `test-directory` (empty by default), `template-ref` (full SHA), optional `template-repository`, and `var-files` (newline-separated paths).

```yaml
with:
  template-ref: ${{ vars.TERRAFORM_DELIVERY_SHA }}
  test-directory: tests/targets
  var-files: |
    config/global.tfvars
    config/uks/pprd/pprd.tfvars
```

For Azure DevOps, use [the example](../examples/azure-pipelines/validate.yml), preserving the `deliveryTemplates` resource alias. Parameters are `directory`, `testDirectory`, `varFiles` and optional `jobName` (default `TerraformValidation`). Give each invocation a distinct jobName when validating multiple roots/examples. Azure Repos PR checks are configured as build-validation branch policies; YAML `pr` triggers apply to other supported source types.

Tests are opt-in because provider-backed tests could contact a cloud. Public consumers must use mocked providers or other credential-free tests. `var-files`/`varFiles` apply only to the Terraform test command, in listed order; they do not turn validate into an authenticated plan. Each path must be a regular committed file in `git archive HEAD`, inside the selected root, with no symbolic-link components. Absolute, escaping, ignored/export-ignored, untracked and staged-only inputs fail before execution.

The underlying CLI is useful locally:

```bash
python3 scripts/validate.py --source-root "$PWD" --directory path/to/root \
  --test-directory tests --var-file config/global.tfvars \
  --var-file config/uks/pprd/pprd.tfvars
```

Validation executes provider/plugin code and may download dependencies. Isolation and lack of credentials are the security boundary; successful validation is not proof of cloud permissions or connectivity. Authenticated delivery has separate [GitHub](azure/github-actions.md) and [Azure DevOps](azure/azure-devops.md) entrypoints.
