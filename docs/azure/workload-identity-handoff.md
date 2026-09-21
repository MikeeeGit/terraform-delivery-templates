# Export applied workload identity bindings

The optional workload handoff extends the existing cluster/registry metadata export. It reads explicitly non-sensitive Terraform outputs and writes a new review JSON containing the dedicated workload identity, exact ServiceAccount manifest, CSI authentication parameters and selected issuer/subject bindings. It does not read state, fetch credentials, obtain access tokens, apply manifests or prove live authorization.

Use outputs from the reviewed applied AKS stack, including the `workload_identities.federated_credentials` metadata. Older snapshots without that metadata must be refreshed after applying the current output configuration. Keep handoff files private and ignored.

```bash
python3 ../terraform-delivery-templates/scripts/azure/platform_handoff.py \
  --template delivery.gateway.apps.json \
  --aks-outputs aks-outputs.json --registry-outputs network-outputs.json \
  --delivery-config ../azure-aks-foundation/delivery.azure.json \
  --environment pprd --region uks --output delivery.private.json \
  --workload-identity platform-demo --service-account-key app \
  --workload-output workload.private.json
```

Choose the actual application template for your maintained or compatibility controller profile. The helper retains its overlays and approval environments while replacing cluster and registry metadata. All three workload options must be supplied together; omitting them preserves the original handoff behavior. Existing output files are never overwritten. If the second output cannot be created, the newly created first output is removed and any existing file is preserved.

The helper rejects an unrelated identity subscription/tenant, malformed identity resource ID/client ID, a namespace mismatch, a missing selected slot, or applied federation with a different issuer, subject or token-exchange audience. Federation coverage comes from the actual AKS output metadata, not only a desired ServiceAccount list.

Review `service_account_manifest` and commit its content in the intended application's overlay. Copy only the generated `clientID`, `tenantId` and `usePodIdentity` values into its SecretProviderClass; configure the real vault and object references separately. Pods also need the exact ServiceAccount, workload identity label and CSI volume mount. A TLS `SecretProviderClass` must synchronize both `tls.key` and `tls.crt` from certificate secret material and have a live mounting consumer. The helper deliberately does not patch unrelated files or export secret values.

Follow the [AKS TLS profile](https://github.com/MikeeeGit/azure-aks-foundation/blob/main/examples/ingress-tls/README.md) and the chosen application's controller profile. Verify live vault permissions, CSI custom-resource authorization, network/DNS reachability and certificate rotation separately. Never assume a successful metadata export proves those prerequisites.

## Complete application/platform handoff

For the maintained Azure workload sample, [three-tier handoff](three-tier-azure-deployment.md#3-generate-the-platformapplication-identity-bindings) generates both platform ServiceAccount declarations, application identity/CSI patches and the real-Azure expected contract from the same applied identity. The original metadata-only helper remains available for other consumers.
