# Disposable lab TLS certificates

This example supplies the TLS files for a short-lived Azure three-tier trial. The [local helper](../../../../scripts/azure/create_lab_certificates.py) creates a private CA and separate backend/frontend keys and certificates for exactly `web.example.test`, `api.example.test`, `preview.example.test` and `private.example.test`. Validity is limited to 1–7 days, default seven. It verifies the chain, server-auth purpose, every hostname, matching private keys and the exported PFX before reporting success. It makes no Azure calls.

These reserved names and the locally created CA are for a disposable lab only. The helper is not a production CA, does not automate renewal or revocation, and does not install a root into a machine/browser trust store. Real domains need the organisation's certificate issuance and lifecycle process. Clients in this example trust only the explicitly supplied lab public CA for the selected request.

## Generate outside Git

Use Linux or WSL with Python 3 and OpenSSL 1.1.1 or newer. Run from a reviewed checkout of this repository. The output directory must be absolute, new and outside every Git working tree; its parent must already exist. Existing directories and symlink paths/ancestors are rejected. The helper creates directory mode `0700` and file mode `0600`, including temporary keys, and does not print certificate/key bytes or OpenSSL diagnostics.

```bash
set -euo pipefail
set +x
umask 077
LAB_PRIVATE_ROOT="$HOME/aks-lab-private"
mkdir -p "$LAB_PRIVATE_ROOT"
chmod 700 "$LAB_PRIVATE_ROOT"
LAB_CERT_DIR="$LAB_PRIVATE_ROOT/certificates-run-01"
python3 scripts/azure/create_lab_certificates.py \
  --output-dir "$LAB_CERT_DIR" --days 7
```

Use a fresh run directory after expiry or for a new trial. Do not reuse a directory, extend validity by editing the script, or create private material inside a Git repository, CI artifact directory or Terraform working directory.

| Output | Consumer and handling |
| --- | --- |
| `ca.pem` | Public root only. Gateway backend trusted-root input and explicit client/receipt CA trust. Contains no private key. |
| `backend.crt.pem`, `backend.chain.pem` | Backend leaf, and leaf-plus-root chain, for inspection. All four reserved hostnames are SANs. |
| `backend.key.pem` | Private backend key. Keep private; never pass to Terraform. |
| `backend.secret.pem` | Leaf-plus-root chain followed by its unencrypted private key. Upload as the CSI PEM secret. |
| `frontend.crt.pem`, `frontend.chain.pem`, `frontend.key.pem` | Separate frontend leaf/chain/private key. The frontend and backend keys are different. |
| `frontend.pfx` | Frontend key, leaf and root for Key Vault certificate import. Its password is deliberately empty; treat the entire file as private key material. |
| `ca.key.pem` | Lab CA private signing key. Never upload to Key Vault, AKS, CI artifacts or Git. |
| `manifest.json` | Local creation time, validity, reserved names and public-certificate SHA-256 fingerprints; contains no private keys. |

The Python tests run actual OpenSSL verification and load the combined CSI PEM as a TLS certificate/key. They also extract and check the PFX, reject unlisted hostnames, and test output isolation and failure cleanup. This proves local file compatibility; it does not establish a successful Azure import, CSI mount or Application Gateway handshake.

## Seed the owned private vault

Deploy the [workload-vault root](../workload-vault/README.md) first. For a lab using that same vault for frontend and backend TLS, declare the approved operator's existing Entra object ID in **both** `secret_administrator_object_ids` and `certificate_seed_operator_object_ids`. Terraform then grants Secrets Officer and Certificates Officer separately, only at the new owned vault. Neither grant is implicit and neither grants the application's runtime identity these administrative roles.

Authenticate as that operator on the trusted private worker. Confirm the selected tenant, applied vault name, private DNS/endpoint route and role propagation. Transfer private files only over the authenticated private management channel, preserving private permissions; never copy an Azure token cache. Use a private working directory and disable shell tracing. The following commands read files directly and suppress response bodies:

```bash
set -euo pipefail
set +x
umask 077
: "${VAULT_NAME:?Set the applied lab vault name}"
: "${LAB_CERT_DIR:?Set the existing absolute private certificate directory}"

az keyvault secret set --vault-name "$VAULT_NAME" \
  --name platform-demo-ingress --file "$LAB_CERT_DIR/backend.secret.pem" \
  --encoding utf-8 --content-type application/x-pem-file \
  --only-show-errors --output none

az keyvault certificate import --vault-name "$VAULT_NAME" \
  --name platform-demo-frontend --file "$LAB_CERT_DIR/frontend.pfx" \
  --only-show-errors --output none

# This is a non-sensitive readiness fixture, not a real application credential.
printf '%s' 'disposable-lab-readiness' > "$LAB_CERT_DIR/qualification.txt"
chmod 600 "$LAB_CERT_DIR/qualification.txt"
az keyvault secret set --vault-name "$VAULT_NAME" \
  --name platform-demo-qualification --file "$LAB_CERT_DIR/qualification.txt" \
  --encoding utf-8 --only-show-errors --output none
```

The backend object is a **secret holding PEM chain and key**, matching the maintained CSI `objectType: secret` / `objectFormat: pem` profile. The frontend operation imports a **certificate**, whose associated secret contains the PFX for Application Gateway. These are different objects and consumption paths. Microsoft's [certificate import guidance](https://learn.microsoft.com/en-us/azure/key-vault/certificates/tutorial-import-certificate) and [CSI identity/object-type guidance](https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-identity-access) describe those interfaces. The current profile synchronizes the backend secret into the Gateway's Kubernetes TLS Secret; the CA signing key is never involved in runtime access.

A seed operation creates a new object version if the name already exists. Use only the trial's owned vault and reviewed names. Do not place PEM/PFX bytes, passwords or secret values in tfvars, Terraform resources/data sources, state, command-line arguments or logs. The helper's public root is the only certificate file intended for a Terraform input.

## Connect the certificate inputs

1. In the private app handoff, select TLS secret `platform-demo-ingress` and qualification secret `platform-demo-qualification`. Use the applied workload managed identity, both AKS issuer federations and exact vault-scoped Secrets User grant. The backend secret must be mounted before the Kubernetes Gateway TLS Secret can synchronize.
2. In the gateway consumer, set the frontend certificate reference to the **versionless secret URI** `https://<applied-vault-name>.vault.azure.net/secrets/platform-demo-frontend`. Use the owned vault ID and the gateway's separately declared Secrets User identity grant. Private DNS/routes must let the gateway reach that vault; the seed operator's access does not grant runtime access.
3. Supply only `ca.pem` to `trusted_root_certificates` and bind each HTTPS web/API/preview backend setting to its name, following the [gateway private-CA profile](https://github.com/MikeeeGit/azure-application-gateway/tree/main/examples/private-ca). Keep the backend settings/probe Host names and TLS SNI consistent with these SANs. Do not pass `backend.secret.pem` or the leaf certificate as the root.
4. Copy only the public `ca.pem` into the private platform/application consumer's reviewed trust path and set the receipt's ingress `ca_file` accordingly. This public CA is safe to include in the reviewed deployment bundle. Keep every key, combined secret PEM and PFX outside that repository and bundle.
5. Use the same public CA with the [Azure traffic qualifier](https://github.com/MikeeeGit/aks-platform-demo/blob/main/docs/AZURE-WORKLOAD.md#qualify-the-stable-azure-gateway-through-cutover-and-rollback), which connects to the observed gateway IP while retaining the expected hostname for SNI/Host. A browser/DNS entry or `curl --resolve` does not replace the server certificate's SAN and chain checks.

The local `ca.pem` and gateway backend trust establish separate client-to-gateway and gateway-to-backend trust relationships. A passing local OpenSSL test is not an Azure deployment report. After the actual pipelines, retain separate private CSI qualification and stable-endpoint deployment/cutover/rollback reports. Do not use `curl -k`, skip certificate verification or globally trust this root to make a failed check pass.

## Remove and rotate the trial material

Keep both slots and the old certificate versions available until rollback acceptance is complete. For a longer trial, generate a fresh directory/CA, review the public trust changes and seed new leaf/PFX versions; changing the frontend Key Vault version does not instantly prove gateway refresh, and changing the backend secret does not instantly prove CSI synchronization. Observe the current live certificate and rerun qualification before retiring prior trust.

Follow the [ordered three-tier removal](../../../../docs/azure/three-tier-removal.md): withdraw traffic and remove dependent applications/gateway resources before retiring their vault objects. The vault has purge protection and is soft-deleted through its Terraform owner; do not attempt to purge it or bypass retention. For a retained vault, retire the exact trial objects through the approved secret/certificate lifecycle after their consumers have gone. Remove the opt-in seed-operator grants through reviewed Terraform when they are no longer required.

Finally delete the exact private run directory and transferred copies from the operator/worker, remove temporary operator login caches and runner registrations, and retain only permitted private metadata/reports. Confirm the resolved directory before deletion; never target a repository or a shared parent directory. Ordinary file deletion does not guarantee secure erasure on SSDs, backups or snapshots, so use an encrypted private workspace and its normal retention policy. Do not publish certificate private material as cleanup evidence.
