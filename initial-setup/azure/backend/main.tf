terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.33, < 5.0"
    }
  }
  # Intentionally local for the first apply. migrate_state.py installs the backend.
}

provider "azurerm" {
  features {
    storage {
      # Grant initial Blob Data access after ARM creates the account. Avoid a
      # first-bootstrap data-plane readiness check before that role exists.
      data_plane_available = false
    }
  }
  subscription_id     = var.subscription_id
  tenant_id           = var.tenant_id
  storage_use_azuread = true
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "state" {
  for_each = var.backend_environments
  name     = "${var.secondary_region}-${each.key}-tfstate-rsg"
  location = var.location
  tags     = var.tags
}

resource "azurerm_storage_account" "state" {
  for_each                        = var.backend_environments
  name                            = "${var.secondary_region}${each.key}${var.prefix}tfstatesa"
  resource_group_name             = azurerm_resource_group.state[each.key].name
  location                        = azurerm_resource_group.state[each.key].location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  tags                            = var.tags
  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
    ip_rules       = var.administrator_ipv4
  }
  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 14
    }
    container_delete_retention_policy {
      days = 14
    }
  }
}

resource "azurerm_role_assignment" "bootstrap_blob" {
  for_each             = var.backend_environments
  scope                = azurerm_storage_account.state[each.key].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_storage_container" "state" {
  for_each              = var.backend_environments
  name                  = "${var.secondary_region}-${each.key}-azdo-tfstate"
  storage_account_id    = azurerm_storage_account.state[each.key].id
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.bootstrap_blob]
}

output "backends" {
  description = "Non-secret backend settings; keep organization-specific values in your private consumer."
  value = {
    for environment in var.backend_environments : environment => {
      subscription_id      = var.subscription_id
      tenant_id            = var.tenant_id
      resource_group_name  = azurerm_resource_group.state[environment].name
      storage_account_name = azurerm_storage_account.state[environment].name
      container_name       = azurerm_storage_container.state[environment].name
      use_azuread_auth     = true
    }
  }
}
