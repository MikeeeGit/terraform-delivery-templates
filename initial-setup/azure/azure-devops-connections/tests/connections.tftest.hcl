mock_provider "azurerm" {
  mock_data "azurerm_user_assigned_identity" {
    defaults = {
      client_id = "00000000-0000-0000-0000-000000000005"
      tenant_id = "00000000-0000-0000-0000-000000000001"
    }
  }
}
mock_provider "azuredevops" {
  mock_resource "azuredevops_serviceendpoint_azurerm" {
    defaults = {
      id                                   = "00000000-0000-0000-0000-000000000099"
      workload_identity_federation_issuer  = "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000001/v2.0"
      workload_identity_federation_subject = "service-issued-opaque-subject"
    }
  }
}
variables {
  identity_subscription_id = "00000000-0000-0000-0000-000000000003"
  tenant_id                = "00000000-0000-0000-0000-000000000001"
  organization_url         = "https://dev.azure.com/example"
  project_id               = "00000000-0000-0000-0000-000000000004"
  connections = {
    app = {
      name                     = "pprd-app-federated"
      identity_id              = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/identity/providers/Microsoft.ManagedIdentity/userAssignedIdentities/app"
      client_id                = "00000000-0000-0000-0000-000000000005"
      target_subscription_id   = "00000000-0000-0000-0000-000000000003"
      target_subscription_name = "PPRD"
      pipeline_ids             = [42, 43]
    }
  }
}
run "service_issued_trust_and_explicit_pipeline_access" {
  command = apply
  assert {
    condition     = azurerm_federated_identity_credential.azure_devops["app"].issuer == "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000001/v2.0" && azurerm_federated_identity_credential.azure_devops["app"].subject == "service-issued-opaque-subject"
    error_message = "Federation must follow the actual service endpoint, not a constructed legacy issuer/subject."
  }
  assert {
    condition     = length(azuredevops_pipeline_authorization.delivery) == 2 && alltrue([for a in azuredevops_pipeline_authorization.delivery : contains([42, 43], a.pipeline_id)])
    error_message = "Only the individually declared pipelines may use the endpoint."
  }
}
run "reject_all_pipelines_sentinel" {
  command = plan
  variables {
    connections = {
      app = {
        name      = "app", identity_id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/identity/providers/Microsoft.ManagedIdentity/userAssignedIdentities/app"
        client_id = "00000000-0000-0000-0000-000000000005", target_subscription_id = "00000000-0000-0000-0000-000000000003", target_subscription_name = "PPRD", pipeline_ids = [0]
      }
    }
  }
  expect_failures = [var.connections]
}
