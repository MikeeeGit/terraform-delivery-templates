# Release policy

Use semantic versions with migration notes for changed workflow inputs, script
flags, manifest schemas, permissions and supported runtime versions. During early
development use prereleases and state which adapters have only local validation.

Consumers pin full commit SHAs and record release names in comments. The reusable
workflow reference and `template-ref` must match. Azure repository resources also
pin a full commit. Movable branches/tags are labels, not the immutable trust anchor.

Actions use verified official upstream SHAs with matching version comments.
Dependabot proposes reviewed action/provider changes; review the example workflow
pins too because they live outside `.github/workflows`. Terraform upgrades require
changing `.terraform-version`, the pinned release checksum and both CI platforms.
Review lockfile changes and rerun supported fixtures before publishing.

Add release badges or deployment claims only when the referenced hosted evidence
exists. Keep unqualified cloud adapters explicitly marked as such.
