# Hub/spoke delivery example

Use the [complete platform scenario](../../../docs/azure/hub-spoke-platform.md) and the network repository's configuration pack. These caller examples deploy one private network consumer, not arbitrary repositories under an unrestricted token.

Copy github-network.yml into that consumer's .github/workflows directory, or configure an Azure pipeline from azure-network.yml. Both select uks/hub, uks/pprd and uks/prd. They inherit the shared private-project/protected-branch guards and saved-plan workflow.

Configure separate plan/apply identities for each environment. GitHub variable names are AZURE_HUB_PLAN_CLIENT_ID, AZURE_HUB_APPLY_CLIENT_ID, AZURE_PPRD_PLAN_CLIENT_ID, AZURE_PPRD_APPLY_CLIENT_ID, AZURE_PRD_PLAN_CLIENT_ID and AZURE_PRD_APPLY_CLIENT_ID. Each identity needs its own exact environment/region federation subject and reviewed backend/workload scope. Set TERRAFORM_DELIVERY_SHA to the reviewed v0.3.0 commit. The examples default to plan only; GitHub apply additionally requires ENABLE_TERRAFORM_APPLY=true.

Configure hub-uks-plan/apply, pprd-uks-plan/apply and prd-uks-plan/apply environments with the documented approvals and branch controls. Azure DevOps additionally requires the named WIF service connections, pipeline authorization and exclusive apply locks. Review template resources if consuming from a different project or GitHub.

Run the networks in two reviewed configuration phases: first enable_peerings=false, then true after all referenced states exist. Hub finishes before spokes. A successful plan-only hub job does not mean the hub was deployed; first creation still needs approved applies in the required order.

The egress add-on uses a separate state and explicit cross-subscription route permissions. It is not silently included in this pipeline. Run it after network peering, verify DNS/routes, then continue with private AKS and gateway consumer pipelines. Keep their approvals, state and lifecycles independent.

These files are examples outside the framework's active .github/workflows. No public CI run authenticates to Azure or deploys them.
