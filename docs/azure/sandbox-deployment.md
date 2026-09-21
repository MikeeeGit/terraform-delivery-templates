# First Azure sandbox deployment and operational rehearsal

This runbook connects the public examples into a private Azure trial: hub/spoke networking, inspected egress, two independent private AKS slots, Envoy Gateway, the sample application and Application Gateway WAF. It adds a fresh HTTPS installation path while preserving the direct-Service and migration examples. Use the [architecture walkthrough](hub-spoke-platform.md) for ownership and the linked component guides for their full configuration contracts.

The application has two delivery options: the existing pipeline applies Kustomize, or Argo CD reconciles application configuration from Git. Both methods share the original Kustomize source. CI renders and validates it once; Argo CD consumes the resulting plain YAML and reconciles the desired state. Read [delivery methods](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/delivery-methods.md) and the [Argo CD deployment guide](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/argocd-deployment.md). Choose one application owner for each namespace/slot. Terraform still owns Azure infrastructure and the gateway's active traffic target.

This is a paid, explicitly selected sandbox operation. The published examples contain synthetic values and are not ready to apply unchanged. Credential-free tests do not demonstrate your Azure permissions, quota, private networking, managed CSI or WAF path. Record actual evidence at each gate below.

For state-managed CI identities, service connections, native application permissions and generated workload bindings, follow the [three-tier Azure deployment guide](three-tier-azure-deployment.md) alongside this network and traffic runbook. Its Azure workload profile adds an actual Key Vault CSI qualification gate; it retains the explicit first-platform-authority boundary.

## 1. Decide scope, cost and access before provisioning

For the complete example, deploy the hub plus PPRD and PRD **networks**, but start with only the PPRD **AKS pair** and gateway. The current hub peerings and route-only add-on explicitly reference both spoke networks; omitting PRD requires a deliberate private configuration change, not just skipping its apply. UK West recovery workloads are outside this rehearsal. Both slots are in one region; they are upgrade/deployment slots, not regional disaster recovery.

Record privately:

| Decision | Required before apply |
|---|---|
| Azure target | Tenant, backend/hub/PPRD/PRD subscription aliases, region and resource names; aliases may deliberately map to one sandbox subscription if naming and policy remain unambiguous |
| Network | Nonoverlapping hub/spoke, pod and Service CIDRs; real routes to the private management worker; DNS recursion/zone ownership |
| Public hostnames | Controlled web/API/preview names and, if used, private-listener name; replace all `.test` placeholders together |
| Certificates | Existing frontend/backend vault(s), certificate ownership, SANs, complete chain, exportable backend key, renewal plan and network access |
| Delivery | Private consumers, full reviewed shared-template commits, exact OIDC subjects, approval environments and separate build/platform/app identities |
| Operations | Named operator, start/end time, agreed spend limit, alert recipients, cleanup owner and resources intentionally retained |

Estimate the selected region/SKUs using the [Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/) before applying. Create [budget alerts](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets) and retain the estimate with the plan; alerts are not spending caps. The supplied PPRD pair starts four `Standard_D4s_v5` nodes (one system and one user node per slot), and aks02 can grow to three nodes per pool. That is 16 initial vCPUs, up to 32 before upgrade surge; each pool also permits 10% surge. Cluster tiers default Standard. Gateway autoscale defaults to min2/max10; Firewall, gateway, node disks, load balancers/public IPs, registry, storage and optional logs can continue charging while the app is idle. Any smaller sandbox settings are explicit private choices that must leave enough capacity for two controllers/proxies, the app and system workloads.

**Stop point:** if the identity/network/certificate prerequisites or intended spend are unclear, complete the credential-free checks and private configuration first. There is no benefit in leaving billable clusters waiting for a certificate or an unreachable runner.

## 2. Prepare private consumers and input files

Keep public library repositories separate from real environment configuration. One practical private workspace is:

```text
terraform-delivery-templates/  # reviewed public framework checkout
aks-delivery-templates/        # reviewed public application/platform library
network/                      # private azure-network-foundation consumer
firewall/                     # private azure-firewall consumer
routes/                       # private copy of network examples/hub-spoke/egress
aks/                          # private azure-aks-foundation consumer
gateway/                      # private azure-application-gateway consumer
platform/                     # contents of examples/platform-envoy
application/                  # private aks-platform-demo consumer
evidence/                     # private, access-controlled records; never public Git
```

Use a distinct Terraform state key per component/environment/region. If you rename a consumer, update every remote-state reference before its first deployment. After resources exist, retain the state key or perform an explicit migration; a repository rename must not silently select empty state. Pin helper scripts and reusable workflow/template sources to the same reviewed full commit.

### Consolidate optional profiles before helper delivery

The saved-plan helpers and private component pipelines read exactly:

1. `config/global.tfvars`
2. `config/<region>/<environment>/<environment>.tfvars`

They do not discover additional example files. `TF_CLI_ARGS*` and `TF_VAR_*` are deliberately removed by the helper. Terraform also replaces map inputs rather than recursively merging them. A three-file `terraform test` command demonstrates an example composition; it does not configure the authenticated helper.

Merge these selected maps into the corresponding **private target** before the normal plan cycle. Replace existing assignments rather than duplicating them; preserve unrelated entries and replace synthetic IDs/hosts. Review the private Git diff and saved plan.

| Private target | Example values to consolidate | Plan evidence |
|---|---|---|
| Firewall hub | [Platform egress](https://github.com/MikeeeGit/azure-firewall/tree/main/examples/aks-platform) `rule_collection_groups` | Exact registry/auth/CDN and vault destinations; retained other groups/priorities |
| AKS PPRD | [TLS identity](https://github.com/MikeeeGit/azure-aks-foundation/tree/main/examples/ingress-tls) `workload_identities` | Dedicated app UAMI, two issuer federations for the same ServiceAccount, exact vault role |
| AKS PPRD | Complete `clusters` map with actual UDR fields and chosen `.21` ingress metadata | Both slots retained, correct subnet/route-table per slot, no accidental replacement/removal |
| Gateway PPRD | [HTTPS-first](https://github.com/MikeeeGit/azure-application-gateway/tree/main/examples/https-first) `backend_settings`, `backend_dns_records`, `backend_pools` | Live aks01 `.21`, preview aks02 `.21`, HTTPS443 and expected Host/probes |

For an existing serving HTTP deployment use the separate candidate/cutover profiles instead; the fresh profile is not a migration shortcut. Keep the selected target's old reviewed maps and plans available for rollback.

## 3. Bootstrap state, identities and a private management path

Follow [backend bootstrap](bootstrap.md): begin with local state, create private Entra-authenticated storage, then migrate the existing state using the supplied helper. Retain protected recovery copies. Choose globally unique storage/ACR names and real allowed egress addresses. State migration and role propagation are independent gates.

Configure private CI consumers or use the local operator path. The [state-managed identity and connection roots](three-tier-azure-deployment.md) create CI UAMIs, OIDC trust, Azure role assignments and Azure DevOps service connections. Configure approval reviewers, protected environments and private worker access separately. Review the [private component callers](../../examples/azure/component/README.md), [GitHub setup](github-actions.md) and [Azure DevOps setup](azure-devops.md). Separate plan/apply, registry build, platform/bootstrap, ordinary app and workload identities. An Azure Contributor role alone does not grant role-assignment or storage data access.

The public network pack reserves `GatewaySubnet` and hub `shared`; it provisions neither VPN/ExpressRoute connectivity nor a runner VM. Establish a trusted management/worker path with private AKS DNS/routing before Kubernetes operations. A VM in the hub shared subnet or an existing correctly routed private worker is an operator-owned option; its provisioning, hardening and removal must be included in the trial inventory. Never place a diagnostic VM in the dedicated firewall or Application Gateway subnets. Keep public PR jobs on credential-free hosted workers.

Check prerequisites in the intended workload subscription, using read-only discovery first:

```bash
az account show --query '{tenant:tenantId,subscription:id,name:name}' --output table
az aks get-versions --location uksouth --output table
az vm list-skus --location uksouth --resource-type virtualMachines --all --output table
az vm list-usage --location uksouth --output table
az feature show --namespace Microsoft.Compute --name EncryptionAtHost --query properties.state
```

Select supported cluster patches, zone/SKU availability and sufficient family/regional quota including surge. Register required providers/features through the subscription owner; Terraform provider auto-registration is disabled. Host encryption defaults on and needs the feature plus supported VM sizes. Shared custom AKS DNS in another subscription requires `Microsoft.ContainerService` registration in both. Validate actual Entra group object IDs and cross-subscription role scopes. The sample's desired version is not proof of regional availability.

**Gate:** backend migration is verified; correct tenant/subscriptions are selected; worker routing/DNS and outbound tool/chart/identity access are prepared; privilege/federation and quota checks have owners and recorded results.

## 4. Create network, firewall, DNS and route dependencies

Copy the complete [hub/spoke configuration pack](https://github.com/MikeeeGit/azure-network-foundation/tree/main/examples/hub-spoke) into the private network root and replace IDs, backend coordinates, unique registry name and remote-state keys. Keep `enable_peerings=false`. Plan/apply hub, then PPRD and PRD separately. After all states exist, enable peerings and reapply each side. Require all four peering directions to be Connected.

The normal local cycle below selects one private consumer and target; review every context and saved plan. Repeat only for the intended component/target:

```bash
source ../terraform-delivery-templates/scripts/azure/terraform-functions.sh
tf_setup network hub uks
tf_env
tf_init
tf_plan
# Inspect target, state key, resource changes and saved plan before approval.
tf_apply
```

Export outputs from each selected initialized root into a **new private evidence file**, not a public working tree. Review the output schema before retaining it; never export raw state or credential values. The relevant handoffs are:

| Producer | Values consumed next |
|---|---|
| Hub network | `vnet_id`, `vnet-rg`, `subnet_ids.AzureFirewallSubnet`, corresponding prefix, managed private DNS zone IDs, `acr_id`, `acr_name`, `acr_login_server` |
| Spoke network | `vnet`, `vnet_id`, subnet IDs/prefixes for each slot and gateway; actual address spaces |
| Firewall | `firewall_id`, `firewall_private_ip`, policy/public-IP IDs |
| Route add-on | `route_table_ids.pprd.aks01`, `.aks02` and associated subnet IDs |

Apply the firewall against the existing hub subnet/resource group with the consolidated registry/Envoy/CSI egress policy. Standard ACR needs its actual login/auth/data endpoint path; the example Blob wildcard is an explicit tradeoff, not registry-only isolation. Node image egress and private runner package/chart/Trivy-database egress are separate policies. Vault access also needs its own real endpoint and permissions.

Set both spoke VNet DNS server lists to the **actual** firewall private IP before creating AKS nodes. The hub proxy needs links/forwarding to required private zones; custom upstreams must not forward the same queries back in a loop. Prepare route tables with `enable_aks_routes=false`; after reviewing peerings, NSGs, DNS and firewall policy, explicitly enable associations. Keep node route CSVs empty so the add-on is their single owner. Never attach AKS forced-tunnel routes to the Application Gateway subnet.

Use a temporary private test host to verify UDP/TCP DNS, required registry/platform connections and effective routes. An `udr_egress_ready` flag only records operator acknowledgement. Map each real route-table ID into the corresponding cluster target and set `outbound_type="userDefinedRouting"` only after these checks. The original AKS target defaults to managed `loadBalancer` outbound; do not accidentally retain that value after building the UDR design.

**Gate:** actual DNS and egress work from intended node/worker paths; firewall and route associations have one owner; no nonexistent next-hop address or unverified DNS loop is accepted.

## 5. Prepare vaults, create both clusters and bind outputs

Provision/reuse the reviewed certificate vaults before their dependent role assignments. The AKS TLS example creates an application identity and access to an **existing** RBAC vault; it creates no vault or certificate. Backend TLS requires an exportable private key and a valid chain for the real web/API Host/SNI names. The frontend certificate separately covers all selected listener names. The supplied Azure gateway uses standard public-CA backend trust; self-signed/private-CA trust needs an explicit extension that is not provided by this profile. Never place PFX/key/certificate-secret bytes in Git, tfvars, logs or build artifacts.

Update the full AKS target from actual spoke/subnet/DNS/ACR/route outputs. Preserve both cluster entries, independent pod/Service CIDRs and selected versions. Merge the workload identity map and configure real administrative Entra group IDs. Set desired ingress metadata to the chosen Envoy `.21` values; it is metadata until a Kubernetes Service actually allocates that frontend. Apply the reviewed plan.

Verify both slots independently: Entra **user** kubeconfig, private FQDN resolution, node/add-on readiness, kubelet registry permission and authenticated image pulls. Local accounts and Run Command are disabled; do not use `--admin` or make the API public to bypass a failing management path. Allow normal role/federation propagation, inspect the actual error, and review a fresh plan before infrastructure retry.

Export `clusters`, `workload_identities`, `deployment_context` and registry outputs privately, then use [the workload handoff helper](workload-identity-handoff.md). It validates the actual identity, both OIDC issuers and exact subject `system:serviceaccount:platform-demo:platform-demo`, without exporting keys. Review the new delivery JSON and ServiceAccount binding. Update the app and platform declarations consistently with the same applied client ID, tenant ID, vault/object names, namespace and selected cluster targets.

**Gate:** both private cluster APIs and kubelet image pulls work; handoff target/identity checks pass; CSI add-on, workload federation, vault role and actual network path are ready. A successful metadata export is not proof of a successful certificate mount.

## 6. Establish namespace permissions and the independent platform tier

Use the [operator walkthrough](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/operators-walkthrough.md) and [platform services guide](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/platform-services.md). Bootstrap the restricted app namespace and scoped application access with the separately approved bootstrap identity. Set Pod Security policy versions to the actual chosen cluster minor. The platform identity requires cluster-scoped permission for CRDs, GatewayClass, controller RBAC and Helm; ordinary application delivery must remain separate.

The pipeline-driven method needs actual permission for HTTPRoute and SecretProviderClass operations and Gateway status reads. Namespace Azure RBAC Writer alone is not proof of these custom-resource rights. Review the [explicit authorization recipe](https://github.com/MikeeeGit/aks-delivery-templates/tree/main/examples/authorization), including its opt-in Azure ABAC preview and namespace trust boundary. Qualify positive server-dry-run and negative platform-write tests using the actual app deployer on both slots. If preview is unsuitable, choose and validate a different authorization model before app delivery; do not silently broaden the app identity. Argo CD has its own reconciler permissions and registration/bootstrap contract in its deployment guide.

Copy the maintained Envoy platform example's **contents** into the private platform consumer. Replace target IDs and reserved frontend/subnet/source-range values; keep chart/CRD/image pins aligned. Prepare and review its immutable bundle, then install both slots sequentially through the separately approved platform lifecycle. The controller runs in `envoy-gateway-system`; proxy and TLS Gateway are in `platform-demo`. Do not put controller credentials in the app namespace.

First installation may leave Gateway pending because the TLS Secret does not yet exist. The app's live CSI mounting pod synchronizes `platform-demo-tls`; platform controller readiness must succeed first, while full Gateway/HTTPS acceptance follows app rollout. A pending first-use certificate is not permission to ignore later Gateway/route failures.

**Gate:** pinned CRDs are Established; controllers are ready; platform manifests refer to the right namespaces/addresses/hosts; application authorization is proven; neither application method owns or prunes the other platform tier accidentally.

## 7. Deploy one scanned release through the selected application method

Build the protected source commit once, push it to the chosen ACR and scan the exact immutable digest. A promotable receipt exists only after the security gate passes and binds source, digest and trusted producer run. Retain that receipt and its scan result privately. Registry presence or a mutable tag is not equivalent evidence.

For pipeline delivery, use the sample's private callers with `delivery.gateway.apps.json`, the reviewed shared-template SHA and exact selected slots. Render/review the Kustomize bundle and deploy the same digest to both clusters, sequentially by default. Require rollout, observed source revision/slot, current Gateway and HTTPRoute conditions, and certificate-validated web/API responses.

For Argo CD, follow the additional [deployment/design guide](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/argocd-deployment.md) and its operational instructions. Promote the approved digest/source into the reviewed Git desired state for the selected slot, observe reconciliation and perform the same release/HTTPS checks. Argo health/sync status alone is not a test of the Azure request path. Do not run imperative application apply against resources Argo is reconciling. Changing ownership between methods is an explicit controlled handover, preserving platform resources and traffic ownership.

Check the CSI mount and `SecretProviderClassPodStatus`; inspect Secret type/key **names** without printing key bytes. Verify certificate SAN/chain/expiry as a TLS client and rehearse renewal/reload separately. Retain a mounting workload while its synchronized Secret is required. The app's ServiceAccount and projected federation token are separate from the delivery identity.

## 8. Prove the actual Azure traffic path, then add WAF

The reusable HTTPS test uses port forwarding to the selected Envoy Service. It exercises TLS, route and application behavior but bypasses the Azure load balancer. Independently confirm each Service's allocated private IP and test real routed traffic.

The supplied Envoy source ranges allow only the Application Gateway subnet. A management worker in the hub is intentionally excluded from direct ILB access. For private diagnostics, add a separately reviewed narrow worker source range to both private profiles or use another allowed diagnostic path; remove temporary access afterward. Do not put a VM into the dedicated gateway subnet or widen access to the Internet. A timeout from an excluded source is not proof that Envoy is unhealthy.

From an allowed private source, test each real frontend with certificate hostname verification. For example, set the real host/IP/slot values first:

```bash
curl --fail --show-error --resolve "$WEB_HOST:443:$SLOT_PRIVATE_IP" "https://$WEB_HOST/healthz"
curl --fail --show-error --resolve "$WEB_HOST:443:$SLOT_PRIVATE_IP" "https://$WEB_HOST/version"
curl --fail --show-error --resolve "$API_HOST:443:$SLOT_PRIVATE_IP" "https://$API_HOST/api/version"
```

Do not use `-k`. Verify exact expected slot/revision, allowed and rejected hosts, and Cilium NetworkPolicy from explicitly allowed/denied test clients. The final Envoy-to-app hop is HTTP with NetworkPolicy, not workload mTLS. A default kind cluster cannot prove Azure Cilium enforcement.

For a genuinely empty gateway, merge the [HTTPS-first profile](https://github.com/MikeeeGit/azure-application-gateway/tree/main/examples/https-first) into private gateway PPRD inputs: stable alias → verified aks01 `.21`, preview → verified aks02 `.21`, all backend settings HTTPS443. The gateway owns its child alias zone and links; include the hub link when the firewall is the DNS proxy. Use distinct environment alias zones if sharing a hub. Inspect the saved plan and apply only after both backends and frontend certificate access are ready.

Check actual backend health:

```bash
az network application-gateway show-backend-health \
  --resource-group "$GATEWAY_RESOURCE_GROUP" --name "$GATEWAY_NAME"
```

Verify the public/private listener paths, frontend TLS/SANs, redirects, web/API routing, preview's selected release, headers and WAF behavior. Public DNS is separately owned; `curl --resolve` can test an intended hostname against the actual public IP before DNS publication. Enable/review the chosen diagnostic destination without storing secret request bodies. A healthy probe alone does not demonstrate every application route or WAF policy.

**Gate:** both private endpoints and actual WAF frontend requests return the expected release; identity, CSI, DNS, Cilium, source ranges, certificate trust and backend health have real Azure evidence.

## 9. Rehearse update, traffic cutover and rollback

Keep aks01 active and deploy a second scanned source/digest only to aks02 through the chosen method. Check the active slot remains unchanged and the preview shows the new release. Retain the previous source/digest and complete gateway configuration.

Create a separately reviewed gateway saved plan to move the stable alias to the verified candidate, with the correct protocol/Host/probe contract. Neither the application pipeline nor Argo CD changes this Terraform traffic target. Observe DNS/probe/connection convergence and real requests; a TTL does not promise instantaneous or zero-downtime cutover. Retarget preview to the now-inactive slot when preparing the next release.

Rehearse application rollback through the same owner (previous receipt for pipeline delivery; reviewed desired-state reversal for Argo) and traffic rollback through a separate gateway plan. If returning to a legacy HTTP endpoint, restore both address and protocol. Keep data/schema migration and recovery separate; this stateless sample does not prove database rollback or replicated regional failover.

## 10. Retain evidence and remove the sandbox deliberately

Record exact repository/template commits, tool/chart/image digests, state keys, selected Azure IDs, reviewed plans, producer/deployment or reconciliation runs, scan receipts, both-slot responses and observed cutover/rollback outcomes. Keep an explicit passed/failed/not-run table. Retain sensitive environment metadata privately. Do not archive raw kubeconfigs, token-bearing logs, state or TLS key material with a public test report.

Cleanup is an operation with dependencies, not deletion of a state file:

1. Withdraw test client traffic/DNS and remove the gateway or its relevant traffic dependencies after confirming scope.
2. Suspend/detach the selected application reconciler through its documented handover/removal procedure; remove app and platform resources while cluster APIs and certificate/network paths still exist. With Argo, inspect finalizers/prune scope before deleting Applications or controller components.
3. Remove the AKS clusters and identities through their reviewed state. Keep subnet routes/DNS until cluster deletion completes; inventory managed node resource groups, disks, IPs and load balancers afterward.
4. Remove route associations/tables, then firewall, after confirming no remaining clients use its egress or DNS.
5. Disable/remove both peering directions while states still exist; remove spokes, then hub networks and registry only when no consumers remain.
6. Remove separately created runner/test hosts, vaults/certificates, public DNS, federated credentials, role assignments, GitOps credentials/registrations and diagnostic resources according to the retained/removed inventory. Do not remove shared services by assumption.
7. Independently inventory remaining billable resources. Preserve state/backend and recovery evidence until cleanup is verified. Bootstrap storage manages its own state: its final removal requires exporting/reviewing recovery state and an explicit backend retirement procedure. It is reasonable to retain this small protected backend for the next rehearsal.

Use the correct initialized private root and review a destroy plan before invoking the explicit local `tf_destroy` operation. It is not the ordinary saved-plan apply workflow: check that no configuration/context drift occurred between review and execution. Never use resource-group deletion or missing state to bypass ownership/dependency review. Stopping a cluster does not remove all billable dependencies.

## What the validation evidence means

| Evidence | Proves | Still requires Azure qualification |
|---|---|---|
| Terraform format/validate and provider mocks | Declared schema, target contracts and tested composition/guard behavior | Policy, quota, resource IDs, role propagation and actual provider service behavior |
| Local app tests, Helm/Kustomize render and receipt tests | App behavior and selected-source/digest/configuration safety contracts | Cluster admission, runtime networking and managed services |
| Hosted two-cluster pipeline acceptance | Real tested image deployment, Envoy HTTPS, selected-slot update and rollback in its temporary Kubernetes environment | Azure CNI/ILB/private API, Entra, CSI/vault and WAF |
| Hosted Argo acceptance, when a retained run passes | Only the actual reconciliation, ownership and release scenarios in that report | Azure integrations and untested Git-host/identity arrangements |
| This private sandbox rehearsal | The real Azure checks individually recorded as passed | Production load, longer-term rotation/upgrade, observability, recovery and untested scenarios |

A workflow definition is not a passing run. Use retained run artifacts and current commit identifiers when explaining the result, and leave any skipped or failed gate visible.
