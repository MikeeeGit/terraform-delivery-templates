# Contributing

Open an issue or pull request describing the concrete change and its effect on consumers. Keep examples synthetic and avoid identifiers/configuration from a real estate.

Run the README validation commands before submitting. Terraform changes need meaningful mocked tests for changed contracts and rejection of unsafe input. Run examples through backend-disabled initialization and validation. Tests must not require Azure or AWS credentials. Never run cloud operations on untrusted pull-request code.

Use Terraform formatting, typed variables with descriptions, stable map keys and descriptive outputs. Keep dependency updates reviewable and preserve exact tool/action pins. Root/example provider lockfiles record tested versions; reusable child constraints describe the supported provider family. A caller's root lockfile governs its actual provider selection.

Releases use semantic versions. Breaking API/state-layout changes require migration notes and a major release once stable; initial 0.x releases may evolve. A maintainer verifies CI, checks for accidental secrets/private data and reviews the diff before tagging. Pin consumers to a reviewed commit and upgrade through a pull request.

See SECURITY.md for disclosure and deployment boundaries.
