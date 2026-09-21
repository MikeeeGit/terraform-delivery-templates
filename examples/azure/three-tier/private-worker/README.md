# Private Azure deployment worker

This small Terraform root supplies the trusted network-connected worker needed by the three-tier Azure example. It owns a dedicated resource group, Ubuntu 22.04 Gen2 VM, NIC and NIC-level NSG. It can also own Blob private endpoints for explicitly selected state storage accounts.

The default has **no public IP and no inbound access**. A separately reviewed `operator_ssh_cidr` IPv4 **/32** enables one Standard public IP and TCP/22 from that address only. SSH passwords remain disabled. The explicit deny rule overrides Azure's default inbound VNet allow; no inbound CI service port is needed.

The default VM is `Standard_D2s_v4` with two vCPUs/eight GiB, a 64-GiB Standard SSD OS disk, trusted launch, the Azure VM agent and encryption at host. The exact Canonical Marketplace image version is a required input; floating `latest` is rejected. Verify image/SKU/feature availability and include the worker in regional and VM-family quota estimates.

This root is validated with Terraform/provider mocks. It does not claim a running Azure worker, functioning private DNS or an executed CI job.

## Inputs and ownership

| Input | Purpose |
| --- | --- |
| `tenant_id`, `subscription_id`, `location` | Explicit worker deployment target |
| `name_prefix` | Unique prefix for the owned resource group and worker resources |
| `subnet_id` | Existing management/worker subnet in the selected subscription |
| `admin_ssh_public_key` | Your public key; the private key stays outside Terraform |
| `image_version` | Reviewed exact Canonical Jammy 22.04 Gen2 image version |
| `operator_ssh_cidr` | Optional single operator IPv4 /32; null preserves private-only access |
| `blob_private_endpoints` | Map of owned state account IDs, endpoint subnet IDs and existing Blob private-DNS zone IDs |
| `enable_managed_identity`, `identity_state_roles` | Optional worker-local identity with explicitly scoped container data access |

The network tier owns the supplied subnets, UDRs, central DNS zones and VNet links. This root attaches an NSG to its own NIC and never replaces a subnet's NSG or route table. Private AKS APIs, vault endpoints and state Blob endpoints must resolve and route from the worker.

With no public IP, supply an explicit working outbound path such as the reviewed hub Firewall route. Do not assume Azure's historical implicit outbound access exists. Firewall rules must also permit the worker's actual Azure login, CI service, package, chart, registry and scanner endpoints. AKS node egress rules alone do not describe every worker dependency.

The optional operator public IP is an explicit management/outbound path when the subnet routes permit it. If a default route instead sends traffic through a firewall, review return-path symmetry before relying on direct public SSH. A changing operator IP requires an updated reviewed /32 and Terraform apply; do not widen the rule to regain access.

## State Blob private endpoints

Azure Storage public-IP rules cannot provide the intended access from a same-region Azure worker. Use [Blob private endpoints](https://learn.microsoft.com/en-us/azure/storage/common/storage-private-endpoints) and the existing hub `privatelink.blob.core.windows.net` zone. [Storage network limitations](https://learn.microsoft.com/en-us/azure/storage/common/storage-network-security-limitations) explain the same-region public-IP restriction.

Each `blob_private_endpoints` map item names:

```hcl
blob_private_endpoints = {
  state = {
    storage_account_id  = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/examplestate"
    subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/hub-rg/providers/Microsoft.Network/virtualNetworks/hub/subnets/private-endpoints"
    private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/hub-rg/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
  }
}
```

Use applied IDs and retain ownership of every selected endpoint in the trial inventory. The network tier must link that zone to the worker VNet. Endpoints grant network connectivity, not storage permissions. Check endpoint approval, DNS returning the private IP and the actual CI identity's container data access before state operations.

The optional system identity is disabled by default. Its only accepted grants are `Storage Blob Data Reader` or `Storage Blob Data Contributor` on individual Blob containers. These are still significant permissions: state can contain sensitive application data, and any trusted process on the VM can request that identity's token. Ordinary CI jobs should use their separately federated plan/apply/build/platform/application identities; this root grants no subscription administration.

## Plan a private consumer

Copy this root and its lockfile to a private consumer. Add its reviewed backend and normal private delivery configuration before using shared component pipelines. The public [worker.tfvars.example](worker.tfvars.example) contains synthetic IDs and deliberately omits a usable operator key.

Review the actual image version:

```bash
az vm image show --subscription "$WORKER_SUBSCRIPTION_ID" \
  --location "$WORKER_LOCATION" \
  --urn Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest \
  --query name --output tsv
```

Put the returned reviewed version into the private input. The example version was available in UK South when prepared; other regions and later runs must verify availability.

Generate/store your SSH key outside the repository using the normal operator process, then supply only its public half:

```bash
set -euo pipefail
: "${WORKER_SSH_PUBLIC_KEY:?Path to your own SSH .pub file}"
export TF_VAR_admin_ssh_public_key="$(cat "$WORKER_SSH_PUBLIC_KEY")"
terraform init -input=false -lockfile=readonly
terraform plan -var-file=worker.private.tfvars -out=worker.private.tfplan
# Apply the reviewed private saved plan through the authorised operator/pipeline.
terraform apply worker.private.tfplan
terraform output -json > worker.applied.json
```

Keep plans/state private. Initial bootstrap may need a temporary operator-owned state path before the worker and its Blob endpoints exist; migrate that state deliberately and retain recovery evidence. Do not run two state backends against the same worker resources.

## Bootstrap and CI lifecycle

1. Use the private management route, or the explicitly enabled /32 SSH path, with your own key. Verify the host identity against an independently trusted channel before accepting it. Azure VM Run Command can retrieve the initial public host-key fingerprint or install reviewed non-secret packages; do not use it to store registration tokens or copy an operator token cache.
2. Install reviewed Azure CLI, Terraform, Git and required build tools. Use the shared delivery repository's pinned tool installer and hashed Python requirements for kubectl, kubelogin and Helm. Validate versions and private DNS/routes before registering any runner.
3. For the initial native-platform grant, use a separate operator account/session and dedicated `AZURE_CONFIG_DIR`. Perform the supported interactive or device-code Azure login on the worker. The [platform bootstrap command](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/platform-ci-bootstrap.md) requires an actual Entra user and observed administrator-group membership. Never place that operator session in the CI runner account; log out and remove its temporary cache after bootstrap.
4. Register only a trusted private repository's ephemeral runner/agent using the CI host's short-lived registration mechanism. Transfer its registration material over the authenticated management channel into private temporary files/stdin, without command tracing. Tokens, private keys and agent credentials do not belong in Terraform variables, state, cloud-init, Git or published artifacts.
5. Run one protected job at a time on this small worker. Jobs authenticate using their purpose-specific federated identities. Do not expose this worker to public pull requests, fork code or arbitrary repositories.
6. Remove the runner registration after its assigned job, clear its workspace and temporary credential directories, and retain the permitted private validation evidence. Rebuild the worker from its pinned infrastructure after untrusted execution or suspected compromise.

The Terraform root deliberately creates infrastructure only: it contains no CI registration token, agent registration extension, cloud-init or ambient subscription grant. The full [three-tier worked example](../../../../docs/azure/three-tier-worked-example.md) records the chosen CI host, caller, source and evidence for the actual trial.

## Outputs and removal

`worker` reports VM ID/name, resource group, private IP, optional public IP, SSH username, subnet, size, image version and optional identity principal ID. `blob_private_endpoints` reports owned endpoint IDs; `identity_state_roles` records exact granted scopes. None contains a credential.

Retain this worker and state connectivity until application, platform and dependent infrastructure cleanup finishes. Remove runner registrations and operator sessions first. Then create/review a destroy plan for this root from an independent authorized host that can still access the backend. Removing the worker also removes its owned NIC/NSG, optional public IP, Blob private endpoints and explicitly managed worker identity roles; the existing network, DNS zone and state accounts remain separately owned.

Destroying its Blob endpoint can remove the worker's backend path during cleanup. Preserve the operator's separately tested state access until the final state write completes. Only then retire the hub/backend according to the [removal procedure](../../../../docs/azure/three-tier-removal.md). Verify the final Azure resource inventory rather than treating a disconnected SSH session as successful cleanup.

## Credential-free validation

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test
```

Mock tests check default isolation, the exact /32 SSH opt-in, key-only/encrypted VM configuration, pinned image, state endpoint/DNS binding, narrow optional identity roles and rejected broad inputs. Real allocation, SSH, DNS, private endpoint access and CI federation require the separate Azure trial.
