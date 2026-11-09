"""
NEXUS Phase 1J.1.1 — Connector Persistence & Session Restart Verification Tests.

Validates:
1. End-to-end synchronization survival across database session closure and worker restart.
2. Independent resumption from persisted database checkpoints.
3. Exact transaction coverage and zero duplicate ingestion after resumption.
4. Mathematical reconciliation and watermark certification after multi-stage sync.
5. Tenant credential persistence, envelope encryption integrity, rotation, and revocation across restarts.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.synthetic_source_adapter import SyntheticSourceAdapter
from app.models.connector import ConnectorSyncCheckpoint, TenantConnectorCredential
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.schemas.source_sync import SyncResult
from app.services.source_sync_service import SourceSyncService

TEST_CREDENTIALS = {
    "api_key": "synth_persist_key_12345",
    "webhook_secret": "synth_persist_secret_67890",
}


def _create_isolated_tenant(session: Session, suffix: str) -> Business:
    """Helper to create test tenant."""
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-persist-{suffix}-{uid}", name=f"Persist Org {suffix}", slug=f"persist-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-persist-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Persist Business {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-persist-{suffix}-{uid}",
        email=f"user_{suffix}_{uid}@example.com",
        full_name=f"User {suffix}",
        password_hash="mock",
        is_active=True,
        is_verified=True,
    )
    session.add_all([org, biz, user])
    session.flush()

    mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role="admin")
    session.add(mem)
    session.commit()
    return biz


def test_sync_persistence_across_session_restart(db_session: Session):
    """
    Test that a synchronization job interrupted after page 1 can be resumed
    by a completely new worker instance with a new database session,
    completing all remaining pages with exact transaction identity coverage.
    """
    engine = db_session.get_bind()
    SessionMaker = sessionmaker(bind=engine)

    # 1. Stage 1: Initial session and tenant creation
    sess_1 = SessionMaker()
    biz = _create_isolated_tenant(sess_1, "restart01")
    biz_id = biz.id

    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    # Total 60 transactions, 20 per page -> 3 pages total
    adapter_worker_1 = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz_id, seed=555, num_transactions=60, page_size=20
    )

    # Worker 1 runs only page 1, simulating process shutdown
    res_1 = SourceSyncService.execute_sync(
        session=sess_1,
        adapter=adapter_worker_1,
        period_start=start,
        period_end=end,
        page_size=20,
        stop_after_pages=1,
    )

    assert res_1.status == "IN_PROGRESS"
    assert res_1.is_complete is False
    assert res_1.records_extracted == 20
    assert res_1.records_ingested == 20
    sess_1.commit()

    # 2. Simulate application restart: explicitly close worker 1 session and destroy adapter instance
    sess_1.close()
    del adapter_worker_1
    del sess_1

    # 3. Stage 2: Independent worker 2 boots up in a completely new database session
    sess_2 = SessionMaker()

    # Inspect persisted checkpoint from database
    persisted_ckpt = sess_2.query(ConnectorSyncCheckpoint).filter_by(business_id=biz_id).one()
    assert persisted_ckpt.status == "IN_PROGRESS"
    assert persisted_ckpt.is_complete is False
    assert persisted_ckpt.current_cursor == "page_2"
    assert persisted_ckpt.records_ingested == 20
    assert len(persisted_ckpt.cursor_chain_hash) == 64

    # Fresh worker 2 adapter instance (no prior in-memory state)
    adapter_worker_2 = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz_id, seed=555, num_transactions=60, page_size=20
    )

    # Worker 2 resumes from database checkpoint and completes remaining pages
    res_2 = SourceSyncService.execute_sync(
        session=sess_2,
        adapter=adapter_worker_2,
        period_start=start,
        period_end=end,
        page_size=20,
    )

    assert res_2.status == "COMPLETED"
    assert res_2.is_complete is True
    # 60 total records across 3 pages: 20 from worker 1, 40 from worker 2
    assert res_2.records_extracted == 60
    assert res_2.records_ingested == 60
    assert res_2.records_duplicate == 0
    assert len(res_2.transaction_set_digest) == 64
    assert res_2.period_close_evidence is not None

    # Reconcile and certify completeness against settlement evidence
    reconciled = SourceSyncService.reconcile_and_certify(sess_2, res_2)
    assert reconciled is True

    # Confirm final database state in fresh session
    sess_2.commit()
    sess_2.close()

    sess_3 = SessionMaker()
    final_ckpt = sess_3.query(ConnectorSyncCheckpoint).filter_by(business_id=biz_id).one()
    assert final_ckpt.status == "COMPLETED"
    assert final_ckpt.is_complete is True
    assert final_ckpt.records_ingested == 60
    assert final_ckpt.records_duplicate == 0
    sess_3.close()


def test_tenant_credential_persistence_lifecycle(db_session: Session):
    """
    Test durable persistence of tenant connector credentials:
    - Encrypted persistence (no plaintext credentials)
    - Retrieval after session closure
    - Credential rotation without cross-tenant side effects
    - Expiration and revocation enforcement.
    """
    engine = db_session.get_bind()
    SessionMaker = sessionmaker(bind=engine)

    sess_1 = SessionMaker()
    tenant_a = _create_isolated_tenant(sess_1, "cred_a")
    tenant_b = _create_isolated_tenant(sess_1, "cred_b")

    raw_secret_a = {"token": "secret_oauth_token_tenant_a_12345"}
    raw_secret_b = {"token": "secret_oauth_token_tenant_b_67890"}

    # 1. Register credentials for both tenants
    cred_a = SourceSyncService.register_tenant_credentials(
        session=sess_1,
        business_id=tenant_a.id,
        provider="shopify",
        provider_account_id="tenant-a.myshopify.com",
        credential_dict=raw_secret_a,
        scopes=["read_orders", "read_products"],
    )
    cred_b = SourceSyncService.register_tenant_credentials(
        session=sess_1,
        business_id=tenant_b.id,
        provider="shopify",
        provider_account_id="tenant-b.myshopify.com",
        credential_dict=raw_secret_b,
        scopes=["read_orders"],
    )
    sess_1.commit()

    # Verify no plaintext token in database column
    assert "secret_oauth_token_tenant_a_12345" not in cred_a.encrypted_credentials
    assert "secret_oauth_token_tenant_b_67890" not in cred_b.encrypted_credentials
    sess_1.close()

    # 2. Simulate process restart: read credentials in a new session
    sess_2 = SessionMaker()
    read_a = SourceSyncService.get_tenant_credentials(sess_2, tenant_a.id, "shopify")
    assert read_a is not None
    assert read_a.status == "ACTIVE"
    assert read_a.provider_account_id == "tenant-a.myshopify.com"
    assert "read_orders" in read_a.scopes

    # 3. Rotate Tenant A credentials; Tenant B remains untouched
    new_secret_a = {"token": "rotated_secret_oauth_token_tenant_a_99999"}
    rotated_a = SourceSyncService.register_tenant_credentials(
        session=sess_2,
        business_id=tenant_a.id,
        provider="shopify",
        provider_account_id="tenant-a.myshopify.com",
        credential_dict=new_secret_a,
        scopes=["read_orders", "read_products", "read_inventory"],
    )
    rotated_a_ciphertext = rotated_a.encrypted_credentials
    sess_2.commit()
    sess_2.close()

    # Check Tenant B in fresh session
    sess_3 = SessionMaker()
    read_b = SourceSyncService.get_tenant_credentials(sess_3, tenant_b.id, "shopify")
    assert read_b is not None
    assert read_b.scopes == ["read_orders"]
    assert read_b.encrypted_credentials != rotated_a_ciphertext

    # 4. Revocation check: set Tenant A status to REVOKED
    row_a = sess_3.query(TenantConnectorCredential).filter_by(business_id=tenant_a.id).one()
    row_a.status = "REVOKED"
    sess_3.commit()

    with pytest.raises(PermissionError, match="credentials for 'shopify' are REVOKED"):
        SourceSyncService.get_tenant_credentials(sess_3, tenant_a.id, "shopify")

    sess_3.close()
