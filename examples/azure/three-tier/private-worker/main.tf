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
  features {}
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
}
locals {
  tags = merge(var.tags, { ManagedBy = "Terraform", Purpose = "Private deployment worker" })
}
resource "azurerm_resource_group" "worker" {
  name     = "${var.name_prefix}-rg"
  location = var.location
  tags     = local.tags
}
resource "azurerm_public_ip" "operator" {
  count               = var.operator_ssh_cidr == null ? 0 : 1
  name                = "${var.name_prefix}-operator-pip"
  location            = var.location
  resource_group_name = azurerm_resource_group.worker.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}
resource "azurerm_network_security_group" "worker" {
  name                = "${var.name_prefix}-nsg"
  location            = var.location
  resource_group_name = azurerm_resource_group.worker.name
  tags                = local.tags
}
resource "azurerm_network_security_rule" "operator_ssh" {
  count                       = var.operator_ssh_cidr == null ? 0 : 1
  name                        = "OperatorSsh"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "22"
  source_address_prefix       = var.operator_ssh_cidr
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.worker.name
  network_security_group_name = azurerm_network_security_group.worker.name
}
resource "azurerm_network_security_rule" "deny_inbound" {
  name                        = "DenyAllInbound"
  priority                    = 4096
  direction                   = "Inbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.worker.name
  network_security_group_name = azurerm_network_security_group.worker.name
}
resource "azurerm_network_interface" "worker" {
  name                = "${var.name_prefix}-nic"
  location            = var.location
  resource_group_name = azurerm_resource_group.worker.name
  tags                = local.tags
  ip_configuration {
    name                          = "worker"
    subnet_id                     = var.subnet_id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = var.operator_ssh_cidr == null ? null : azurerm_public_ip.operator[0].id
  }
}
resource "azurerm_network_interface_security_group_association" "worker" {
  network_interface_id      = azurerm_network_interface.worker.id
  network_security_group_id = azurerm_network_security_group.worker.id
}
resource "azurerm_linux_virtual_machine" "worker" {
  name                            = "${var.name_prefix}-vm"
  location                        = var.location
  resource_group_name             = azurerm_resource_group.worker.name
  size                            = var.vm_size
  admin_username                  = var.admin_username
  network_interface_ids           = [azurerm_network_interface.worker.id]
  disable_password_authentication = true
  provision_vm_agent              = true
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  encryption_at_host_enabled      = var.host_encryption_enabled
  tags                            = local.tags
  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }
  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = var.image_version
  }
  os_disk {
    name                 = "${var.name_prefix}-os"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 64
  }
  dynamic "identity" {
    for_each = var.enable_managed_identity ? [true] : []
    content {
      type = "SystemAssigned"
    }
  }
  # No cloud-init, agent registration token, private key or deployment credential.
  depends_on = [
    azurerm_network_interface_security_group_association.worker,
    azurerm_network_security_rule.deny_inbound,
    azurerm_network_security_rule.operator_ssh,
  ]
}
resource "azurerm_role_assignment" "worker_state" {
  for_each                         = var.enable_managed_identity ? var.identity_state_roles : {}
  scope                            = each.value.scope
  role_definition_name             = each.value.role_definition_name
  principal_id                     = azurerm_linux_virtual_machine.worker.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}
resource "azurerm_private_endpoint" "state_blob" {
  for_each            = var.blob_private_endpoints
  name                = "${var.name_prefix}-${each.key}-blob-pe"
  location            = var.location
  resource_group_name = azurerm_resource_group.worker.name
  subnet_id           = each.value.subnet_id
  tags                = local.tags
  private_service_connection {
    name                           = "state-blob"
    private_connection_resource_id = each.value.storage_account_id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "state-blob"
    private_dns_zone_ids = [each.value.private_dns_zone_id]
  }
}
