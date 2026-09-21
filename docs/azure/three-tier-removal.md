# Remove the three-tier Azure trial safely

Use this procedure after the [worked deployment](three-tier-worked-example.md), including a failed or partially completed trial. Remove Kubernetes-managed ingress resources while their controllers, nodes, identities, DNS and network still exist. Then remove dependent Terraform states in reverse dependency order. Deleting a state file is not cleanup.

**Qualification status:** this removal procedure needs an actual retained Azure run before it can be described as qualified. Record every completed, failed and intentionally retained item. Use the exact subscription, resource IDs, state keys and source revisions from the deployment inventory.

## Scripted removal run list

The single entry point is [teardown_lab.py](../../scripts/azure/teardown_lab.py). It prints the dependency order when called with **list**, and exposes separately reviewed phases. Start from the [private configuration example](../../examples/azure/three-tier/teardown/README.md). This script targets the isolated UK South lab profile and its exact component names; it is not a general subscription deletion tool.

Set the following paths to the reviewed library checkout and private configuration/recovery directories:

```bash
TOOL="$TEMPLATES/scripts/azure/teardown_lab.py"
CONFIG="$PRIVATE/teardown.json"
RECOVERY="$PRIVATE/removal"
python3 "$TOOL" list
```

Use a new output directory for each attempt. Keep recovery outside Git and outside the consumer workspace. The configured operator profile, Terraform binary and bootstrap PAT must be the same retained credentials/tools used for this lab.

For **every component row** below, inventory, plan, review and apply the exact saved plan:

```bash
python3 "$TOOL" inventory --config "$CONFIG" \
  --component "$COMPONENT" --environment "$ENVIRONMENT" > "$INVENTORY"
SOURCE_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_sha256"])' "$INVENTORY")"
python3 "$TOOL" plan --config "$CONFIG" \
  --component "$COMPONENT" --environment "$ENVIRONMENT" \
  --expected-source-sha256 "$SOURCE_SHA" --output "$ATTEMPT"
# Review $ATTEMPT/destroy-plan.txt and receipt.json before the next command.
PLAN_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["plan_sha256"])' "$ATTEMPT/receipt.json")"
python3 "$TOOL" apply --config "$CONFIG" \
  --component "$COMPONENT" --environment "$ENVIRONMENT" \
  --expected-plan-sha256 "$PLAN_SHA" --output "$ATTEMPT"
```

The scripts reject wrong subscriptions/backends, foreign resource groups, shared directory objects, changed source/state and create/update/replace actions. Each apply writes its result and a final private state snapshot. A failed action stops the sequence; retain its output and re-plan after resolving the actual cause.

| Order | Action to run | Target / completion gate |
| --- | --- | --- |
| 1 | **freeze** | Pass every exact private lab pipeline ID with repeated --pipeline-id flags and --execute. No lab run may remain active/queued. Required policies are retained. |
| 2 | Component removal | **aks-lab-gateway / pprd**; withdraw WAF traffic before removing its backends. |
| 3 | **services** | Run once per slot with that slot's verified --bundle directory, a fresh --output and --execute. Add an explicit loopback --proxy-url only if using the operator SSH tunnel. |
| 4 | Component removal | **aks-lab-azure-devops-connections / hub, prd, pprd**. Keep the bootstrap PAT until these endpoints and federations are removed; revoke it afterward. |
| 5 | Component removal | **aks-lab-delivery-identities / prd, pprd, hub**. The retained operator owns all remaining cleanup. |
| 6 | Component removal | **aks-lab-aks / pprd**, then **aks-lab-workload-vault / pprd**. Record the protected vault's soft-delete retention. |
| 7 | Component removal | **aks-lab-routes / hub** while the Firewall data source and VNets still exist. |
| 8 | **unregister-agent** | Pass the exact --queue-id and --agent-id with --execute. Prove operator state access without the worker, then close its management tunnels. |
| 9 | Component removal | **aks-lab-private-worker / hub**, then **aks-lab-firewall / hub**. |
| 10 | **detach-plan**, then **apply** | **aks-lab-network / hub, pprd, prd**. Use the same inventory/hash workflow, substituting detach-plan for plan. Only peering deletions are accepted. |
| 11 | Component removal | **aks-lab-network / prd, pprd, hub**, in that order. The removal planner explicitly disables peering data reads. |
| 12 | **backend-plan**, then **backend-apply** | Migrate the existing bootstrap state to protected local recovery, inspect the saved plan, then retire all three backend accounts. |
| 13 | **verify** | Supply both pre-removal cluster inventory.json paths with repeated --cluster-inventory flags. Every exact owned RG and actual managed node RG must be absent. |

Examples for the non-component phases:

```bash
python3 "$TOOL" services --config "$CONFIG" --bundle "$AKS01_BUNDLE" \
  --output "$RECOVERY/services-aks01" --execute
python3 "$TOOL" services --config "$CONFIG" --bundle "$AKS02_BUNDLE" \
  --output "$RECOVERY/services-aks02" --execute
python3 "$TOOL" backend-plan --config "$CONFIG" --output "$RECOVERY/backend"
# Review its migrated state identity, destroy-plan.txt and receipt.json.
python3 "$TOOL" backend-apply --config "$CONFIG" --output "$RECOVERY/backend" \
  --expected-plan-sha256 "$REVIEWED_BACKEND_PLAN_SHA"
python3 "$TOOL" verify --config "$CONFIG" \
  --cluster-inventory "$RECOVERY/services-aks01/inventory.json" \
  --cluster-inventory "$RECOVERY/services-aks02/inventory.json" \
  --output "$RECOVERY/final-inventory"
```

The services phase deletes the exact verified app bundle, deletes its Gateway, waits for owned Services and Azure frontends to disappear, then uninstalls Envoy. It does not force finalizers. The backend phase independently rereads every component state and requires zero managed resources before migration. A backup copy alone is not a backend migration.

Also verify the bootstrap PAT revocation and protected deleted-vault retention through their recorded owners. Quota, provider registration, the existing administrator group, private CI history and off-cloud recovery evidence are intentionally retained. They are not active lab compute/network resources. For Argo-installed Azure consumers, complete the reconciliation handover below before the services phase; the direct Azure profile does not install Argo.

## 1. Freeze changes and record ownership

Stop new infrastructure/platform/app deployments and wait for running operations to finish. Retain access for the operator and the Terraform identity that will perform cleanup. Keep the private worker, backend and recovery copies reachable until the last dependent operation completes.

Record:

- Every component root/backend key and its owned resource groups. Match the applied `aks-lab` naming qualifier and independent backend storage prefix; never substitute unqualified PPRD groups.
- Both AKS resource IDs and managed node resource groups, including the disposable shared-pool profile if selected.
- WAF, private/public frontend IPs, Envoy Services, certificate/vault dependencies and public DNS records.
- App release receipts, platform receipts, Argo registrations/credentials if present, and any manually created worker/probes.
- Shared resources and data intentionally retained, with owner and expiry.

Inspect planned destruction. A trial namespace, name prefix or tag alone is not sufficient authority to delete an entire existing resource group. Do not use subscription-wide deletion, `az group delete` or `terraform state rm` as shortcuts around ownership or dependency failures. Respect resource locks; only the lock owner should approve their removal.

## 2. Withdraw traffic, then detach application reconciliation

Withdraw test public DNS/client traffic or redirect it to the explicitly retained healthy target. Remove the disposable WAF through its reviewed gateway state, or remove only the owned trial listener/backend configuration when a gateway is shared. Wait for the actual gateway operation and any required drain period; preserve certificates until the gateway no longer uses them.

Freeze direct app pipelines on both slots. For Argo, follow [application ownership handover](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/argocd-operations.md#switching-between-direct-and-argo-delivery): disable any automatic reconciliation, terminate outstanding operations through the approved UI/CLI, and confirm no ApplicationSet or parent Application will recreate the app. The maintained sample uses manual sync, but inspect the actual configuration.

Inspect the selected Application's finalizers and operation state before deletion:

```bash
kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$AKS_CONTEXT" \
  --namespace argocd get application "$ARGO_APPLICATION" \
  -o jsonpath='{.metadata.finalizers}{"\n"}{.status.operationState.phase}{"\n"}'
```

The sample Application has no deletion finalizer. After verifying that it still has none, no operation is running and recreation is disabled, remove that Application only; confirm application workloads remain until their explicit removal below. If finalizers exist, review their actual cascade scope through the Argo removal procedure first. Kubernetes `--cascade=orphan` alone does not neutralise an Argo finalizer. Do not remove finalizers blindly or delete the entire Argo namespace first.

Keep Argo controllers alive while any intentionally cascading app deletion is outstanding. Retain or revoke repository credentials/cluster registrations only after their cleanup dependency is finished. A namespace/cluster shared with another app needs its own retained-resource decision.

## 3. Remove app resources, then cloud ingress while controllers remain

Log in as the authorised platform/operator identity using Entra **user** credentials. The ordinary application Role deliberately lacks deletion privileges. Select one cluster at a time and verify its subscription, API endpoint and context. Do not use `--admin` or Run Command.

Record owned resources and cloud endpoints before changing them:

```bash
kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$AKS_CONTEXT" \
  --namespace platform-demo get deployments,services,httproutes,gateways,envoyproxies
kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$AKS_CONTEXT" \
  --all-namespaces get services -o wide
az aks show --subscription "$WORKLOAD_SUBSCRIPTION" \
  --resource-group "$AKS_RESOURCE_GROUP" --name "$AKS_NAME" \
  --query '{id:id,nodeResourceGroup:nodeResourceGroup}' --output json
```

Use the retained reviewed application bundle to remove its exact resources only after traffic is withdrawn and reconciliation detached:

```bash
kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$AKS_CONTEXT" \
  delete --filename "$APP_BUNDLE/manifest.yaml" \
  --ignore-not-found=true --wait=true --timeout=300s
```

Inspect for app-owned leftovers from earlier releases/profiles; non-pruning delivery may have left resources absent from the latest bundle. Remove those only after matching them to the inventory. Preserve shared namespace/platform objects until their own step.

For the maintained Envoy profile, delete the owned Gateway **before uninstalling its controller**:

```bash
kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$AKS_CONTEXT" \
  --namespace platform-demo delete gateway platform-demo-private \
  --ignore-not-found=true --wait=true --timeout=300s
```

Keep Envoy Gateway and Azure's cloud controllers running. Verify that the Gateway's generated Deployments/Services are removed, the corresponding LoadBalancer Services finish deletion, and the recorded Azure frontend IP/rule dependencies are released. AKS may retain a shared load balancer for other services/outbound traffic; do not delete an entire shared load balancer by name.

Use `kubectl wait --for=delete service/<observed-owned-service> --namespace platform-demo --timeout=300s` with the same explicit kubeconfig/context for each recorded Envoy Service. Then verify Azure state for the recorded load-balancer/frontend resources. A missing Gateway object alone does not prove cloud cleanup.

If a Service is stuck Terminating, inspect its events/finalizer, cloud-controller errors, role assignments, subnet permissions and Azure operation state. Restore missing access/controller/network dependencies and let normal reconciliation complete. Do not force-remove service finalizers or tear down the network to bypass the failure.

Once the proxy Services and cloud dependencies are gone, remove the owned `ClientTrafficPolicy/application-gateway-client-ip` and `EnvoyProxy/private-proxy`, then uninstall the exact controller release:

```bash
helm --kubeconfig "$KUBECONFIG_FILE" --kube-context "$AKS_CONTEXT" \
  uninstall envoy-gateway --namespace envoy-gateway-system --wait --timeout 10m
```

For an already absent release, confirm that state with `helm list` and continue the inventory rather than hiding arbitrary uninstall failures. Inspect any release hooks or cluster-scoped resources. The separately applied CRDs and GatewayClass are not necessarily removed by Helm. On a disposable cluster that is about to be destroyed, record their remaining ownership; on a retained cluster, delete only after confirming no other consumers or custom resources depend on them. Never bulk-delete Gateway API CRDs from a shared cluster.

If Argo was installed solely for this trial, remove its owned installation only after all applications and cleanup operations have completed. If retained, remove only the trial's owned Project/registration/credentials and grants. Remove the app namespace only after reviewing any remaining SecretProviderClass, TLS Secret, ServiceAccount and binding ownership.

Repeat for the second slot.

**Gate:** no trial ingress LoadBalancer Service is pending deletion; its cloud frontend dependencies are released; owned workloads/controllers are removed or explicitly retained. The AKS nodes, Azure identities and network have remained available throughout.

## 4. Revoke bootstrap access while the cluster exists

For a cluster being retained, clear native application subjects by committing explicit empty `deploy_principal_object_ids` and `deploy_kubernetes_usernames` values, then reapply the native bootstrap through the authorised operator. Removing the target from config does not revoke its binding.

For optional platform CI access, set that target's `platform_principal_keys: []` and rerun the same [platform bootstrap command](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/platform-ci-bootstrap.md). Keep `--allow-platform-admin` as the explicit operation opt-in; the generated binding now has no subjects. Verify the actual platform identity receives Forbidden for previously allowed cluster writes. Other independent grants remain additive.

If the clusters are being destroyed immediately, removing their objects also removes in-cluster bindings, but retain a record of the decision. Do not revoke the operator or Terraform destroy identity prematurely. Azure Cluster User grants and workload MI/FIC/resource permissions belong to the AKS Terraform state and are removed there.

## 5. Destroy dependent Terraform roots in order

Use the deployment's exact private roots and backend keys. Preserve routes, DNS, firewall and private workers until every dependent cluster/vault operation completes.

| Order after Kubernetes cleanup | Root/action | Stop condition |
| --- | --- | --- |
| 1 | Finish owned gateway removal if not already done | No listener/backend/certificate dependencies on the trial |
| 2 | Transfer remaining Terraform cleanup to the retained bootstrap operator | All pipeline jobs stopped; exact backends and operator access verified |
| 3 | Destroy optional Azure DevOps connections for every deployed environment | Pipeline authorizations, federations and endpoints removed while their managed identities exist; revoke the bootstrap PAT afterward |
| 4 | Destroy delivery-identity roots | Scoped role assignments removed while their target scopes exist; operator authority remains independent |
| 5 | Destroy `aks` PPRD state | Both clusters and their owned workload/control-plane identities, federations and roles removed; managed node resource groups inventoried |
| 6 | Destroy disposable `workload-vault` state, or retain explicitly | Private endpoint/DNS-group released; protected soft-deleted vault recorded |
| 7 | Destroy `routes` state while its Firewall data source exists | No surviving AKS client uses its tables; associations removed by the dependency graph |
| 8 | Unregister the worker, close management tunnels and destroy the worker root | Retained operator has independently proved state access without the worker or its Blob private endpoints |
| 9 | Destroy `firewall` | No surviving client depends on its DNS/egress; VNets remain available |
| 10 | Disable/reapply every network peering side while all states still exist | All four peerings removed without missing-state lookups |
| 11 | Destroy PRD/PPRD network states, then hub | Private endpoints, nodes, workers and gateway NICs gone; isolated ACR and hub DNS ownership reconciled |
| 12 | Retain or separately retire backend bootstrap | Every other cleanup and recovery requirement completed; migrate self-hosted bootstrap state before deleting its storage |


Remove any external certificate/DNS/diagnostic resources through their actual owners. Shared frontend vaults, subscriptions and Entra groups are not implicitly owned by this trial. If identity state contains grants to a hub resource about to disappear, review that state's grant removal while the scope exists, keeping essential cleanup authority until the appropriate step. Keep all related state snapshots consistent.

For a component root, establish the exact helper context and verify backend first:

```bash
cd "$WORKSPACE/aks"
source "$WORKSPACE/terraform-delivery-templates/scripts/azure/terraform-functions.sh"
tf_setup aks pprd uks
tf_env
tf_init
python3 "$WORKSPACE/terraform-delivery-templates/scripts/azure/terraform.py" verify-backend
```

Review a destroy plan with the same authenticated subscription and exact input files:

```bash
terraform plan -destroy \
  -var-file=config/global.tfvars \
  -var-file=config/uks/pprd/pprd.tfvars \
  -out="$WORKSPACE/evidence/aks-destroy.tfplan"
terraform show "$WORKSPACE/evidence/aks-destroy.tfplan"
```

Ensure the direct Terraform process uses the same intended identity/subscription and no stray `TF_VAR_*` or `TF_CLI_ARGS*` overrides. The framework strips those overrides for its own calls; an unrelated raw Terraform invocation does not.

After review, either apply that exact saved destroy plan with `terraform apply "$WORKSPACE/evidence/aks-destroy.tfplan"` under the same reviewed context, or use the maintained interactive `tf_destroy` helper. The helper runs a **fresh** destroy operation, not that saved plan; do not describe it as applying the saved artifact. Re-review after any source/input/state change. No destroy command is a pipeline-style permission to remove arbitrary resource groups.

For standalone identities/connections/vault roots use their initialised private backend and corresponding reviewed variable file. Resume an interrupted destroy from the same state; never delete the state or remove managed resources from it merely to obtain a green run.

## 6. Respect Key Vault retention and preserve backend recovery

The workload vault keeps purge protection enabled. The maintained provider explicitly uses:

```hcl
features {
  key_vault {
    purge_soft_delete_on_destroy = false
  }
}
```

This requests soft deletion during Terraform removal instead of a permanent purge. It does not disable vault protection. AzureRM otherwise defaults that provider feature to true; see the [pinned provider feature reference](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.81.0/website/docs/guides/features-block.html.markdown).

Record the deleted vault name, location, deletion/recovery status and retention expiry without exporting its contents. The default example retains 90 days; a reviewed 7–90 day retention must be chosen before creation. A protected deleted vault cannot be purged early or have its name reused by another new vault. Recover the original with its state/ownership reviewed, choose a fresh name for a new trial, or wait for retention. Do not change protection, discard state or retry purge as a workaround. See [Microsoft recovery and purge-protection rules](https://learn.microsoft.com/en-us/azure/key-vault/general/key-vault-recovery).

Keep the protected state backend until cleanup is independently verified. It contains its own bootstrap state: deleting it as an ordinary workload destroys recovery access. Retain the backend only when the deployment owner has chosen that retention. For a complete disposable-lab teardown, migrate the bootstrap state from its AzureRM backend to protected local or independently retained recovery storage **before** deleting the accounts it manages. A backup export alone does not change the active backend. Verify the migrated lineage, resource identities and expected serial change; then create and apply a fresh backend deletion plan as the retained operator. Never publish state backups or attach them to public CI.

## 7. Verify completion and resume failures

Check each exact owned resource group and both recorded AKS node resource groups; keep subscription explicit:

```bash
az resource list --subscription "$WORKLOAD_SUBSCRIPTION" \
  --resource-group "$OWNED_RESOURCE_GROUP" \
  --query '[].{id:id,type:type,name:name}' --output table
```

A missing group may be the expected result; confirm against the inventory rather than interpreting any command error as successful removal. Inventory residual disks, public IPs, load balancers, NICs, endpoints, registry, firewall, gateway, diagnostics, workers, CI connections/identities and protected deleted vaults. Cross-check actual Azure resources with final state, not only tags. Costs can lag; record retained billable resources explicitly.

| Evidence | Required outcome |
| --- | --- |
| Application ownership | Direct deployments frozen; Argo operations stopped/detached; no controller recreates deleted app |
| Kubernetes ingress | Gateway/proxy/controller ordering recorded; owned Services and cloud frontend dependencies gone |
| AKS destruction | Both clusters removed; managed node groups and owned identities/grants checked |
| Network removal | Routes/peerings removed in dependency order; no shared network deleted |
| State/retention | Final state preserved; deleted-vault retention and backend retention/retirement recorded |
| Remaining inventory | Every leftover is explained, with owner, cost implication and next action |

If Terraform reports a dependency, inspect the recorded owner and complete that prerequisite; generate a fresh plan. If a Kubernetes finalizer is stuck, restore its controller/access path. If the private worker is gone too early, restore an approved management path rather than opening the cluster API. If cleanup authority was revoked, have the existing operator restore only the required scope.

Mark removal passed only when all intended active resources are gone and every retained item is documented. A stopped cluster, missing state file or successful Helm uninstall alone is not complete teardown.
