variable "subscription_id" {
  description = "Subscription holding state, independent of workload subscriptions."
  type        = string
}
variable "tenant_id" {
  description = "Microsoft Entra tenant containing the backend subscription."
  type        = string
}
variable "prefix" {
  description = "Globally unique lowercase prefix; match delivery.azure.json."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]{3,8}$", var.prefix))
    error_message = "Use 3-8 lowercase letters/digits. Generated account names must also fit 24 characters."
  }
  validation {
    condition     = alltrue([for environment in var.backend_environments : can(regex("^[a-z0-9]{3,24}$", "${var.secondary_region}${environment}${var.prefix}tfstatesa"))])
    error_message = "Every generated state account name must contain 3-24 lowercase letters/digits; shorten the region, environment or prefix."
  }
}
variable "secondary_region" {
  description = "Backend region abbreviation used by delivery.azure.json."
  type        = string
  default     = "ukw"
}
variable "location" {
  description = "Azure location matching secondary_region."
  type        = string
  default     = "ukwest"
}
variable "backend_environments" {
  description = "Logical state stores. dev aliases pprd; shr aliases hub; bcdr aliases prd."
  type        = set(string)
  default     = ["hub", "pprd", "prd"]
  validation {
    condition     = alltrue([for value in var.backend_environments : can(regex("^[a-z0-9]{2,4}$", value))])
    error_message = "Backend environment labels must contain 2-4 lowercase letters/digits."
  }
}
variable "administrator_ipv4" {
  description = "Operator IPv4 addresses allowed to bootstrap and migrate state; /32 addresses use the bare IP."
  type        = list(string)
  validation {
    condition     = length(var.administrator_ipv4) > 0 && alltrue([for value in var.administrator_ipv4 : can(cidrnetmask(strcontains(value, "/") ? value : "${value}/32")) && value != "0.0.0.0/0"])
    error_message = "Provide explicit IPv4 addresses/CIDRs; never allow 0.0.0.0/0."
  }
}
variable "tags" {
  description = "Tags applied to backend resources."
  type        = map(string)
  default     = { purpose = "terraform-state", managed_by = "terraform" }
}


variable "resource_group_name_prefix" {
  description = "Optional isolated backend resource-group qualifier after region/environment; empty preserves existing names. Does not alter storage account names."
  type        = string
  default     = ""
  nullable    = false
  validation {
    condition     = var.resource_group_name_prefix == "" || can(regex("^([a-z]|[a-z][a-z0-9-]{0,18}[a-z0-9])$", var.resource_group_name_prefix))
    error_message = "resource_group_name_prefix must be empty or 1-20 lowercase letters/digits/hyphens, starting with a letter and ending alphanumeric."
  }
}
