# Azure first-time setup

Use the [complete bootstrap guide](../../docs/azure/bootstrap.md) in a private deployment checkout.

This directory resolves the initial remote-state dependency in an explicit order:

1. **backend/** creates state resource groups, storage accounts, role assignments and private containers using local state.
2. **migrate_state.py** migrates the existing local bootstrap state into the created backend after interactive confirmation and verifies the state contents.
3. **federate.py** reviews or creates new secretless deployment identities and scoped roles from a private configuration.
4. Configure CI service connections/environments and workload delivery settings, then follow [getting started](../../docs/getting-started.md).

| File | Purpose |
|---|---|
| `backend/terraform.tfvars.example` | Synthetic backend input example; copy to ignored terraform.tfvars and replace values |
| `backend/main.tf` | Local-state storage bootstrap; no pre-existing remote backend required |
| `migrate_state.py` | Explicit migration with retained backups and state comparison |
| `federation.json.example` | Template for reviewed issuer/subject/role configuration |
| `federate.py` | New-identity creation; default is review-only, --apply asks for confirmation |

Requirements: pinned Terraform, Azure CLI, Python 3.10+, Azure access to the selected tenant/subscriptions and permission for the requested role assignments. Storage firewall access must include the actual operator/runner egress.

The examples are not deployable credentials. Account names must be globally unique and no longer than 24 characters. Preserve generated state, plan and migration files privately; keep provider lockfiles with the deployment configuration.

These helpers do not run automatically from public CI and do not alter existing applications or infrastructure merely by being cloned. See the guide for exact commands, external CI configuration, permissions and recovery boundaries.

## State-managed CI identity lifecycle

Use [delivery-identities](delivery-identities/README.md) for repeatable per-environment CI UAMIs, GitHub federation and role assignments. Add [azure-devops-connections](azure-devops-connections/README.md) for state-managed service endpoints and exact pipeline authorisations. The older create-once federation helper remains available for its existing app-registration workflow; do not let it and Terraform manage the same identity or grants.
