# Private workload Key Vault

This Terraform example supplies an environment's application vault before the AKS stack creates workload identities and vault-reader roles. It creates a dedicated resource group, an RBAC-enabled Standard Key Vault, a private endpoint and its DNS zone group. Public network access is disabled and purge protection is enabled. It stores no secret or certificate values in Terraform configuration, state or outputs.

Use a separate private state and unique vault name for each environment. Copy the directory into a private infrastructure consumer, replace [terraform.tfvars.example](terraform.tfvars.example), and configure the existing private backend before shared pipeline use. Keep the provider lockfile. The root's standard workflow executes Terraform against this directory; include its reviewed variable file or merge values into the consumer's normal target configuration.

## Dependencies and permissions

| Input | Existing owner |
|---|---|
| Workload tenant/subscription | Selected private delivery configuration |
| `private_endpoint_subnet_id` | Applied spoke `subnet_ids["private-endpoints"]` |
| `private_dns_zone_id` | Applied hub `managed_private_dns_zone_ids["privatelink.vaultcore.azure.net"]` |
| `secret_administrator_object_ids` | Reviewed existing Entra operators/groups or seed-pipeline principals |
| `certificate_seed_operator_object_ids` | Optional reviewed certificate seed operators; defaults to an empty set |

The [hub/spoke network pack](https://github.com/MikeeeGit/azure-network-foundation/tree/main/examples/hub-spoke) already owns the endpoint subnets, central zone and links to the hub/spokes. This vault state adds the endpoint DNS zone group; it does not duplicate VNet links. Custom DNS or Azure Firewall DNS proxy must resolve the linked zone from node and worker networks. Check endpoint approval, NSG policy and routing as well as DNS; a zone ID alone does not provide connectivity. [Microsoft Private Link guidance](https://learn.microsoft.com/en-us/azure/key-vault/general/private-link-service) explains the network and DNS prerequisites.

The Terraform apply identity needs resource-group/vault/private-endpoint creation, subnet join access, role-assignment administration at this vault, and permission to associate records with the existing hub DNS zone. Where the hub is another subscription, grant the apply identity the required DNS-zone rights there too; workload-subscription Contributor does not cover that zone.

Each configured secret administrator receives **Key Vault Secrets Officer** only at this vault. The optional `certificate_seed_operator_object_ids` set separately grants **Key Vault Certificates Officer** at this same owned vault for frontend certificate import and rotation; its default `[]` grants no certificate administration. An operator seeding both backend secrets and a frontend certificate needs both explicit inputs. Removing an object ID from the certificate set removes its Terraform-managed grant on the next reviewed apply. No data permission is implicitly granted to the Terraform caller or CI deployment identities. The AKS stack separately grants **Key Vault Secrets User** to the application's workload identity using this vault's `id` output. Removing an administrator from this map removes its state-managed grant on the next reviewed apply.

## Provision and seed

From a trusted private infrastructure worker:

```bash
terraform init
terraform plan -out=workload-vault.tfplan
terraform show workload-vault.tfplan
terraform apply workload-vault.tfplan
terraform output -json vault
```

The initial ARM deployment needs no secret data access. After creation, seed the actual objects from a worker that reaches the private endpoint and is authenticated as one of the declared secret administrators. Keep secret material in an approved private source and disable shell tracing. The following optional commands read existing local private files, suppress value output and use reviewed object names:

```bash
: "${VAULT_NAME:?Use the applied vault name}"
: "${QUALIFICATION_SECRET_FILE:?Use the private application test secret file}"
: "${BACKEND_CERTIFICATE_PEM_FILE:?Use the approved backend certificate and private-key PEM file}"
az keyvault secret set --vault-name "$VAULT_NAME"   --name platform-demo-qualification --file "$QUALIFICATION_SECRET_FILE"   --encoding utf-8 --only-show-errors --output none
az keyvault secret set --vault-name "$VAULT_NAME"   --name platform-demo-ingress --file "$BACKEND_CERTIFICATE_PEM_FILE"   --encoding utf-8 --content-type application/x-pem-file --only-show-errors --output none
```

The backend TLS object above is deliberately a **secret containing PEM certificate/key material**, matching the CSI profile's `objectType: secret` and `objectFormat: pem`. It is not an Azure Key Vault certificate resource and these commands do not issue a certificate. For frontend Key Vault certificate import, opt in to the separate `certificate_seed_operator_object_ids` grant and follow the [disposable lab certificate guide](../lab-certificates/README.md). The helper produces locally verified backend PEM and frontend PFX inputs for reserved `example.test` names; it never uploads them itself. The backend certificate must cover the real web/API hostnames and satisfy Application Gateway's configured trust. The frontend gateway certificate remains a separately owned dependency. [Azure CLI secret file support](https://learn.microsoft.com/en-us/cli/azure/keyvault/secret?view=azure-cli-latest#az-keyvault-secret-set) describes the seed operation.

Apply the AKS workload identity map with the returned vault ID and both intended slots. Export the AKS identity/federation/role outputs, then run the application handoff and platform/application pipelines described by the parent three-tier deployment guide. Keep object names consistent in the generated SecretProviderClasses. Qualify the live CSI mount and application readiness on each cluster without printing secret contents.

## Validation and lifecycle

```bash
terraform init -backend=false -input=false -lockfile=readonly
terraform fmt -check -recursive
terraform validate
terraform test
```

Provider mocks cover private-only RBAC configuration, purge protection, exact endpoint/DNS dependencies, explicit secret-administrator grants, opt-in vault-scoped certificate operators and rejection of unrelated zone/subscription inputs. They do not prove tenant policy, role propagation, endpoint approval, private DNS reachability or CSI access.

Purge protection cannot be disabled after enabling it. The default soft-delete retention is 90 days; choose an explicit 7-90 day value before creation. Deleting a sandbox vault does not immediately release its name or permit purging it. Plan retention and recovery alongside private state; never delete state to bypass a failed destroy or name conflict.

## Remove the private trial

Follow [ordered three-tier removal](../../../../docs/azure/three-tier-removal.md) after withdrawing traffic and removing the dependent application, platform load balancers and AKS workload identity grants. Keep the private network, cleanup identity and Terraform backend available until this root's reviewed destroy completes.

The provider explicitly sets `key_vault.purge_soft_delete_on_destroy = false`. Terraform therefore requests soft deletion instead of a permanent purge while the resource's `purge_protection_enabled = true` remains intact. Retain the final state and deleted-vault metadata/expiry privately. Deletion does not immediately release the globally unique vault name; recover the original through a reviewed state/ownership procedure, use a fresh trial name, or wait for retention. Never disable protection or discard state to force teardown. See the [AzureRM feature reference](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.81.0/website/docs/guides/features-block.html.markdown) and [Microsoft recovery guidance](https://learn.microsoft.com/en-us/azure/key-vault/general/key-vault-recovery).

Remove the endpoint and its DNS zone group through this state. Hub DNS zones and spoke subnet/VNet links belong to the network states and must remain until their other consumers are gone.

## Application Gateway certificate retrieval

For a vault that supplies an Application Gateway frontend certificate, explicitly set `allow_trusted_azure_services = true` when using the trusted-service integration. The default remains `false`. This changes only the network bypass to `AzureServices`: public network access remains disabled, default-deny remains in place, and the gateway managed identity still needs the declared Key Vault reader role.

The exception permits services on Microsoft's trusted-services list to reach the vault without using its private endpoint; it is broader than a gateway-specific network allowlist. It does not grant those services permission to read secrets. Keep the private endpoint and VNet DNS links for AKS and operator access, and consider a separate certificate vault when its network policy should differ from application secrets.

A disposable live trial with public access disabled and bypass set to `None` received `ApplicationGatewayKeyVaultSecretAccessDenied` after role propagation and verification of the private DNS links. Record actual gateway provisioning and certificate access after opting in; Terraform validation alone cannot qualify the integration. See [Application Gateway certificate integration](https://learn.microsoft.com/en-us/azure/application-gateway/key-vault-certs) and [Key Vault network security](https://learn.microsoft.com/en-us/azure/key-vault/general/network-security).
