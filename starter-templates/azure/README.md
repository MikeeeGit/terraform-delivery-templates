# Private Azure consumer starter

Copy this directory's contents, including `.github`, `.gitignore` and `.terraform.lock.hcl`, into a private repository. All identifiers are synthetic. Replace delivery/config values together and follow [the complete getting-started guide](https://github.com/MikeeeGit/terraform-delivery-templates/blob/v0.2.0/docs/getting-started.md) and [bootstrap guide](https://github.com/MikeeeGit/terraform-delivery-templates/blob/v0.2.0/docs/azure/bootstrap.md).

`main.tf` intentionally demonstrates a small workload resource group. Use [azure-network-foundation](https://github.com/MikeeeGit/azure-network-foundation) when you want the full network composition. This starter does not create its own backend.

The `validate.yml` workflow has no cloud permissions. The manual plan/apply callers require a private repository, reviewed `TERRAFORM_DELIVERY_SHA`, OIDC identities, allowed network access and configured environments. CI apply is disabled until you explicitly enable the documented approval controls. Azure caller triggers are disabled; the apply example deliberately starts with `enableApply: false`.

The shared workflow/pipeline references target `v0.2.0`; ensure that release exists and pin its reviewed commit before first use. An empty template SHA fails before authentication. The local `tf_setup` repository argument must match this consumer's folder name.

For a complete network and workload example, see the [hub/spoke platform guide](https://github.com/MikeeeGit/terraform-delivery-templates/blob/v0.3.0/docs/azure/hub-spoke-platform.md). This minimal resource-group starter remains useful for testing delivery setup.
