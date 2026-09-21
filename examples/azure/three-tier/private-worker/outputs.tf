output "worker" {
  description = "Non-secret worker connection and ownership metadata. No credentials or tokens are exported."
  value = {
    id                    = azurerm_linux_virtual_machine.worker.id
    name                  = azurerm_linux_virtual_machine.worker.name
    resource_group_name   = azurerm_resource_group.worker.name
    private_ip_address    = azurerm_network_interface.worker.private_ip_address
    public_ip_address     = var.operator_ssh_cidr == null ? null : azurerm_public_ip.operator[0].ip_address
    ssh_username          = var.admin_username
    subnet_id             = var.subnet_id
    vm_size               = azurerm_linux_virtual_machine.worker.size
    image_version         = azurerm_linux_virtual_machine.worker.source_image_reference[0].version
    identity_principal_id = var.enable_managed_identity ? azurerm_linux_virtual_machine.worker.identity[0].principal_id : null
  }
}
output "blob_private_endpoints" {
  value = { for key, endpoint in azurerm_private_endpoint.state_blob : key => {
    id                 = endpoint.id
    storage_account_id = endpoint.private_service_connection[0].private_connection_resource_id
    subnet_id          = endpoint.subnet_id
  } }
}
output "identity_state_roles" {
  value = { for key, role in azurerm_role_assignment.worker_state : key => {
    id                   = role.id
    principal_id         = role.principal_id
    scope                = role.scope
    role_definition_name = role.role_definition_name
  } }
}
