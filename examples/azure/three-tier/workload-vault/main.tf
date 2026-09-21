terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.81, < 5.0"
    }
  }
  # Add the reviewed private backend in the consumer before shared deployment.
}
provider "azurerm" {
  features {
    key_vault {
      # Retain protected soft-deleted vaults; never attempt a purge on destroy.
      purge_soft_delete_on_destroy = false
    }
  }
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
}
locals {
  prefix = "${var.region}-${var.environment}-${var.name_prefix}"
  tags   = merge(var.tags, { Environment = var.environment, ManagedBy = "Terraform" })
}
resource "azurerm_resource_group" "vault" {
  name     = "${local.prefix}-vault-rg"
  location = var.location
  tags     = local.tags
}
resource "azurerm_key_vault" "workload" {
  name                            = var.vault_name
  location                        = var.location
  resource_group_name             = azurerm_resource_group.vault.name
  tenant_id                       = var.tenant_id
  sku_name                        = "standard"
  rbac_authorization_enabled      = true
  public_network_access_enabled   = false
  purge_protection_enabled        = true
  soft_delete_retention_days      = var.soft_delete_retention_days
  enabled_for_deployment          = false
  enabled_for_disk_encryption     = false
  enabled_for_template_deployment = false
  tags                            = local.tags
  network_acls {
    bypass         = "None"
    default_action = "Deny"
  }
}
resource "azurerm_private_endpoint" "vault" {
  name                = "${local.prefix}-vault-pe"
  location            = var.location
  resource_group_name = azurerm_resource_group.vault.name
  subnet_id           = var.private_endpoint_subnet_id
  tags                = local.tags
  private_service_connection {
    name                           = "vault"
    private_connection_resource_id = azurerm_key_vault.workload.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "vault"
    private_dns_zone_ids = [var.private_dns_zone_id]
  }
}
resource "azurerm_role_assignment" "secret_administrator" {
  for_each             = var.secret_administrator_object_ids
  scope                = azurerm_key_vault.workload.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = each.value
}
output "vault" {
  description = "Non-secret environment vault and endpoint metadata. Feed id to AKS workload roles and the application handoff."
  value = {
    id                  = azurerm_key_vault.workload.id
    name                = azurerm_key_vault.workload.name
    uri                 = azurerm_key_vault.workload.vault_uri
    tenant_id           = var.tenant_id
    subscription_id     = var.subscription_id
    environment         = var.environment
    region              = var.region
    resource_group_name = azurerm_resource_group.vault.name
    private_endpoint_id = azurerm_private_endpoint.vault.id
  }
}
