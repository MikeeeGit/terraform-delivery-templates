# Testing

The tested toolchain is Terraform 1.16.3 and committed provider lockfiles. Install the pinned CLI before running:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate.py --source-root "$PWD" --directory tests/fixtures/mock-module --test-directory tests
python3 scripts/validate.py --source-root "$PWD" --directory initial-setup/azure/backend --test-directory tests
python3 scripts/validate.py --source-root "$PWD" --directory starter-templates/azure --test-directory tests
bash -n scripts/azure/terraform-functions.sh scripts/github/github-functions.sh
```

The Python suite exercises argument handling, namespace/configuration validation, backend targeting, default workspace, separate manifest receipts, changed/expired plans, source mutation during planning, untracked/ignored/symlink inputs, strict CI visibility guards and archived var-file selection. All cloud commands are mocked or omitted. Terraform fixtures use native mock providers; bootstrap checks the same backend naming contract, restricted storage defaults and invalid name combinations.

Run `actionlint` against `.github/workflows/*.yml` and the starter GitHub callers. Parse the Azure YAML with a YAML parser and check all embedded Bash blocks with `bash -n`. PowerShell files can be syntax-checked with `System.Management.Automation.Language.Parser`; wrapper parity can be tested using a fake `python3` command without authenticating. Keep third-party tooling pinned in a controlled development/runner image.

Public CI runs the Python suite and all three Terraform validation/test roots. Azure DevOps delivery YAML and GitHub deployment adapters have source/syntax/mock validation; no public CI deploys infrastructure or attempts to validate real approval/IAM configuration.

A private sandbox acceptance run must separately demonstrate actual OIDC subjects, role propagation, locked remote-state access, a reviewed saved-plan apply, stale-plan rejection, environment gates and cleanup on failure. Record the exact consumer/template/module commits, toolchain and result. Do not describe mocked or schema-only evidence as cloud deployment proof.
