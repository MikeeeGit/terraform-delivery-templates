# Terraform-managed Azure DevOps federated connections

This root connects existing CI managed identities from [delivery-identities](../delivery-identities/README.md) to an existing private Azure DevOps project. It creates each Resource Manager service connection, attaches federation using the service's returned issuer and subject, and authorises only the listed pipeline IDs. It verifies that each supplied client ID and tenant match the selected actual managed identity.

The Terraform Azure DevOps provider uses the private bootstrap worker's supported authentication environment. Do not put its token in Terraform files, tfvars, backend settings or logs. The bootstrap operator needs service-connection administration in the selected project and federated-credential management on the identities. Azure role assignments stay in their owning Terraform stacks.

Supply `organization_url`, `project_id`, `tenant_id`, `identity_subscription_id` and `connections` in private inputs. Each connection entry has:

```hcl
application = {
  name                     = "example-pprd-application-federated"
  identity_id              = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/uks-pprd-example-delivery-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uks-pprd-example-application"
  client_id                = "00000000-0000-0000-0000-000000000101"
  target_subscription_id   = "00000000-0000-0000-0000-000000000003"
  target_subscription_name = "Example PPRD"
  pipeline_ids             = [101, 102]
}
```

Create separate plan, apply, build, platform and application entries from the applied identity outputs. Use the actual target subscription for each endpoint, including the hub subscription for registry builds. An endpoint's subscription metadata does not grant Azure access. Bind each caller's `serviceConnection`/`buildServiceConnection`/`deployServiceConnection` parameter to the appropriate output name.

An empty pipeline set intentionally creates an endpoint with no pipeline authorisations. After creating the private pipeline definitions, add their exact IDs and reapply; zero/all-pipeline sentinels are rejected. Do not grant all-pipeline access outside this root because it overrides individual restrictions. Removing a managed authorisation/federation from configuration revokes it on apply; independently created grants remain additive.

Use a distinct private backend/state key and the normal reviewed saved-plan/apply cycle. The service endpoint and managed identity must remain in the same Entra tenant. Confirm the first real pipeline login before proceeding. Azure DevOps is migrating from its older issuer to Microsoft Entra-issued trust; copying a historic `sc://` formula can create unusable credentials. This root deliberately follows returned endpoint metadata. [Microsoft's federation setup](https://learn.microsoft.com/en-us/azure/devops/pipelines/release/configure-workload-identity?view=azure-devops), [provider resource](https://registry.terraform.io/providers/microsoft/azuredevops/latest/docs/resources/serviceendpoint_azurerm).

Credential-free tests mock the service response to prove exact issuer/subject propagation and individual pipeline authorisation. They do not prove the live DevOps service/provider lifecycle; retain first-login evidence in the private deployment.
