# Recover an orphaned Azure state lock

Terraform can finish calculating a plan and then fail while releasing the Azure Blob state lock. A failed pipeline is not a usable plan approval: recover the state lock, then run and review a fresh plan.

This failure was observed during disposable Azure qualification with Terraform 1.16.3. The connection-reset cause was not established. In that version, the backend removes its lock metadata before releasing the Blob lease; either operation can fail independently. The pinned SDK does not retry these PUT requests after a missing HTTP response. This explains why recovery can find either a lease with metadata or a lease whose metadata has already been removed. See the [Terraform backend implementation](https://github.com/hashicorp/terraform/blob/v1.16.3/internal/backend/remote-state/azure/client.go) and [pinned SDK request handling](https://github.com/hashicorp/go-azure-sdk/blob/sdk/v0.20250131.1134653/sdk/client/client.go).

## Establish ownership before recovery

1. Confirm that the failed pipeline has finished and its Terraform process has stopped. Check for other pipeline runs and local operators using the same state key.
2. Match the subscription, storage account, container, key and workspace to the failed run's reviewed backend configuration. Similar environment names are not sufficient.
3. Read the current Blob lease status, ETag and metadata with the authorized backend operator. Keep this output private. Retain the failed run, source commit and state recovery snapshot.
4. Compare any surviving Terraform lock record with the failed run's lock ID, operation, creation time and owner. A different lock or changed evidence requires a new investigation.

Do not disable state locking, automatically unlock after every failure, break an unknown lease, or delete the state Blob. Increasing AzureRM resource timeouts does not change Terraform core's backend unlock requests.

## Select the recovery operation

When matching Terraform lock metadata remains, initialize the exact existing backend and use Terraform's normal guarded operation:

```bash
terraform force-unlock "$failed_run_lock_id"
```

Read its confirmation carefully. Run it only after establishing that the recorded owner is no longer active. This changes the lock, not the infrastructure.

When the metadata has already been removed, Terraform cannot validate the lock record. An authorized storage operator can release the **known failed run's exact lease**, conditioned on the unchanged Blob ETag:

```bash
az storage blob lease release \
  --auth-mode login \
  --subscription "$backend_subscription_id" \
  --account-name "$backend_storage_account" \
  --container-name "$backend_container" \
  --blob-name "$backend_state_key" \
  --lease-id "$failed_run_lock_id" \
  --if-match "$observed_blob_etag"
```

Populate these values from the verified failed run and current readback; preserve the ETag's quoted value. An ID or ETag mismatch must stop recovery. Do not replace this with an unconditional lease break.

## Verify and resume

Read the Blob again and verify that the lease is available/unlocked. Retain the recovery result privately, then queue a fresh pipeline at the intended protected source commit. Review its new binary plan and receipt before approving apply. If the transport failure repeats, capture and investigate it; a successful retry establishes recovery, not a permanent fix.

Keep authentication headers, state contents and raw Terraform diagnostic traces out of public build logs. The operational record should distinguish the failed run, the recovery action and the new successful run.

Return to [local helpers](local-helpers.md), [Azure deployment](sandbox-deployment.md) or [three-tier removal](three-tier-removal.md).
