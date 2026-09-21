terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.81, < 5.0"
    }
  }
  # Configure a private backend in the consumer after the first bootstrap.
}
provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
}
locals {
  prefix = "${var.region}-${var.environment}-${var.name_prefix}"
  federations = { for row in flatten([
    for key, identity in var.identities : [
      for name, federation in identity.github_environments : {
        key      = "${key}/${name}"
        identity = key
        issuer   = "https://token.actions.githubusercontent.com"
        subject  = "repo:${federation.repository}:environment:${replace(federation.environment, ":", "%3A")}"
      }
    ]
  ]) : row.key => row }
  assignments = { for row in flatten([
    for key, identity in var.identities : [
      for name, role in identity.role_assignments : {
        key = "${key}/${name}", identity = key, role = role
      }
    ]
  ]) : row.key => row }
}
resource "azurerm_resource_group" "identity" {
  name     = "${local.prefix}-delivery-rg"
  location = var.location
  tags     = merge(var.tags, { Environment = var.environment, ManagedBy = "Terraform" })
}
resource "azurerm_user_assigned_identity" "delivery" {
  for_each            = var.identities
  name                = "${local.prefix}-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.identity.name
  tags                = azurerm_resource_group.identity.tags
}
resource "azurerm_federated_identity_credential" "github" {
  for_each                  = local.federations
  name                      = "github-${substr(sha256(each.key), 0, 24)}"
  user_assigned_identity_id = azurerm_user_assigned_identity.delivery[each.value.identity].id
  issuer                    = each.value.issuer
  subject                   = each.value.subject
  audience                  = ["api://AzureADTokenExchange"]
}
resource "azurerm_role_assignment" "delivery" {
  for_each                         = local.assignments
  scope                            = each.value.role.scope
  role_definition_name             = each.value.role.role_definition_name
  principal_id                     = azurerm_user_assigned_identity.delivery[each.value.identity].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
  condition                        = each.value.role.condition
  condition_version                = each.value.role.condition == null ? null : "2.0"
}
output "identities" {
  description = "Non-secret CI identities. Keep environment metadata in private consumers. AKS grants belong to the AKS stack."
  value = { for key, identity in azurerm_user_assigned_identity.delivery : key => {
    id                  = identity.id
    client_id           = identity.client_id
    principal_id        = identity.principal_id
    resource_group_name = azurerm_resource_group.identity.name
    tenant_id           = var.tenant_id
    subscription_id     = var.subscription_id
    environment         = var.environment
    region              = var.region
    purpose             = var.identities[key].purpose
    role_assignments = { for assignment_key, assignment in azurerm_role_assignment.delivery : assignment_key => {
      id    = assignment.id, principal_id = assignment.principal_id,
      scope = assignment.scope, role_definition_name = assignment.role_definition_name
    } if local.assignments[assignment_key].identity == key }
    github_federations = { for name, f in azurerm_federated_identity_credential.github : name => { issuer = f.issuer, subject = f.subject } if local.federations[name].identity == key }
  } }
}
