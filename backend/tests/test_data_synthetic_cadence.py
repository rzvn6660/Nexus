"""Tests for the Realistic Synthetic Customer Cadence Dataset Generator (Phase 1B.2)."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.analytics.core.context import AnalysisContext
from app.analytics.customer.cadence import CustomerCadenceAnalyzer
from app.analytics.customer.validation import HistoricalCadenceValidator
from app.data.synthetic.cadence_generator import (
    CadenceGeneratorConfig,
    CadenceValidationDatasetGenerator,
)
from sqlalchemy.orm import Session


def test_cadence_generator_reproducibility():
    """Verify that identical random seeds produce exact byte-for-byte identical datasets."""
    gen1 = CadenceValidationDatasetGenerator(seed=123)
    data1 = gen1.generate(CadenceGeneratorConfig(seed=123, num_customers=30, end_date=date(2023, 6, 30)))

    gen2 = CadenceValidationDatasetGenerator(seed=123)
    data2 = gen2.generate(CadenceGeneratorConfig(seed=123, num_customers=30, end_date=date(2023, 6, 30)))

    assert len(data1["customers"]) == len(data2["customers"])
    assert len(data1["sales"]) == len(data2["sales"])
    assert len(data1["sale_items"]) == len(data2["sale_items"])

    for c1, c2 in zip(data1["customers"], data2["customers"]):
        assert c1["customer_code"] == c2["customer_code"]
        assert c1["acquisition_date"] == c2["acquisition_date"]

    for s1, s2 in zip(data1["sales"], data2["sales"]):
        assert s1["transaction_number"] == s2["transaction_number"]
        assert s1["transaction_date"] == s2["transaction_date"]
        assert s1["created_at"] == s2["created_at"]
        assert s1["total_amount"] == s2["total_amount"]


def test_cadence_generator_different_seeds():
    """Verify that different random seeds generate distinct customer and transaction data."""
    gen1 = CadenceValidationDatasetGenerator(seed=42)
    data1 = gen1.generate(CadenceGeneratorConfig(seed=42, num_customers=30))

    gen2 = CadenceValidationDatasetGenerator(seed=999)
    data2 = gen2.generate(CadenceGeneratorConfig(seed=999, num_customers=30))

    assert data1["sales"][0]["total_amount"] != data2["sales"][0]["total_amount"]
    assert data1["sales"][0]["transaction_date"] != data2["sales"][0]["transaction_date"]


def test_cadence_generator_entity_counts_and_dates():
    """Verify entity counts, chronological consistency, and valid purchase date bounds."""
    cfg = CadenceGeneratorConfig(
        seed=42,
        num_customers=50,
        start_date=date(2022, 1, 1),
        end_date=date(2023, 12, 31),
    )
    gen = CadenceValidationDatasetGenerator(seed=42)
    data = gen.generate(cfg)

    customers = data["customers"]
    sales = data["sales"]
    sale_items = data["sale_items"]

    assert len(customers) == 50
    assert len(sales) >= 50  # Each customer has at least 1 order
    assert len(sale_items) >= len(sales)

    cust_acq_map = {c["id"]: c["acquisition_date"] for c in customers}

    for s in sales:
        c_acq = cust_acq_map[s["customer_id"]]
        tx_dt = s["transaction_date"]
        # Transaction event cannot precede customer acquisition date
        assert tx_dt.date() >= c_acq
        # Ingestion timestamp (created_at) must be at or after transaction event timestamp
        assert s["created_at"] >= tx_dt
        # Financial reconciliation
        assert s["total_amount"] > Decimal("0.00")
        assert s["subtotal"] > Decimal("0.00")


def test_one_time_buyer_share_calibration():
    """Verify that one_time_buyer_pct parameter is respected within statistical tolerance."""
    cfg = CadenceGeneratorConfig(
        seed=101,
        num_customers=100,
        one_time_buyer_pct=0.45,
    )
    gen = CadenceValidationDatasetGenerator(seed=101)
    data = gen.generate(cfg)

    one_time_share = data["metadata"]["one_time_buyers_share"]
    # Check within +/- 10% tolerance (0.35 to 0.55)
    assert 0.35 <= one_time_share <= 0.55


def test_customer_specific_cadence_and_renewal_variation():
    """Verify that frequent vs long-cycle archetypes exhibit distinct inter-purchase intervals."""
    cfg = CadenceGeneratorConfig(
        seed=42,
        num_customers=120,
        start_date=date(2022, 1, 1),
        end_date=date(2023, 12, 31),
        one_time_buyer_pct=0.0,  # All repeat buyers
    )
    gen = CadenceValidationDatasetGenerator(seed=42)
    data = gen.generate(cfg)

    sales = data["sales"]
    customers = data["customers"]

    # Compute customer-level mean interval
    cust_txns: dict[int, list[datetime]] = {c["id"]: [] for c in customers}
    for s in sales:
        cust_txns[s["customer_id"]].append(s["transaction_date"])

    intervals_by_cust: dict[int, float] = {}
    for cid, dates in cust_txns.items():
        if len(dates) >= 2:
            dates.sort()
            diffs = [(dates[i + 1] - dates[i]).total_seconds() / 86400.0 for i in range(len(dates) - 1)]
            intervals_by_cust[cid] = sum(diffs) / len(diffs)

    # Some customers should have short cadences (< 20d) and some long (> 60d)
    short_cadences = [m for m in intervals_by_cust.values() if m < 20.0]
    long_cadences = [m for m in intervals_by_cust.values() if m > 60.0]

    assert len(short_cadences) > 0
    assert len(long_cadences) > 0


def test_ingestion_delay_simulation_and_created_at_separation():
    """Verify that created_at models pipeline latency after transaction_date."""
    cfg = CadenceGeneratorConfig(
        seed=777,
        num_customers=40,
        mean_ingestion_delay_days=3.0,
        tail_delay_prob=0.15,
        tail_delay_max_days=14.0,
    )
    gen = CadenceValidationDatasetGenerator(seed=777)
    data = gen.generate(cfg)

    delays_hours = []
    for s in data["sales"]:
        delay = (s["created_at"] - s["transaction_date"]).total_seconds() / 3600.0
        assert delay >= 0.0
        delays_hours.append(delay)

    mean_delay_days = (sum(delays_hours) / len(delays_hours)) / 24.0
    # Mean delay should be in expected range (around 3 to 6 days due to tail)
    assert 2.0 <= mean_delay_days <= 7.0
    # At least some sales should experience tail delay > 7 days (168 hours)
    has_tail_delay = any(d > 168.0 for d in delays_hours)
    assert has_tail_delay is True


def test_scenario_complete_pipeline_execution(db_session: Session):
    """
    Load complete_pipeline scenario into database and evaluate with HistoricalCadenceValidator.
    Verifies that the entire pipeline executes and produces valid validation results.
    """
    dataset = CadenceValidationDatasetGenerator.create_scenario("complete_pipeline", seed=42)
    CadenceValidationDatasetGenerator.load_into_session(
        session=db_session, dataset=dataset, business_id="biz-complete-pipe"
    )

    ctx = AnalysisContext(business_id="biz-complete-pipe")
    cutoff = datetime(2023, 6, 30, 23, 59, tzinfo=UTC)

    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
    )

    assert result.total_customers_evaluated > 50
    assert result.scored_customers_count > 0
    assert result.insufficient_history_count > 0  # One-time buyers are tracked
    assert result.is_complete_followup is True
    assert result.baseline_no_purchase_rate is not None
    assert "critical" in result.confusion_matrices
    assert "high_critical" in result.confusion_matrices


def test_scenario_delayed_ingestion_with_valid_watermark(db_session: Session):
    """
    Verify that an authoritative ingestion watermark verifies complete follow-up
    even when delayed ingestion records are present.
    """
    dataset = CadenceValidationDatasetGenerator.create_scenario(
        "delayed_ingestion_valid_watermark", seed=101
    )
    CadenceValidationDatasetGenerator.load_into_session(
        session=db_session, dataset=dataset, business_id="biz-delayed-wm"
    )

    ctx = AnalysisContext(business_id="biz-delayed-wm")
    cutoff = datetime(2023, 4, 30, 23, 59, tzinfo=UTC)
    # Outcome window: May 7 to July 6
    # Authoritative watermark at Dec 31, 2023
    wm = datetime(2023, 12, 31, 23, 59, tzinfo=UTC)

    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
        ingestion_watermark=wm,
    )

    assert result.is_complete_followup is True
    assert result.is_followup_verified is True
    assert result.followup_status == "verified_complete"
    assert result.censoring_reason is None


def test_scenario_incomplete_future_followup_censoring(db_session: Session):
    """
    Verify that when dataset ends early (March 15, 2023), evaluating a cutoff on March 1
    with 60-day horizon is cleanly flagged as right-censored.
    """
    dataset = CadenceValidationDatasetGenerator.create_scenario(
        "incomplete_future_followup", seed=202
    )
    CadenceValidationDatasetGenerator.load_into_session(
        session=db_session, dataset=dataset, business_id="biz-incomplete-censored"
    )

    ctx = AnalysisContext(business_id="biz-incomplete-censored")
    cutoff = datetime(2023, 3, 1, 23, 59, tzinfo=UTC)

    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
    )

    assert result.is_complete_followup is False
    assert result.followup_status == "incomplete_censored"
    assert "precedes outcome window end" in result.censoring_reason


def test_scenario_cross_tenant_isolation(db_session: Session):
    """
    Verify strict tenant isolation across biz-alpha and biz-beta generated in the cross_tenant scenario.
    """
    dataset = CadenceValidationDatasetGenerator.create_scenario("cross_tenant", seed=42)

    # Separate loads by tenant
    sales_a = [s for s in dataset["sales"] if s["business_id"] == "biz-alpha"]
    sales_b = [s for s in dataset["sales"] if s["business_id"] == "biz-beta"]
    cust_a = [c for c in dataset["customers"] if c["business_id"] == "biz-alpha"]
    cust_b = [c for c in dataset["customers"] if c["business_id"] == "biz-beta"]

    ds_a = {
        "customers": cust_a,
        "products": dataset["products"],
        "sales": sales_a,
        "sale_items": [it for it in dataset["sale_items"] if it["sale_id"] in {s["id"] for s in sales_a}],
        "metadata": {"business_id": "biz-alpha"},
    }
    ds_b = {
        "customers": cust_b,
        "products": dataset["products"],
        "sales": sales_b,
        "sale_items": [it for it in dataset["sale_items"] if it["sale_id"] in {s["id"] for s in sales_b}],
        "metadata": {"business_id": "biz-beta"},
    }

    CadenceValidationDatasetGenerator.load_into_session(db_session, ds_a, business_id="biz-alpha")
    CadenceValidationDatasetGenerator.load_into_session(db_session, ds_b, business_id="biz-beta")

    ctx_a = AnalysisContext(business_id="biz-alpha")
    as_of = datetime(2023, 12, 31, 23, 59, tzinfo=UTC)
    cadence_summary_a = CustomerCadenceAnalyzer.evaluate(
        session=db_session, context=ctx_a, as_of_date=as_of
    )

    # All 50 biz-alpha customers acquired by Dec 31, 2023 are evaluated
    assert cadence_summary_a.total_customers_evaluated == len(cust_a)
    for r in cadence_summary_a.records:
        assert r.customer_code.startswith("CUST-SYNTH-")
        # Ensure no biz-beta records leaked into biz-alpha
        assert not r.customer_code.startswith("CUST-BETA-")


def test_scenario_seasonal_and_long_cycle_behavior(db_session: Session):
    """Verify seasonal and long-cycle customer behavior generation and archetype overrides."""
    data_seasonal = CadenceValidationDatasetGenerator.create_scenario("seasonal_active", seed=42)
    data_long = CadenceValidationDatasetGenerator.create_scenario("long_cycle_short_horizon", seed=42)

    assert len(data_seasonal["customers"]) == 100
    assert len(data_long["customers"]) == 100

    # Verify custom archetype weights were applied to the scenario
    seasonal_dist = data_seasonal["metadata"]["archetype_distribution"]
    long_dist = data_long["metadata"]["archetype_distribution"]

    assert seasonal_dist["seasonal"] >= 40, f"Expected >= 40 seasonal customers, got {seasonal_dist}"
    assert long_dist["long_cycle"] >= 40, f"Expected >= 40 long-cycle customers, got {long_dist}"


def test_robustness_seeds_multi_seed_generation():
    """Verify multi-seed robustness scenario generates distinct datasets for all specified seeds."""
    robustness_data = CadenceValidationDatasetGenerator.create_scenario("robustness_seeds")
    scenarios_by_seed = robustness_data["scenarios_by_seed"]

    assert len(scenarios_by_seed) == 4
    for s in [42, 101, 777, 999]:
        assert s in scenarios_by_seed
        assert len(scenarios_by_seed[s]["customers"]) == 80
        assert len(scenarios_by_seed[s]["sales"]) > 0
