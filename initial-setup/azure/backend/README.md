# Terraform state backend bootstrap

Follow [bootstrap and migration](../../../docs/azure/bootstrap.md). This root starts locally, creates protected Entra-authenticated storage and returns actual backend coordinates. Migrate existing state before shared use. Keep state, plans and recovery copies private.

## Preserve defaults or isolate a new trial

`resource_group_name_prefix` defaults to empty, preserving `<secondary_region>-<environment>-tfstate-rsg`. For a new disposable lab, [terraform.isolated-lab.tfvars.example](terraform.isolated-lab.tfvars.example) sets it to `aks-lab`: PPRD becomes `uks-pprd-aks-lab-tfstate-rsg`. Every selected environment group receives the qualifier.

The independent storage `prefix` remains 3-8 lowercase letters/digits subject to the final 24-character limit. Account/container naming retain their existing contract. Choose a globally available account name; the example is synthetic.

Set each private `delivery.azure.json` backend resource group to the actual output. This example uses `{secondary_region}-{backend_environment}-aks-lab-tfstate-rsg`. Update remote-state references too. The helper does not infer this qualifier from the storage prefix and adds no new placeholder token. `migrate_state.py` reads actual `backends` outputs, including the resource group.

Choose the qualifier before a new deployment. Changing it on existing state risks resource-group/storage replacement; it is not automatic migration. Network isolation uses the separate `name_prefix` input in Azure Network Foundation.

Read [ordered removal](../../../docs/azure/three-tier-removal.md) before backend deletion. Keep storage containing its own state until dependent workloads and recovery checks are complete. Naming changes do not supply the private worker's storage network path.

## Keep operator-owned state separate

For a new deployment, enable `operator_state_container_name = "example-bootstrap"` before granting component CI access. `operator_state_environment` defaults to `hub` and must name an account owned by this root. The optional container is private and distinct from that account's ordinary environment container; `operator_backend` returns its actual coordinates, or null when disabled. Defaults create no additional container and leave existing outputs unchanged.

Store backend bootstrap and delivery-identity/grant states in this operator-controlled container. Keep component plan/apply Blob Data Contributor grants at their individual environment **container** scopes. Avoid account-wide CI data grants, which also cover the operator container. Do not give component CI storage-account administration or key-list access that could bypass this separation. A separate container is an RBAC boundary only while its parent-account permissions preserve that boundary.

The authorized operator already receives Blob Data Contributor on the owned account for first-time bootstrap. Moving existing state requires an explicit verified migration before any component CI grants; merely enabling this option does not move state. Retain protected recovery evidence and ensure only the selected backend remains active. Worker Blob private endpoints provide network reachability without granting data access.

This is an additive public hardening of the retained first-time backend pattern: operator-controlled trust/bootstrap state is separated from state writable by normal component delivery. It does not introduce a CI identity or grant new component permissions.

## Credential-free validation

```bash
terraform init -backend=false -input=false -lockfile=readonly
terraform fmt -check -recursive
terraform validate
terraform test
```

Mocks validate default/isolated naming and access settings. They do not prove storage reachability, role propagation or migration.
