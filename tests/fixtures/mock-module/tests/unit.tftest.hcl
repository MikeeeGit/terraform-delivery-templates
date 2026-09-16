mock_provider "random" {
  mock_resource "random_string" {
    defaults = {
      result = "mock-generated-name"
    }
  }
}

run "configured_length_and_mocked_result" {
  command = apply
  variables {
    name_length = 16
  }
  assert {
    condition     = random_string.name.length == 16
    error_message = "The requested name length must reach the resource."
  }
  assert {
    condition     = output.generated_name == "mock-generated-name"
    error_message = "The output must propagate the mocked provider result."
  }
}

run "invalid_length_is_rejected" {
  command = plan
  variables {
    name_length = 1
  }
  expect_failures = [var.name_length]
}
