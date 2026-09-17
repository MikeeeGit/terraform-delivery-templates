# Worked platform: networks, firewall, dual AKS and one application release

This scenario connects infrastructure and application delivery into a single operating sequence. Use private consumer repositories for real configuration and authenticated delivery. Public repositories contain synthetic values and credential-free validation.

## Repository and state ownership

| Repository/example | Owns | Consumes |
|---|---|---|
| azure-network-foundation/examples/hub-spoke | Hub/two spokes, subnets, NSGs, peering, hub DNS, spoke links and shared example ACR | Backend bootstrap, subscription aliases |
| azure-firewall | VNet firewall, public IP, inherited base/child policies, rule collections and diagnostics | Existing hub resource group and AzureFirewallSubnet |
| Network examples/hub-spoke/egress | Four AKS route tables and optional associations | Applied firewall ID, both spoke network outputs |
| azure-aks-foundation | Independent aks01/aks02 clusters, pools, control-plane/kubelet/workload identities and roles | Network, regional DNS, route tables and ACR |
| azure-application-gateway | WAF gateway, listeners/probes/routing, TLS access and optional private backend aliases | Dedicated subnet, actual backend Services and existing Key Vault certificate |
| terraform-delivery-templates | Infrastructure bootstrap, Terraform saved-plan delivery and local helpers | Reviewed private infrastructure inputs |
| aks-delivery-templates | Image build, immutable release receipts, Kustomize render/apply and rollout checks | Private app configuration, protected identity/environment controls |
| aks-platform-demo | New sample app, Dockerfile and per-slot Kustomize overlays | Shared application templates and applied infrastructure |

The [network pack](https://github.com/MikeeeGit/azure-network-foundation/tree/v0.3.0/examples/hub-spoke) uses hub10.80/16, pprd10.81/16 and prd10.82/16. Two AKS slots live in one selected spoke; these are independent upgrade/deployment slots, not automatic regional disaster recovery.

~~~mermaid
flowchart TD
  Boot[Private state and OIDC bootstrap] --> Network[Hub, spokes, DNS and ACR]
  Network --> FW[Azure Firewall and inherited policy]
  FW --> DNS[Spoke DNS and AKS route attachment]
  DNS --> AKS[Independent aks01 and aks02]
  Source[Reviewed application commit] --> Build[Build once and push to ACR]
  Build --> Receipt[Immutable image digest and source commit]
  AKS --> Render[Kustomize selected slot]
  Receipt --> Render
  Render --> Deploy[Private API apply and rollout checks]
  Deploy --> ILB[Private Service for each cluster]
  ILB --> Gateway[Application Gateway WAF and TLS]
  Gateway --> Verify[Application check, reviewed cutover and rollback]
~~~

## What was reused

The inspected aks-common-templates source uses Kustomize for applications, with environment, location and cluster-suffix parameters. Its separate platform-service template uses Helm. The public application path retains the Kustomize targeting/configuration/CSI/deploy/rollout pattern. It adds digest promotion, explicit target records, user rather than admin kubecredentials, fatal deployment failures, separate workload identities and GitHub support.

The updated September archive includes the application's AKS branch. Its container pipeline builds once, selects an existing release for later promotion, loops over chosen cluster slots and calls shared ConfigMap, CSI and Kustomize templates, with ordered environments and application checks. Separate optional database delivery is application-specific; this stateless sample has no database. Earlier snapshots contained the IIS branch instead, so they were not sufficient evidence for the AKS flow. The public sample is newly authored Node application code; no proprietary business logic, variable groups, machine paths or deployment credentials are copied.

The archived community ingress-nginx platform installer is not carried into this baseline: that project retired in March2026. The sample instead uses one internal LoadBalancer Service per cluster directly behind Application Gateway. For a multi-application ingress platform, choose a maintained controller separately. [Kubernetes retirement statement](https://kubernetes.io/blog/2026/01/29/ingress-nginx-statement/).

## 1. Bootstrap and create the network path

Follow the [first-time guide](../getting-started.md) and [Azure bootstrap guide](bootstrap.md). Create private backend storage and scoped identities, migrate bootstrap state and configure OIDC. Each component/target needs a distinct state key; real backend coordinates belong in the private consumer.

Copy the full network configuration into a new private network consumer. Replace tenant/subscription IDs, state coordinates and the globally unique exampleplatformacr registry name. The hub pack enables a Standard ACR with its admin account disabled. It uses authenticated public registry endpoints; a private-link registry design requires Premium, endpoint/DNS configuration and a build runner with the appropriate path.

Apply hub first, then the spokes, with peerings disabled. Enable peerings and reapply all three states; verify every direction is Connected. Shared DNS zones exist before spoke links. The demo is UK South; UK West remains a separately planned recovery deployment.

Use the [private component pipeline callers](../../examples/azure/component/README.md) for firewall, routes, AKS and gateway roots, retaining separate states and readiness gates. Apply the standalone [firewall](https://github.com/MikeeeGit/azure-firewall) using actual hub outputs. It owns the complete policy. Add actual ACR login/data/authentication endpoints needed for image pulls to its reviewed egress policy; do not assume the AKS platform FQDN tag covers every private application dependency.

Update both spoke VNet DNS server lists to the firewall's private IP. The DNS proxy needs hub links to every required private zone. Prepare the [route-only add-on](https://github.com/MikeeeGit/azure-network-foundation/tree/v0.3.0/examples/hub-spoke/egress) with enable_aks_routes=false, then explicitly attach routes after reviewing peering/DNS/NSGs/policy. Verify actual DNS and outbound paths from private test hosts before acknowledging UDR readiness in AKS. Application Gateway receives no AKS route table.

## 2. Create independent clusters and application permissions

Use the AKS repository's full pprd/prd target and actual network, DNS, route-table and ACR outputs. Each cluster gets its own version/pools/CIDRs and identity grants. Shared custom private DNS in another subscription requires Microsoft.ContainerService registration in both subscriptions. Check supported Kubernetes patches, encryption-at-host prerequisites, VM quota and zone support.

Configure classic ACR kubelet access with AcrPull; for an ABAC registry choose the documented repository-reader role instead. Build and deployment identities are separate from kubelet and application workload identities.

Run the shared AKS bootstrap pipeline once per selected cluster, using its separate privileged identity and bootstrap approval environment. Its reviewed bootstrap.apps.json pins the namespace policy version and lists deployment principal object IDs. The pipeline checks private AKS, Entra/Azure RBAC, OIDC/workload identity and requested CSI readiness, creates the restricted application namespace and grants scoped deployment roles. Local operator commands remain an alternative. Do not use administrator kubecredentials: local accounts are disabled. The sample namespace is platform-demo; application-specific ServiceAccount/SecretProviderClass resources remain reviewed namespaced configuration.

For each CI deployment principal and selected cluster, the minimal baseline is:

- Azure Kubernetes Service Cluster User Role on the cluster for user kubeconfig retrieval.
- Azure Kubernetes Service RBAC Writer on the cluster's /namespaces/platform-demo scope for namespaced application resources.
- No cluster administrator grant to ordinary application deployment.

Example commands, after selecting the intended tenant/subscription and replacing reviewed IDs:

~~~sh
az role assignment create --assignee-object-id "$DEPLOY_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal --role "Azure Kubernetes Service Cluster User Role" --scope "$AKS_ID"
az role assignment create --assignee-object-id "$DEPLOY_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal --role "Azure Kubernetes Service RBAC Writer" --scope "$AKS_ID/namespaces/platform-demo"
~~~

Namespace creation uses the separate bootstrap pipeline; other cluster-scoped extensions remain platform tasks. Namespace Writer can access sensitive namespaced resources and run application pods, so treat it as a deployment privilege. Registry build access normally uses AcrPush at the reviewed registry; use the corresponding repository-writer permission if ABAC is enabled. [Microsoft AKS RBAC scope guidance](https://learn.microsoft.com/en-us/azure/aks/manage-azure-rbac).

Both CI systems require trusted private runners that resolve/reach private AKS APIs. A hosted render job can validate manifests without cloud access; the apply job needs the private network. Set required reviewers, branch restrictions and environment concurrency controls outside YAML. Keep public validation jobs on hosted, credential-free workers.

## 3. Export actual targets into the application consumer

Clone the public demo into a private consumer. Its delivery.apps.json selects exact environment/region/slot records, each with its own workload subscription. Registry subscription is separate. AKS output names are authoritative; the app templates never infer cluster names from company naming rules.

From the respective initialized private Terraform roots, export metadata:

~~~sh
terraform output -json > /tmp/aks-outputs.json
# Run in the hub network root:
terraform output -json > /tmp/hub-outputs.json
~~~

Then create a new review file in the private app checkout:

~~~sh
python3 ../terraform-delivery-templates/scripts/azure/platform_handoff.py \
  --template delivery.apps.json \
  --aks-outputs /tmp/aks-outputs.json \
  --registry-outputs /tmp/hub-outputs.json \
  --delivery-config ../azure-aks-foundation/delivery.azure.json \
  --environment pprd --region uks \
  --output delivery.apps.private.json
~~~

The helper checks the applied AKS context against the delivery target, extracts only selected non-sensitive fields, verifies resource ID/name/subscription agreement and refuses to overwrite an existing file. It updates both cluster targets and the registry from actual outputs, preserving app-owned namespace/deployment/overlay settings. It exports only the selected environment/region; use separate reviewed configurations for other environments. It does not create resources, write secrets or grant permissions.

Review the generated file, run the application delivery validator, and make it the private consumer's reviewed configuration. Do not copy real estate configuration back into the public sample. Adjust the Kustomize slot overlays to the actual reserved Service addresses and network policy.

## 4. Build once and deploy selected slots

Use the [shared application templates](https://github.com/MikeeeGit/aks-delivery-templates) from the [sample private pipeline callers](https://github.com/MikeeeGit/aks-platform-demo). Pin the reusable template release to its immutable commit in the private consumer.

Run app tests, build the protected branch commit and push one container image to the configured ACR. Retain the source commit and repository@sha256 digest in the build receipt. The normal promotion caller selects a successful build run from the configured trusted producer, retrieves its receipt and verifies its repository, protected branch, source and run binding. Deploy that same digest to aks01, aks02 or both, sequentially by default; never rebuild an image merely to promote it to another slot. Azure DevOps also has a current-build-to-deploy caller, retaining the same receipt contract.

Rendering reads the committed source/configuration, selects the exact target, substitutes the digest in an isolated Kustomize snapshot and produces a reviewable manifest/receipt bundle. Apply verifies the approved bundle, gets isolated user kubecredentials, checks namespace access, performs server-side validation and waits for rollout. The sample then verifies readiness and the exact requested revision/slot through its selected cluster Service. These checks fail the deployment if the observed release differs. Gateway traffic verification remains a separate end-to-end check.

The sample's internal Services use10.81.0.20 and10.81.4.20, port80 to app8080, with modern Azure internal-load-balancer/IP annotations. These addresses become resources only when the Services are successfully applied. They match the gateway example's private backend/probe configuration. No ingress controller or public Kubernetes LoadBalancer is required for this one application. [Microsoft internal Service guidance](https://learn.microsoft.com/en-us/azure/aks/internal-lb).

## 5. Add the gateway and prove traffic/cutover

Provision a real Key Vault TLS certificate covering the chosen client hostnames, then apply the gateway using its complete example and actual backend addresses. Its owned child private alias zone must link to the hub if the firewall DNS proxy resolves it. Use distinct alias-zone names for different environments linked to the same hub.

Check gateway backend health, TLS, each intended Host/path, redirects and WAF behavior. The sample exposes health/readiness and release/slot metadata for verification. Test inactive and active cluster endpoints from the private network before changing traffic.

Upgrade/deploy the inactive cluster first. Verify the same intended release digest and the correct slot response, then make a separately reviewed gateway backend/DNS target change using Terraform saved-plan delivery. App deployment never changes the active gateway target implicitly. Wait for DNS/probe/connection convergence; optional connection draining does not guarantee instantaneous or zero-downtime DNS cutover.

For application rollback, redeploy the previously approved source/digest bundle. For traffic rollback, restore the previously healthy backend target. Keep the old cluster and compatible data/services available until rollout criteria are met. Persistent data, schemas and secrets require their own compatibility and recovery plan.

## Verification boundaries

Public CI and local tests cover configuration, mock providers, rendering, application behavior and release/target safety contracts. The sample CI additionally includes a credential-free two-kind-cluster acceptance job using real image digests, selected-slot updates and rollback. Its result artifact distinguishes success/failure; a configured job is not a passed run. This Kubernetes test uses a local registry mirror inside temporary test nodes and cannot establish Azure networking or identity readiness. Live acceptance additionally needs image push/pull, private API access, DNS/routes, namespace permissions, certificate retrieval, gateway backend health and end-to-end cutover/rollback in a chosen sandbox.

Firewall, gateway, registry and cluster nodes incur charges while deployed. The public examples do not configure VPN/ExpressRoute, issue certificates or replicate application data. Remove application/gateway dependencies and clusters before routes/firewall/network teardown; retain state throughout.

The platform is ready for reviewed sandbox deployment only after real identities, target values, runner networking and environment approvals have been configured. No live cloud resources are created by public validation.
