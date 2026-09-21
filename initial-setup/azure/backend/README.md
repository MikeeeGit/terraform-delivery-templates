# Terraform state backend bootstrap

Follow [bootstrap and migration](../../../docs/azure/bootstrap.md). This root starts locally, creates protected Entra-authenticated storage and returns actual backend coordinates. Migrate existing state before shared use. Keep state, plans and recovery copies private.

## Preserve defaults or isolate a new trial

`resource_group_name_prefix` defaults to empty, preserving `<secondary_region>-<environment>-tfstate-rsg`. For a new disposable lab, [terraform.isolated-lab.tfvars.example](terraform.isolated-lab.tfvars.example) sets it to `aks-lab`: PPRD becomes `uks-pprd-aks-lab-tfstate-rsg`. Every selected environment group receives the qualifier.

The independent storage `prefix` remains 3-8 lowercase letters/digits subject to the final 24-character limit. Account/container naming retain their existing contract. Choose a globally available account name; the example is synthetic.

Set each private `delivery.azure.json` backend resource group to the actual output. This example uses `{secondary_region}-{backend_environment}-aks-lab-tfstate-rsg`. Update remote-state references too. The helper does not infer this qualifier from the storage prefix and adds no new placeholder token. `migrate_state.py` reads actual `backends` outputs, including the resource group.

Choose the qualifier before a new deployment. Changing it on existing state risks resource-group/storage replacement; it is not automatic migration. Network isolation uses the separate `name_prefix` input in Azure Network Foundation.

Read [ordered removal](../../../docs/azure/three-tier-removal.md) before backend deletion. Keep storage containing its own state until dependent workloads and recovery checks are complete. Naming changes do not supply the private worker's storage network path.

## Credential-free validation

```bash
terraform init -backend=false -input=false -lockfile=readonly
terraform fmt -check -recursive
terraform validate
terraform test
```

Mocks validate default/isolated naming and access settings. They do not prove storage reachability, role propagation or migration.
