# AWS architecture roadmap

AWS delivery is intentionally not implemented in this release. The existing cloud-neutral hosted validation entrypoints can validate and mock-test AWS Terraform without credentials. No AWS login, backend bootstrap, deployment workflow or credentials are shipped.

A future adapter should retain the same reviewed boundaries: private trusted consumers, explicit account/region and state configuration, OIDC trust restricted to the actual repository/environment, least-privilege plan/apply roles, locked saved plans with separate integrity receipts, protected approvals, exact-run artifact retrieval and cleanup. Azure-specific backend aliases, service connections and firewall operations should remain in the Azure adapter.

The expected AWS bootstrap would establish a private, encrypted, versioned state bucket and supported S3 state locking, then OIDC federation and scoped deployment roles. Account organization, networking and recovery decisions need separate design and tests before this can be called supported. GCP remains later scope.
