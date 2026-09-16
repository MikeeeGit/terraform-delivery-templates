mock_provider "azurerm" {}
variables {
  subscription_id_map  = { pprd = "00000000-0000-0000-0000-000000000003" }
  subscription         = "pprd"
  environment          = "pprd"
  location             = "uksouth"
  location_abbreviated = "uks"
  company_abbreviation = "example"
}
run "synthetic_workload" {
  command = plan
  assert {
    condition     = output.resource_group_name == "uks-pprd-example-example-rsg"
    error_message = "The workload should use the selected environment and region."
  }
}
