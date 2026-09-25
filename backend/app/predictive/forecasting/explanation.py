"""Forecast explanation formulation adhering strictly to the Section 27 schema."""

from app.investigation.validators import CausalitySafeguard
from app.predictive.schemas import (
    EvaluationMetrics,
    ForecastDataQuality,
    ForecastPredictionPoint,
    ModelMetadata,
)


class ForecastExplainer:
    """
    Constructs transparent, evidence-backed forecast narratives adhering strictly
    to the 7 required sections without prescriptive recommendations.
    """

    @classmethod
    def explain(
        cls,
        target_metric: str,
        frequency: str,
        model: ModelMetadata,
        predictions: list[ForecastPredictionPoint],
        evaluation: EvaluationMetrics,
        data_quality: ForecastDataQuality,
        training_period: dict[str, str | None] | None = None,
        forecast_period: dict[str, str | None] | None = None,
        assumptions: list[str] | None = None,
        limitations: list[str] | None = None,
        rag_context_text: str | None = None,
        explanation_level: str = "manager",
    ) -> str:
        """Convenience invocation wrapper supporting flexible parameter passing."""
        train_p = training_period or {"from": data_quality.date_from, "to": data_quality.date_to}
        fcst_p = forecast_period or {
            "from": predictions[0].period if predictions else None,
            "to": predictions[-1].period if predictions else None,
        }
        assump = assumptions or ["Historical commercial patterns remain stationary."]
        limits = limitations or ["Exogenous economic shocks are unobserved."]
        return cls.generate(
            target_metric=target_metric,
            frequency=frequency,
            training_period=train_p,
            forecast_period=fcst_p,
            model=model,
            predictions=predictions,
            evaluation=evaluation,
            data_quality=data_quality,
            assumptions=assump,
            limitations=limits,
            rag_context_text=rag_context_text,
        )

    @classmethod
    def generate(
        cls,
        target_metric: str,
        frequency: str,
        training_period: dict[str, str | None],
        forecast_period: dict[str, str | None],
        model: ModelMetadata,
        predictions: list[ForecastPredictionPoint],
        evaluation: EvaluationMetrics,
        data_quality: ForecastDataQuality,
        assumptions: list[str],
        limitations: list[str],
        rag_context_text: str | None = None,
    ) -> str:
        """
        Formulate structured narrative:
        - ### Forecast
        - ### Model
        - ### Historical basis
        - ### Accuracy
        - ### Uncertainty
        - ### Important assumptions
        - ### Limitations
        """
        sections: list[str] = []

        # 1. ### Forecast
        forecast_lines: list[str] = []
        metric_name = target_metric.replace("_", " ").title()
        if predictions:
            first_p = predictions[0]
            last_p = predictions[-1]
            if len(predictions) == 1:
                forecast_lines.append(
                    f"Projected {metric_name} for {first_p.period} is **${first_p.point_forecast:,.2f}** "
                    f"(estimated prediction interval: **${first_p.lower_bound:,.2f} – ${first_p.upper_bound:,.2f}** at {int(first_p.confidence_level * 100)}% coverage)."
                )
            else:
                forecast_lines.append(
                    f"Projected {metric_name} across the next {len(predictions)} {frequency} periods "
                    f"({first_p.period} to {last_p.period}):"
                )
                for p in predictions:
                    forecast_lines.append(
                        f"- **{p.period}**: Expected **${p.point_forecast:,.2f}** (Interval: ${p.lower_bound:,.2f} – ${p.upper_bound:,.2f})"
                    )
        else:
            forecast_lines.append(f"No quantitative forecast could be generated for {metric_name}.")
        sections.append("### Forecast\n" + "\n".join(forecast_lines))

        # 2. ### Model
        model_desc = f"Selected validated model: **{model.name.replace('_', ' ').title()}** (v{model.version}, {model.model_type})."
        if model.selection_reason:
            model_desc += f"\n- *Selection rationale*: {model.selection_reason}"
        sections.append("### Model\n" + model_desc)

        # 3. ### Historical basis
        t_from = training_period.get("from") or "start of recorded history"
        t_to = training_period.get("to") or "latest period"
        history_desc = (
            f"Trained on **{data_quality.observation_count}** {frequency} observations spanning "
            f"**{t_from}** through **{t_to}**."
        )
        if data_quality.zero_periods_count > 0:
            history_desc += f" (Identified {data_quality.zero_periods_count} periods with zero activity)."
        sections.append("### Historical basis\n" + history_desc)

        # 4. ### Accuracy
        acc_lines = [
            f"- **MAE (Mean Absolute Error)**: ${evaluation.mae:,.2f}",
            f"- **RMSE (Root Mean Squared Error)**: ${evaluation.rmse:,.2f}",
            f"- **sMAPE (Symmetric Mean Absolute % Error)**: {evaluation.smape:.1f}%",
        ]
        if evaluation.mape is not None:
            acc_lines.append(f"- **MAPE**: {evaluation.mape:.1f}%")
        if evaluation.wape is not None:
            acc_lines.append(f"- **WAPE**: {evaluation.wape:.1f}%")
        acc_lines.append(
            "\n*Note*: All accuracy metrics were measured out-of-sample via temporal backtesting "
            "to guarantee zero future data leakage."
        )
        sections.append("### Accuracy\n" + "\n".join(acc_lines))

        # 5. ### Uncertainty
        uncert_lines = [
            "Prediction intervals represent model and residual uncertainty derived from historical error variance.",
            f"The bounds represent an estimated {int((predictions[0].confidence_level if predictions else 0.95) * 100)}% coverage interval.",
            "As the forecast horizon extends further into the future, uncertainty bounds widen proportionately.",
        ]
        sections.append("### Uncertainty\n" + "\n".join(uncert_lines))

        # 6. ### Important assumptions
        assump_lines = [f"- {a}" for a in assumptions]
        if not assump_lines:
            assump_lines = [
                "- Historical sales velocity, demand patterns, and seasonality are assumed to continue into future periods.",
                "- Product catalog structure and pricing policies remain consistent with the historical baseline.",
            ]
        sections.append("### Important assumptions\n" + "\n".join(assump_lines))

        # 7. ### Limitations
        limit_lines = [f"- {lim}" for lim in limitations]
        if not limit_lines:
            limit_lines = [
                "- The model cannot predict exogenous economic shocks, competitor price adjustments, or unobserved market disruptions.",
                "- Forecast values represent statistical projections rather than guaranteed commercial outcomes.",
            ]
        sections.append("### Limitations\n" + "\n".join(limit_lines))

        # Optional RAG Business Policy Context
        if rag_context_text:
            sections.append(f"### Relevant Business Policy Context\n{rag_context_text.strip()}")

        raw_narrative = "\n\n".join(sections)

        # Enforce causality and prescriptive safeguards
        sanitized_narrative = CausalitySafeguard.sanitize_diagnostic_text(raw_narrative)
        return sanitized_narrative
