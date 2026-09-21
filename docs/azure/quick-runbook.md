# Run the three-tier dual-AKS example

Use this page as the run list. The [worked deployment](three-tier-worked-example.md) provides first-time configuration, and the [identity design](three-tier-azure-deployment.md) explains the three tiers. Keep actual IDs, certificates, state and evidence in private consumers.

The disposable Azure profile uses one selected subscription, UK South, a hub and two spoke networks, and **two AKS clusters in the PPRD spoke**. The second spoke has no clusters. These environment names select new lab resources. Dynatrace is excluded.

## First-time setup

1. Select the subscription, unique storage/registry names, quota and supported AKS version. Set a budget alert and removal time; an Azure budget alert does not stop spending.
2. Create private component consumers, protected main branches, manual pipelines and approval environments. Pin shared libraries to reviewed full commits.
3. Apply backend bootstrap as the retained operator, migrate its state to the operator-only container, and apply the hub network/ACR with peerings disabled.
4. Apply separate delivery identities, scoped grants and service connections/FICs for the actual pipeline IDs.
5. Prepare private worker access and the retained operator's independent state-access path. Prepare certificates and seed the private workload vault when its infrastructure is available.

Follow the detailed guide's dependencies; downstream values must come from successful upstream applies.

## Deployment actions and pipelines

Choose the corresponding private caller in your project. Save each successful run ID/source commit. Review each Terraform plan before approving that run's apply stage.

| Order | Run | Selection and required result |
| --- | --- | --- |
| 1 — infrastructure | Network | Apply both spokes; enable/reapply all peering sides. Four directions must be Connected. |
| 2 — infrastructure | Private worker | Worker online; private DNS, API and state access checked; registration token retired. |
| 3 — infrastructure | Firewall, then routes | Create Firewall/DNS proxy and route tables; set spoke DNS; enable AKS route associations after egress checks. |
| 4 — infrastructure | Workload vault | Private endpoint/DNS and seed roles applied. Seed TLS and qualification material; review the trusted-services option for Gateway certificate retrieval. |
| 5 — infrastructure | Dual AKS | Apply the complete pprd/uks pair, including workload MI, both FICs, Key Vault/ACR grants and CI Cluster User grants. |
| 6 — handoff | Generate configuration | Run three_tier_handoff.py against actual wrapped Terraform outputs; commit the private platform/app bindings. |
| 7 — access | Discover identities | Observe platform and application Kubernetes identities on each slot. Bootstrap platform access as the retained operator. |
| 8 — platform | Platform services | Select **clusterSlots: [aks01, aks02]** and **deploySequentially: true**. Install Gateway API/Envoy and private TLS listener prerequisites. |
| 9 — platform | Application bootstrap | Select **clusterSlots: [aks01, aks02]**. Establish namespace/native application RBAC and verify CSI prerequisites. |
| 10 — application | Image build | Build/test/push once; require the immutable scan to pass. Record build run ID, definition ID and receipt artifact name. |
| 11 — application | Promote selected build | Select that build, **clusterSlots: [aks01, aks02]**, **deploySequentially: true**. Approve each rendered bundle; both slots must report the same image/revision. |
| 12 — cloud traffic | Application Gateway | Apply WAF/TLS after its certificate prerequisites. Verify actual provisioning, backend health and HTTPS through WAF. |
| 13 — qualification | Workload and traffic checks | Retain real CSI/readiness records for both slots and the initial stable endpoint record for aks01. |

The sample promotion caller qualifies Azure workload identity after deployment. A queued pipeline or rendered manifest is not a completed deployment. In the Azure DevOps UI enter both slots as the object list above; REST dispatch requires object template parameters to be JSON-encoded strings.

## Update, switch and roll back

1. Commit the next app change and run **Image build** once. Keep its passed scan and release receipt.
2. Run **Promote selected build** with the new build ID and **clusterSlots: [aks02]**. Keep aks01 on the earlier build.
3. Verify the standby through its preview WAF listener and prove stable web/API traffic still reaches the original aks01 revision.
4. Change only the stable backend DNS record in Gateway Terraform to the aks02 listener IP. Run **Gateway**, review its saved plan and approve the traffic change.
5. Run the traffic qualifier for **traffic-cutover**; require healthy selected backends and valid TLS responses from aks02 at the new revision.
6. Restore the record to aks01 through **Gateway**. Run **traffic-rollback** and verify the original slot/revision.

DNS caching and connection draining mean switching is not instantaneous. These stateless checks cover new connections, not session continuity or stateful recovery.

## Remove the lab

Follow the [scripted removal run list](three-tier-removal.md#scripted-removal-run-list). It covers Kubernetes services, dependent Terraform states, connections/identities, worker/Firewall/network and migration of the backend's own state before deleting its storage. Keep the operator and private recovery files until independent Azure inventory confirms removal.

## Evidence and scope

Record public/offline checks, kind direct/Argo acceptance, actual Azure pipeline/identity/CSI/traffic results and final removal separately. The [sanitized original platform plan](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/containerization-platform-plan.md) and [requirements matrix](https://github.com/MikeeeGit/aks-delivery-templates/blob/main/docs/containerization-requirements.md) preserve the wider design and distinguish implemented capabilities from remaining qualification work.
