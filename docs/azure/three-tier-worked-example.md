# Worked Azure deployment: three tiers and two AKS slots

Deploy a disposable Azure environment through Terraform, platform and application pipelines, then rehearse an inactive-slot update, traffic switchover and rollback. Use the [identity architecture](three-tier-azure-deployment.md) for the contracts and read [ordered removal](three-tier-removal.md) before creating resources.

For the runnable disposable Kubernetes counterpart, use the [kind worked example](https://github.com/MikeeeGit/aks-platform-demo/blob/main/docs/WORKED-EXAMPLE.md). It exercises shared deployment components without creating Azure resources.

**Qualification status:** the disposable direct-delivery Azure trial passed dual-slot deployment, real Key Vault CSI access, standby-only promotion, WAF traffic cutover and traffic rollback on 21 September 2026. See the [dated qualification record](qualification-2026-09-21.md) for exact runs, removal results and limits. For a new deployment, start your own evidence rows at **not run**; prior results do not qualify a different subscription or configuration.

## Select scope and capacity

The example uses `pprd/uks` as a selector; that name does not authorise changes to an existing environment. Use fresh names and states. A dedicated trial subscription can map hub, pprd and prd aliases to one subscription, retaining distinct resource names and keys.

Create hub and both spoke **networks**, one firewall/route add-on, one workload vault, the PPRD AKS pair and one WAF gateway. Leave PRD clusters/gateway and regional recovery workloads undeployed. The maintained network/route pack references both spokes; omitting one requires an intentional configuration change.

Use the maintained [disposable dual-AKS lab profile](https://github.com/MikeeeGit/azure-aks-foundation/tree/main/examples/disposable-lab). Each slot has two `Standard_D4s_v4` system nodes, no user pool, fixed counts and `sku_tier = "Free"`. Its explicit `system_pool.only_critical_addons_enabled = false` allows application/Envoy workloads on those nodes. Normal inputs default to `true`, preserving dedicated system pools and a separate user pool.

This is an evaluation tradeoff: application/controller pressure can affect system workloads, and the Free tier has no financially backed control-plane uptime SLA. Preserve replicas, readiness/disruption protections and host encryption. If scheduling or requests exceed capacity, stop and review more capacity; optional Argo services add demand. The dated Azure trial exercised this small profile for functional acceptance, not a load or upgrade-capacity benchmark.

Microsoft currently documents at least two nodes and a four-vCPU VM for system pools; B-series is unsupported there. The selected D4s_v4 nodes each have four vCPUs. See [system pool requirements](https://learn.microsoft.com/en-us/azure/aks/use-system-pools) and [AKS evaluation tiers](https://learn.microsoft.com/en-us/azure/aks/free-standard-pricing-tiers).

| Capacity event | DSv4-family vCPUs |
| --- | ---: |
| Both slots at steady state: four D4s_v4 nodes | 16 |
| One slot adds its single upgrade surge node | 20 |
| Both slots surge concurrently | 24 |
| Private D2s_v4 worker, accounted separately | 2 additional |

Serialize slot upgrades for this trial: reserve **16 steady AKS vCPUs plus four surge vCPUs**, then add the worker and any other regional/family usage. A worker-inclusive 24-core quota is insufficient for two concurrent surges if the worker also uses DSv4. SKU visibility does not grant quota or guarantee allocation. The profile retains `max_surge = "10%"`, which adds one node on a two-node pool.

Merge the profile's complete `clusters` map into the private AKS target before helper/CI delivery; extra example tfvars are not automatically loaded. Keep fixed counts and omit both `min_count` and `max_count`. Choose available zones and supported versions. Retain a regional estimate from the [pricing calculator](https://azure.microsoft.com/pricing/calculator/), a budget alert and cleanup time (budget alerts do not stop spending). Free cluster management does not make nodes, disks, Firewall, WAF, load balancers, ACR, workers or storage free.

Read-only preflight in the selected subscription:

```bash
az account show --query '{tenant:tenantId,subscription:id,name:name}' --output table
az aks get-versions --location uksouth --output table
az vm list-skus --location uksouth --resource-type virtualMachines --all --output table
az vm list-usage --location uksouth --output table
az feature show --namespace Microsoft.Compute --name EncryptionAtHost --query properties.state
```

Select current supported versions, family/regional quota including surge, provider registrations and encryption-at-host support. The public example's desired version is not proof of availability. Set namespace Pod Security versions to the chosen Kubernetes minors.

## Prepare consumers and state ownership

Three tiers do not imply one Terraform state. The maintained component CI caller expects each component at its private repository root. Use this local layout:

```text
workspace/
  terraform-delivery-templates/  # reviewed public library
  aks-delivery-templates/        # reviewed public library
  bootstrap-state/              # framework initial-setup/azure/backend
  aks-lab-delivery-identities/   # framework initial-setup/azure/delivery-identities
  aks-lab-azure-devops-connections/ # federated connections root
  aks-lab-network/               # private azure-network-foundation consumer
  aks-lab-firewall/              # private azure-firewall consumer
  aks-lab-routes/                # complete network examples/hub-spoke/egress root
  aks-lab-private-worker/        # framework examples/azure/three-tier/private-worker
  aks-lab-workload-vault/        # framework examples/azure/three-tier/workload-vault
  aks-lab-aks/                   # private azure-aks-foundation consumer
  aks-lab-gateway/               # private azure-application-gateway consumer
  aks-lab-platform-services/     # contents of shared examples/platform-envoy
  aks-lab-application/           # complete private aks-platform-demo consumer
  evidence/                     # private run records
```

For this new trial, set network `name_prefix = "aks-lab"` and backend `resource_group_name_prefix = "aks-lab"`. They preserve old defaults when empty but isolate new names: `uks-pprd-aks-lab-vnet-rg-01` for the VNet group and `uks-pprd-aks-lab-tfstate-rsg` for a UK South backend group. Use the same network qualifier on hub/spokes. See [network naming](https://github.com/MikeeeGit/azure-network-foundation/tree/main/examples/isolated-lab) and [backend isolation](../../initial-setup/azure/backend/README.md).

Choose a separate globally unique alphanumeric storage `prefix`. Set every private delivery backend resource-group template to `{secondary_region}-{backend_environment}-aks-lab-tfstate-rsg` and update all remote-state coordinates from actual outputs. The helper does not infer a resource-group qualifier from the storage prefix. These inputs must be chosen before first deployment; changing them on existing state can replace resources.

Set `WORKSPACE` to this directory, use `umask 077` and create the evidence directory. Pin each library's reusable templates and helper checkouts to the same reviewed full commit. Commit consumer configuration before rendering: helpers archive the selected commit, not uncommitted changes.

Record these state keys before first init. They assume the private component names above.

The supplied teardown helper enforces these directory names, state keys and isolated resource-group names. Use this exact profile for the worked trial. Different naming, regions or shared resources require an explicitly adapted and tested ownership guard.

| Order | Root/target | State key | Dependency |
| --- | --- | --- | --- |
| 1 | Backend bootstrap | `terraform-delivery-bootstrap.tfstate` after migration | Authorised operator |
| 2 | Network hub/uks | `aks-lab-network-hub-uks.tfstate` | Backend; peerings disabled |
| 3 | Delivery identities | `aks-lab-delivery-identities-ENV-uks.tfstate`, one each for hub/pprd/prd | Backend, actual hub ACR and existing grant scopes |
| 4 | Azure DevOps connections | `aks-lab-azure-devops-connections-ENV-uks.tfstate`, one each for hub/pprd/prd | Identities and exact private lab pipeline IDs |
| 5 | Network pprd/uks and prd/uks | `aks-lab-network-pprd-uks.tfstate` / `aks-lab-network-prd-uks.tfstate` | Hub zones; then enable peerings |
| 6 | Private worker hub/uks | `aks-lab-private-worker-hub-uks.tfstate` | Hub subnet, Blob DNS and backend accounts |
| 7 | Firewall hub/uks | `aks-lab-firewall-hub-uks.tfstate` | Firewall subnet |
| 8 | Routes hub/uks | `aks-lab-routes-hub-uks.tfstate` | Firewall and spokes |
| 9 | Workload vault | `aks-lab-workload-vault-pprd-uks.tfstate` | Endpoint subnet and vault DNS zone |
| 10 | AKS pprd/uks | `aks-lab-aks-pprd-uks.tfstate` | Network, DNS, ACR, routes and vault |
| 11 | Gateway pprd/uks | `aks-lab-gateway-pprd-uks.tfstate` | Both HTTPS backends and frontend certificate |

Set `operator_state_container_name = "aks-lab-bootstrap"` in the isolated backend input. Keep bootstrap, identity/grant and optional service-connection states in that operator-only container; component CI identities receive data roles only on their component containers. Granting CI write access to the identity state would let it alter its own access model. Backend bootstrap starts locally and migrates its existing state using [the bootstrap guide](bootstrap.md), selecting `--operator-state` for this profile. Configure a private AzureRM backend with `use_azuread_auth = true` and a separate explicit key for each standalone identities/connections/vault root. Those roots use reviewed `terraform.tfvars` and their documented Terraform commands; the component helper does not configure them automatically.

Update all network/route remote-state references if names or keys change. Never initialise two roots against one key, or silently switch keys after deployment. State, saved plans, real inputs, observations and reports stay private.

## Tier 1: provision infrastructure and identities

### First bootstrap and CI trust

1. Apply and migrate the backend as the authorised operator.
2. Copy the complete [hub/spoke pack](https://github.com/MikeeeGit/azure-network-foundation/tree/main/examples/hub-spoke) into `aks-lab-network`. Replace synthetic IDs, backend coordinates, state keys and the globally unique ACR name. Keep peerings disabled.
3. Apply hub as the operator. Its actual ACR ID is required for the build identity's scoped grant. This resolves initial trust/resource dependencies.
4. Apply [delivery identities](../../initial-setup/azure/delivery-identities/README.md). Keep plan, apply, build, platform and app identities distinct. Code the actual backend/ACR grants and cross-subscription subnet, DNS, remote-state and role-administration rights.
5. For Azure DevOps, apply [federated connections](../../initial-setup/azure/azure-devops-connections/README.md), authorising only actual pipeline IDs. For GitHub, protect environments and configure exact federation subjects and client-ID variables.

Each private component repository has its own GitHub OIDC subject. Expand the federation map for its actual repository/environment pairs; a subject for one infrastructure repository does not authenticate other component repos. Split identities where federation limits require it.

Infrastructure jobs use `hub-uks-plan/apply`, `pprd-uks-plan/apply` and PRD network equivalents. Build uses `pprd-image-build`; platform uses `platform-pprd-uks-aks01/aks02`; app uses `pprd-uks-aks01/aks02`. Here a slash abbreviates two distinct environment names, not a literal slash in their names.

Use [private component callers](../../examples/azure/component/README.md) for subsequent network, firewall, routes, AKS and gateway delivery. Each has saved-plan review and apply; the templates do not automatically orchestrate a cross-repository transaction. Local equivalent for one selected component:

```bash
cd "$WORKSPACE/aks-lab-network"
source "$WORKSPACE/terraform-delivery-templates/scripts/azure/terraform-functions.sh"
tf_setup aks-lab-network hub uks
tf_env
tf_init
tf_plan
# Review selected state, source and saved plan before applying.
tf_apply
terraform output -json > "$WORKSPACE/evidence/network-hub.json"
```

Repeat only for the selected root/target. Standalone roots use their documented init, saved-plan, show and apply cycle with their explicit backend. Handoffs require wrapped `terraform output -json`, not `terraform output -json output_name` or raw state.

### Networks, private worker and workload vault

Apply both spokes; enable and reapply all peering sides, requiring four Connected directions. Apply firewall with [platform egress rules](https://github.com/MikeeeGit/azure-firewall/tree/main/examples/aks-platform). Prepare routes with associations disabled; set spoke DNS to the actual firewall private IP and verify private resolution before enabling associations.

Keep Application Gateway routing separate from AKS forced tunnelling and leave AKS CSV routes empty when the route add-on owns them. The [private-worker example](../../examples/azure/three-tier/private-worker/README.md) provides a small Linux VM on an existing subnet and explicit Blob private endpoints for state access. Private access is the default; the optional operator SSH path requires a single reviewed IPv4 address and a public key. The VM does not contain CI registration tokens or grant itself deployment authority.

Give the worker a separate explicit state key and record its ownership, management path, DNS, outbound routing and removal. Same-region Azure Storage access cannot rely on the worker public IP allowlist; use the declared Blob private endpoints and hub DNS zone. Install reviewed tools and a repository-scoped CI runner separately. Keep one-time operator login separate from the runner account, use short-lived registration tokens, and remove registrations and local credentials during teardown.

Apply the [private workload-vault root](../../examples/azure/three-tier/workload-vault/README.md) against the applied endpoint subnet and hub DNS zone. Declare the seed operator's Secrets Officer grant in code. Keep purge protection and choose retention before creation. When Application Gateway retrieves its frontend certificate from this vault, review the explicit `allow_trusted_azure_services` option. Its default is false; enabling it permits the Microsoft trusted-services list while keeping public network access disabled and RBAC required. Verify certificate retrieval in the real gateway; successful private DNS and an assigned role alone do not prove access.

Create the trial certificates using the [lab certificate helper](../../examples/azure/three-tier/lab-certificates/README.md). It generates and verifies a seven-day CA, separate backend PEM and frontend PFX outside Git. Its guide also creates the qualification file, imports the frontend certificate and identifies the exact operator permissions. The optional `certificate_seed_operator_object_ids` vault input grants certificate import rights explicitly. Only the public CA belongs in app/gateway trust inputs.

Seed from that authorised private path, using existing local files and suppressing values:

```bash
set -euo pipefail
set +x
test -n "$VAULT_NAME"
test -f "$QUALIFICATION_SECRET_FILE"
test -f "$BACKEND_CERTIFICATE_PEM_FILE"
az keyvault secret set --vault-name "$VAULT_NAME" \
  --name platform-demo-qualification --file "$QUALIFICATION_SECRET_FILE" \
  --encoding utf-8 --only-show-errors --output none
az keyvault secret set --vault-name "$VAULT_NAME" \
  --name platform-demo-ingress --file "$BACKEND_CERTIFICATE_PEM_FILE" \
  --encoding utf-8 --content-type application/x-pem-file --only-show-errors --output none
```

These commands import material; they do not issue certificates. Use a nonempty qualification value and a backend PEM covering the actual web/API names with its complete certificate chain. For a disposable trial, a private test CA can issue names under `example.test`: configure the gateway’s explicit [private CA trust](https://github.com/MikeeeGit/azure-application-gateway/tree/main/examples/private-ca) and give diagnostic clients that public CA. Keep private keys out of Terraform inputs, state and Git. Frontend WAF certificate import remains a separate [sandbox prerequisite](sandbox-deployment.md). Arrange certificates and private workers before creating clusters.

### Apply AKS and generate the handoffs

Merge trial sizing, native authorization and TLS workload identity into the complete private AKS target. Preserve both clusters, separate subnets/CIDRs and unrelated map entries. Use applied ACR, DNS and route IDs. UDR requires the earlier real egress gate.

Before exporting identity outputs, initialise the identities root against its explicit **pprd** operator-container key and verify the selected backend. A checkout last used for hub or prd still points at that backend until deliberately reinitialised. Likewise, export hub registry outputs from the hub network state and AKS outputs from the pprd AKS state. Pipeline execution does not initialise your separate local checkout.

```bash
cd "$WORKSPACE"
terraform -chdir=aks-lab-delivery-identities output -json > evidence/identities.json
python3 terraform-delivery-templates/scripts/azure/three_tier_handoff.py ci \
  --identities evidence/identities.json \
  --tenant-id "$TENANT_ID" --environment pprd --region uks \
  --platform-key platform --application-key application \
  --namespace platform-demo --slots aks01 aks02 \
  --output evidence/aks-delivery-principals.tfvars.json
```

Merge generated `delivery_principals` into `aks-lab-aks/config/uks/pprd/pprd.tfvars`. Helpers read only global/selected target tfvars, not extra generated files. Choose `kubernetes_authorization_mode = "kubernetes_rbac"` and reviewed existing Entra administrator groups. Terraform creates CI Cluster User access, both workload OIDC federations and exact vault rights.

Apply AKS; verify private user API, node and add-on readiness on both slots. In the local AKS checkout select `tf_setup aks-lab-aks pprd uks`, run `tf_env` and `tf_init`, and verify its backend before exporting. From the workspace, export `terraform -chdir=aks-lab-aks output -json > evidence/aks.json`, then:

```bash
python3 terraform-delivery-templates/scripts/azure/three_tier_handoff.py application \
  --template aks-lab-application/delivery.azure-workload.apps.json \
  --platform-template aks-lab-platform-services/platform.services.json \
  --aks-outputs evidence/aks.json --registry-outputs evidence/network-hub.json \
  --delivery-config aks-lab-aks/delivery.azure.json \
  --environment pprd --region uks \
  --workload-identity platform-demo --service-account-key app \
  --vault-id "$APPLICATION_VAULT_ID" \
  --certificate-name platform-demo-ingress --secret-name platform-demo-qualification \
  --output-directory evidence/generated-pprd
```

Review and overlay generated application/platform files onto complete consumers. Set real hosts, Envoy IPs/subnets and permitted source ranges separately; the identity generator does not invent network settings. Commit the result. Replacing a cluster requires fresh applied outputs and issuer checks.

## Tier 2: bootstrap access and install platform services

Install pinned Python/client dependencies using [getting started](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/getting-started.md).

Run [identity discovery](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/native-azure-authorization.md) as the actual platform and application CI identities on both slots: four observations for two shared environment identities. Match tenant/client/cluster to Terraform and retain the API-returned usernames.

An existing Entra operator performs [first platform CI bootstrap](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/platform-ci-bootstrap.md). Copy `examples/platform.access.json`, select the dedicated platform key, and combine original platform discovery records into a JSON array. From the private app consumer:

```bash
.venv/bin/python ../aks-delivery-templates/scripts/bootstrap.py platform-access \
  --source . --config delivery.azure-workload.apps.json \
  --platform-access-config platform.access.json \
  --aks-outputs ../evidence/aks.json \
  --identity-records ../evidence/platform-identities.json \
  --environment pprd --region uks --slot aks01 --allow-platform-admin
```

Repeat for aks02 after reviewing the first result. This explicit binding gives the platform identity broad Kubernetes administration for CRDs/controllers/RBAC; application/build purposes cannot be selected. Initial operator authority remains a prerequisite.

Deploy platform services next: copy shared `examples/github-platform.yml` or `examples/azure-platform.yml` into the platform consumer, aligning every reference to the reviewed shared commit. Deploy both slots sequentially through the actual platform CI identity. It prepares/reviews the receipt, installs CRDs/controllers and creates platform-owned ServiceAccounts, Gateways and proxies. [Platform services](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/platform-services.md) documents exact local prepare/apply commands for diagnosis.

Populate `bootstrap.native.apps.json` from application discovery and the actual Pod Security minor, then commit it. Run the protected application-bootstrap caller for both slots using its dedicated bootstrap identity. This was the Azure trial's pipeline route. The authorised operator can perform the equivalent operation locally:

```bash
SOURCE_COMMIT=$(git rev-parse HEAD)
.venv/bin/python ../aks-delivery-templates/scripts/bootstrap.py apply \
  --source . --config delivery.azure-workload.apps.json \
  --bootstrap-config bootstrap.native.apps.json --commit "$SOURCE_COMMIT" \
  --environment pprd --region uks --slot aks01
```

Repeat for aks02. Verify app HTTPRoute/CSI dry-run succeeds while RoleBinding, Gateway mutation and cluster writes are forbidden. Record those negative checks separately; the dated trial's successful deployment does not stand in for every authorization case.

**Gate:** actual platform CI operations pass on both slots, CRDs are Established and controllers ready. Observe intended private IP allocation. Initial TLS readiness may await the CSI mounting app, but controller failures/Pending Pods must be resolved. Operator success alone does not qualify federated CI.

## Tier 3: release and qualify the app

Use the full [Azure workload callers](https://github.com/MikeeeGit/aks-platform-demo/blob/main/docs/AZURE-WORKLOAD.md). Copy the GitHub build/deploy caller to `.github/workflows/build-deploy.yml` and matching promotion caller to `.github/workflows/promote.yml`, or create Azure pipelines for their equivalent YAML. Select `delivery.azure-workload.apps.json`, actual build/deploy identities and private workers; update all shared references together.

Run release **A** on `["aks01","aks02"]` sequentially. Retain producer run, source commit, immutable digest, security receipt and both deployment/Azure qualification reports. Each slot must return A and its own slot value. The qualifier checks actual Pod/CSI identity, object version, mounted-secret readiness and revision without exporting secret values. Do not use platform privileges for app qualification.

For Argo, retain the same Azure workload profile and use the [build-only/Git promotion route](https://github.com/MikeeeGit/aks-platform-demo/blob/main/docs/AZURE-WORKLOAD.md#argo-cd-uses-the-same-azure-profile), followed by the same qualifier after exact-revision sync. Argo reconciles rendered YAML produced from Kustomize. Choose one writer per namespace.

## WAF, traffic switchover and rollback

Test routed HTTPS through both actual private Envoy IPs. Default source ranges admit the WAF subnet, not an arbitrary worker; use a reviewed narrow diagnostic source if needed. Port-forward tests bypass the Azure load balancer.

```bash
curl --fail --show-error --cacert "$PUBLIC_CA_FILE" --resolve "$WEB_HOST:443:$SLOT_PRIVATE_IP" "https://$WEB_HOST/version"
curl --fail --show-error --cacert "$PUBLIC_CA_FILE" --resolve "$API_HOST:443:$SLOT_PRIVATE_IP" "https://$API_HOST/api/version"
```

Retain TLS verification; check slot/revision, rejected hosts and actual Cilium policy. Merge the [HTTPS-first gateway profile](https://github.com/MikeeeGit/azure-application-gateway/tree/main/examples/https-first) into the private gateway target. Stable `backend_dns_records.service.ip_addresses` points to verified aks01; preview points to aks02. Apply only after both backends and frontend certificate access are ready.

```bash
az network application-gateway show-backend-health \
  --resource-group "$GATEWAY_RESOURCE_GROUP" --name "$GATEWAY_NAME"
```

Test actual frontend TLS/web/API/preview/redirect/WAF behavior, not only probes.

| Step | App operation | Terraform traffic operation | Acceptance |
| --- | --- | --- | --- |
| Baseline | A on both slots | Stable alias → aks01 | Both qualify; stable A/aks01 |
| Candidate | Build B; deploy aks02 only | None | Preview B; stable remains A |
| Switchover | Keep both running | Fresh saved plan: alias → aks02 | Stable requests converge to B/aks02 |
| Traffic rollback | Preserve A on aks01 | Fresh plan: alias → aks01 | Stable A/aks01 restored |
| Additional app rollback | Promote original successful A receipt to aks02 without rebuild | None | Original digest and Azure qualification pass; this additional operation was not exercised in the dated Azure trial |
| Optional repeat | Re-promote/requalify B on aks02 | Separately approve alias → aks02 | Full evidence retained |

For GitHub promotion, choose A's successful producer run and `build-workflow=build-deploy.yml` when that was its producer; `image-build.yml` is different. Azure promotion likewise needs the actual producer definition/run. Under Argo, reverse reviewed desired state and sync only the selected slot.

Use the app repository’s [Azure traffic qualifier](https://github.com/MikeeeGit/aks-platform-demo/blob/main/docs/AZURE-WORKLOAD.md#qualify-the-stable-azure-gateway-through-cutover-and-rollback) at each row. Retain separate reports against the same gateway resource, frontend IP and hostnames; it checks actual frontend ownership, selected backend health and CA-verified responses for the expected slot/revision. The CSI and traffic reports establish different parts of the path.

The WAF endpoint/listeners/backend FQDN remain stable. DNS caches, probes and connections make convergence noninstantaneous. Keep the former healthy slot through the rollback window. Never apply a stale plan after editing inputs. See [cutover semantics](https://github.com/MikeeeGit/azure-application-gateway/blob/main/docs/cutover.md). This stateless exercise does not qualify database rollback or regional recovery.

## Evidence and failure recovery

Retain exact source/template/tool/chart/image versions, state keys, Azure IDs, times and actual run links privately.

| Gate | Evidence | Initial status |
| --- | --- | --- |
| Scope/backend | Approved target/budget, inventory, migrated state, fresh plan | Not run |
| CI trust | Actual plan/apply/build/platform/app federated logins | Not run |
| Infrastructure | Applied plans, private APIs/nodes/ACR, DNS/UDR checks | Not run |
| Permissions | MI/FIC/grant outputs, observed usernames, allowed/denied API operations | Not run |
| Platform | Both CI receipts, CRD/controller readiness, real ILBs | Not run |
| Application A | Producer/security receipt and both source/digest/CSI reports | Not run |
| WAF | Backend health, TLS and real stable/preview responses | Not run |
| Candidate/cutover | Inactive B, unchanged active A, stable B after apply | Not run |
| Rollback | Traffic restored A and app receipt rollback requalified | Not run |
| Optional rotation | New test-secret version on all mounting Pods, both slots | Not run |
| Removal | Ordered destroy and remaining/retained inventory | Not run |

Use passed, failed, not run or intentionally retained, with evidence and timestamps. A kind pass cannot replace an Azure row.

For partial Terraform failure, keep state, inspect actual resources and generate a fresh plan in the same root/key. For federation failures, correct exact trust and repeat discovery as the intended identity. For private timeouts, fix DNS/routes/worker access while retaining TLS/private API controls. For Pending Pods or Helm failure, inspect scheduling/release state and prepare a fresh receipt after correction. For CSI failure, inspect issuer/subject/client, vault grant/object and private network path. Keep stable traffic on the healthy slot while correcting a candidate.

If removal is interrupted, preserve state, authority and networking and resume [ordered removal](three-tier-removal.md) at the last verified gate. The Azure rehearsal is complete only when the selected delivery method, both clusters, real managed services, traffic rehearsal and removal have retained successful evidence.
