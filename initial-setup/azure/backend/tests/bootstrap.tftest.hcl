mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      object_id       = "00000000-0000-0000-0000-000000000005"
      tenant_id       = "00000000-0000-0000-0000-000000000001"
      subscription_id = "00000000-0000-0000-0000-000000000002"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/mock/providers/Microsoft.Storage/storageAccounts/mockstate"
    }
  }
}
variables {
  subscription_id    = "00000000-0000-0000-0000-000000000002"
  tenant_id          = "00000000-0000-0000-0000-000000000001"
  prefix             = "example"
  administrator_ipv4 = ["203.0.113.10"]
}
run "backend_contract" {
  command = plan
  assert {
    condition     = output.backends["pprd"].storage_account_name == "ukwpprdexampletfstatesa" && output.backends["pprd"].container_name == "ukw-pprd-azdo-tfstate"
    error_message = "Bootstrap names must match the delivery.azure.json contract."
  }
  assert {
    condition     = alltrue([for value in azurerm_storage_account.state : !value.shared_access_key_enabled && !value.allow_nested_items_to_be_public && value.network_rules[0].default_action == "Deny"])
    error_message = "State accounts must require Azure AD and restricted network access."
  }
}
run "reject_oversized_account_name" {
  command = plan
  variables {
    prefix = "example01"
  }
  expect_failures = [var.prefix]
}
run "reject_oversized_region_combination" {
  command = plan
  variables {
    secondary_region = "longregion"
  }
  expect_failures = [var.prefix]
}
