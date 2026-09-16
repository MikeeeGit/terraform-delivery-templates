terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.33, < 5.0"
    }
  }
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id_map[var.subscription]
  resource_provider_registrations = "none"
}

# Add modules here, or start from azure-network-foundation for the complete network example.
resource "azurerm_resource_group" "example" {
  name     = "${var.location_abbreviated}-${var.environment}-${var.company_abbreviation}-example-rsg"
  location = var.location
  tags     = { environment = var.environment, managed_by = "terraform" }
}

output "resource_group_name" {
  description = "Example workload resource group; no backend resources are created here."
  value       = azurerm_resource_group.example.name
}
