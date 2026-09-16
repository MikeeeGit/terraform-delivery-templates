# Configuration and naming

`delivery.azure.json` is a non-secret configuration file in the **consumer root**. The complete synthetic [starter example](../starter-templates/azure/delivery.azure.json) is the schema reference; schema version is `1`.

| Field | Meaning |
|---|---|
| `tenant_id` | Expected tenant for backend and workload subscriptions |
| `subscriptions` | Alias → subscription UUID map, matching Terraform's `subscription_id_map` |
| `environments.<name>.subscription_alias` | Workload subscription alias |
| `environments.<name>.backend_environment` | State-store environment alias |
| `backend.subscription_alias` | Backend subscription alias, independent of workload |
| `regions` | Allowed region abbreviations |
| `secondary_region`, `prefix` | Values for default backend naming |
| `backend.resource_group`, `storage_account`, `container`, `key` | Literal names or supported format fields |
| `environments.<name>.backend` | Optional per-environment overrides of backend fields |

Supported placeholders are `{repository}`, `{environment}`, `{region}`, `{secondary_region}`, `{backend_environment}` and `{prefix}`. Arbitrary expressions are not executed. Names and path selectors are validated; the generated storage name must fit Azure's 3–24 lowercase alphanumeric requirement.

Defaults preserve the original convention:

```text
resource group: {secondary_region}-{backend_environment}-tfstate-rsg
storage account: {secondary_region}{backend_environment}{prefix}tfstatesa
container: {secondary_region}-{backend_environment}-azdo-tfstate
state key: {repository}-{environment}-{region}.tfstate
```

The `azdo` container suffix is retained for compatibility and can be replaced explicitly in configuration. `repository` is the consumer's name, never the template repository's name. Local `tf_setup` requires the current folder name to match. CI passes the repository name explicitly; override it only when deliberately preserving an existing state key after a rename.

Variables load in order: `config/global.tfvars`, then `config/<region>/<environment>/<environment>.tfvars`. Both must exist. The helper does not parse HCL to infer account IDs: keep the JSON subscription map and Terraform map aligned in review. Terraform providers can explicitly use other subscriptions for legitimate cross-subscription topology; configure and authorize those aliases deliberately.

An optional fourth `tf_setup` prefix argument overrides **backend naming only**. It does not silently rewrite workload tfvars. Update both configurations together when that is intended. No backend guessing, account-context fallback, or legacy container probing occurs.

Commit safe example configuration and `.terraform.lock.hcl`. Put real deployment configuration in private consumers. Keep state, saved plans, generated migration files, local helper receipts and actual secrets out of public source.
