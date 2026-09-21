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
    condition     = output.backends["pprd"].storage_account_name == "ukwpprdexampletfstatesa" && output.backends["pprd"].container_name == "ukw-pprd-azdo-tfstate" && output.backends["pprd"].resource_group_name == "ukw-pprd-tfstate-rsg"
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

run "isolated_backend_groups_preserve_account_and_container_contract" {
  command = plan
  variables {
    resource_group_name_prefix = "aks-lab"
  }
  assert {
    condition     = output.backends["pprd"].resource_group_name == "ukw-pprd-aks-lab-tfstate-rsg" && output.backends["hub"].resource_group_name == "ukw-hub-aks-lab-tfstate-rsg"
    error_message = "Explicit isolation must qualify every backend resource group."
  }
  assert {
    condition     = output.backends["pprd"].storage_account_name == "ukwpprdexampletfstatesa" && output.backends["pprd"].container_name == "ukw-pprd-azdo-tfstate" && azurerm_storage_account.state["pprd"].resource_group_name == output.backends["pprd"].resource_group_name
    error_message = "Isolated resource groups must reach storage while preserving independent account/container names."
  }
}

run "reject_invalid_backend_group_qualifier" {
  command = plan
  variables {
    resource_group_name_prefix = "AKS/Lab"
  }
  expect_failures = [var.resource_group_name_prefix]
}

run "reject_oversized_backend_group_qualifier" {
  command = plan
  variables {
    resource_group_name_prefix = "abcdefghijklmnopqrstu"
  }
  expect_failures = [var.resource_group_name_prefix]
}

run "operator_state_disabled_preserves_default_resources" {
  command = plan
  assert {
    condition     = output.operator_backend == null && length(azurerm_storage_container.operator) == 0 && length(azurerm_storage_container.state) == 3
    error_message = "Default bootstrap must preserve the three existing component containers and no operator container."
  }
}
run "operator_state_is_a_distinct_private_container" {
  command = plan
  variables {
    operator_state_container_name = "example-bootstrap"
  }
  assert {
    condition     = output.operator_backend.container_name == "example-bootstrap" && output.operator_backend.storage_account_name == output.backends["hub"].storage_account_name && output.operator_backend.resource_group_name == output.backends["hub"].resource_group_name && output.operator_backend.tenant_id == var.tenant_id && output.operator_backend.subscription_id == var.subscription_id && output.operator_backend.use_azuread_auth
    error_message = "Operator output must match its selected owned account with separate container coordinates."
  }
  assert {
    condition     = azurerm_storage_container.operator[0].container_access_type == "private" && length(azurerm_storage_container.state) == 3 && output.backends["hub"].container_name == "ukw-hub-azdo-tfstate"
    error_message = "Operator isolation must retain private access and unchanged component containers."
  }
}
run "operator_state_can_select_another_owned_account" {
  command = plan
  variables {
    operator_state_container_name = "example-bootstrap"
    operator_state_environment    = "pprd"
  }
  assert {
    condition     = output.operator_backend.storage_account_name == output.backends["pprd"].storage_account_name && output.operator_backend.resource_group_name == output.backends["pprd"].resource_group_name
    error_message = "An explicit owned environment must select that actual state account."
  }
}
run "reject_operator_container_name_collision" {
  command = plan
  variables {
    operator_state_container_name = "ukw-hub-azdo-tfstate"
  }
  expect_failures = [var.operator_state_container_name]
}
run "reject_invalid_operator_container_name" {
  command = plan
  variables {
    operator_state_container_name = "invalid--container"
  }
  expect_failures = [var.operator_state_container_name]
}
run "reject_unowned_operator_state_environment" {
  command = plan
  variables {
    operator_state_container_name = "example-bootstrap"
    operator_state_environment    = "dev"
  }
  expect_failures = [var.operator_state_container_name]
}
