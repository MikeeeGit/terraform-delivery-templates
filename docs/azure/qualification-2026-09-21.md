# Dual-AKS Azure qualification — 21 September 2026

This record describes a disposable deployment of the three-tier reference system. Use the [short run list](quick-runbook.md) to repeat the sequence and the [worked procedure](three-tier-worked-example.md) for first-time inputs. Actual subscriptions, endpoint addresses, credentials, certificates, plans, state and full logs remain in private consumer repositories and protected operator evidence.

## Environment and delivery path

The trial used one selected Azure subscription, UK South, a hub and two spokes, and **two private AKS clusters in the PPRD spoke**. The second spoke contained no AKS cluster. Both clusters used AKS 1.35.8, the Free control-plane tier and a disposable shared system/workload pool of two Standard_D4s_v4 nodes per cluster. Local accounts were disabled. Azure CNI Overlay with Cilium, user-defined routes, Azure Firewall DNS/egress, private Key Vault connectivity and Application Gateway WAF formed the cloud path.

Terraform created the infrastructure, delivery/workload managed identities, federated credentials, service connections and scoped Azure grants. Separate platform and application pipelines used those identities. The retained operator bootstrapped the native Kubernetes authorization boundary; application pipelines then deployed through their own scoped identity.

The exercised application method was **direct pipeline delivery using Kustomize**. Envoy Gateway 1.9.1 and Gateway API 1.6.1 provided private HTTPS ingress. Argo CD remains an additional supported delivery example, with separate kind acceptance; this record does not claim an Argo deployment to Azure. Dynatrace was excluded.

## Recorded deployment results

Run numbers below identify the retained private Azure DevOps evidence. Public readers can inspect the shared implementation and repeat the procedure; they cannot access the private run logs.

| Operation | Retained result |
| --- | --- |
| Terraform dual-AKS deployment | Run **956 passed**; both private clusters and their identity/federation/RBAC prerequisites applied. |
| Discover federated CI identities | Runs **958–961 passed**; observed platform and application identities on both slots. |
| Platform services on both slots | Run **963 passed**; controllers, Gateway API and private listener resources installed through platform CI. |
| Application namespace/access bootstrap | Run **966 passed** on both slots. |
| Application Gateway certificate path | Run **973 passed** after the explicitly reviewed Key Vault trusted-services option. |
| Initial image build and scan | Run **974 passed**; image digest prefix **e35c6e9fac2e…**, source **2a7390d15d30…**. |
| Promote one build to both clusters | Run **977 passed**, including actual Key Vault CSI/readiness qualification on both slots. |
| Initial stable WAF endpoint | Three rounds of hostname-verified HTTPS checks returned the expected aks01 web/API revision. |
| Second immutable image build and scan | Run **985 passed**; image digest prefix **5839009875ae…**, source **9d7daac100f65…**. This revision updates the delivery caller; it does not represent a new application feature. |
| Update standby only | Run **986 passed** on aks02, including live CSI qualification; aks01 retained the first release. |
| Standby isolation | Three HTTPS samples verified the new release through preview; separate stable web/API samples still returned the original aks01 release. |
| Traffic cutover | Run **987 passed**; its reviewed saved plan updated only the stable private DNS A record. Three subsequent web/API samples returned the new aks02 revision through WAF. |
| Traffic rollback | Run **988 passed**; its reviewed plan restored only that record. Three subsequent hostname-verified HTTPS samples returned the original aks01 web/API revision. |

Both image builds passed the configured HIGH/CRITICAL scan policy. Promotion used recorded image digests; it did not rebuild an image. Receipts bind source revision, target, rendered manifest hash and certificate trust material.

## Full removal result

**Passed on 21 September 2026; final independent verification at 22:15 UTC.** The maintained [teardown entry point](../../scripts/azure/teardown_lab.py) was used for the staged removal, including recovery from the failures described below. [Repeat the removal run list](three-tier-removal.md#scripted-removal-run-list).

| Completion gate | Observed result |
| --- | --- |
| Freeze delivery and withdraw traffic | All 13 private lab pipelines disabled; WAF gateway removed through its reviewed saved Terraform plan. |
| Remove Kubernetes services on both slots | App resources and Gateways removed; original Azure load-balancer frontends confirmed released before Envoy was uninstalled. |
| Remove lab CI access | All ten lab service connections, their federations and pipeline authorizations removed; all three connection states empty. |
| Retire bootstrap credential | Exact bootstrap PAT confirmed in the revoked inventory, rejected by an authentication probe with HTTP 401, then removed from the local credential file. |
| Preserve existing application connections | All three pre-existing connections in the separate shared project retained identical IDs, names, type, sharing, readiness and project-reference metadata in the before/after comparison. |
| Remove infrastructure and identities | Both private AKS clusters and managed node groups, workload/delivery identities and grants, workload vault, routes, worker, Firewall, peerings, spokes, hub, registry and private DNS removed. The exact worker agent was unregistered and its management tunnel closed first. |
| Retire all state storage | All **15 component states** independently reread with **zero managed instances**. Bootstrap state migrated to protected local recovery with matching lineage/resources; the reviewed 13-resource plan removed all three backend accounts, four containers, three owned grants and three groups. Final local backend state contains zero managed instances. |
| Independent Azure inventory | All **18 exact owned resource groups**, including both recorded AKS node groups, absent. No active lab resource group remains. |

The protected workload vault remains as a **soft-deleted retention record**, scheduled for purge on **20 December 2026 at 21:40 UTC**. Purge protection was preserved. Quota, provider registration, the existing administrator group, disabled private pipeline definitions, private CI history and off-cloud recovery evidence are intentionally retained. They are distinct from the removed active lab infrastructure. Billing records can arrive after resource deletion.

The retained final inventory report has SHA-256 **274f74f5c55c1f1c47065a03e96a89755d0b0c4e74b2d8bcca5e7fceb287a836**. Its resource identifiers and underlying state remain private. This trial qualifies initial deployment and complete removal; a second reconstruction after this teardown was not performed.

## Independent public validation

- The framework's **146 Python tests passed**, including wrong-backend/ownership rejection, saved-plan integrity, service cleanup, connection boundaries and exact PAT retirement. Terraform mock validation also passed, including **eight workload-vault tests**. [Framework checks at the tested implementation](https://github.com/MikeeeGit/terraform-delivery-templates/actions/runs/35657907385).
- Both updated application acceptance jobs passed at source **457bcaf9a1d3364c1a465177c901f612f2b90808**, using shared templates **d15f578dd05d1becf162b5fa67b5d0503a06da4c**: direct validation/worked deployment in **3m52s**, and Argo dual-cluster acceptance in **8m37s**. [Public run and retained job artifacts](https://github.com/MikeeeGit/aks-platform-demo/actions/runs/35659668749).

The kind tests exercise real disposable Kubernetes controllers and the selected delivery engines, including promotion, traffic selection, rollback and cleanup. They do not exercise Azure federation, CSI, private DNS or WAF; the separate Azure results above provide that evidence for the direct-delivery profile.

## Findings incorporated into the maintained code

- **Image scanning needs sufficient writable disk.** The real scan exposed an undersized temporary filesystem. The scanner now uses an isolated runner-disk cache, the runner UID and read-only registry credentials, without mounting the Docker socket.
- **Scan findings remained blocking.** The first runtime image failed on high-severity base/runtime-package findings. The pinned Node base was updated and build-only package managers removed from the final image; subsequent real scans passed.
- **Azure pipeline artifacts have a metadata download path.** Promotion now resolves and validates the pipeline artifact URL, including its organization collection and project path, before reading the release bundle.
- **Gateway certificate access needs the full network and identity path.** The trial required an explicit trusted-Azure-services exception on the private workload vault, alongside its managed-identity role and private DNS. The public option defaults to false; consumers review their actual certificate path.
- **Terraform state comparisons must account for check ordering.** The removal rehearsal encountered reordered check-result objects with unchanged state/resource content. The helper normalizes only that ordering and still rejects changed lineage, serial, resources, values or check outcomes.
- **Private management tunnels need liveness checks.** A stale operator SSH tunnel stopped carrying API requests while the worker still reached AKS. Recreating that exact tunnel restored hostname-verified TLS and operator authentication. Use SSH server-alive probes and bounded Kubernetes request timeouts; retain the controller and network until cleanup succeeds.
- **Controller removal must match the pinned Helm client.** Helm 4 removed the older list-all flag. Explicit release-status filters work with the selected client; the retry retained and rechecked the original Azure frontend addresses before uninstalling Envoy.
- **Credential deletion has a propagation boundary.** Azure DevOps initially rejected deleting connections immediately after their Azure federated credentials were deleted. Fresh plans after confirming empty credential lists removed the remaining endpoints. The recovery preserved state, evidence and cleanup authentication.
- **Revoked PAT metadata can remain queryable.** A token-detail response is not proof that a credential remains usable. Retirement now verifies the owner's revoked-token inventory and a rejected authentication probe, and handles a retry after successful revocation before deleting the local credential.

## Limits

This is a stateless reference application, two slots in one region and a small disposable capacity profile. The results do not qualify a production business application, stateful recovery, session continuity, load-driven scaling, upgrade headroom, multi-region recovery, mesh mTLS, certificate rotation, Windows workloads or enterprise observability. Real Cilium allow/deny enforcement and every negative authorization case require their own recorded acceptance; successful deployment alone does not establish them.

The broader original design and its remaining requirements are preserved in the [sanitized platform plan](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/containerization-platform-plan.md) and [requirements matrix](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/containerization-requirements.md).
