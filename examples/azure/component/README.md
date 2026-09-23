# Private component delivery callers

Use these inactive caller examples for each separate private infrastructure consumer: firewall, AKS, Application Gateway, or the network repository's standalone route-only egress root. Public CI validates code without Azure credentials; these private callers perform reviewed saved-plan delivery.

1. Put one component root, delivery.azure.json and its config/ hierarchy at the private repository root. For egress, copy the complete examples/hub-spoke/egress directory as the root. Keep a distinct state key for each component/target.
2. Replace synthetic configuration with actual outputs and backend values. The component's delivery contract must agree with the selected environment/region/subscriptions.
3. Merge any chosen optional profile into the private target tfvars before planning. Helpers load only `config/global.tfvars` followed by `config/<region>/<environment>/<environment>.tfvars`; example third-file inputs are not automatically included. Merge whole maps deliberately, preserving unrelated entries, and replace duplicate assignments. This applies to AKS workload identity, firewall platform egress and gateway HTTPS profiles.
4. Copy github-component.yml into .github/workflows/, or create an Azure pipeline using azure-component.yml. Pin both reusable workflow/template sources and script checkout to the same reviewed immutable commit.
5. Configure separate plan/apply identities, backend access and the named private agent pool. Use each private caller's actual OIDC subject. Configure required approvals, branch controls and apply concurrency/exclusive locks using the [platform setup guide](../../../docs/azure/hub-spoke-platform.md).
6. Choose the target, run plan-only, review its receipt, then enable approved saved-plan application. The GitHub repository flag ENABLE_TERRAFORM_APPLY also defaults closed.

| Component | Example target | Required preceding step |
|---|---|---|
| Firewall | hub/uks | Hub VNet, dedicated firewall subnet and resource group |
| AKS routes | hub/uks | All peerings plus applied firewall; prepare tables before explicit attachment |
| AKS | pprd/uks or prd/uks | Validated DNS/routes, dedicated subnets, ACR and private API zone |
| Gateway WAF | pprd/uks (the supplied complete target) | Dedicated subnet, valid TLS certificate, deployed internal application Services |

A selectable target must exist in that component's delivery.azure.json and config/ files; the common helper rejects unsupported selections. Route delivery deliberately grants explicit permissions in the two spoke subscriptions while remaining a single hub-owned state. Application Gateway traffic changes use the same reviewed component pipeline after inactive-cluster smoke tests.

Apply dependencies in the order in the [complete platform walkthrough](../../../docs/azure/hub-spoke-platform.md). Separate states do not imply automatic cross-repository orchestration: each readiness gate must pass before the next component is started. Namespace/bootstrap and application delivery use the shared AKS templates after infrastructure readiness.
