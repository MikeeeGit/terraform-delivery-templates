variable "tenant_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "Use the selected Entra tenant UUID."
  }
}
variable "subscription_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "Use the selected workload subscription UUID."
  }
}
variable "location" { type = string }
variable "name_prefix" {
  description = "Unique disposable worker prefix; this root owns its RG, VM, NIC, NSG and optional endpoints."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,43}$", var.name_prefix))
    error_message = "Use a lowercase name prefix of 2-44 characters."
  }
}
variable "subnet_id" {
  description = "Existing dedicated management/worker subnet in this subscription. Network owns routes and DNS."
  type        = string
  validation {
    condition     = can(regex("(?i)^/subscriptions/${var.subscription_id}/resourceGroups/[^/]+/providers/Microsoft.Network/virtualNetworks/[^/]+/subnets/[^/]+$", var.subnet_id))
    error_message = "Use an existing worker subnet resource ID in the selected subscription."
  }
}
variable "vm_size" {
  type        = string
  default     = "Standard_D2s_v4"
  description = "Two vCPU/eight GiB default. Verify actual regional capacity and family quota."
}
variable "image_version" {
  description = "Exact available Canonical Jammy 22.04 Gen2 image version; latest is intentionally forbidden."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+[.][0-9]+[.][0-9]+$", var.image_version))
    error_message = "Pin an exact numeric Marketplace image version, not latest."
  }
}
variable "admin_username" {
  type    = string
  default = "azureuser"
  validation {
    condition     = can(regex("^[a-z][a-z0-9_-]{0,30}$", var.admin_username)) && !contains(["root", "admin", "administrator"], var.admin_username)
    error_message = "Use a non-root Linux administrative username."
  }
}
variable "admin_ssh_public_key" {
  description = "Operator-generated public SSH key only. The private key must never enter Terraform."
  type        = string
  validation {
    condition     = can(regex("^ssh-(ed25519|rsa) [A-Za-z0-9+/=]+([ ][^\\r\\n]+)?$", trimspace(var.admin_ssh_public_key)))
    error_message = "Provide one OpenSSH RSA or Ed25519 public key."
  }
}
variable "operator_ssh_cidr" {
  description = "Optional reviewed operator IPv4 /32. Enables one public IP and source-restricted SSH; null keeps the worker private."
  type        = string
  default     = null
  validation {
    condition     = var.operator_ssh_cidr == null ? true : can(cidrnetmask(var.operator_ssh_cidr)) && can(regex("^([0-9]{1,3}[.]){3}[0-9]{1,3}/32$", var.operator_ssh_cidr))
    error_message = "Public SSH requires one explicit IPv4 /32; broader ranges and IPv6 are forbidden."
  }
}
variable "host_encryption_enabled" {
  description = "Retained by default; requires Compute EncryptionAtHost registration and SKU support. Any trial override must be explicit."
  type        = bool
  default     = true
}
variable "enable_managed_identity" {
  description = "Optional worker-local identity; CI jobs should authenticate using their own federated identities."
  type        = bool
  default     = false
}
variable "identity_state_roles" {
  description = "Optional explicit blob-container data access for worker bootstrap. No management-plane or subscription-wide roles."
  type = map(object({
    scope                = string
    role_definition_name = string
  }))
  default = {}
  validation {
    condition     = var.enable_managed_identity || length(var.identity_state_roles) == 0
    error_message = "Enable the worker identity explicitly before declaring its state roles."
  }
  validation {
    condition = alltrue([for role in values(var.identity_state_roles) :
      contains(["Storage Blob Data Reader", "Storage Blob Data Contributor"], role.role_definition_name) &&
      can(regex("(?i)^/subscriptions/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}/resourceGroups/[^/]+/providers/Microsoft.Storage/storageAccounts/[a-z0-9]{3,24}/blobServices/default/containers/[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", role.scope))
    ])
    error_message = "Worker identity grants must be explicit Blob Data Reader/Contributor roles on individual storage containers."
  }
}
variable "blob_private_endpoints" {
  description = "Explicit owned state-account Blob endpoints. Network owns the supplied subnets, central private DNS zone and VNet links."
  type = map(object({
    storage_account_id  = string
    subnet_id           = string
    private_dns_zone_id = string
  }))
  default = {}
  validation {
    condition = alltrue([for key, endpoint in var.blob_private_endpoints :
      can(regex("^[a-z][a-z0-9-]{0,19}$", key)) &&
      can(regex("(?i)^/subscriptions/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}/resourceGroups/[^/]+/providers/Microsoft.Storage/storageAccounts/[a-z0-9]{3,24}$", endpoint.storage_account_id)) &&
      can(regex("(?i)^/subscriptions/${var.subscription_id}/resourceGroups/[^/]+/providers/Microsoft.Network/virtualNetworks/[^/]+/subnets/[^/]+$", endpoint.subnet_id)) &&
      can(regex("(?i)^/subscriptions/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}/resourceGroups/[^/]+/providers/Microsoft.Network/privateDnsZones/privatelink[.]blob[.]core[.]windows[.]net$", endpoint.private_dns_zone_id))
    ])
    error_message = "Use stable endpoint keys, existing storage IDs, endpoint subnets in this subscription and the Blob Private Link DNS zone."
  }
}
variable "tags" {
  type    = map(string)
  default = {}
}
