variable "tenant_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "Supply the selected tenant UUID."
  }
}
variable "subscription_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "Supply the identity subscription UUID."
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
variable "tags" {
  type    = map(string)
  default = {}
}
variable "identities" {
  description = "One separate CI identity per purpose and environment. Workload/pod identities remain in the AKS stack."
  type = map(object({
    purpose = string
    github_environments = optional(map(object({
      repository  = string
      environment = string
    })), {})
    role_assignments = optional(map(object({
      scope                = string
      role_definition_name = string
      condition            = optional(string)
    })), {})
  }))
  validation {
    condition = length(var.identities) > 0 && alltrue([
      for key, i in var.identities : can(regex("^[a-z][a-z0-9-]{0,31}$", key)) &&
      contains(["terraform-plan", "terraform-apply", "build", "platform", "application"], i.purpose)
    ])
    error_message = "Use safe identity keys and explicit Terraform plan/apply, build, platform or application purposes."
  }
  validation {
    condition = alltrue(flatten([for i in var.identities : [
      for f in i.github_environments : can(regex("^[A-Za-z0-9_.-]+(@[0-9]+)?/[A-Za-z0-9_.-]+(@[0-9]+)?$", f.repository)) &&
      length(trimspace(f.environment)) > 0 && !can(regex("[\\r\\n*]", f.environment))
    ]]))
    error_message = "GitHub federation requires an exact OIDC owner/repository segment (including immutable IDs where enabled) and protected environment, without wildcards or newlines."
  }
  validation {
    condition = alltrue([for i in var.identities :
      length(distinct([for f in i.github_environments : "${f.repository}:environment:${replace(f.environment, ":", "%3A")}"])) == length(i.github_environments)
    ])
    error_message = "An identity cannot contain duplicate GitHub issuer/subject bindings."
  }
  validation {
    condition     = alltrue([for i in var.identities : length(i.github_environments) <= 18])
    error_message = "Reserve at least two of the identity's 20 federation slots for service connections."
  }
  validation {
    condition = alltrue(flatten([for i in var.identities : [
      for r in i.role_assignments : can(regex("(?i)^/subscriptions/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}(/[^*\\r\\n]+)?$", r.scope)) &&
      length(trimspace(r.role_definition_name)) > 0 && !can(regex("[*\\r\\n]", r.role_definition_name)) &&
      (r.condition == null ? true : length(trimspace(r.condition)) > 0)
    ]]))
    error_message = "Every role needs an explicit Azure subscription/resource scope and role name; conditions cannot be empty."
  }
}
