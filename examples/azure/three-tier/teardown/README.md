# Disposable Azure removal

Start with the [removal run list](../../../../docs/azure/three-tier-removal.md#scripted-removal-run-list). Copy config.example.json outside Git, replace every synthetic value and set mode 0600. Workspace, operator profile and private recovery directories must be mode 0700. Recovery must be outside the consumer workspace.

The scripts support the UK South, single-subscription disposable profile, with these consumer directory names: bootstrap-state, aks-lab-network, aks-lab-firewall, aks-lab-routes, aks-lab-private-worker, aks-lab-workload-vault, aks-lab-aks, aks-lab-gateway, aks-lab-delivery-identities and aks-lab-azure-devops-connections. The component/environment allowlist and isolated resource-group names are enforced. They refuse unrelated names, subscriptions, shared directory objects and unsupported source execution.

Install the reviewed Terraform 1.16.3 binary, Azure CLI with Azure DevOps extension, and the pinned kubectl/Helm/kubelogin clients used during deployment. Cluster cleanup also needs PyYAML from this repository's hashed requirements.txt. Authenticate the retained operator in the configured isolated Azure profile. Connections removal needs the still-valid narrow bootstrap PAT; retire that credential after its endpoints/federations have been removed.

Use the consumers' actual generated provider files, inputs and lockfiles. Recreate them through the deployment helper if your local checkout lacks them; do not initialize an empty replacement state. Scripts copy reviewed source into separate recovery directories and do not reuse a consumer's cached backend. All aliases must resolve to the selected disposable subscription.

These are reference-profile removal tools, not subscription cleanup tools. Adapt and test their ownership boundaries before using different names, regions, shared resources, Argo installations or multiple subscriptions.
