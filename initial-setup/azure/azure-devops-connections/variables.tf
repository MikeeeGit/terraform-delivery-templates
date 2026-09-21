variable "identity_subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "organization_url" {
  type = string
  validation {
    condition     = can(regex("^https://dev\\.azure\\.com/[A-Za-z0-9_-]+/?$", var.organization_url))
    error_message = "Supply the selected Azure DevOps organization URL."
  }
}
variable "project_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.project_id))
    error_message = "Supply the existing private project UUID."
  }
}
variable "connections" {
  description = "One endpoint per purpose/target; exact pipeline IDs only. Empty IDs create an unauthorized endpoint ready for a later reviewed update."
  type = map(object({
    name                     = string
    identity_id              = string
    client_id                = string
    target_subscription_id   = string
    target_subscription_name = string
    pipeline_ids             = set(number)
  }))
  validation {
    condition = length(var.connections) > 0 && alltrue([
      for c in var.connections :
      can(regex("(?i)^/subscriptions/${var.identity_subscription_id}/resourceGroups/[^/]+/providers/Microsoft.ManagedIdentity/userAssignedIdentities/[^/]+$", c.identity_id)) &&
      can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", c.client_id)) &&
      can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", c.target_subscription_id)) &&
      length(trimspace(c.name)) > 0 && alltrue([for id in c.pipeline_ids : id > 0 && floor(id) == id])
    ])
    error_message = "Use identities from the selected identity subscription, UUIDs and positive integer pipeline IDs."
  }
  validation {
    condition     = length(distinct([for c in var.connections : lower(c.name)])) == length(var.connections)
    error_message = "Service connection names must be unique."
  }
}
