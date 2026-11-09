# NEXUS Production Deployment and Operations Runbook

**Version:** 1.0.0
**Phase Reference:** NEXUS Phase 1 End-to-End Production Readiness
**Target Environment:** Production / Multi-Tenant SaaS
**Minimum Database Revision:** `021_phase1j2_webhook_inbox`
**Classification:** Operational Security & SRE Standard Operating Procedure (SOP)

---

## 1. Executive Summary & Purpose

This runbook establishes the formal deployment, configuration, key management, operational procedures, and incident response protocols required to operate the NEXUS Phase 1 ingestion, reconciliation, period-close certification, and customer cadence pipelines in a live enterprise environment.

NEXUS enforces strict separation between:
1. **Isolated Synthetic Sandbox Rehearsals** (safe for automated regression and integration testing).
2. **Protected Benchmark Tenants** (e.g. Apex Specialty Commerce, which must remain strictly `DIAGNOSTIC_ONLY`).
3. **Live Operational Production Tenants** (which require authenticated cloud KMS providers, live merchant OAuth credentials, and signed financial attestations).

---

## 2. System Architecture & Component Topology

```
                          ┌──────────────────────────────────────────────┐
                          │         External Merchant Platforms          │
                          │   (Shopify Admin GraphQL / Stripe API)       │
                          └───────────────────────┬──────────────────────┘
                                                  │ Webhooks & Sync REST
                                                  ▼
                          ┌──────────────────────────────────────────────┐
                          │            Reverse Proxy / Ingress           │
                          │     (Raw Body Preserved, TLS 1.3, Rate Limit)│
                          └───────────────────────┬──────────────────────┘
                                                  │
                 ┌────────────────────────────────┴────────────────────────────────┐
                 ▼                                                                 ▼
   ┌───────────────────────────┐                                     ┌───────────────────────────┐
   │    Webhook Inbox API      │                                     │   Connector Sync Worker   │
   │ (/connectors/webhooks/*)  │                                     │  (Shopify/Stripe Adapters)│
   └─────────────┬─────────────┘                                     └─────────────┬─────────────┘
                 │                                                                 │
                 └────────────────────────────────┬────────────────────────────────┘
                                                  │
                                                  ▼
                          ┌──────────────────────────────────────────────┐
                          │        Ingestion Writer Coordinator          │
                          │   (PostgreSQL 64-bit Advisory Locks)         │
                          │ - Shared Locks: Ingestion & Webhooks         │
                          │ - Exclusive Locks: Period Close Certification│
                          └───────────────────────┬──────────────────────┘
                                                  │
                                                  ▼
                          ┌──────────────────────────────────────────────┐
                          │           PostgreSQL 16 Database             │
                          │  - Revision: 021_phase1j2_webhook_inbox      │
                          │  - Encrypted Credentials (AES-256-GCM)       │
                          │  - Checkpoints & Durable Webhook Inbox       │
                          │  - Immutable Manifest Submissions Ledger     │
                          └───────────────────────┬──────────────────────┘
                                                  │
                                                  ▼
                          ┌──────────────────────────────────────────────┐
                          │            Cloud KMS Master Key              │
                          │        (AWS KMS / GCP KMS / Vault)           │
                          │  Context-Bound Envelope DEK Decryption       │
                          └──────────────────────────────────────────────┘
```

---

## 3. Production Environment Prerequisites

### 3.1 PostgreSQL 16 Configuration
The database must be PostgreSQL 16+ configured with explicit transaction and connection limits:

```ini
# postgresql.conf
max_connections = 200
shared_buffers = 4GB
work_mem = 64MB
maintenance_work_mem = 512MB
effective_cache_size = 12GB
wal_level = replica
max_wal_size = 16GB
min_wal_size = 2GB
checkpoint_completion_target = 0.9

# Advisory locks & timeout boundaries
statement_timeout = 60000ms                # 60s max per individual query
idle_in_transaction_session_timeout = 30000ms # 30s max idle lock duration
lock_timeout = 15000ms                     # 15s max lock acquisition wait
```

### 3.2 Environment Variables & Fail-Closed Guardrails
In production, set the following environment variables. The NEXUS application runtime enforces a hard fail-closed check: if `APP_ENV=production` and `LocalDevelopmentKMSProvider` is invoked, the application immediately aborts with `KMSError`.

```bash
# Core Environment
APP_ENV=production
ENVIRONMENT=production
DEBUG=false
NEXUS_API_SECRET_KEY=<generate-strong-64-char-hex>

# Database Connection (Connection Pooling via PgBouncer or native SQLAlchemy pool)
DATABASE_URL=postgresql+psycopg://nexus_prod_user:<PASSWORD>@postgres-prod-primary.internal:5432/nexus_production_db
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30

# Managed Key Management Service (Choose 'aws', 'gcp', or 'vault')
NEXUS_KMS_PROVIDER=aws

# AWS KMS Configuration (when NEXUS_KMS_PROVIDER=aws)
AWS_REGION=us-east-1
AWS_KMS_KEY_ARN=arn:aws:kms:us-east-1:123456789012:key/550e8400-e29b-41d4-a716-446655440000

# GCP Cloud KMS Configuration (when NEXUS_KMS_PROVIDER=gcp)
GCP_KMS_PROJECT_ID=nexus-production-cloud
GCP_KMS_LOCATION_ID=global
GCP_KMS_KEY_RING_ID=nexus-production-ring
GCP_KMS_CRYPTO_KEY_ID=nexus-tenant-credentials

# HashiCorp Vault Configuration (when NEXUS_KMS_PROVIDER=vault)
VAULT_ADDR=https://vault.internal.nexus:8200
VAULT_TOKEN=<approle-generated-periodic-token>
VAULT_TRANSIT_KEY=nexus-credentials-master
```

---

## 4. Production Key Management Service (KMS) Provisioning

All connector credentials stored in `tenant_connector_credentials` are envelope-encrypted using AES-256-GCM. Plaintext credentials are never written to disk or database logs.

### 4.1 AWS KMS Setup

1. **Create Customer Managed Key (CMK):**
   ```bash
   aws kms create-key \
     --description "NEXUS Production Tenant Credential Master Key" \
     --key-usage ENCRYPT_DECRYPT \
     --customer-master-key-spec SYMMETRIC_DEFAULT \
     --origin AWS_KMS \
     --tags TagKey=Application,TagValue=NEXUS TagKey=Environment,TagValue=Production
   ```

2. **Enable Automatic Annual Rotation:**
   ```bash
   aws kms enable-key-rotation --key-id <KEY_ARN>
   ```

3. **Define IAM Least-Privilege Policy for NEXUS Workload:**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "AllowNEXUSEnvelopeCrypto",
         "Effect": "Allow",
         "Action": [
           "kms:Encrypt",
           "kms:Decrypt",
           "kms:GenerateDataKey",
           "kms:DescribeKey"
         ],
         "Resource": "arn:aws:kms:us-east-1:123456789012:key/<KEY_ID>",
         "Condition": {
           "StringEquals": {
             "kms:ViaService": "kms.us-east-1.amazonaws.com"
           }
         }
       }
     ]
   }
   ```

### 4.2 GCP Cloud KMS Setup

1. **Create KeyRing and Symmetric Key:**
   ```bash
   gcloud kms keyrings create nexus-production-ring --location global
   gcloud kms keys create nexus-tenant-credentials \
     --keyring nexus-production-ring \
     --location global \
     --purpose "encryption" \
     --rotation-period "365d" \
     --next-rotation-time "$(date -u -v+365d +%Y-%m-%dT%H:%M:%SZ)"
   ```

2. **Grant IAM Role to NEXUS Service Account (GKE / Workload Identity):**
   ```bash
   gcloud kms keys add-iam-policy-binding nexus-tenant-credentials \
     --keyring nexus-production-ring \
     --location global \
     --member "serviceAccount:nexus-api@nexus-production-cloud.iam.gserviceaccount.com" \
     --role "roles/cloudkms.cryptoKeyEncrypterDecrypter"
   ```

### 4.3 HashiCorp Vault Setup

1. **Mount Transit Secrets Engine and Create Key:**
   ```bash
   vault secrets enable transit
   vault write -f transit/keys/nexus-credentials-master \
     type=aes256-gcm96 \
     auto_rotate_period=8760h \
     derived=false \
     convergent_encryption=false
   ```

2. **Vault Policy (`nexus-kms-policy.hcl`):**
   ```hcl
   path "transit/encrypt/nexus-credentials-master" {
     capabilities = ["update"]
   }
   path "transit/decrypt/nexus-credentials-master" {
     capabilities = ["update"]
   }
   path "transit/keys/nexus-credentials-master" {
     capabilities = ["read"]
   }
   ```

### 4.4 Master Key Emergency Revocation & Re-encryption Runbook

When a master key version is compromised or scheduled for decommission:

1. **Register New Master Key Version** in Cloud KMS.
2. **Execute In-Memory Re-encryption Utility:**
   The `EnvelopeEncryptionEngine.reencrypt_credentials` decrypts the credential with `current_kms` in memory and re-encrypts using `new_kms` without storing intermediate plaintexts:
   ```python
   new_envelope = EnvelopeEncryptionEngine.reencrypt_credentials(
       envelope_str=record.encrypted_credentials,
       business_id=record.business_id,
       provider=record.provider,
       provider_account_id=record.provider_account_id,
       current_kms=current_kms_provider,
       new_kms=new_kms_provider,
       new_kms_key_id=new_key_version,
   )
   record.encrypted_credentials = new_envelope
   record.kms_key_id = new_key_version
   session.commit()
   ```
3. **Revoke Compromised Key:**
   ```bash
   # AWS KMS: Disable Key
   aws kms disable-key --key-id <OLD_KEY_ARN>

   # GCP KMS: Destroy Key Version
   gcloud kms keys versions destroy 1 --key nexus-tenant-credentials --keyring nexus-production-ring --location global

   # Vault: Set min_decryption_version
   vault write transit/keys/nexus-credentials-master/config min_decryption_version=2
   ```

---

## 5. Connector Webhook Ingress & Worker Infrastructure

### 5.1 Reverse Proxy / Ingress Requirements
Stripe and Shopify webhook signatures are calculated against the exact raw payload bytes. Ingress proxies (e.g. NGINX, Traefik, AWS ALB) must:
- **Preserve Raw Request Body:** Do not normalize line endings, compress, or re-encode payload bytes prior to application dispatch.
- **Enforce TLS 1.3:** Reject insecure HTTP/1.0 or plain HTTP traffic.
- **Forward Headers Intact:**
  - Stripe: `Stripe-Signature`
  - Shopify: `X-Shopify-Hmac-SHA256`, `X-Shopify-Topic`, `X-Shopify-Shop-Domain`, `X-Shopify-Webhook-Id`

### 5.2 Webhook Inbox Table & Lifecycle Statuses
All incoming webhook deliveries are persisted in `connector_webhook_inbox` before processing:

| Status | Meaning | Action / Escalation |
|---|---|---|
| `PENDING` | Received and deduplicated, awaiting worker pickup | Normal ingestion queue |
| `PROCESSING` | Claimed by worker, heartbeat updated every 30s | Worker is running |
| `PROCESSED` | Successfully validated, reconciled, and applied | Terminal success |
| `QUARANTINED` | Payload hash mismatch under duplicate event ID | Security review required |
| `FAILED` | Processing failed due to validation or DB exception | Retry with exponential backoff |

### 5.3 Dead-Letter Queue (DLQ) & Worker Recovery Procedure
If an ingestion worker crashes or loses database connectivity, events can remain in `PROCESSING` status.

1. **Detect Abandoned Claims:**
   Workers must update `last_heartbeat_at`. Events in `PROCESSING` status with no heartbeat for > 5 minutes are abandoned.
2. **Execute Recovery Command:**
   ```sql
   UPDATE connector_webhook_inbox
   SET status = 'PENDING',
       worker_id = NULL,
       locked_at = NULL,
       retry_count = retry_count + 1
   WHERE status = 'PROCESSING'
     AND last_heartbeat_at < NOW() - INTERVAL '5 minutes'
     AND retry_count < 5;
   ```
3. **Escalate Persistent Failures:**
   Events reaching `retry_count >= 5` transition to `FAILED` and trigger a P2 on-call alert.

---

## 6. Database Migration & Rollback Protocol

### 6.1 Strict Alembic Revision Preservation
The production database baseline is strictly pinned to:
`021_phase1j2_webhook_inbox`

**Prohibition Rule:** Under no circumstances should an unreviewed `022` migration be created or applied in production without architectural audit approval.

### 6.2 Pre-Deployment Invariant Verification
Before deploying application updates, execute the invariant check:

```bash
python scratch/check_alembic_and_apex.py
```

Expected output:
- `CURRENT_ALEMBIC_REVISION`: `021_phase1j2_webhook_inbox`
- `APEX_CUSTOMERS_COUNT`: `1000`
- `APEX_SALES_COUNT`: `3500`
- `APEX_SALE_ITEMS_COUNT`: `11221`
- `APEX_TOTAL_WATERMARKS`: `0`
- `APEX_ACTIVE_WATERMARKS`: `0`
- `APEX_WEBHOOK_INBOX_ROWS`: `0`

---

## 7. Monitoring, Observability & Alerting Thresholds

| Metric | Target / SLA | Alert Threshold | Severity | Recommended Mitigation |
|---|---|---|---|---|
| **Checkpoint Sync Lag** | < 1 hour | > 6 hours | **P3** | Check connector rate limits, worker health, external API status |
| **Webhook Quarantine Rate** | 0.00% | > 0.1% in 15m | **P2** | Potential payload tampering or replay attack; inspect quarantined IDs |
| **Reconciliation Mismatches** | 0 mismatches | > 0 unmatched at close | **P2** | Audit Stripe fee schedules, refund timing gaps, or partial payouts |
| **Ingestion Lock Contention** | < 500ms wait | > 30s lock wait | **P3** | Ingestion worker overlapping with active period-close run; check long-running transactions |
| **Apex Tenant Isolation** | 0 mutations | ANY write attempt | **P1 (Critical)** | Immediate page: automated security lockdown of any caller targeting Apex |
| **KMS Provider Availability** | 99.999% | 1 failure | **P1 (Critical)** | Cloud KMS unreachable; check IAM role permissions, network routing, or Vault cluster status |

---

## 8. Real Merchant Onboarding & Go-Live Checklist

To promote a tenant from synthetic rehearsal to live production certification:

- [ ] **Step 1: Production Infrastructure Deployed**
  - Managed PostgreSQL 16 primary + replica online.
  - AWS KMS / GCP KMS / Vault provider verified with fail-closed tests.
  - Alembic revision confirmed at `021_phase1j2_webhook_inbox`.
- [ ] **Step 2: Merchant OAuth Credentials Acquired**
  - Live Shopify App installed on merchant store with `read_orders`, `read_products`, `read_all_orders` scopes.
  - Live Stripe Restricted API Key (`rk_live_...`) provisioned with read-only charges, payouts, balance transactions.
  - Live webhook signing secrets securely entered via tenant admin UI.
- [ ] **Step 3: Envelope Encryption Verified**
  - Credentials encrypted with context binding: `business_id`, `provider`, `provider_account_id`.
  - Credentials masked (`***REDACTED***`) across all API responses.
- [ ] **Step 4: Initial Authoritative Historical Sync Completed**
  - Shopify commercial orders extracted and checkpoints promoted.
  - Stripe settlement payouts and charge records extracted.
  - Cross-source reconciliation produces 100% match or clean variance breakdown.
- [ ] **Step 5: Period-Close Evidence Package Signed**
  - Ed25519 or HMAC-SHA256 signature generated by authenticated Finance Controller.
  - Canonical dataset content digest matches persisted database state.
  - Manifest durably recorded in `manifest_submissions` ledger.
- [ ] **Step 6: Production Watermark Certified**
  - Authoritative ingestion watermark recorded with live production provenance.
  - Tenant certification policy transitions tenant from `DIAGNOSTIC_ONLY` to `ACTIONABLE`.
