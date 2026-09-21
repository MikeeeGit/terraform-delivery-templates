# Rebuilding the three-tier Azure deployment

The Azure deployment consists of infrastructure, cluster platform services and application delivery. Identities, trust and permissions cross all three tiers. This guide connects the public component repositories into private consumers with per-environment managed identities and two independent AKS slots. The existing direct and Argo delivery methods and the disposable Kubernetes tests remain available.

| Tier | Repository and executable entry points | Owns |
| --- | --- | --- |
| 1. Infrastructure | Terraform Delivery Templates, Azure Network Foundation, Azure Firewall, Azure AKS Foundation and Azure Application Gateway | State, network, clusters, control-plane/kubelet identities, CI identities and federation, workload identities and both OIDC issuer bindings, Azure role assignments |
| 2. Platform | AKS Delivery Templates: identity discovery, namespace bootstrap and platform services workflows/stages | Namespaces, application Kubernetes permissions, workload ServiceAccount binding, pinned controllers/CRDs, Envoy Gateway and common services |
| 3. Application | AKS Platform Demo: Azure workload build/deploy and promotion callers | Build/scan receipt, immutable image, application resources, CSI secret mounting, rollout, HTTPS and Azure workload qualification |

The workload identity is used by Pods to access Key Vault. The application deployment identity authenticates CI to the Kubernetes API. They are separate identities even when their names refer to the same application/environment. The platform identity has a separate responsibility for controllers and cluster resources. A kubelet identity pulls images; annotating an application ServiceAccount does not grant registry pull access to the nodes.

For the full deployment, traffic switch and removal sequence, follow the [worked Azure procedure](three-tier-worked-example.md) and [removal procedure](three-tier-removal.md). The [disposable kind worked example](https://github.com/MikeeeGit/aks-platform-demo/blob/main/docs/WORKED-EXAMPLE.md) exercises the shared Kubernetes engines with a local infrastructure adapter.

## 1. Create the private consumers and configuration

Use the [Azure sandbox deployment](sandbox-deployment.md) for hub/spoke networking, firewall/UDR/DNS, quota, private workers, certificates and Application Gateway WAF. Keep those prerequisites and traffic cutover gates. This guide adds the identity lifecycle and generated application/platform bindings.

Use three private consumer repositories, or equivalent separated roots in one private project:

```text
platform-infrastructure/
  bootstrap/state/
  bootstrap/identities/              # delivery-identities root, one state per environment
  bootstrap/azure-devops/            # optional service connections root
  network/ firewall/ aks/ gateway/   # maintained Terraform component roots
platform-services/
  platform.services.json             # copy examples/platform-envoy contents
  manifests/ values/
  pipelines/                        # platform and discovery callers
platform-application/
  deploy/                           # complete sample app deployment sources
  delivery.azure-workload.apps.json
  azure.workload.json
  bootstrap.native.apps.json
  .github/workflows/ or pipelines/   # full app callers
```

Run the commands below from a workspace containing the three private consumer directories, the checked-out public libraries `terraform-delivery-templates/` and `aks-delivery-templates/`, and a private `evidence/` directory (`mkdir -m 700 evidence`). Copy the complete examples before overlaying generated files. Pin every reusable workflow/template to the same reviewed full commit for that library. Keep real input values, generated configuration and evidence private. Public CI never receives cloud credentials. PPRD and PRD use separate states and identity grants, even if a disposable trial deliberately shares one Azure subscription.

## 2. Terraform: bootstrap CI trust, then infrastructure and workload access

Create the state backend with the [existing bootstrap](bootstrap.md). Create separate plan, apply, build, platform and application UAMIs using [delivery identities](../../initial-setup/azure/delivery-identities/README.md). Its example contains explicit state, resource and role-administration scopes. Bootstrap authority is required once; routine pipelines then use the created federation. Retain protected state so reruns update and remove owned identities/grants rather than create one-off duplicates.

For Azure DevOps, apply [federated service connections](../../initial-setup/azure/azure-devops-connections/README.md), then bind their names to the private callers. Authorise each intended pipeline ID explicitly. For GitHub, use the exact subject format for the private repository and protect the environments named in the federation. Configure the corresponding client ID repository variables used by the callers. Federation never substitutes for protected source/approval settings.

Apply the selected network/firewall/route prerequisites. Provide the application vault and its private network path; the [workload vault example](../../examples/azure/three-tier/workload-vault/README.md) creates an RBAC vault and private endpoint against the existing network/DNS. Certificate material and application secret values are populated through the authorised secret-management process, outside Terraform state. Seed a nonempty `platform-demo-qualification` secret for the sample check; never publish its value. The backend certificate must satisfy the existing HTTPS guide.

Keep the [AKS workload identity map](https://github.com/MikeeeGit/azure-aks-foundation/tree/main/examples/ingress-tls) in each environment's AKS inputs. It declares the application ServiceAccount, both cluster slots and exact vault/resource grants. Add other Azure access by adding scoped roles to that workload identity's map. Do not grant all workloads the node or platform identity.

Export the applied CI identity root as a wrapped output snapshot in a private evidence directory:

```bash
terraform -chdir=platform-infrastructure/bootstrap/identities output -json > evidence/identities.json
python3 terraform-delivery-templates/scripts/azure/three_tier_handoff.py ci \
  --identities evidence/identities.json \
  --tenant-id "$TENANT_ID" --environment pprd --region uks \
  --platform-key platform --application-key application \
  --namespace platform-demo --slots aks01 aks02 \
  --output evidence/aks-delivery-principals.tfvars.json
```

The output is a typed `delivery_principals` input for Azure AKS Foundation. Merge that value into the target's private input file before using the normal component helper; the helper only reads its documented global and environment files. Do not assume it automatically discovers an extra tfvars file.

For the native permission profile, explicitly set `kubernetes_authorization_mode = "kubernetes_rbac"` and the existing authorised Entra administrator group IDs. This retains Entra authentication and disabled local accounts. The default Azure RBAC profile is preserved. Review [AKS CI identity and authorization](https://github.com/MikeeeGit/azure-aks-foundation/blob/main/docs/ci-identity-and-authorization.md) before choosing the mode; switching a live cluster needs a separate access migration.

Apply AKS and its permissions. Terraform owns each CI principal's Cluster User role on the declared slots, plus the existing workload UAMI, exact per-slot OIDC federations and Azure resource roles. Cluster User permits obtaining user kubeconfig; Kubernetes permissions still belong to tier 2.

## 3. Generate the platform/application identity bindings

Export the applied AKS and hub registry roots using wrapped `terraform output -json` snapshots. The handoff requires non-sensitive outputs, including actual workload role-assignment and federation metadata.

```bash
python3 terraform-delivery-templates/scripts/azure/three_tier_handoff.py application \
  --template platform-application/delivery.azure-workload.apps.json \
  --platform-template platform-services/platform.services.json \
  --aks-outputs evidence/aks.json --registry-outputs evidence/hub.json \
  --delivery-config platform-infrastructure/aks/delivery.azure.json \
  --environment pprd --region uks \
  --workload-identity platform-demo --service-account-key app \
  --vault-id "$APPLICATION_VAULT_ID" \
  --certificate-name platform-demo-ingress --secret-name platform-demo-qualification \
  --output-directory evidence/generated-pprd
```

Review and copy the generated `application/` and `platform/` file trees over the corresponding private consumer roots. JSON written to the named YAML patch files is valid YAML and is accepted by Kustomize. The generated pack updates both AKS targets, registry details, both platform ServiceAccount declarations, application identity/TLS patches, app CSI provider and the expected Azure qualification contract.

This eliminates manual copying of client IDs between the tiers. It rejects a wrong tenant/environment, missing slot, different federation subject/issuer, mismatched vault grant or incompatible sample profile. It never retrieves secrets or overwrites an existing output directory. Hostnames, Envoy frontend IPs/subnets/source ranges and approved controller pins remain your reviewed platform/network configuration; the identity generator does not invent them.

## 4. Platform: discover CI identity, bootstrap namespace access, install services

Use [native Azure authorization](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/native-azure-authorization.md). Run the identity-discovery workflow/stage as the actual application CI identity on both slots. It verifies the client ID, obtains user credentials and records the Kubernetes username returned by the API. Match these private observations to Terraform's `delivery_authorization` output. Populate the native bootstrap map from those observations; do not guess Kubernetes usernames from UUIDs.

Run the native namespace bootstrap as an already authorised Entra operator. It creates the application Role and a consolidated RoleBinding for the declared deployers, with HTTPRoute/CSI writes and Gateway reads. Native mode creates no imperative Azure role grants. Removing a subject from the managed binding and reapplying removes its access through that binding; other grants remain additive.

Install the maintained platform profile using the existing prepare/apply lifecycle and generated platform configuration. This installs pinned Gateway API/Envoy CRDs, controllers, both slot-specific proxies/Gateways and the workload ServiceAccount. The workload's first CSI mount supplies the TLS Secret, so full Gateway/HTTPS acceptance follows application rollout.

**Initial platform authority:** follow the [platform CI bootstrap](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/platform-ci-bootstrap.md). An existing Entra administrator explicitly opts in to bind only the Terraform-declared platform identity on the selected slots, after matching real identity-discovery records. The guarded command uses user credentials and supports explicit subject revocation. The platform pipeline can then run the maintained lifecycle; build/application identities retain their separate scopes. Cluster User alone does not provide Kubernetes write permissions. The initial operator/group and private connectivity remain prerequisites.

The existing Azure RBAC path remains available. Its custom-resource ABAC recipe is an explicit preview option and must not be silently replaced with unrestricted app permissions. Do not run two grant owners against the same resources.

## 5. Application: build once, deploy both slots, prove Azure access

Use the full [Azure workload callers](https://github.com/MikeeeGit/aks-platform-demo/blob/main/docs/AZURE-WORKLOAD.md) in the private application consumer:

- `examples/delivery/github-azure-workload-build-deploy.yml` or `azure-azure-workload-build-deploy.yml` for build, scan, immutable receipt and selected-slot deployment.
- The matching `*-azure-workload-promote.yml` caller to promote a selected existing release without rebuilding.

The build identity publishes to ACR; the application identity deploys through the scoped native binding. The per-environment workload UAMI accesses Key Vault through the exact ServiceAccount on either cluster's OIDC issuer. Application secret values are mounted by CSI and are not synchronised to a Kubernetes Secret. Backend TLS retains its separate TLS Secret synchronisation required by the Gateway.

The Azure profile adds an opt-in readiness requirement for a nonempty mounted application secret. Its qualifier checks the actual cluster/identity binding, selected deployment revision, mounting Pods, CSI status and readiness without recording secret contents. Run on both slots. A valid manifest or successful kind deployment cannot satisfy this Azure gate.

For Argo CD, retain the existing reviewed Git promotion/sync path using the same rendered Azure workload overlay. Argo owns application reconciliation; bootstrap and platform installation remain independent. Run the same Azure qualifier after sync and readiness. Do not imperatively deploy the app into a namespace owned by Argo. The workload MI/CSI path is identical under either delivery owner.

## 6. Rebuild and operation

For a fresh authorised target: apply the reviewed Terraform roots, perform initial access bootstrap, apply platform services, then deploy the selected application release. Adding/replacing a cluster changes its OIDC issuer: Terraform recreates the corresponding federation, then generate fresh handoffs and bootstrap that cluster before deploying to it. Reusing a ServiceAccount name does not make the old issuer valid.

Changes to identities, role scopes and federation are Terraform changes. Application namespace permissions are platform-bootstrap changes. Image/digest and app configuration changes are application releases. Cutover and traffic rollback remain separately reviewed Application Gateway changes, as described in the sandbox guide. Keep backend state, source pins and private observations with the deployment record.

## What is validated

Offline Terraform tests validate schema, declared identities/roles, mode selection and federation/output contracts. Python tests exercise target/role/federation mismatches and generated configuration. Real Kustomize rendering checks the produced application manifests. Application tests check that missing or empty required secret mounts fail readiness without exposing content. Shared tests exercise allowed/denied native RBAC operations and identity-discovery failures. Hosted kind tests remain Kubernetes application/controller evidence.

Only an actual Azure run can qualify service-connection login, Entra permissions, private DNS/routing, ACR pull, managed CSI/Key Vault access and WAF traffic. Record those results per environment and slot. The publication of these templates is not evidence that an Azure deployment has passed.
