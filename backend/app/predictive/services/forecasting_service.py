"""Central ForecastingService orchestrating data extraction, validation, backtesting, and prediction."""

import calendar
import time
from datetime import UTC, date, datetime
from uuid import uuid4

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.predictive.data.quality import TimeSeriesQualityGate
from app.predictive.data.time_series import TimeSeriesPreparer
from app.predictive.evaluation.metrics import EvaluationMetrics
from app.predictive.forecasting.explanation import ForecastExplainer
from app.predictive.registry.model_registry import ModelRegistry
from app.predictive.schemas import (
    DataQualityStatus,
    ForecastDataQuality,
    ForecastEvidence,
    ForecastPredictionPoint,
    ForecastRequest,
    ForecastResult,
    ForecastStatus,
    ModelMetadata,
    ModelPolicy,
)
from app.rag.retrieval.retriever import HybridRetriever
from app.rag.semantic.ontology import semantic_resolver

logger = get_logger("app.predictive.service")


class ForecastingService:
    """
    Central orchestration service for Phase 7 Predictive Intelligence.
    Guarantees deterministic model selection, strict out-of-sample backtesting,
    probabilistically valid prediction intervals, and comprehensive provenance.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.registry = ModelRegistry()
        self.semantic_resolver = semantic_resolver
        self.retriever = HybridRetriever(session)

    def generate_forecast(
        self,
        target_metric: str = "revenue",
        frequency: str = "monthly",
        forecast_horizon: int = 3,
        entity_type: str | None = None,
        entity_id: str | None = None,
        model_policy: str = "validated_best",
        specific_model: str | None = None,
        confidence_level: float = 0.95,
        explanation_level: str = "manager",
        reference_date: date | None = None,
        query: str | None = None,
    ) -> ForecastResult:
        """Convenience keyword-based execution wrapper for forecast()."""
        pol = ModelPolicy(model_policy) if isinstance(model_policy, str) else model_policy
        req = ForecastRequest(
            query=query,
            target_metric=target_metric,
            forecast_horizon=forecast_horizon,
            frequency=frequency,
            entity_type=entity_type,
            entity_id=entity_id,
            model_policy=pol,
            specific_model=specific_model,
            confidence_level=confidence_level,
            explanation_level=explanation_level,
            reference_date=reference_date,
        )
        return self.forecast(req)

    def forecast(self, request: ForecastRequest) -> ForecastResult:
        """Execute end-to-end forecasting pipeline for a structured or natural language inquiry."""
        start_time = time.perf_counter()
        forecast_id = f"FCST-{uuid4().hex[:8].upper()}"

        # 1. Resolve Target Metric & Scope from Query if provided
        target = request.target_metric.lower().strip()
        entity_type = request.entity_type
        entity_id = request.entity_id

        if request.query:
            semantic_res = self.semantic_resolver.resolve(request.query)
            if semantic_res.resolved_kpi:
                target = semantic_res.resolved_kpi.canonical_name
            elif "demand" in request.query.lower() or "units" in request.query.lower():
                target = "units_sold"
            elif "order" in request.query.lower():
                target = "order_volume"

        horizon = request.forecast_horizon
        frequency = request.frequency.lower().strip()
        max_horizon = getattr(settings, "MAX_FORECAST_HORIZON", 12)

        # 2. Validate Horizon Boundary
        if horizon > max_horizon or horizon < 1:
            err_msg = f"Requested forecast horizon ({horizon}) exceeds maximum allowable limit ({max_horizon})."
            logger.warning(f"Forecasting {forecast_id} rejected: {err_msg}")
            empty_dq = ForecastDataQuality(
                status=DataQualityStatus.INVALID,
                observation_count=0,
                frequency=frequency,
                blocking_reasons=[err_msg],
            )
            empty_meta = ModelMetadata(name="none", model_type="none", is_baseline=True)
            empty_eval = EvaluationMetrics(mae=0.0, rmse=0.0, smape=0.0)
            empty_ev = ForecastEvidence(
                forecast_id=forecast_id,
                target_metric=target,
                training_range={"from": None, "to": None},
                forecast_horizon=horizon,
                frequency=frequency,
                model="none",
                validation_metrics=empty_eval,
                selected_model_rationale=err_msg,
                data_quality_status=DataQualityStatus.INVALID.value,
            )
            return ForecastResult(
                forecast_id=forecast_id,
                status=ForecastStatus.UNAVAILABLE,
                target_metric=target,
                frequency=frequency,
                training_period={"from": None, "to": None},
                forecast_period={"from": None, "to": None},
                model=empty_meta,
                predictions=[],
                evaluation=empty_eval,
                data_quality=empty_dq,
                evidence=empty_ev,
                limitations=[err_msg],
                explanation=f"### Forecast\nForecast unavailable: {err_msg}",
            )

        # 3. Extract Historical Telemetry
        series_df = TimeSeriesPreparer.extract_series(
            session=self.session,
            target_metric=target,
            frequency=frequency,
            entity_type=entity_type,
            entity_id=entity_id,
        )

        min_obs = (
            getattr(settings, "MIN_OBSERVATIONS_DAILY", 14)
            if frequency == "daily"
            else getattr(settings, "MIN_OBSERVATIONS_MONTHLY", 4)
        )

        # 4. Data Quality Gate
        data_quality, is_ready = TimeSeriesQualityGate.evaluate(
            df=series_df,
            frequency=frequency,
            min_observations=min_obs,
            date_col="period_label",
            value_col="value",
        )

        if not is_ready:
            scope_desc = f" for '{entity_id}'" if entity_id else ""
            reason = (
                f"Insufficient historical data to produce a reliable {frequency} forecast for {target}{scope_desc}. "
                f"Series contains {data_quality.observation_count} observations; minimum required is {min_obs}."
            )
            logger.info(f"Forecasting {forecast_id} halted: {reason}")
            empty_meta = ModelMetadata(name="none", model_type="none", is_baseline=True)
            empty_eval = EvaluationMetrics(mae=0.0, rmse=0.0, smape=0.0)
            empty_ev = ForecastEvidence(
                forecast_id=forecast_id,
                target_metric=target,
                training_range={"from": data_quality.date_from, "to": data_quality.date_to},
                forecast_horizon=horizon,
                frequency=frequency,
                model="none",
                validation_metrics=empty_eval,
                selected_model_rationale=reason,
                data_quality_status=data_quality.status.value,
                limitations=[reason] + data_quality.blocking_reasons,
            )
            return ForecastResult(
                forecast_id=forecast_id,
                status=ForecastStatus.UNAVAILABLE,
                target_metric=target,
                entity_type=entity_type,
                entity_id=entity_id,
                frequency=frequency,
                training_period={"from": data_quality.date_from, "to": data_quality.date_to},
                forecast_period={"from": None, "to": None},
                model=empty_meta,
                predictions=[],
                evaluation=empty_eval,
                data_quality=data_quality,
                evidence=empty_ev,
                limitations=[reason] + data_quality.blocking_reasons,
                explanation=f"### Forecast\nForecast unavailable: {reason}\n\n### Limitations\n- {reason}",
            )

        y_train = series_df["value"].to_numpy(dtype=np.float64)

        # 5. Model Selection via Out-of-Sample Backtesting
        model, eval_metrics, model_meta, _all_candidates = self.registry.select_best_model(
            y=y_train,
            target_metric=target,
            frequency=frequency,
            policy=request.model_policy,
            specific_model=request.specific_model,
        )

        # 6. Generate Out-of-Sample Predictions & Confidence Intervals
        point_preds = model.predict(horizon)
        lower_bounds, upper_bounds = model.get_prediction_intervals(
            horizon, confidence_level=request.confidence_level
        )

        # 7. Generate Chronological Future Intervals
        last_start_str = series_df["period_start"].iloc[-1]
        last_dt = pd.to_datetime(last_start_str)

        future_points: list[ForecastPredictionPoint] = []
        for h in range(1, horizon + 1):
            if frequency == "monthly":
                m_offset = last_dt.month + h
                year_offset = last_dt.year + (m_offset - 1) // 12
                month_num = ((m_offset - 1) % 12) + 1
                _, last_day = calendar.monthrange(year_offset, month_num)
                p_start = datetime(year_offset, month_num, 1, tzinfo=UTC)
                p_end = datetime(year_offset, month_num, last_day, 23, 59, 59, tzinfo=UTC)
                label = f"{year_offset}-{month_num:02d}"
            elif frequency == "weekly":
                p_start = last_dt + pd.Timedelta(weeks=h)
                p_end = p_start + pd.Timedelta(days=6, hours=23, minutes=59, seconds=59)
                label = p_start.strftime("%Y-W%U")
            else:  # daily
                p_start = last_dt + pd.Timedelta(days=h)
                p_end = p_start + pd.Timedelta(hours=23, minutes=59, seconds=59)
                label = p_start.strftime("%Y-%m-%d")

            pt_val = round(float(point_preds[h - 1]), 2)
            low_val = round(float(lower_bounds[h - 1]), 2)
            up_val = round(float(upper_bounds[h - 1]), 2)

            future_points.append(
                ForecastPredictionPoint(
                    period=label,
                    period_start=p_start.isoformat(),
                    period_end=p_end.isoformat(),
                    point_forecast=pt_val,
                    lower_bound=low_val,
                    upper_bound=up_val,
                    confidence_level=request.confidence_level,
                )
            )

        # 8. Retrieve Relevant Business Context RAG
        rag_context_text = None
        if request.query:
            try:
                rag_res = self.retriever.retrieve(query=f"{request.query} {target} forecast", top_k=2)
                rag_context_text = rag_res.context_text
            except Exception as e:  # noqa: BLE001
                logger.warning(f"RAG retrieval skipped in forecasting {forecast_id}: {e}")

        # 9. Formulate Assumptions, Limitations & Provenance Evidence
        assumptions = [
            f"Historical commercial patterns observed between {data_quality.date_from} and {data_quality.date_to} remain stationary.",
            "Transactional data captures completed and shipped operational sales only.",
            f"Prediction intervals are derived under a {int(request.confidence_level * 100)}% coverage distribution assumption.",
        ]

        limitations = [
            "Exogenous macroeconomic shocks, consumer inflation shifts, and unannounced competitor actions are unobserved.",
            f"Forecast extends {horizon} steps into the future; longer horizon intervals exhibit wider error distributions.",
        ]
        if data_quality.warnings:
            limitations.extend(data_quality.warnings)

        forecast_period = {
            "from": future_points[0].period if future_points else None,
            "to": future_points[-1].period if future_points else None,
        }

        training_period = {
            "from": data_quality.date_from,
            "to": data_quality.date_to,
        }

        evidence = ForecastEvidence(
            forecast_id=forecast_id,
            target_metric=target,
            training_range=training_period,
            forecast_horizon=horizon,
            frequency=frequency,
            model=model_meta.name,
            model_parameters=model_meta.parameters,
            validation_metrics=eval_metrics,
            selected_model_rationale=model_meta.selection_reason or "Lowest out-of-sample backtest error.",
            assumptions=assumptions,
            limitations=limitations,
            data_quality_status=data_quality.status.value,
        )

        # 10. Formulate Explanation Narrative adhering to Section 27 Schema
        explanation = ForecastExplainer.generate(
            target_metric=target,
            frequency=frequency,
            training_period=training_period,
            forecast_period=forecast_period,
            model=model_meta,
            predictions=future_points,
            evaluation=eval_metrics,
            data_quality=data_quality,
            assumptions=assumptions,
            limitations=limitations,
            rag_context_text=rag_context_text,
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            f"Forecast {forecast_id} for {target} ({horizon} {frequency} steps) completed in {elapsed_ms}ms "
            f"using {model_meta.name} (MAE=${eval_metrics.mae:,.2f})."
        )

        return ForecastResult(
            forecast_id=forecast_id,
            status=ForecastStatus.COMPLETED,
            target_metric=target,
            entity_type=entity_type,
            entity_id=entity_id,
            frequency=frequency,
            training_period=training_period,
            forecast_period=forecast_period,
            model=model_meta,
            predictions=future_points,
            evaluation=eval_metrics,
            data_quality=data_quality,
            evidence=evidence,
            assumptions=assumptions,
            limitations=limitations,
            explanation=explanation,
        )
