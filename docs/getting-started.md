# Getting started

Choose a public reusable source repository and a **separate private deployment consumer**. This framework's own public CI performs no cloud login or deployment. The private restriction is enforced before authenticated jobs or persistent deployment runners start.

## From zero

1. Install Git, Python 3.10+ (`python3` on PATH), Azure CLI and the Terraform version in `.terraform-version`. Install GitHub CLI if using `gha_*` helpers. Use Linux x64 CI runners; the included checksum installer targets that platform.
2. Follow [Azure bootstrap](azure/bootstrap.md) to create backend storage using local state, migrate it explicitly, and prepare OIDC identities.
3. Copy `starter-templates/azure` into a private repository, or use [azure-network-foundation](https://github.com/MikeeeGit/azure-network-foundation) for the complete network composition. Do not copy another deployment's `.git`, `.terraform`, state, plans or private variable files. Preserve `.gitignore` and `.terraform.lock.hcl`.
4. Fill root-level `delivery.azure.json`; update matching subscription aliases in `config/global.tfvars`. Keep the chosen target in `config/<region>/<environment>/<environment>.tfvars`. The sample IDs and documentation-only IPs must be replaced. The starter demonstrates uks/hub, uks/pprd, uks/prd, ukw/hub and ukw/bcdr.
5. Commit the reviewed configuration and provider lockfile to the private consumer. Review module sources and pin immutable versions/commits. Use the [configuration contract](conventions.md) when changing backend names or aliases.

## First local workload plan

Clone this framework beside the consumer. Run `az login --tenant <expected-tenant>` first, then use these commands **from the consumer root**, whose folder name must match the selected repository name:

```bash
source ../terraform-delivery-templates/scripts/azure/terraform-functions.sh
tf_setup my-private-network pprd uks
tf_init
tf_plan
# Review the displayed plan. This applies that saved binary plan:
tf_apply
```

PowerShell uses the same Python implementation:

```powershell
. ../terraform-delivery-templates/scripts/azure/terraform-functions.ps1
tf_setup my-private-network pprd uks
tf_init
tf_plan
tf_apply
```

`tf_apply` requires confirmation and rejects changed inputs, expired plans or a different target. `tf_plan` formats local files; review resulting changes. Ordinary init retains the lockfile. Provider upgrades use the explicit `tf_upgrade` command and a reviewed lockfile change. See [all local commands](azure/local-helpers.md).

For the network foundation, build networks before enabling remote-state peerings. A plan that needs a remote state cannot succeed before that state exists. Configure DNS zone links/resolver forwarding for clients that need private-endpoint names.

## GitHub Actions

The starter's `.github/workflows/validate.yml` is safe for public checks. The manual `tf-validate.yml` and `tf-apply.yml` callers are authenticated **private-only** plans/delivery; their names preserve the original helper convention.

Set `TERRAFORM_DELIVERY_SHA` to the full reviewed framework commit for `v0.2.0`, and `AZURE_PLAN_CLIENT_ID` / `AZURE_APPLY_CLIENT_ID` to your identities. Create `<environment>-<region>-plan` and `<environment>-<region>-apply` environments with exact federation subjects. Configure required reviewers, prevent self-approval/bypass, and restrict deployments to the protected branch. Keep `ENABLE_TERRAFORM_APPLY` unset/false until these controls are verified. See [the complete GitHub guide](azure/github-actions.md), including plan-feature limitations.

The starter selects hosted runners; the reusable template also supports the original trusted self-hosted model. State networking must allow the chosen runner before init. Public PR jobs always remain hosted and credential-free.

## Azure DevOps

Copy the starter's `azure-pipelines-plan.yml` / `azure-pipelines-apply.yml` into the private consumer. Configure the template repository resource, the Microsoft Terraform extension, separate WIF service connections and deployment environments. The apply example deliberately starts with `enableApply: false`; enable it only after approval and exclusive-lock checks are configured. See [the full Azure DevOps guide](azure/azure-devops.md).

Run the first real deployment against a small, budgeted sandbox and record its result separately. Repository validation and mocked plans demonstrate code behavior; they do not establish your tenant permissions, approval settings or network reachability.
