# Security

Do not post credentials, Terraform state, plan files, private configuration or vulnerability exploit details in a public issue.

Report a vulnerability using GitHub private vulnerability reporting if the repository offers it. Otherwise open an issue containing only a request for a private contact channel; do not include sensitive details.

Public CI validates synthetic examples and mocked providers without deployment credentials. Real deployments must run in an access-controlled repository/project with scoped workload identities, protected branches/environments, private plan storage and backend locking. Module tests do not prove cloud IAM, network security, connectivity, or compliance.

Never commit state, saved plans, backend credentials, account identifiers copied from another environment, service-principal secrets, PATs or private keys. Generated plan/state output can disclose secrets even when an input is marked sensitive.
