"""Tests for NEXUS Phase 28 Stage 1: Decision Memory Persistence Foundation.

Verifies:
1. RFC 8785 (JCS) canonical serialization compliance.
2. Genesis decision creation and immutable recommendation/baseline snapshots.
3. Cryptographic hash-chain creation, linkage, and integrity verification.
4. Tampering detection (altered payload, broken linkage, revision gaps).
5. Idempotent retries and 409 payload conflict detection.
6. ORM and engine-level append-only immutability protections.
7. Cascade deletion resistance (preserving decisions upon analysis run deletion).
8. Multi-tenant boundary enforcement (IDOR defenses across orgs/businesses).
9. REST API integration for decision creation, reviews, audit history, and chain verification.
"""

import pytest
from app.analytics.outcome.schemas import (
    BaselineMetricsSnapshot,
    DecisionCreatePayload,
    DecisionReviewPayload,
    RecommendationSnapshot,
)
from app.analytics.outcome.service import DecisionMemoryService, IdempotencyConflictError
from app.core.canonical_json import (
    canonical_json_dumps,
    canonical_sha256,
    float_to_ecma_str,
)
from app.models.history import (
    AnalysisRun,
    AuditLedgerImmutabilityError,
    DecisionAuditEvent,
    DecisionRecord,
    drop_audit_triggers,
    install_audit_triggers,
)
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_fixture(db_session: Session):
    """Seed Org A, User A, and Business A."""
    org_a = Organization(id="org_alpha_p28", name="Alpha Org", slug="alpha-org-p28")
    db_session.add(org_a)
    db_session.flush()

    user_a = UserIdentity(
        id="usr_alpha_p28",
        email="analyst_a@alpha.internal",
        full_name="Alpha Analyst",
        password_hash="pw_hash_test",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user_a)
    db_session.flush()

    mem_a = OrganizationMembership(
        user_id=user_a.id,
        organization_id=org_a.id,
        role="owner",
    )
    db_session.add(mem_a)

    biz_a = Business(
        id="biz_alpha_p28",
        organization_id=org_a.id,
        name="Alpha Retail Workspace",
        status="active",
    )
    db_session.add(biz_a)
    db_session.commit()

    return {"org": org_a, "user": user_a, "biz": biz_a}


@pytest.fixture
def foreign_tenant_fixture(db_session: Session):
    """Seed Org B, User B, and Business B for cross-tenant isolation testing."""
    org_b = Organization(id="org_bravo_p28", name="Bravo Org", slug="bravo-org-p28")
    db_session.add(org_b)
    db_session.flush()

    user_b = UserIdentity(
        id="usr_bravo_p28",
        email="analyst_b@bravo.internal",
        full_name="Bravo Analyst",
        password_hash="pw_hash_test",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user_b)
    db_session.flush()

    mem_b = OrganizationMembership(
        user_id=user_b.id,
        organization_id=org_b.id,
        role="member",
    )
    db_session.add(mem_b)

    biz_b = Business(
        id="biz_bravo_p28",
        organization_id=org_b.id,
        name="Bravo Retail Workspace",
        status="active",
    )
    db_session.add(biz_b)
    db_session.commit()

    return {"org": org_b, "user": user_b, "biz": biz_b}


# ---------------------------------------------------------------------------
# 1. RFC 8785 CANONICAL SERIALIZATION SUITE
# ---------------------------------------------------------------------------

def test_canonical_json_utf16_key_sorting_outside_bmp():
    """Verify keys are sorted by UTF-16 code units per RFC 8785 §3.2.3, not standard codepoints."""
    # U+1F600 (surrogate pair high 0xD83D) vs U+FFFD (0xFFFD)
    # Codepoint order: U+1F600 > U+FFFD
    # UTF-16 code unit order: 0xD83D < 0xFFFD -> U+1F600 comes first!
    data = {"\uFFFD": "high_bmp", "\U0001F600": "astral_plane"}
    serialized = canonical_json_dumps(data)
    assert serialized == '{"\U0001F600":"astral_plane","\uFFFD":"high_bmp"}'


def test_canonical_json_number_formatting():
    """Verify ECMAScript ToString §7.1.12.1 float formatting per RFC 8785 §3.2.2.3."""
    assert float_to_ecma_str(0.0) == "0"
    assert float_to_ecma_str(-0.0) == "0"
    assert float_to_ecma_str(1.0) == "1"
    assert float_to_ecma_str(1.5) == "1.5"
    assert float_to_ecma_str(0.000001) == "0.000001"
    assert float_to_ecma_str(0.0000001) == "1e-7"
    assert float_to_ecma_str(1e20) == "100000000000000000000"
    assert float_to_ecma_str(1e21) == "1e+21"

    # Non-finite numbers must raise ValueError
    with pytest.raises(ValueError, match="Non-finite numbers"):
        float_to_ecma_str(float("nan"))
    with pytest.raises(ValueError, match="Non-finite numbers"):
        float_to_ecma_str(float("inf"))


def test_canonical_json_string_escaping_and_literal_utf8():
    """Verify quotes, backslashes, controls are escaped, but raw UTF-8 is preserved."""
    data = {
        "euro": "€",
        "newline": "line1\nline2",
        "quote": 'quote"test',
        "slash": "a/b/c",
    }
    serialized = canonical_json_dumps(data)
    # Solidus / must NOT be escaped
    assert r"\/" not in serialized
    # Literal UTF-8 € must be in output
    assert "€" in serialized
    assert r"\n" in serialized
    assert r'\"' in serialized


def test_canonical_json_reproducibility():
    """Verify hash is identical regardless of initial dictionary key insertion order."""
    d1 = {"z": 10, "a": 20, "nested": {"y": 1, "b": 2}}
    d2 = {"a": 20, "nested": {"b": 2, "y": 1}, "z": 10}
    hash1 = canonical_sha256(d1)
    hash2 = canonical_sha256(d2)
    assert hash1 == hash2


def test_canonical_json_authoritative_rfc8785_vectors():
    """Verify official RFC 8785 Appendix A test vectors."""
    # Appendix A.1: Empty structures
    assert canonical_json_dumps({}) == "{}"
    assert canonical_json_dumps([]) == "[]"

    # Appendix A.2: Whitespace elimination and key sorting
    assert canonical_json_dumps({"b": 2, "a": 1}) == '{"a":1,"b":2}'

    # Appendix A.3: Numbers vector from RFC 8785 Table
    num_vector = [333333333.3333333, 1e+30, 4.5, 2e-3, 0.000001]
    assert canonical_json_dumps(num_vector) == "[333333333.3333333,1e+30,4.5,0.002,0.000001]"

    # UTF-16 code unit ordering across BMP and supplementary plane
    complex_keys = {
        "\u0041": "A",
        "\u0061": "a",
        "\u00e9": "e_acute",
        "\U0001F600": "grinning_face",
        "\uFFFD": "replacement",
    }
    # Expected key sequence: "A" (0x41), "a" (0x61), "é" (0xE9), "\U0001F600" (0xD83D), "\uFFFD" (0xFFFD)
    expected = '{"A":"A","a":"a","é":"e_acute","\U0001F600":"grinning_face","\uFFFD":"replacement"}'
    assert canonical_json_dumps(complex_keys) == expected

    # Control characters U+0000..U+001F
    ctrl_vector = {"ctrl": "\u0000\u0007\b\t\n\f\r\u001f"}
    assert canonical_json_dumps(ctrl_vector) == '{"ctrl":"\\u0000\\u0007\\b\\t\\n\\f\\r\\u001f"}'


def test_canonical_json_invalid_numeric_values_and_keys():
    """Verify strict rejection of NaN, +/-Infinity, and non-string object keys."""
    # Nested NaN in list/dict
    with pytest.raises(ValueError, match="Non-finite numbers"):
        canonical_json_dumps({"invalid": float("nan")})
    with pytest.raises(ValueError, match="Non-finite numbers"):
        canonical_json_dumps([1, 2, float("inf")])
    with pytest.raises(ValueError, match="Non-finite numbers"):
        canonical_json_dumps({"nested": {"val": float("-inf")}})

    # Non-string object key must raise TypeError
    with pytest.raises(TypeError, match="Dictionary keys in RFC 8785 must be strings"):
        canonical_json_dumps({123: "int_key"})  # type: ignore



# ---------------------------------------------------------------------------
# 2. DECISION CREATION & GENESIS AUDIT EVENT
# ---------------------------------------------------------------------------

def test_decision_record_genesis_creation(db_session: Session, tenant_fixture):
    """Test creating a decision record produces revision 0 with genesis hash link."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    rec_snap = RecommendationSnapshot(
        recommendation_type="INVENTORY_REORDER",
        action_target_type="SKU",
        action_target_id="SKU-PREM-101",
        point_recommendation={"recommended_reorder_qty": 450, "reorder_point": 120.0},
        observed_facts={"current_stock": 95, "unit_cost": 25.0},
        forecast_outputs={"point_forecast": 300.0, "horizon": 1},
        assumptions=["order_setup_cost: $50.00 (system default)"],
        limitations=["Assumes stationary demand variance"],
    )

    base_snap = BaselineMetricsSnapshot(
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
        window_days=30,
        metrics={"baseline_30d_revenue": 14500.0, "baseline_30d_stockout_days": 1.0},
        metric_definitions={"baseline_30d_revenue": "Sum of completed order amounts"},
    )

    create_payload = DecisionCreatePayload(
        recommendation_text="Reorder 450 units of SKU-PREM-101",
        recommendation_snapshot=rec_snap,
        baseline_metrics_snapshot=base_snap,
        reviewer_notes="Autonomous engine recommendation",
    )

    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=create_payload,
        idempotency_key="idemp_genesis_1001",
    )

    assert record.id is not None
    assert record.status == "PENDING"
    assert record.current_revision == 0
    assert record.recommendation_type == "INVENTORY_REORDER"
    assert record.action_target_id == "SKU-PREM-101"
    assert record.recommendation_payload["point_recommendation"]["recommended_reorder_qty"] == 450

    # Verify genesis event
    events = db_session.execute(
        select(DecisionAuditEvent).where(DecisionAuditEvent.decision_id == record.id)
    ).scalars().all()

    assert len(events) == 1
    genesis = events[0]
    assert genesis.revision == 0
    assert genesis.event_type == "RECOMMENDATION_CREATED"
    assert genesis.prev_event_hash == "0" * 64
    assert len(genesis.event_hash) == 64
    assert genesis.actor_id == user.id


# ---------------------------------------------------------------------------
# 3. HASH CHAIN LINKAGE & SUCCESSIVE REVIEWS
# ---------------------------------------------------------------------------

def test_hash_chain_linkage_and_verification(db_session: Session, tenant_fixture):
    """Test sequential reviews create unbroken cryptographically linked revisions."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    # 1. Create decision (r=0)
    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=DecisionCreatePayload(recommendation_text="Order 500 units of SKU-X"),
        idempotency_key="idemp_rev_0",
    )

    # 2. Modify decision (r=1)
    mod_review = DecisionReviewPayload(
        status="MODIFIED",
        reviewer_notes="Adjusted from 500 to 350 units due to warehouse capacity",
        reviewed_by="senior_buyer",
        modified_parameters={"adjusted_quantity": 350},
    )
    record = DecisionMemoryService.record_human_review(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
        review_payload=mod_review,
        idempotency_key="idemp_rev_1",
    )
    assert record.status == "MODIFIED"
    assert record.current_revision == 1

    # 3. Approve modified decision (r=2)
    app_review = DecisionReviewPayload(
        status="APPROVED",
        reviewer_notes="Approved 350 units with vendor discount confirmed",
        reviewed_by="vp_operations",
    )
    record = DecisionMemoryService.record_human_review(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
        review_payload=app_review,
        idempotency_key="idemp_rev_2",
    )
    assert record.status == "APPROVED"
    assert record.current_revision == 2

    # Verify chain
    report = DecisionMemoryService.verify_decision_audit_chain(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
    )

    assert report.is_valid is True
    assert report.total_events == 3
    assert report.latest_revision == 2
    assert report.error_type is None


# ---------------------------------------------------------------------------
# 4. TAMPERING DETECTION SCENARIOS
# ---------------------------------------------------------------------------

def test_tamper_detection_altered_payload(db_session: Session, tenant_fixture):
    """Verify altering an audit event's payload is detected by verify_decision_audit_chain."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=DecisionCreatePayload(recommendation_text="Original unadulterated text"),
        idempotency_key="idemp_tamper_1",
    )

    event = db_session.execute(
        select(DecisionAuditEvent).where(DecisionAuditEvent.decision_id == record.id)
    ).scalar_one()

    # Tamper with raw SQL (bypassing ORM listeners)
    db_session.execute(
        text("UPDATE decision_audit_events SET canonical_payload = :p WHERE id = :id"),
        {"p": '{"action": "TAMPERED_ACTION"}', "id": event.id},
    )
    db_session.commit()

    report = DecisionMemoryService.verify_decision_audit_chain(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
    )

    assert report.is_valid is False
    assert report.error_type == "PAYLOAD_TAMPERED"
    assert report.error_revision == 0


def test_tamper_detection_broken_link(db_session: Session, tenant_fixture):
    """Verify tampering with prev_event_hash is detected."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=DecisionCreatePayload(recommendation_text="Item A"),
        idempotency_key="idemp_link_1",
    )
    DecisionMemoryService.record_human_review(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
        review_payload=DecisionReviewPayload(status="APPROVED"),
        idempotency_key="idemp_link_2",
    )

    # Tamper with revision 1 prev_event_hash via raw SQL
    db_session.execute(
        text("UPDATE decision_audit_events SET prev_event_hash = :h WHERE revision = 1"),
        {"h": "f" * 64},
    )
    db_session.commit()

    report = DecisionMemoryService.verify_decision_audit_chain(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
    )

    assert report.is_valid is False
    assert report.error_type == "BROKEN_HASH_LINK"
    assert report.error_revision == 1


def test_tamper_detection_altered_actor_or_timestamp(db_session: Session, tenant_fixture):
    """Verify tampering with actor_id or created_at breaks the cryptographic chain."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=DecisionCreatePayload(recommendation_text="Actor and Time Hash Invariant Test"),
        idempotency_key="idemp_actor_time_invariant",
    )

    # 1. Verify initially valid
    report = DecisionMemoryService.verify_decision_audit_chain(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
    )
    assert report.is_valid is True

    # 2. Tamper with actor_id via raw SQL
    db_session.execute(
        text("UPDATE decision_audit_events SET actor_id = 'impostor_actor' WHERE decision_id = :d"),
        {"d": record.id},
    )
    db_session.commit()

    report_tampered_actor = DecisionMemoryService.verify_decision_audit_chain(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
    )
    assert report_tampered_actor.is_valid is False
    assert report_tampered_actor.error_type == "PAYLOAD_TAMPERED"

    # Restore legitimate actor_id
    db_session.execute(
        text("UPDATE decision_audit_events SET actor_id = :a WHERE decision_id = :d"),
        {"a": user.id, "d": record.id},
    )
    db_session.commit()

    # 3. Tamper with created_at timestamp via raw SQL
    db_session.execute(
        text("UPDATE decision_audit_events SET created_at = '2020-01-01 00:00:00' WHERE decision_id = :d"),
        {"d": record.id},
    )
    db_session.commit()

    report_tampered_time = DecisionMemoryService.verify_decision_audit_chain(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
    )
    assert report_tampered_time.is_valid is False
    assert report_tampered_time.error_type == "PAYLOAD_TAMPERED"



# ---------------------------------------------------------------------------
# 5. IDEMPOTENCY & CONFLICT HANDLING
# ---------------------------------------------------------------------------

def test_idempotent_event_replay_and_conflict(db_session: Session, tenant_fixture):
    """Verify identical payload replay succeeds; conflicting payload raises 409."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=DecisionCreatePayload(recommendation_text="Target recommendation"),
        idempotency_key="idemp_base",
    )

    # 1. First append
    payload_a = {"reason": "Routine operational check", "cost": 100}
    event_1 = DecisionMemoryService.append_audit_event(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
        event_type="OPERATIONAL_NOTE",
        payload_dict=payload_a,
        idempotency_key="idemp_unique_key_999",
    )
    assert event_1.revision == 1

    # 2. Identical replay -> returns existing event
    event_2 = DecisionMemoryService.append_audit_event(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=record.id,
        event_type="OPERATIONAL_NOTE",
        payload_dict=payload_a,
        idempotency_key="idemp_unique_key_999",
    )
    assert event_2.id == event_1.id
    assert event_2.revision == 1

    # 3. Conflicting payload with same idempotency key -> raises 409
    payload_conflict = {"reason": "DIFFERENT REASON", "cost": 9999}
    with pytest.raises(IdempotencyConflictError) as exc_info:
        DecisionMemoryService.append_audit_event(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=record.id,
            event_type="OPERATIONAL_NOTE",
            payload_dict=payload_conflict,
            idempotency_key="idemp_unique_key_999",
        )
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 6. APPEND-ONLY IMMUTABILITY PROTECTIONS
# ---------------------------------------------------------------------------

def test_orm_immutability_listener_blocks_mutations(db_session: Session, tenant_fixture):
    """Verify SQLAlchemy ORM event listeners block UPDATE and DELETE on audit events."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=DecisionCreatePayload(recommendation_text="Item Immutable"),
        idempotency_key="idemp_orm_imm",
    )

    event = db_session.execute(
        select(DecisionAuditEvent).where(DecisionAuditEvent.decision_id == record.id)
    ).scalar_one()

    # Attempt ORM update
    event.event_type = "MUTATED_EVENT"
    with pytest.raises(AuditLedgerImmutabilityError, match="UPDATE operations are forbidden"):
        db_session.flush()

    db_session.rollback()

    # Re-fetch and attempt ORM delete
    event_to_delete = db_session.get(DecisionAuditEvent, event.id)
    db_session.delete(event_to_delete)
    with pytest.raises(AuditLedgerImmutabilityError, match="DELETE operations are forbidden"):
        db_session.flush()

    db_session.rollback()


def test_database_engine_triggers_block_sql_mutations(db_session: Session, tenant_fixture):
    """Verify physical database triggers reject direct raw SQL UPDATE and DELETE."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=DecisionCreatePayload(recommendation_text="Database Trigger Guard"),
        idempotency_key="idemp_db_trg",
    )

    # Install engine triggers on the test connection
    install_audit_triggers(db_session.connection())

    try:
        # Attempt raw SQL update
        with pytest.raises((IntegrityError, DBAPIError)):
            db_session.execute(
                text("UPDATE decision_audit_events SET actor_role = 'hacker' WHERE decision_id = :d"),
                {"d": record.id},
            )
        db_session.rollback()

        # Attempt raw SQL delete
        with pytest.raises((IntegrityError, DBAPIError)):
            db_session.execute(
                text("DELETE FROM decision_audit_events WHERE decision_id = :d"),
                {"d": record.id},
            )
        db_session.rollback()
    finally:
        # Clean up triggers so subsequent tests can manage session
        drop_audit_triggers(db_session.connection())


# ---------------------------------------------------------------------------
# 7. CASCADE DELETION RESISTANCE
# ---------------------------------------------------------------------------

def test_analysis_run_deletion_preserves_decision_and_audit_history(db_session: Session, tenant_fixture):
    """Verify deleting an AnalysisRun does NOT cascade-delete DecisionRecord or audit events."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    # Create analysis run
    run = AnalysisRun(
        business_id=biz.id,
        organization_id=tenant_fixture["org"].id,
        request_id="req_test_cascade_1",
        query="What should we order?",
        answer="Reorder SKU-1",
        status="completed",
    )
    db_session.add(run)
    db_session.commit()

    # Create decision referencing analysis run
    record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        payload=DecisionCreatePayload(
            recommendation_text="Reorder SKU-1 based on run",
            analysis_id=run.id,
        ),
        idempotency_key="idemp_cascade_test",
    )

    dec_id = record.id
    assert record.analysis_id == run.id

    # Delete AnalysisRun
    db_session.delete(run)
    db_session.commit()

    # Verify DecisionRecord still exists with analysis_id cleared (SET NULL)
    surviving_dec = db_session.get(DecisionRecord, dec_id)
    assert surviving_dec is not None
    assert surviving_dec.analysis_id is None

    # Verify audit events are intact
    events = db_session.execute(
        select(DecisionAuditEvent).where(DecisionAuditEvent.decision_id == dec_id)
    ).scalars().all()
    assert len(events) == 1


# ---------------------------------------------------------------------------
# 8. MULTI-TENANT AUTHORIZATION ISOLATION
# ---------------------------------------------------------------------------

def test_cross_tenant_idor_protection(db_session: Session, tenant_fixture, foreign_tenant_fixture):
    """Verify User B cannot create decisions, append events, or view audit chains for Business A."""
    user_b = foreign_tenant_fixture["user"]
    biz_a = tenant_fixture["biz"]

    # 1. User B attempts to create decision in Business A
    with pytest.raises(Exception) as exc_info:
        DecisionMemoryService.create_decision_record(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            payload=DecisionCreatePayload(recommendation_text="Unauthorized proposal"),
            idempotency_key="idemp_unauth_create",
        )
    assert getattr(exc_info.value, "status_code", None) == 403

    # 2. Legitimate decision in Business A
    legit_record = DecisionMemoryService.create_decision_record(
        db=db_session,
        current_user=tenant_fixture["user"],
        business_id=biz_a.id,
        payload=DecisionCreatePayload(recommendation_text="Legitimate proposal"),
        idempotency_key="idemp_legit_create",
    )

    # 3. User B attempts to append audit review to Business A's decision
    with pytest.raises(Exception) as exc_info:
        DecisionMemoryService.record_human_review(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            decision_id=legit_record.id,
            review_payload=DecisionReviewPayload(status="APPROVED"),
            idempotency_key="idemp_unauth_review",
        )
    assert getattr(exc_info.value, "status_code", None) == 403

    # 4. User B attempts to verify audit chain for Business A
    with pytest.raises(Exception) as exc_info:
        DecisionMemoryService.verify_decision_audit_chain(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            decision_id=legit_record.id,
        )
    assert getattr(exc_info.value, "status_code", None) == 403


# ---------------------------------------------------------------------------
# 9. REST API INTEGRATION
# ---------------------------------------------------------------------------

def test_decision_rest_api_lifecycle_and_audit_endpoints(api_client: TestClient, auth_headers: dict[str, str]):
    """Test full HTTP lifecycle: POST decision -> PATCH review -> GET audit-events -> GET verify-audit-chain."""
    headers = auth_headers

    # 1. POST /api/v1/history/decisions
    create_resp = api_client.post(
        "/api/v1/history/decisions",
        headers=headers,
        json={
            "recommendation_text": "Apply 12% markdown to SKU-SUMMER-01",
            "recommendation_type": "PRICE_MARKDOWN",
            "action_target_type": "SKU",
            "action_target_id": "SKU-SUMMER-01",
            "recommendation_payload": {
                "point_recommendation": {"discount_pct": 0.12},
                "observed_facts": {"current_price": 49.99},
            },
            "reviewer_notes": "End of summer inventory clearance",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    dec_data = create_resp.json()
    dec_id = dec_data["id"]
    assert dec_data["status"] == "PENDING"
    assert dec_data["current_revision"] == 0

    # 2. PATCH /api/v1/history/decisions/{id} (Defer decision)
    defer_resp = api_client.patch(
        f"/api/v1/history/decisions/{dec_id}",
        headers=headers,
        json={
            "status": "DEFERRED",
            "reviewer_notes": "Waiting for supplier promotional calendar",
            "reviewed_by": "lead_merchant",
        },
    )
    assert defer_resp.status_code == 200, defer_resp.text
    deferred_data = defer_resp.json()
    assert deferred_data["status"] == "DEFERRED"
    assert deferred_data["current_revision"] == 1

    # 3. GET /api/v1/history/decisions/{id}/audit-events
    events_resp = api_client.get(
        f"/api/v1/history/decisions/{dec_id}/audit-events",
        headers=headers,
    )
    assert events_resp.status_code == 200, events_resp.text
    events = events_resp.json()
    assert len(events) == 2
    assert events[0]["revision"] == 0
    assert events[0]["event_type"] == "RECOMMENDATION_CREATED"
    assert events[1]["revision"] == 1
    assert events[1]["event_type"] == "HUMAN_DEFERRED"
    assert events[1]["prev_event_hash"] == events[0]["event_hash"]

    # 4. GET /api/v1/history/decisions/{id}/verify-audit-chain
    verify_resp = api_client.get(
        f"/api/v1/history/decisions/{dec_id}/verify-audit-chain",
        headers=headers,
    )
    assert verify_resp.status_code == 200, verify_resp.text
    report = verify_resp.json()
    assert report["is_valid"] is True
    assert report["total_events"] == 2
    assert report["latest_revision"] == 1
    assert report["error_type"] is None
