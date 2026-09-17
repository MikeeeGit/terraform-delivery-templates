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
| aks-delivery-templates | Separate namespace/RBAC bootstrap, versioned Helm platform services, scanned image receipts, Kustomize app delivery and selected-slot HTTPS checks | Private platform/app configuration, protected identities and environments |
| aks-platform-demo | New sample app, Dockerfile and per-slot Kustomize overlays | Shared application templates and applied infrastructure |

The [network pack](https://github.com/MikeeeGit/azure-network-foundation/tree/v0.3.0/examples/hub-spoke) uses hub10.80/16, pprd10.81/16 and prd10.82/16. Two AKS slots live in one selected spoke; these are independent upgrade/deployment slots, not automatic regional disaster recovery.

~~~mermaid
flowchart TD
  Boot[Private state and OIDC bootstrap] --> Network[Hub, spokes, DNS and ACR]
  Network --> FW[Azure Firewall and inherited policy]
  FW --> DNS[Spoke DNS and AKS route attachment]
  DNS --> AKS[Independent aks01 and aks02]
  AKS --> Platform[Namespace/RBAC, Gateway API CRDs and Envoy Helm release]
  Source[Reviewed application commit] --> Build[Build once, push and scan immutable image]
  Build --> Receipt[Passed scan, image digest and source commit]
  Platform --> Render[Kustomize selected slot]
  Receipt --> Render
  Render --> Deploy[Private API apply and rollout checks]
  Deploy --> ILB[HTTPRoute and private Envoy HTTPS endpoint per cluster]
  ILB --> Gateway[Application Gateway WAF and TLS re-encryption]
  Gateway --> Verify[Application check, reviewed cutover and rollback]
~~~

## What was reused

The inspected aks-common-templates source uses Kustomize for applications, with environment, location and cluster-suffix parameters. Its separate platform-service template uses Helm. The public application path retains the Kustomize targeting/configuration/CSI/deploy/rollout pattern. It adds digest promotion, explicit target records, user rather than admin kubecredentials, fatal deployment failures, separate workload identities and GitHub support.

The updated September archive includes the application's AKS branch. Its container pipeline builds once, selects an existing release for later promotion, loops over chosen cluster slots and calls shared ConfigMap, CSI and Kustomize templates, with ordered environments and application checks. Separate optional database delivery is application-specific; this stateless sample has no database. Earlier snapshots contained the IIS branch instead, so they were not sufficient evidence for the AKS flow. The public sample is newly authored Node application code; no proprietary business logic, variable groups, machine paths or deployment credentials are copied.

The maintained platform profile replaces community ingress-nginx with Gateway API and Envoy Gateway, retaining the independently versioned Helm setup layer. Application Gateway WAF fronts a private HTTPS listener in each cluster; HTTPRoute connects it to the sample ClusterIP Service. A smaller direct-ILB sample remains available for learning, and original NGINX configuration is labelled as a retired compatibility reference. See the [three-tier explanation](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/three-tier-deployment-system.md) and [ingress migration guide](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/ingress-migration.md).

## 1. Bootstrap and create the network path

Follow the [first-time guide](../getting-started.md) and [Azure bootstrap guide](bootstrap.md). Create private backend storage and scoped identities, migrate bootstrap state and configure OIDC. Each component/target needs a distinct state key; real backend coordinates belong in the private consumer.

Copy the full network configuration into a new private network consumer. Replace tenant/subscription IDs, state coordinates and the globally unique exampleplatformacr registry name. The hub pack enables a Standard ACR with its admin account disabled. It uses authenticated public registry endpoints; a private-link registry design requires Premium, endpoint/DNS configuration and a build runner with the appropriate path.

Apply hub first, then the spokes, with peerings disabled. Enable peerings and reapply all three states; verify every direction is Connected. Shared DNS zones exist before spoke links. The demo is UK South; UK West remains a separately planned recovery deployment.

Use the [private component pipeline callers](../../examples/azure/component/README.md) for firewall, routes, AKS and gateway roots, retaining separate states and readiness gates. Apply the standalone [firewall](https://github.com/MikeeeGit/azure-firewall) using actual hub outputs. It owns the complete policy. Add actual ACR login/data/authentication endpoints needed for image pulls to its reviewed egress policy; do not assume the AKS platform FQDN tag covers every private application dependency.

Update both spoke VNet DNS server lists to the firewall's private IP. The DNS proxy needs hub links to every required private zone. Prepare the [route-only add-on](https://github.com/MikeeeGit/azure-network-foundation/tree/v0.3.0/examples/hub-spoke/egress) with enable_aks_routes=false, then explicitly attach routes after reviewing peering/DNS/NSGs/policy. Verify actual DNS and outbound paths from private test hosts before acknowledging UDR readiness in AKS. Application Gateway receives no AKS route table.

## 2. Create independent clusters and application permissions

Use the AKS repository's full pprd/prd target and actual network, DNS, route-table and ACR outputs. Each cluster gets its own version/pools/CIDRs and identity grants. Shared custom private DNS in another subscription requires Microsoft.ContainerService registration in both subscriptions. Check supported Kubernetes patches, encryption-at-host prerequisites, VM quota and zone support.

Configure classic ACR kubelet access with AcrPull; for an ABAC registry choose the documented repository-reader role instead. Build and deployment identities are separate from kubelet and application workload identities.

Run the shared AKS bootstrap pipeline once per selected cluster, using its separate privileged identity and bootstrap approval environment. Its reviewed bootstrap.gateway.apps.json pins the namespace policy version and lists deployment principal object IDs. The pipeline checks private AKS, Entra/Azure RBAC, OIDC/workload identity and requested CSI readiness, creates the restricted application namespace and grants scoped deployment roles. Local operator commands remain an alternative. Do not use administrator kubecredentials: local accounts are disabled. The sample namespace is platform-demo; application-specific ServiceAccount/SecretProviderClass resources remain reviewed namespaced configuration.

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

Clone the public demo into a private consumer. Its delivery.gateway.apps.json selects exact environment/region/slot records, each with its own workload subscription. Registry subscription is separate. AKS output names are authoritative; the app templates never infer cluster names from company naming rules.

From the respective initialized private Terraform roots, export metadata:

~~~sh
terraform output -json > /tmp/aks-outputs.json
# Run in the hub network root:
terraform output -json > /tmp/hub-outputs.json
~~~

Then create a new review file in the private app checkout:

~~~sh
python3 ../terraform-delivery-templates/scripts/azure/platform_handoff.py \
  --template delivery.gateway.apps.json \
  --aks-outputs /tmp/aks-outputs.json \
  --registry-outputs /tmp/hub-outputs.json \
  --delivery-config ../azure-aks-foundation/delivery.azure.json \
  --environment pprd --region uks \
  --output delivery.apps.private.json
~~~

The helper checks the applied AKS context against the delivery target, extracts only selected non-sensitive fields, verifies resource ID/name/subscription agreement and refuses to overwrite an existing file. It updates both cluster targets and the registry from actual outputs, preserving app-owned namespace/deployment/overlay settings. It exports only the selected environment/region; use separate reviewed configurations for other environments. It does not create resources, write secrets or grant permissions.

Review the generated file, run the application delivery validator, and make it the private consumer's reviewed configuration. Do not copy real estate configuration back into the public sample. Review the [workload identity handoff](workload-identity-handoff.md) to bind the selected ServiceAccount to the applied UAMI and both OIDC issuers. Adjust the platform slot configuration to actual reserved ingress addresses and the app overlay to the intended TLS/route and NetworkPolicy contracts.

## 4. Install versioned cluster platform services

Use the shared framework's maintained Envoy platform profile in a separate private platform consumer. Give its pipeline a separately approved platform identity/environment: CRDs, GatewayClass, controller RBAC and Helm release objects require permissions beyond an ordinary app deployment.

The reviewed platform bundle pins CRD bytes, chart package, values and common manifests. Its sequence establishes namespaces without removing existing policy labels, applies explicitly owned CRDs and waits for establishment, installs the Helm controller, then applies per-slot Envoy/Gateway configuration and collects diagnostics. Keep CRD upgrades deliberate; Helm rollback alone cannot undo a schema change.

Reserve candidate ingress addresses distinct from any existing direct or legacy endpoints. The worked PPRD profile uses 10.81.0.21 for aks01 and 10.81.4.21 for aks02, leaving the older .20 endpoints available during migration. Configure only private load balancers and reviewed source ranges. Apply the reviewed [platform egress layer](https://github.com/MikeeeGit/azure-firewall/blob/main/examples/aks-platform/README.md) for controller image pulls and the exact CSI vault, or use verified private mirrors and a separately configured private vault path.

The application namespace contains the platform-owned HTTPS Gateway and app-owned HTTPRoute/Service. Establish and test the app principal's custom-resource permissions. The [authorization example](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/examples/authorization/README.md) makes the opt-in Azure CRD ABAC preview and namespace-wide Writer trust boundary explicit; it is not a silently enabled production default. GatewayNamespace mode puts proxy resources inside the app namespace, where Writer has broad built-in-resource privileges. Key Vault CSI synchronization needs the declared workload identity and a live mounting pod; it may complete only after the app is deployed. See the [operator sequence](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/operators-walkthrough.md).

## 5. Build once and deploy selected slots

Use the [shared application templates](https://github.com/MikeeeGit/aks-delivery-templates) from the [sample private pipeline callers](https://github.com/MikeeeGit/aks-platform-demo). Pin the reusable template release to its immutable commit in the private consumer.

Run app tests, build the protected branch commit and push one container image to the configured ACR. Scan that exact immutable digest with the pinned Trivy scanner and fail on HIGH/CRITICAL findings or scanner errors. Only a passed scan produces a promotable receipt containing the source commit and repository@sha256 digest; keep the separate scan report as a private artifact. The normal promotion caller selects a successful build run from the configured trusted producer, retrieves its receipt and verifies its repository, protected branch, source and run binding. Deploy that same digest to aks01, aks02 or both, sequentially by default; never rebuild an image merely to promote it to another slot. Azure DevOps also has a current-build-to-deploy caller, retaining the same receipt contract.

Rendering reads the committed source/configuration, selects the exact target, substitutes the digest in an isolated Kustomize snapshot and produces a reviewable manifest/receipt bundle. Apply verifies the approved bundle, gets isolated user kubecredentials, checks namespace access, performs server-side validation and waits for rollout. The maintained sample checks readiness and the exact requested revision/slot, current Gateway/HTTPRoute status and HTTPS traffic through the selected Envoy listener with hostname/certificate validation. These checks fail the deployment if the route, TLS or observed release differs. The outer Azure WAF path still requires a separate end-to-end check.

In the maintained profile, Envoy owns the private .21 load balancer and terminates HTTPS443; the app Service is ClusterIP80 to app8080. NetworkPolicy admits the selected Envoy proxy pods. Verify the assigned addresses against the reviewed slot configuration before configuring the gateway backend. The older direct-ILB example owns .20 and remains a distinct profile; never assign the same IP to both Services. [Microsoft internal Service guidance](https://learn.microsoft.com/en-us/azure/aks/internal-lb).

## 6. Add the gateway and prove traffic/cutover

Provision a real Key Vault TLS certificate covering the chosen client hostnames, then apply the gateway using its complete example and actual backend addresses. Its owned child private alias zone must link to the hub if the firewall DNS proxy resolves it. Use distinct alias-zone names for different environments linked to the same hub.

For a migration from the direct HTTP sample, first apply the [candidate-only HTTPS profile](https://github.com/MikeeeGit/azure-application-gateway/blob/main/examples/ingress-tls/README.md): preview uses aks02 .21 over HTTPS443 while the active .20/HTTP80 route stays intact. The later cutover profile explicitly changes the active alias and backend protocol together. Merely changing HTTP80 to HTTPS443 on an existing active HTTP endpoint would break it.

Check gateway backend health, TLS, each intended Host/path, redirects and WAF behavior. The sample exposes health/readiness and release/slot metadata for verification. Test inactive and active cluster endpoints from the private network before changing traffic.

Upgrade/deploy the inactive cluster first. Verify the same intended release digest and the correct slot response, then make a separately reviewed gateway backend/DNS target change using Terraform saved-plan delivery. App deployment never changes the active gateway target implicitly. Wait for DNS/probe/connection convergence; optional connection draining does not guarantee instantaneous or zero-downtime DNS cutover.

For application rollback, redeploy the previously approved source/digest bundle. For traffic rollback, restore the previously healthy backend target. Keep the old cluster and compatible data/services available until rollout criteria are met. Persistent data, schemas and secrets require their own compatibility and recovery plan.

## Verification boundaries

Public CI and local tests cover configuration, mock providers, rendering, application behavior and release/target safety contracts. The sample CI additionally includes a credential-free two-kind-cluster acceptance job using real image digests, selected-slot updates and rollback. Its result artifact distinguishes success/failure; a configured job is not a passed run. This Kubernetes test uses a local registry mirror inside temporary test nodes and cannot establish Azure networking or identity readiness. Live acceptance additionally needs image push/pull, private API access, DNS/routes, namespace permissions, certificate retrieval, gateway backend health and end-to-end cutover/rollback in a chosen sandbox.

Firewall, gateway, registry and cluster nodes incur charges while deployed. The public examples do not configure VPN/ExpressRoute, issue certificates or replicate application data. Remove application/gateway dependencies and clusters before routes/firewall/network teardown; retain state throughout.

The platform is ready for reviewed sandbox deployment only after real identities, target values, runner networking and environment approvals have been configured. No live cloud resources are created by public validation.
