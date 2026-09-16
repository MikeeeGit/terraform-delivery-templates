terraform {
  required_version = ">= 1.12.1, < 2.0.0"
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9.1"
    }
  }
}

variable "name_length" {
  type        = number
  default     = 12
  description = "Length used by this synthetic provider-mocking fixture."
  validation {
    condition     = var.name_length >= 4 && var.name_length <= 64
    error_message = "name_length must be between 4 and 64."
  }
}

resource "random_string" "name" {
  length  = var.name_length
  special = false
}

output "generated_name" {
  value = random_string.name.result
}
