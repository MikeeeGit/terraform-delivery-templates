mock_provider "azurerm" {}
variables {
  tenant_id       = "00000000-0000-0000-0000-000000000001"
  subscription_id = "00000000-0000-0000-0000-000000000003"
  environment     = "pprd"
  region          = "uks"
  location        = "uksouth"
  name_prefix     = "example"
  identities = {
    platform = { purpose = "platform", github_environments = { one = { repository = "example/platform", environment = "pprd:platform" } } }
    app      = { purpose = "application", github_environments = { one = { repository = "example/app", environment = "pprd-app" } } }
    build = {
      purpose = "build"
      role_assignments = {
        push = { scope = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/hub/providers/Microsoft.ContainerRegistry/registries/exampleacr", role_definition_name = "AcrPush" }
      }
    }
  }
}
run "isolated_ci_trust_and_scopes" {
  command = plan
  assert {
    condition     = length(azurerm_user_assigned_identity.delivery) == 3 && length(azurerm_role_assignment.delivery) == 1
    error_message = "CI identities must stay separate and receive only explicitly declared grants."
  }
  assert {
    condition     = azurerm_federated_identity_credential.github["platform/one"].subject == "repo:example/platform:environment:pprd%3Aplatform"
    error_message = "Protected-environment OIDC subjects must be exact and escape colons."
  }
  assert {
    condition     = azurerm_user_assigned_identity.delivery["app"].name == "uks-pprd-example-app" && azurerm_role_assignment.delivery["build/push"].role_definition_name == "AcrPush"
    error_message = "Environment separation and registry-specific build access must be preserved."
  }
}
run "removing_trust_and_grants_removes_managed_resources" {
  command = plan
  variables {
    identities = { app = { purpose = "application" } }
  }
  assert {
    condition     = length(azurerm_federated_identity_credential.github) == 0 && length(azurerm_role_assignment.delivery) == 0 && length(azurerm_user_assigned_identity.delivery) == 1
    error_message = "Removed declarations must not leave managed federations or grants in configuration."
  }
}
run "reject_wildcard_trust" {
  command = plan
  variables {
    identities = { app = { purpose = "application", github_environments = { unsafe = { repository = "example/app", environment = "*" } } } }
  }
  expect_failures = [var.identities]
}
run "reject_workload_identity_in_ci_stack" {
  command = plan
  variables { identities = { app = { purpose = "workload" } } }
  expect_failures = [var.identities]
}

run "immutable_repository_identifiers" {
  command = plan
  variables {
    identities = { app = {
      purpose             = "application"
      github_environments = { app = { repository = "example@123/application@456", environment = "pprd-uks-aks01" } }
    } }
  }
  assert {
    condition     = azurerm_federated_identity_credential.github["app/app"].subject == "repo:example@123/application@456:environment:pprd-uks-aks01"
    error_message = "Immutable owner and repository IDs must be preserved in the OIDC subject."
  }
}
run "reject_duplicate_federation_subjects" {
  command = plan
  variables {
    identities = { app = {
      purpose = "application"
      github_environments = {
        one = { repository = "example/app", environment = "pprd" }
        two = { repository = "example/app", environment = "pprd" }
      }
    } }
  }
  expect_failures = [var.identities]
}
