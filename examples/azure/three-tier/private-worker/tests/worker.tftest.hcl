mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_resource_group" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/example-worker-rg" }
  }
  mock_resource "azurerm_network_interface" {
    defaults = {
      id                 = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/example-worker-rg/providers/Microsoft.Network/networkInterfaces/worker"
      private_ip_address = "10.80.2.4"
    }
  }
  mock_resource "azurerm_network_security_group" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/example-worker-rg/providers/Microsoft.Network/networkSecurityGroups/worker" }
  }
  mock_resource "azurerm_public_ip" {
    defaults = {
      id         = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/example-worker-rg/providers/Microsoft.Network/publicIPAddresses/worker"
      ip_address = "203.0.113.20"
    }
  }
  mock_resource "azurerm_linux_virtual_machine" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/example-worker-rg/providers/Microsoft.Compute/virtualMachines/worker"
      identity = {
        principal_id = "00000000-0000-0000-0000-000000000041"
        tenant_id    = "00000000-0000-0000-0000-000000000001"
        type         = "SystemAssigned"
      }
    }
  }
}
variables {
  tenant_id            = "00000000-0000-0000-0000-000000000001"
  subscription_id      = "00000000-0000-0000-0000-000000000003"
  location             = "uksouth"
  name_prefix          = "example-worker"
  subnet_id            = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/hub-rg/providers/Microsoft.Network/virtualNetworks/hub/subnets/shared"
  image_version        = "22.04.202608060"
  admin_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINSeKmL3ap3bvk6lyVlXQx6lsnr02HXIJfe1O2ze6aiq terraform-mock-fixture"
}
run "private_default_has_no_public_endpoint_or_identity_grants" {
  command = plan
  assert {
    condition     = length(azurerm_public_ip.operator) == 0 && length(azurerm_network_security_rule.operator_ssh) == 0 && azurerm_network_interface.worker.ip_configuration[0].public_ip_address_id == null
    error_message = "Private workers must have no public IP or inbound SSH rule unless explicitly requested."
  }
  assert {
    condition     = azurerm_network_security_rule.deny_inbound.access == "Deny" && azurerm_network_security_rule.deny_inbound.direction == "Inbound" && azurerm_network_security_rule.deny_inbound.priority == 4096 && azurerm_network_security_rule.deny_inbound.destination_port_range == "*"
    error_message = "Explicit deny must override the NSG's implicit VNet inbound allow."
  }
  assert {
    condition     = azurerm_linux_virtual_machine.worker.disable_password_authentication && azurerm_linux_virtual_machine.worker.admin_password == null && azurerm_linux_virtual_machine.worker.custom_data == null && azurerm_linux_virtual_machine.worker.user_data == null && azurerm_linux_virtual_machine.worker.provision_vm_agent && azurerm_linux_virtual_machine.worker.secure_boot_enabled && azurerm_linux_virtual_machine.worker.vtpm_enabled && azurerm_linux_virtual_machine.worker.encryption_at_host_enabled
    error_message = "Retain key-only, trusted-launch, encrypted agent-capable VM without bootstrap secrets."
  }
  assert {
    condition     = length(azurerm_role_assignment.worker_state) == 0 && output.worker.identity_principal_id == null && output.worker.vm_size == "Standard_D2s_v4" && output.worker.image_version == var.image_version && azurerm_linux_virtual_machine.worker.os_disk[0].disk_size_gb == 64
    error_message = "No automatic Azure grants; worker capacity and image pin must reach the VM."
  }
}
run "explicit_operator_ssh_is_single_source_and_port" {
  command = plan
  variables { operator_ssh_cidr = "203.0.113.10/32" }
  assert {
    condition     = length(azurerm_public_ip.operator) == 1 && azurerm_public_ip.operator[0].sku == "Standard" && azurerm_network_interface.worker.ip_configuration[0].public_ip_address_id == azurerm_public_ip.operator[0].id
    error_message = "The optional public IP must be Standard and attached only to this worker."
  }
  assert {
    condition     = azurerm_network_security_rule.operator_ssh[0].source_address_prefix == "203.0.113.10/32" && azurerm_network_security_rule.operator_ssh[0].destination_port_range == "22" && azurerm_network_security_rule.operator_ssh[0].protocol == "Tcp" && azurerm_network_security_rule.operator_ssh[0].priority < azurerm_network_security_rule.deny_inbound.priority
    error_message = "Operator access must remain key-only SSH from exactly the reviewed address."
  }
}
run "explicit_state_endpoint_and_container_data_role" {
  command = plan
  variables {
    enable_managed_identity = true
    identity_state_roles = {
      bootstrap = {
        scope                = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/examplestate/blobServices/default/containers/tfstate"
        role_definition_name = "Storage Blob Data Contributor"
      }
    }
    blob_private_endpoints = {
      state = {
        storage_account_id  = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/examplestate"
        subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/hub-rg/providers/Microsoft.Network/virtualNetworks/hub/subnets/private-endpoints"
        private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/hub-rg/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
      }
    }
  }
  assert {
    condition     = azurerm_private_endpoint.state_blob["state"].private_service_connection[0].subresource_names == tolist(["blob"]) && azurerm_private_endpoint.state_blob["state"].private_service_connection[0].private_connection_resource_id == var.blob_private_endpoints.state.storage_account_id && azurerm_private_endpoint.state_blob["state"].private_dns_zone_group[0].private_dns_zone_ids == tolist([var.blob_private_endpoints.state.private_dns_zone_id])
    error_message = "State endpoints must bind the selected storage account and existing Blob DNS zone."
  }
  assert {
    condition     = length(azurerm_role_assignment.worker_state) == 1 && azurerm_role_assignment.worker_state["bootstrap"].scope == var.identity_state_roles.bootstrap.scope && azurerm_role_assignment.worker_state["bootstrap"].role_definition_name == "Storage Blob Data Contributor" && azurerm_role_assignment.worker_state["bootstrap"].principal_id == azurerm_linux_virtual_machine.worker.identity[0].principal_id
    error_message = "Only the worker identity receives the one explicitly scoped container grant."
  }
}
run "reject_open_ssh" {
  command = plan
  variables { operator_ssh_cidr = "0.0.0.0/0" }
  expect_failures = [var.operator_ssh_cidr]
}
run "reject_subnet_ssh" {
  command = plan
  variables { operator_ssh_cidr = "203.0.113.0/24" }
  expect_failures = [var.operator_ssh_cidr]
}
run "reject_ipv6_ssh" {
  command = plan
  variables { operator_ssh_cidr = "2001:db8::1/128" }
  expect_failures = [var.operator_ssh_cidr]
}
run "reject_unpinned_image" {
  command = plan
  variables { image_version = "latest" }
  expect_failures = [var.image_version]
}
run "reject_wrong_worker_subscription" {
  command = plan
  variables { subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000009/resourceGroups/hub-rg/providers/Microsoft.Network/virtualNetworks/hub/subnets/shared" }
  expect_failures = [var.subnet_id]
}
run "reject_roles_without_worker_identity" {
  command = plan
  variables {
    identity_state_roles = {
      bootstrap = {
        scope                = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/examplestate/blobServices/default/containers/tfstate"
        role_definition_name = "Storage Blob Data Reader"
      }
    }
  }
  expect_failures = [var.identity_state_roles]
}
run "reject_broad_worker_role" {
  command = plan
  variables {
    enable_managed_identity = true
    identity_state_roles = {
      bootstrap = {
        scope                = "/subscriptions/00000000-0000-0000-0000-000000000003"
        role_definition_name = "Owner"
      }
    }
  }
  expect_failures = [var.identity_state_roles]
}
run "reject_wrong_state_dns_zone" {
  command = plan
  variables {
    blob_private_endpoints = {
      state = {
        storage_account_id  = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/examplestate"
        subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/hub-rg/providers/Microsoft.Network/virtualNetworks/hub/subnets/private-endpoints"
        private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/hub-rg/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"
      }
    }
  }
  expect_failures = [var.blob_private_endpoints]
}
