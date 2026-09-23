# Changelog

## Unreleased

- Describe independent target AKS clusters and use the renamed pipeline selectors.
- Add the complete Azure Argo path alongside direct delivery in the run list.
- Refuse workload removal while an Argo Application targets the app namespace;
  document retirement before the existing tested cloud teardown.


## 0.3.0

- Reconcile the September AKS application branch and document separate cluster bootstrap, selected-build promotion and per-cluster verification.
- Add shared private component callers for firewall, routes, AKS and gateway delivery.
- Connect the standalone firewall, shared Kustomize delivery and multi-cluster sample application.
- Export reviewed app targets from actual AKS/registry outputs with explicit subscription and context checks.
- Add a worked hub/spoke, dual-AKS and WAF gateway deployment sequence with explicit state ownership.
- Add private GitHub Actions and Azure DevOps network caller examples with staged hub/spoke delivery.
- Document private DNS, inspected egress, ingress prerequisites, cluster cutover and rollback boundaries.

## 0.2.0 — reviewed Azure framework

Restores the proven Azure DevOps wrapper/stages/setup flow, GitHub environment/region matrix, separate backend/workload targeting, aliases, optional variable groups/scans/firewall access, trusted self-hosted option and Bash/PowerShell helper names from AZDO-TF-Templates. The GitHub source reviewed for credential isolation was develop commit `899d72872fd374b4b9f0543bcc93651926411126`; Azure/local differences were examined before copying behavior. No original Git history, corporate Misc files or private configuration is imported.

Required sanitization replaces hardcoded IDs, corporate names, private URLs and global credential rewrites with `delivery.azure.json`, synthetic examples and job-scoped credentials. Backend convention/suffix can be preserved explicitly, and the local helpers fail closed on mismatched context rather than guessing an account or legacy container.

Reviewed behavior fixes enable state locking/timeouts; make upgrades explicit; confirm local apply/destroy/import; use saved plans on both CI platforms; bind plans to inputs, backend target, toolchain and run; reject moved source branches; use OIDC refresh; propagate optional scan flags; and track the exact GitHub dispatched run. Apply remains disabled until external approval settings are configured. Public CI uses hosted credential-free validation and mocked providers.

Adds a local-state backend bootstrap, explicit remote-state migration with retained backups, reviewed new-identity federation helper, complete private-consumer starter and onboarding guides. Terraform 1.16.3 is pinned for validation/delivery; deployable Azure examples retain the compatible >=1.9,<2 constraint and AzureRM >=4.33,<5 with lockfiles.

The original two optional Ansible templates are documented as a deferred extension outside this Azure network release. They are not silently represented as restored delivery functionality. AWS remains architecture-only; GCP is later scope. Private module credential adapters and platform/tenant provisioning remain explicit operator setup boundaries.

Retires the provisional v0.1 single-target private delivery interface and identity-only AWS/preflight examples. Stable credential-free validation paths remain compatible, with optional ordered var-file inputs added for mocked tests.

## 0.1.0

Provisional public scaffold. Superseded by the source-reviewed scope and interfaces above.
