# Releases

`v0.2.0` is the reviewed Azure framework release target. Before tagging, run the [checks](testing.md), inspect the public diff for identifiers/secrets/state/plans, and review changed interfaces against [the changelog](../CHANGELOG.md).

Commit source first, then publish matching immutable tags on the intended hosts. Consumers should reference a reviewed full SHA for executable template checkouts; examples use the release tag to make the intended version readable. Keep the workflow reference and `TERRAFORM_DELIVERY_SHA` on the same release. Do not reuse or silently move a published tag.

The tested Terraform version lives in `.terraform-version`; the Linux installer also verifies a reviewed release archive SHA-256. Update both together, update workflow pins, and rerun tests. Provider lockfiles belong in deployable roots and examples. Dependabot can propose action changes; review full SHAs and version comments before merging.

Validate a new version in a private sandbox before enabling it for an existing stateful consumer. Input/schema/backend changes need explicit migration notes and a saved backup/recovery path. Never infer that a renamed repository should silently use a new state key.

GitHub is the public source; Azure DevOps mirrors/consumers are private because new public Azure projects are retired. No public release should carry corporate history, Misc experiments, credentials, real backend configuration, state or saved plan artifacts.
