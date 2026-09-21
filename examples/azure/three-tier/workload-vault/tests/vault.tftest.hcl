mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/uks-pprd-example-vault-rg/providers/Microsoft.KeyVault/vaults/example-platform-app"
      vault_uri = "https://example-platform-app.vault.azure.net/"
    }
  }
}
variables {
  tenant_id                  = "00000000-0000-0000-0000-000000000001"
  subscription_id            = "00000000-0000-0000-0000-000000000003"
  environment                = "pprd"
  region                     = "uks"
  location                   = "uksouth"
  name_prefix                = "example"
  vault_name                 = "example-platform-app"
  private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/spoke-rg/providers/Microsoft.Network/virtualNetworks/spoke/subnets/private-endpoints"
  private_dns_zone_id        = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/hub-rg/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"
}
run "private_rbac_vault" {
  command = plan
  assert {
    condition = (!azurerm_key_vault.workload.public_network_access_enabled &&
      azurerm_key_vault.workload.rbac_authorization_enabled &&
      azurerm_key_vault.workload.purge_protection_enabled &&
      azurerm_key_vault.workload.soft_delete_retention_days == 90 &&
      azurerm_key_vault.workload.tenant_id == var.tenant_id &&
      azurerm_key_vault.workload.network_acls[0].default_action == "Deny" &&
    azurerm_key_vault.workload.network_acls[0].bypass == "None")
    error_message = "The vault must retain private-only RBAC access, tenant binding and recovery protection."
  }
  assert {
    condition = (azurerm_private_endpoint.vault.subnet_id == var.private_endpoint_subnet_id &&
      azurerm_private_endpoint.vault.private_service_connection[0].subresource_names == tolist(["vault"]) &&
      azurerm_private_endpoint.vault.private_dns_zone_group[0].private_dns_zone_ids == tolist([var.private_dns_zone_id]) &&
      length(azurerm_role_assignment.secret_administrator) == 0 &&
    length(azurerm_role_assignment.certificate_seed_operator) == 0)
    error_message = "Endpoint ownership must use existing network outputs; no secret administration is implicit."
  }
}
run "explicit_secret_administration" {
  command = plan
  variables {
    secret_administrator_object_ids = { operators = "00000000-0000-0000-0000-000000000031" }
  }
  assert {
    condition     = azurerm_role_assignment.secret_administrator["operators"].scope == azurerm_key_vault.workload.id && azurerm_private_endpoint.vault.private_service_connection[0].private_connection_resource_id == azurerm_key_vault.workload.id && length(azurerm_role_assignment.secret_administrator) == 1 && azurerm_role_assignment.secret_administrator["operators"].role_definition_name == "Key Vault Secrets Officer" && azurerm_role_assignment.secret_administrator["operators"].principal_id == "00000000-0000-0000-0000-000000000031"
    error_message = "Only the configured operator receives secret administration, separate from application workload roles."
  }
}
run "reject_wrong_private_dns_zone" {
  command = plan
  variables { private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/hub-rg/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net" }
  expect_failures = [var.private_dns_zone_id]
}
run "reject_wrong_subnet_subscription" {
  command = plan
  variables { private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000009/resourceGroups/spoke-rg/providers/Microsoft.Network/virtualNetworks/spoke/subnets/private-endpoints" }
  expect_failures = [var.private_endpoint_subnet_id]
}

run "explicit_certificate_seed_operators" {
  command = plan
  variables {
    secret_administrator_object_ids      = { operators = "00000000-0000-0000-0000-000000000031" }
    certificate_seed_operator_object_ids = ["00000000-0000-0000-0000-000000000031", "00000000-0000-0000-0000-000000000032"]
  }
  assert {
    condition = (length(azurerm_role_assignment.certificate_seed_operator) == 2 &&
      alltrue([for id, assignment in azurerm_role_assignment.certificate_seed_operator :
        assignment.principal_id == id && assignment.scope == azurerm_key_vault.workload.id &&
        assignment.role_definition_name == "Key Vault Certificates Officer"
      ]) &&
      length(azurerm_role_assignment.secret_administrator) == 1 &&
      azurerm_role_assignment.secret_administrator["operators"].role_definition_name == "Key Vault Secrets Officer" &&
      azurerm_key_vault.workload.purge_protection_enabled &&
    !azurerm_key_vault.workload.public_network_access_enabled)
    error_message = "Only explicitly selected certificate operators receive the vault-scoped certificate role; secret grants and vault isolation remain intact."
  }
}
run "reject_invalid_certificate_operator" {
  command = plan
  variables { certificate_seed_operator_object_ids = ["not-an-object-uuid"] }
  expect_failures = [var.certificate_seed_operator_object_ids]
}
run "reject_duplicate_certificate_operator_case" {
  command = plan
  variables { certificate_seed_operator_object_ids = ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"] }
  expect_failures = [var.certificate_seed_operator_object_ids]
}

run "trusted_services_opt_in_preserves_other_boundaries" {
  command = plan
  variables { allow_trusted_azure_services = true }
  assert {
    condition = (azurerm_key_vault.workload.network_acls[0].bypass == "AzureServices" &&
      azurerm_key_vault.workload.network_acls[0].default_action == "Deny" &&
      !azurerm_key_vault.workload.public_network_access_enabled &&
      azurerm_key_vault.workload.rbac_authorization_enabled &&
      azurerm_key_vault.workload.purge_protection_enabled &&
      azurerm_private_endpoint.vault.private_service_connection[0].subresource_names == tolist(["vault"]) &&
      length(azurerm_role_assignment.secret_administrator) == 0 &&
      length(azurerm_role_assignment.certificate_seed_operator) == 0)
    error_message = "Trusted-service opt-in must not enable public access, remove private connectivity/protection or add identity grants."
  }
}
