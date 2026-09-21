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
    error_message = "Use the workload subscription UUID."
  }
}
variable "environment" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,11}$", var.environment))
    error_message = "Use a lowercase environment identifier."
  }
}
variable "region" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,5}$", var.region))
    error_message = "Use a lowercase region abbreviation."
  }
}
variable "location" { type = string }
variable "name_prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,23}$", var.name_prefix))
    error_message = "Use a lowercase name prefix of 2-24 characters."
  }
}
variable "vault_name" {
  description = "Globally unique Azure Key Vault name. Do not reuse the synthetic example unchanged."
  type        = string
  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]$", var.vault_name)) && !strcontains(var.vault_name, "--")
    error_message = "Vault names need 3-24 alphanumeric/hyphen characters, start with a letter, end alphanumeric and contain no consecutive hyphens."
  }
}
variable "private_endpoint_subnet_id" {
  description = "Applied spoke subnet_ids.private-endpoints, in this workload subscription. Network state owns the subnet."
  type        = string
  validation {
    condition     = can(regex("(?i)^/subscriptions/${var.subscription_id}/resourceGroups/[^/]+/providers/Microsoft.Network/virtualNetworks/[^/]+/subnets/[^/]+$", var.private_endpoint_subnet_id))
    error_message = "Use an existing private-endpoint subnet resource ID in the workload subscription."
  }
}
variable "private_dns_zone_id" {
  description = "Applied hub managed_private_dns_zone_ids for privatelink.vaultcore.azure.net. Existing network states own the zone and VNet links."
  type        = string
  validation {
    condition     = can(regex("(?i)^/subscriptions/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}/resourceGroups/[^/]+/providers/Microsoft.Network/privateDnsZones/privatelink[.]vaultcore[.]azure[.]net$", var.private_dns_zone_id))
    error_message = "Supply the existing Azure public-cloud Key Vault Private Link DNS zone ID."
  }
}
variable "secret_administrator_object_ids" {
  description = "Explicit existing operator/group/service-principal object IDs granted Secrets Officer at this vault to seed/rotate secret objects. These are not workload reader identities."
  type        = map(string)
  default     = {}
  validation {
    condition     = alltrue([for id in var.secret_administrator_object_ids : can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", id))]) && length(distinct([for id in var.secret_administrator_object_ids : lower(id)])) == length(var.secret_administrator_object_ids)
    error_message = "Use distinct Entra object UUIDs for secret administration."
  }
}
variable "certificate_seed_operator_object_ids" {
  description = "Optional existing operator/group/service-principal object IDs granted Certificates Officer only at this vault for frontend certificate import/rotation. Empty means no certificate administrator grant."
  type        = set(string)
  default     = []
  nullable    = false
  validation {
    condition = (alltrue([for id in var.certificate_seed_operator_object_ids : can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", id))]) &&
    length(distinct([for id in var.certificate_seed_operator_object_ids : lower(id)])) == length(var.certificate_seed_operator_object_ids))
    error_message = "Use distinct Entra object UUIDs for certificate seeding; an empty set grants no certificate administration."
  }
}
variable "soft_delete_retention_days" {
  type    = number
  default = 90
  validation {
    condition     = var.soft_delete_retention_days >= 7 && var.soft_delete_retention_days <= 90 && floor(var.soft_delete_retention_days) == var.soft_delete_retention_days
    error_message = "Choose an integer retention period from 7 to 90 days."
  }
}
variable "tags" {
  type    = map(string)
  default = {}
}

variable "allow_trusted_azure_services" {
  description = "Explicitly allow Key Vault trusted Microsoft services (including Application Gateway certificate retrieval) to bypass network restrictions. Public access stays disabled; RBAC remains required. This exception covers the trusted-services list, not only this gateway."
  type        = bool
  default     = false
  nullable    = false
}
