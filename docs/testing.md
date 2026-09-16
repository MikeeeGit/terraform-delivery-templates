# Testing and qualification

Use Linux amd64, Python 3.10+ and the version selected by `.terraform-version`:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/install_terraform.py --install-dir .tools/bin
PATH="$PWD/.tools/bin:$PATH" python3 scripts/validate.py \
  --source-root "$PWD" --directory tests/fixtures/mock-module --test-directory tests
actionlint .github/workflows/*.yml
```

Python tests cover traversal/symlinks, literal metacharacters, backend isolation,
lockfile protection, version/failure handling and installer checksum integrity.
Saved-plan tests cover changed commit/state/run/lockfile, modified plan+manifest,
expiry, wrong identity/backend, untracked inputs, default workspace, exit code 2
and applying only the verified binary. Terraform execution is mocked in deployment
tests; no Azure requests or resource operations occur.

The synthetic fixture's two native Terraform tests use a mocked Random provider
for configured input/output propagation and invalid-input rejection. Mock apply
exercises the test engine without cloud resources. Provider installation still
downloads a public package. Consumer module tests provide infrastructure-specific
assertions; this fixture tests the template's ability to run mocked tests.

Supported runner contract: GitHub.com hosted and Microsoft-hosted `ubuntu-24.04`.
Pinned actions use Node24 and require current hosted runners. GitHub Enterprise
Server, Windows, macOS and self-hosted runners are not qualified. Installer support
is Linux amd64. CLI upgrades change `.terraform-version`, the reviewed installer
checksum and workflow setup pins together.

Before stable release, execute reusable validation from a separate repository on
both platforms, verify fork isolation, run identity preflights against a disposable
sandbox, and demonstrate blocked approval plus saved-plan apply and rejection
cases. Check actual private-reviewer availability and least-privilege roles.
Mocked tests do not establish cloud integration success.
