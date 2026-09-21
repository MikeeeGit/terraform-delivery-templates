# CI managed identities in Terraform

This root creates separate CI user-assigned managed identities for one environment, exact GitHub environment federations, and explicitly scoped Azure role assignments. Terraform owns their lifecycle: changes and removals appear in the plan and take effect on apply. It creates no client secrets. Pod/workload identities and AKS permissions belong to Azure AKS Foundation.

Copy this directory into a private bootstrap consumer, copy `terraform.tfvars.example` to a private input file, and replace its synthetic values. Start with the existing [state backend bootstrap](../README.md). Run `terraform init`, `terraform plan -out=bootstrap.tfplan`, review the plan, then `terraform apply bootstrap.tfplan` as the authorised bootstrap operator. Keep state and plans private; migrate initial local state to the protected backend before routine use. Do not run these commands in public CI.

The initial operator needs identity/resource creation and role-assignment authority at the declared scopes. A new pipeline identity cannot create its own first trust or permissions. The example's Terraform apply identity has Contributor plus Role Based Access Control Administrator in a dedicated workload subscription because its stacks create role assignments. That is substantial delegated authority: narrow scopes and add reviewed assignment conditions for a shared subscription. Contributor alone cannot restore permissions. Plan uses Reader plus the state data access needed for state locking. The build identity receives registry publishing access, and platform/application identities receive no automatic cloud grants here.

For each additional environment, use a distinct state, identities, federation environments and resource scopes. Do not reuse a PPRD workload or application deployer in PRD. Cross-subscription hub/registry/DNS grants must be explicit; workload subscription Contributor does not cover a hub subscription.

## GitHub trust

The `repository` input is the exact repository segment of the OIDC subject. Current repositories can use immutable owner/repository IDs, for example `example-org@10000001/platform-application@20000002`. Legacy repositories may use `example-org/platform-application`. Select the format from the real repository's OIDC configuration; do not guess it from the Git URL. Custom subject templates need a deliberate extension to this root. This root constructs protected-environment subjects and escapes colons in environment names. It does not create GitHub environments, reviewers or branch protection. Protect the corresponding environment and use its exact name in the consuming job before enabling a privileged federation. [GitHub OIDC subject reference](https://docs.github.com/en/actions/reference/security/oidc).

The example matches the three-tier callers: `pprd-uks-plan`, `pprd-uks-apply`, `pprd-image-build`, `platform-pprd-uks-aks01/aks02`, and `pprd-uks-aks01/aks02`. No pull-request subject is created. Keep public validation credential-free.

## Azure DevOps trust

Set `github_environments = {}` for Azure DevOps-only identities. Use [Azure DevOps connections](../azure-devops-connections/README.md) to create the service endpoints, their exact returned issuer/subject federations and individual pipeline permissions against these managed identities. The two roots own different named federated credentials; keep the total below Azure's per-identity limit.

Export `terraform output -json identities` only when inspecting the values directly. The [three-tier handoff](../../../docs/azure/three-tier-azure-deployment.md) requires the wrapped `terraform output -json` document so it can reject sensitive outputs and bind the selected environment.

## Validation

The root has credential-free provider mock tests for identity separation, federation subject construction, explicit access scopes and removal of declarations. Provider mocks do not validate an actual GitHub/Azure DevOps token exchange, Azure role propagation or deployment authority.
