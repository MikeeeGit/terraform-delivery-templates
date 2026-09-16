# Azure delivery

The reviewed Azure interface is now split into [GitHub Actions](azure/github-actions.md), [Azure DevOps](azure/azure-devops.md), [local helpers](azure/local-helpers.md) and [first-time bootstrap](azure/bootstrap.md).

The provisional single-target `terraform-azure-private.yml` interface is retired in v0.2.0. Use `.github/workflows/terraform-azure.yml` and the explicit `delivery.azure.json` configuration instead. This restores environment/region expansion, aliases and independent backend/workload targets from the original framework.
