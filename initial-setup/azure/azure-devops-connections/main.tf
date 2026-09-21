terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.81, < 5.0"
    }
    azuredevops = {
      source  = "microsoft/azuredevops"
      version = "~> 1.16.0"
    }
  }
}
provider "azurerm" {
  features {}
  subscription_id                 = var.identity_subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
}
# Supply Azure DevOps provider authentication through its supported environment
# variables in the private bootstrap worker; never put credentials in tfvars.
provider "azuredevops" {
  org_service_url = var.organization_url
}
locals {
  authorizations = { for row in flatten([
    for name, connection in var.connections : [
      for pipeline in connection.pipeline_ids : { key = "${name}/${pipeline}", connection = name, pipeline = pipeline }
    ]
  ]) : row.key => row }
}
data "azurerm_user_assigned_identity" "selected" {
  for_each            = var.connections
  name                = try(split("/", each.value.identity_id)[8], "")
  resource_group_name = try(split("/", each.value.identity_id)[4], "")
}
resource "azuredevops_serviceendpoint_azurerm" "delivery" {
  for_each                               = var.connections
  project_id                             = var.project_id
  service_endpoint_name                  = each.value.name
  description                            = "Federated CI identity managed by Terraform"
  service_endpoint_authentication_scheme = "WorkloadIdentityFederation"
  credentials {
    serviceprincipalid = each.value.client_id
  }
  azurerm_spn_tenantid      = var.tenant_id
  azurerm_subscription_id   = each.value.target_subscription_id
  azurerm_subscription_name = each.value.target_subscription_name
  lifecycle {
    precondition {
      condition     = lower(data.azurerm_user_assigned_identity.selected[each.key].client_id) == lower(each.value.client_id) && lower(data.azurerm_user_assigned_identity.selected[each.key].tenant_id) == lower(var.tenant_id)
      error_message = "The service connection client ID and tenant must match the selected existing managed identity."
    }
  }
}
resource "azurerm_federated_identity_credential" "azure_devops" {
  for_each                  = var.connections
  name                      = "azdo-${substr(sha256("${var.project_id}/${each.key}"), 0, 24)}"
  user_assigned_identity_id = each.value.identity_id
  audience                  = ["api://AzureADTokenExchange"]
  # Use the service's returned values; do not construct legacy vstoken/sc:// trust.
  issuer  = azuredevops_serviceendpoint_azurerm.delivery[each.key].workload_identity_federation_issuer
  subject = azuredevops_serviceendpoint_azurerm.delivery[each.key].workload_identity_federation_subject
}
resource "azuredevops_pipeline_authorization" "delivery" {
  for_each    = local.authorizations
  project_id  = var.project_id
  resource_id = azuredevops_serviceendpoint_azurerm.delivery[each.value.connection].id
  type        = "endpoint"
  pipeline_id = each.value.pipeline
  depends_on  = [azurerm_federated_identity_credential.azure_devops]
}
output "connections" {
  description = "Non-secret endpoint names and exact service-issued federation metadata."
  value = { for name, connection in azuredevops_serviceendpoint_azurerm.delivery : name => {
    id           = connection.id
    name         = connection.service_endpoint_name
    client_id    = var.connections[name].client_id
    identity_id  = var.connections[name].identity_id
    issuer       = connection.workload_identity_federation_issuer
    subject      = connection.workload_identity_federation_subject
    pipeline_ids = var.connections[name].pipeline_ids
  } }
}
