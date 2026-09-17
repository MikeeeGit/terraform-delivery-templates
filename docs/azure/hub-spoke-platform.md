# Worked platform: hub, spokes, dual AKS and WAF gateway

This scenario connects the public repositories into one deployment sequence. Every component remains independently deployable, with its own state and documented ownership. Begin in a private consumer; the public source contains synthetic values and credential-free tests.

## Repository roles

| Repository/example | Owns | Consumes |
|---|---|---|
| azure-network-foundation/examples/hub-spoke | Hub and two spokes, four peering directions, CSV policy, hub DNS and spoke links | Backend bootstrap and subscription aliases |
| Network egress add-on | Azure Firewall, policy, AKS route tables and associations | Actual network/subnet IDs and ranges |
| azure-aks-foundation | One or two independent private AKS clusters, identities and node pools | aks01/aks02 subnet IDs, DNS zone, egress prerequisites |
| azure-application-gateway | WAF_v2 gateway, WAF policies, routing/probes, optional stable private backend aliases | Dedicated appgateway subnet, existing ingress endpoints, Key Vault certificates |
| terraform-delivery-templates | Shared bootstrap, saved-plan delivery, local helpers and private caller examples | Reviewed consumer configuration and operator-created CI controls |

The [network pack](https://github.com/MikeeeGit/azure-network-foundation/tree/v0.3.0/examples/hub-spoke) uses a 10.80/16 hub, 10.81/16 preproduction spoke and 10.82/16 production spoke. Each spoke reserves separate aks01, aks02 and appgateway subnets. The two AKS slots are in one selected region/spoke; they are not automatic regional disaster recovery.

## From zero to traffic

1. Bootstrap private remote state and identities with the [first-time guide](../getting-started.md). Replace every synthetic tenant/subscription/backend value and register the resource providers required by the chosen workloads.
2. Copy the network pack into a new private network consumer. Apply hub, then both spokes with peerings disabled. The hub creates the shared private zones before the spokes create their links.
3. Enable peerings in a reviewed commit and apply all three network targets. Check all four directions are Connected.
4. For inspected AKS egress, apply the optional firewall add-on after peering. Update the spoke VNet DNS servers to its real DNS-proxy address, then attach its AKS-only routes in the documented second stage. Verify DNS and outbound dependencies before acknowledging UDR readiness in AKS. Application Gateway retains its own supported routing.
5. Create a private AKS consumer and pass reviewed network outputs or explicitly configured remote-state coordinates. For private APIs, provide the hub-owned regional private DNS zone and correctly scoped identity permissions. Configure administrators, node pools, supported Kubernetes versions and registry access.
6. Create aks01 and aks02 with separate CIDRs/versions/pools as required. Validate private API connectivity from the private management/CI path. Terraform does not create your application workloads or ingress controller.
7. Install and test an internal ingress endpoint in each cluster. Example reserved pprd addresses are 10.81.0.20 and 10.81.4.20. Confirm probe Host, path, port and backend certificate trust match the actual application.
8. Create a private gateway consumer. Reference versionless Key Vault certificate secret identifiers, configure identity access, and supply listeners, probes, backend settings and WAF policy. A child private alias zone owned by the gateway must link to the hub if the firewall DNS proxy resolves gateway names.
9. Validate backend health and an end-to-end request through the intended listener. Keep the inactive cluster running until rollout and rollback criteria are met.

Use [private network caller examples](../../examples/azure/hub-spoke/README.md) for GitHub/Azure DevOps. AKS and gateway retain their own consumer pipelines and approvals. A YAML dependency or environment name does not create required reviewers, provide a network path to private APIs or prove that an upstream apply occurred.

## Blue/green operations

The stable keys aks01 and aks02 identify deployment slots. Traffic selection is a separate decision. Updating a Kubernetes version on one slot must not imply updating the other or changing the active gateway target.

Plan and apply the inactive cluster change first. Deploy compatible workloads, verify startup/readiness and run application checks. Change the explicit gateway backend or owned stable DNS record only after the new ingress is healthy. Account for probe intervals, DNS caching, connection draining and certificate host names. Keep a reviewed rollback change to the previous healthy backend.

DNS selection is not weighted traffic splitting and does not synchronize application/database state. Changes to schemas, secrets, identity subjects, data stores and persistent volumes need their own deployment and recovery plan. Each cluster has its own OIDC issuer; workload federation must trust only the intended issuer/subject pairs.

## Scope and cost

This example provides runnable network and infrastructure configurations. It does not configure a VPN, ExpressRoute circuit, application deployments, ingress-controller manifests, certificate issuance or data replication. Those prerequisites are explicit in the component guides.

Azure Firewall, WAF_v2, two AKS node pools and public IPs incur charges while deployed. Select a budgeted sandbox and review region/SKU availability, node/pod capacity, firewall SNAT capacity and application dependencies before a live apply. No live deployment is performed by this public example's CI.

Hub/spoke peering is non-transitive. The firewall example adds explicit routes for its supported traffic; linked private DNS zones do not add routing. See [Microsoft's routing guidance](https://learn.microsoft.com/en-us/azure/firewall/firewall-multi-hub-spoke) and [AKS outbound requirements](https://learn.microsoft.com/en-us/azure/aks/outbound-rules-control-egress).

## Validation

CI validates module examples, the network configuration pack, egress add-on, AKS single/dual configurations and gateway routing/WAF scenarios with mocked providers. Real deployment evidence must separately include permissions, route/DNS checks, private API connectivity, gateway health, application traffic, cutover and rollback.
