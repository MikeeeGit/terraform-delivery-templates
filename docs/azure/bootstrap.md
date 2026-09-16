# Bootstrap Azure from an empty environment

The normal helpers and CI workflows expect remote state storage to exist. The bootstrap therefore begins with **local state**, creates the storage, and then migrates that existing state. This resolves the first-run dependency without borrowing a backend from another estate.

Run these steps in a private deployment checkout. The public examples contain no valid tenant, subscription, egress IP or deployment identity.

## 1. Tools, access and naming

Use the repository's pinned Terraform 1.16.3, Azure CLI, Git and Python 3. PowerShell and Bash helpers share the same Python implementation. Azure DevOps users also need the Microsoft Terraform extension and appropriate service-connection permissions.

The bootstrap operator needs permission to create resource groups/storage and assign Azure roles in the backend subscription. Identity setup additionally needs permission to create Microsoft Entra applications/service principals and assign the reviewed roles. Deployment identities are separate from this operator.

Choose these values together:

| Value | Used by |
|---|---|
| Tenant ID | Azure login, bootstrap variables, federation configuration and delivery configuration |
| Backend subscription | Storage bootstrap and delivery backend alias; may differ from workloads |
| Workload subscriptions | Terraform subscription map and delivery environment aliases |
| Region code/location | Backend naming and Azure location, such as ukw/ukwest |
| Prefix | Globally unique storage names; copy the same value into delivery configuration |
| Backend environments | Default hub, pprd and prd stores |
| Administrator public egress IPv4 | Restricted storage firewall access during bootstrap/migration |

Generated storage accounts are `<secondary_region><backend_environment><prefix>tfstatesa`. Azure requires 3–24 lowercase letters/digits and global uniqueness. Check every generated name, especially pprd, before applying. The sample prefix `example` is illustrative; choose an available value that fits the complete name.

Use the actual public egress address of the machine running Terraform, including any VPN/NAT. The sample `203.0.113.10` is documentation-only. Review the allowed IPs; do not open the backend to all addresses.

```bash
az login --tenant <tenant-id>
az account set --subscription <backend-subscription-id>
az account show --query '{tenant:tenantId,subscription:id,name:name}' --output table
```

## 2. Create the backend with local state

Copy `initial-setup/azure/backend` into a private bootstrap checkout, or work in a private copy of this framework. Preserve its ignore rules. Begin without a `remote-backend.tf` file.

Copy `terraform.tfvars.example` to the ignored `terraform.tfvars` and replace all sample values. The HCL intentionally has no remote backend at this point.

```bash
cd <private-bootstrap-directory>
terraform init
terraform plan -out=bootstrap.tfplan
terraform show bootstrap.tfplan
terraform apply bootstrap.tfplan
```

Review the plan before applying it. Keep `.terraform.lock.hcl` with your private bootstrap configuration; it records the provider version/checksums. State, variable files, saved plans and generated backend files remain private and ignored.

The configuration creates one resource group, storage account and private container per backend environment. It disables storage shared keys and anonymous blob access, requires TLS 1.2, uses a deny-by-default firewall, enables blob versioning and retains deleted blobs/containers for 14 days. Replication is LRS; review whether your recovery requirements need a different choice before deployment.

The bootstrap operator receives Storage Blob Data Contributor for state migration and ongoing state access. Initial account/container provisioning uses the ARM route; the storage data-plane readiness check is disabled until the initial role can exist, avoiding a first-bootstrap permission cycle. Azure role propagation may take time. If a first attempt fails after resources were created, retain the local state, confirm permissions/network reachability, review a fresh plan and retry; do not delete state and start over.

Check the resulting coordinates:

```bash
terraform output -json backends
```

These coordinates are not credentials, but are still environment-specific information for your private deployment configuration.

## 3. Migrate the bootstrap's existing state

Use the framework's migration helper against the directory you just applied:

```bash
python3 <templates>/initial-setup/azure/migrate_state.py \
  --directory <private-bootstrap-directory> --environment hub
```

The helper requires existing local state and refuses to overwrite an existing `remote-backend.tf`. It reads the created backend output, selects the hub store, and uses the separate key `terraform-delivery-bootstrap.tfstate`.

It asks you to type `migrate`, generates backend configuration, and invokes Terraform's interactive `init -migrate-state`. Read Terraform's migration prompt as well. It compares state lineage, serial and resource data before/after migration and preserves local state/backup files.

If migration fails, keep both states and generated files. Inspect the actual active backend before retrying; do not remove the guard file merely to force a rerun. The script deliberately stops for inspection rather than automatically deleting or reconciling state.

After success, run a fresh plan in the bootstrap directory and verify that resources are already managed. Retain an encrypted/offline recovery copy according to your recovery policy until remote-state recovery is tested. Never commit the local backup or migration-generated backend coordinates to a public repository.

Preserve the backend selection for future checkouts. In the **private bootstrap repository**, review and commit the non-secret generated `remote-backend.tf` declaration (it is initially ignored, so use `git add -f remote-backend.tf` after review). Retain the generated backend coordinates in your protected private configuration or secret/configuration store. On a fresh checkout, restore that configuration and run `terraform init -backend-config=.backend.generated.hcl` before planning. Confirm the remote backend and existing resources before making changes. Local state, backups and saved plans remain ignored.

The bootstrap state now manages the storage containing itself. Treat storage deletion, firewall changes and role removal as recovery-sensitive changes. Export a protected backup and plan access/recovery before changing those controls.

## 4. Populate delivery configuration

Copy the starter's `delivery.azure.json` into the private workload root and update it from the bootstrap outputs. Keep the same prefix, region, environment aliases and backend names.

The default aliases allow dev to use pprd's store, shr to use hub's, and bcdr to use prd's. State keys remain distinct: `<repository>-<environment>-<region>.tfstate`. The bootstrap key is separate from these workload keys.

For azure-network-foundation, update both `config/global.tfvars` and `delivery.azure.json` with matching subscription IDs, and update the explicit remote-network backend entries in the selected environment tfvars.

## 5. Configure federation and roles

Prefer secretless workload identity federation. Do not create a client secret merely to follow old setup instructions.

For GitHub, create a **private** consumer repository and the environments used by the workflows:

- `<environment>-<region>-plan`
- `<environment>-<region>-apply`

For example, pprd/uks uses `pprd-uks-plan` and `pprd-uks-apply`. Add protected-branch restrictions and required approval checks as appropriate before enabling apply. Configure repository variables `AZURE_PLAN_CLIENT_ID`, `AZURE_APPLY_CLIENT_ID` and `TERRAFORM_DELIVERY_SHA`; the last value is the full reviewed framework commit corresponding to the release.

Use each platform's **actual issuer, subject and audience**. A default GitHub environment subject may resemble `repo:OWNER/REPOSITORY:environment:pprd-uks-plan`, but organization/repository subject customization can change it. Do not copy a guessed subject into Azure.

The optional `scripts/github/oidc_subject.py` helper prints only `iss`, `sub` and `aud` from a manual private setup job. Run it on an isolated hosted runner with `id-token: write`, the exact intended environment, and `PRIVATE_REPOSITORY` set from the actual repository-private property. This discovery job needs no Azure credential. Do not print the full JWT.

For Azure DevOps, the automatic workload identity federation service-connection wizard can create and connect the identity itself. Use that route directly when appropriate; do not then run the new-app helper against the identity it already created. For a manual route, follow the current service-connection UI/API sequence and use the exact issuer/subject it provides. Authorize only the intended pipelines. Configure the Microsoft Terraform extension, deployment environments/approvals, an optional variable group and, if consuming the public GitHub templates, the repository service connection named in the starter.

Azure DevOps supports separate plan, apply and backend service connections. The GitHub implementation uses separate plan/apply identities; each needs access to the selected backend as well as its workload permissions.

| Identity/purpose | Starting scope to review |
|---|---|
| Workload plan | Reader over the resources being planned; additional read permissions only where needed |
| Workload apply | Contributor at the narrow scope required to create/manage the stack |
| State operations | Storage Blob Data Contributor scoped to the needed container |
| Optional runner firewall changes | Storage Account Contributor on the backend account, plus any separately reviewed Key Vault firewall permission |

Plan access is not read-only overall: acquiring state locks and accessing the blob requires backend permissions. The example root creates resource groups, so a role scoped to a not-yet-existing group cannot create those groups; either use the necessary subscription scope or change ownership deliberately.

For GitHub or an explicitly planned new-app setup, review `initial-setup/azure/federation.json.example` and save a private configuration with the intended `tenant_id`, unique application names, exact federation values and scoped roles:

```bash
python3 <templates>/initial-setup/azure/federate.py <private-federation.json>
python3 <templates>/initial-setup/azure/federate.py <private-federation.json> --apply
```

The first command reviews without creating identities. The second prompts before creation. Use a federations list with a unique name, exact issuer and exact subject for every trusted environment/region; the legacy single federation object is also accepted. The helper creates new apps/service principals, those configured federated credentials, and the scoped role assignments. An identity used across multiple GitHub environment/region jobs needs a credential for each actual subject; plan and apply remain separate identities. It does not create CI service connections, environments, approvals or repository settings for you, and does not silently modify existing apps.

Progress/client IDs are written to the ignored `.terraform-delivery/identity-receipt.json`. After a partial failure, inspect the receipt and Azure objects before deciding how to reconcile. Keep application names unique; rerunning is intentionally not an automatic update operation.

## 6. First network plan and apply

Return to [getting started](../getting-started.md), select the private workload repository/environment/region with `tf_setup`, initialize the chosen backend, and review a saved plan.

For the network foundation, create selected networks with peerings disabled first, then enable peerings once their remote states exist. Configure DNS links or resolver forwarding before expecting private endpoints to resolve from client VNets.

## Validation limits

Source validation and mocked tests cover configuration, targeting, receipts and expected command behavior. They do not demonstrate role propagation, your tenant's policies, private network reachability, service-connection approvals or a real Azure deployment. Record a sandbox deployment separately after configuring your own private consumer and budget.
