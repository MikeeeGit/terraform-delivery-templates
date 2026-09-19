# VM and SQL workloads

[Azure VM Foundation](https://github.com/MikeeeGit/azure-vm-foundation) is a VM consumer of these templates, alongside the AKS foundation. It provides private Linux/Windows VMs, managed data disks, a safe inventory adapter and staged Ansible configuration for SQL Server Always On.

## Delivery order

1. Bootstrap private state, OIDC identities and protected deployment environments with the existing bootstrap runbook.
2. Deploy the network foundation and export the explicit subnet ID/CIDR maps. Configure AD DNS, NSGs, routing and the private management path.
3. Configure the VM consumer's `delivery.azure.json`, `config/global.tfvars` and `config/uks/dev/dev.tfvars`. Its delivery contract checks the tenant, subscription aliases, environment and region against the manifest.
4. Run the shared credential-free validation. The VM repository pins both reusable workflow and implementation to reviewed commit `472c0c5bebe7f07aca8c51c7fabf0a47280a0b25`; upgrade these together after review.
5. In a private consumer, use protected plan/apply with OIDC. Windows credentials are resolved by Terraform from a version-pinned existing Key Vault secret reference. The strict delivery helper rejects inherited `TF_VAR_*` values; do not try to inject the password that way or commit its value. Keep state/plans private and grant only the necessary secret-read/network access.
6. Complete the reviewed Windows/domain/SQL management bootstrap, export the `ansible_hosts` output and generate inventory with the VM repository's adapter.
7. Run the OS/SQL baseline, then the WSFC/availability-group playbook from a private connected controller. A separate opt-in playbook seeds a synthetic demonstration database.

The Terraform stage never invokes Ansible through a resource provisioner. Cloud-resource changes and guest/database changes have separate evidence and maintenance boundaries. No automatic forced failover, cluster removal or production restore is part of routine convergence.

## Examples and evidence

- [VM architecture](https://github.com/MikeeeGit/azure-vm-foundation/blob/main/docs/ARCHITECTURE.md)
- [Complete handoff and credential flow](https://github.com/MikeeeGit/azure-vm-foundation/blob/main/docs/DELIVERY.md)
- [Inactive private deployment caller](https://github.com/MikeeeGit/azure-vm-foundation/blob/main/examples/delivery/private-deploy.yml)
- [SQL prerequisites and live-lab acceptance](https://github.com/MikeeeGit/azure-vm-foundation/blob/main/docs/SQL-ALWAYS-ON.md)
- [Hosted contract/syntax CI](https://github.com/MikeeeGit/azure-vm-foundation/actions/workflows/ci.yml)

The reference is two synchronous SQL replicas in different subnets/zones within one region, with an independent file-share witness. It does not implement a cross-region DR policy. Mocked Terraform, inventory tests, PowerShell behavior checks and Ansible syntax checks are offline evidence; real Azure, AD, SQL seeding, listener connectivity and failover require the documented disposable lab.
