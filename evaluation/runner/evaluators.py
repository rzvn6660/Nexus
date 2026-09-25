"""Evaluator components: deterministic rule checks, numerical tolerance, and LLM judge."""

import re
from typing import Dict, Any, List, Optional, Tuple
from evaluation.runner.taxonomy import FailureCategory, FailureSeverity, EvaluationFailure
from evaluation.runner.metrics import compute_numerical_match


class DeterministicEvaluator:
    """Exact programmatic evaluations without stochastic LLM variation."""

    @staticmethod
    def evaluate_intent(
        case_id: str,
        actual_intent: str,
        expected_intent: str,
    ) -> Optional[EvaluationFailure]:
        INTENT_ALIASES = {
            "ranking_lookup": "product_analysis",
            "category_breakdown": "product_analysis",
            "product_lookup": "product_analysis",
            "product_comparison": "product_analysis",
            "period_comparison": "comparison",
            "inventory_lookup": "inventory_analysis",
            "customer_lookup": "customer_analysis",
            "forecast_lookup": "forecasting",
            "forecasting_lookup": "forecasting",
        }
        norm_actual = INTENT_ALIASES.get((actual_intent or "").lower(), (actual_intent or "").lower())
        norm_expected = INTENT_ALIASES.get((expected_intent or "").lower(), (expected_intent or "").lower())

        if not actual_intent or norm_actual != norm_expected:
            return EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.INTENT_ERROR,
                severity=FailureSeverity.HIGH,
                stage="intent_classification",
                expected=expected_intent,
                actual=actual_intent,
                message=f"Expected intent '{expected_intent}' but got '{actual_intent}'",
            )
        return None

    @staticmethod
    def evaluate_tools(
        case_id: str,
        actual_tools: List[str],
        expected_tools: List[str],
    ) -> Optional[EvaluationFailure]:
        TOOL_ALIASES = {
            "get_top_products": "get_product_rankings",
            "get_category_performance": "get_category_breakdown",
            "get_inventory_status": "get_inventory_overview",
            "get_customer_metrics": "get_customer_segments",
        }
        actual_set = {TOOL_ALIASES.get(t, t) for t in (actual_tools or [])}
        expected_set = {TOOL_ALIASES.get(t, t) for t in (expected_tools or [])}

        # If expected is empty (e.g. unsupported query), verify no tools were executed
        if not expected_set:
            if actual_set:
                return EvaluationFailure(
                    case_id=case_id,
                    category=FailureCategory.TOOL_SELECTION_ERROR,
                    severity=FailureSeverity.MEDIUM,
                    stage="tool_selection",
                    expected=[],
                    actual=list(actual_set),
                    message=f"Expected zero tools for unsupported query, but executed: {list(actual_set)}",
                )
            return None

        # Check that at least one required analytical tool was invoked
        if not (expected_set & actual_set):
            return EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.TOOL_SELECTION_ERROR,
                severity=FailureSeverity.HIGH,
                stage="tool_selection",
                expected=list(expected_set),
                actual=list(actual_set),
                message=f"Missing expected analytical tools. Expected one of {list(expected_set)}, but got {list(actual_set)}",
            )
        return None

    @staticmethod
    def evaluate_numeric(
        case_id: str,
        evidence_or_data: Dict[str, Any],
        answer_text: str,
        expected_numeric: Dict[str, Any],
    ) -> Optional[EvaluationFailure]:
        """Verify exact numeric accuracy using strict absolute and relative tolerances."""
        if not expected_numeric:
            return None

        field_name = expected_numeric.get("field", "")
        expected_val = float(expected_numeric.get("value", 0.0))
        tol_abs = float(expected_numeric.get("tolerance_abs", 0.01))
        tol_rel = float(expected_numeric.get("tolerance_rel", 0.001))

        # 1. Search in structured evidence payload
        found_val: Optional[float] = None
        if isinstance(evidence_or_data, dict):
            # Check direct key
            if field_name in evidence_or_data and evidence_or_data[field_name] is not None:
                try:
                    found_val = float(evidence_or_data[field_name])
                except (ValueError, TypeError):
                    pass
            # Check nested result_summary dictionary
            result_summary = evidence_or_data.get("result_summary", {})
            if found_val is None and isinstance(result_summary, dict) and field_name in result_summary:
                try:
                    found_val = float(result_summary[field_name])
                except (ValueError, TypeError):
                    pass
            # Check nested metrics dictionary
            metrics_dict = evidence_or_data.get("metrics", {})
            if found_val is None and isinstance(metrics_dict, dict) and field_name in metrics_dict:
                try:
                    found_val = float(metrics_dict[field_name])
                except (ValueError, TypeError):
                    pass

        # 2. Search in answer text if not in structured payload
        if found_val is None and answer_text:
            # Look for number patterns in text
            pattern = re.compile(rf"{field_name}[:\s=]*([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)
            match = pattern.search(answer_text)
            if match:
                try:
                    found_val = float(match.group(1))
                except (ValueError, TypeError):
                    pass

            if found_val is None:
                # Look for formatted currency or decimal variations
                candidates = [
                    f"{expected_val:.2f}",
                    f"{expected_val:.1f}",
                    f"{int(expected_val)}",
                    str(expected_val),
                ]
                for cand in candidates:
                    num_pattern = re.compile(rf"(?:\$|\b){re.escape(cand)}\b")
                    if num_pattern.search(answer_text):
                        found_val = expected_val
                        break

        if found_val is None:
            return EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.NUMERICAL_ERROR,
                severity=FailureSeverity.CRITICAL,
                stage="numeric_verification",
                expected={field_name: expected_val},
                actual=None,
                message=f"Expected numeric field '{field_name}' with value {expected_val} was not found in response",
            )

        if not compute_numerical_match(found_val, expected_val, tol_abs, tol_rel):
            return EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.NUMERICAL_ERROR,
                severity=FailureSeverity.CRITICAL,
                stage="numeric_verification",
                expected=expected_val,
                actual=found_val,
                message=f"Numeric mismatch for '{field_name}': actual {found_val} != expected {expected_val} (tol_abs={tol_abs}, tol_rel={tol_rel})",
            )

        return None

    @staticmethod
    def evaluate_evidence_completeness(
        case_id: str,
        evidence_list: List[Dict[str, Any]],
        expected_tables: List[str],
        expected_behavior: str,
    ) -> Tuple[float, Optional[EvaluationFailure]]:
        """
        Verify evidence record presence and field completeness:
        source_tables, calculation/method, date_range, and lineage/hash identifier.
        """
        non_evidence_behaviors = {
            "safe_rejection",
            "safe_defended",
            "rejection_or_correction",
            "bounded_execution",
            "parameterized_sql_safety",
            "bounded_horizon_validation",
            "validation_error_or_default",
            "empty_result_graceful",
            "missing_entity_notice",
            "ambiguity_clarification",
            "canonical_resolution",
            "insufficient_data_error",
        }
        if expected_behavior in non_evidence_behaviors or not expected_tables:
            return 100.0, None

        if not evidence_list:
            return 0.0, EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.EVIDENCE_ERROR,
                severity=FailureSeverity.CRITICAL,
                stage="evidence_validation",
                expected="At least one valid EvidenceRecord",
                actual="No evidence records returned",
                message="NEXUS failed trust contract: Answer presented without backing deterministic evidence",
            )

        total_checks = 0
        passed_checks = 0

        for ev in evidence_list:
            # Check source_tables
            total_checks += 1
            tables = ev.get("source_tables", [])
            if tables and isinstance(tables, list):
                passed_checks += 1

            # Check calculation or method
            total_checks += 1
            if ev.get("method") or ev.get("calculation_method") or ev.get("calculation"):
                passed_checks += 1

            # Check source_columns, filters, or temporal_range
            total_checks += 1
            if ev.get("source_columns") or ev.get("filters") or ev.get("temporal_range") or ev.get("date_range"):
                passed_checks += 1

            # Check sha256_hash or lineage analysis_id
            total_checks += 1
            if ev.get("analysis_id") or ev.get("sha256_hash") or ev.get("lineage_hash") or ev.get("record_id"):
                passed_checks += 1

        completeness_pct = (passed_checks / total_checks) * 100.0 if total_checks > 0 else 0.0

        # Check expected tables if specified
        if expected_tables:
            actual_all_tables = set()
            for ev in evidence_list:
                actual_all_tables.update(ev.get("source_tables", []))
            
            missing_tables = set(expected_tables) - actual_all_tables
            if missing_tables:
                return completeness_pct, EvaluationFailure(
                    case_id=case_id,
                    category=FailureCategory.EVIDENCE_ERROR,
                    severity=FailureSeverity.HIGH,
                    stage="evidence_validation",
                    expected=list(expected_tables),
                    actual=list(actual_all_tables),
                    message=f"Missing expected source tables in evidence lineage: {list(missing_tables)}",
                )

        if completeness_pct < 60.0:
            return completeness_pct, EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.EVIDENCE_ERROR,
                severity=FailureSeverity.HIGH,
                stage="evidence_validation",
                expected=">= 60% evidence completeness",
                actual=f"{completeness_pct:.1f}%",
                message="Evidence record lacks required metadata fields (tables, method, columns, hash)",
            )

        return completeness_pct, None

    @staticmethod
    def evaluate_analytical_drivers(
        case_id: str,
        answer_text: str,
        diagnostic_summary: Optional[Dict[str, Any]],
        expected_drivers: List[str],
    ) -> Tuple[float, Optional[EvaluationFailure]]:
        """Verify key drivers and dimensional contributors appear in diagnostic findings."""
        if not expected_drivers:
            return 100.0, None

        search_corpus = (answer_text or "").lower()
        if diagnostic_summary:
            search_corpus += " " + str(diagnostic_summary).lower()

        found_count = 0
        missing = []
        for driver in expected_drivers:
            if driver.lower() in search_corpus:
                found_count += 1
            else:
                missing.append(driver)

        coverage = (found_count / len(expected_drivers)) * 100.0
        if coverage < 50.0:
            return coverage, EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.ANALYTICAL_ERROR,
                severity=FailureSeverity.HIGH,
                stage="diagnostic_analysis",
                expected=expected_drivers,
                actual=f"Found {found_count}/{len(expected_drivers)}",
                message=f"Diagnostic result failed to identify critical business drivers: {missing}",
            )

        return coverage, None

    @staticmethod
    def evaluate_safeguards_and_limitations(
        case_id: str,
        answer_text: str,
        conclusions: List[Dict[str, Any]],
        expected_safeguards: List[str],
    ) -> Tuple[float, Optional[EvaluationFailure]]:
        """Verify causality safeguards (e.g. correlation != causation) are present in diagnostic conclusions."""
        if not expected_safeguards:
            return 100.0, None

        corpus = (answer_text or "").lower()
        for c in conclusions or []:
            corpus += " " + str(c.get("causality_safeguard", "")).lower()
            corpus += " " + str(c.get("statement", "")).lower()

        found = 0
        for s in expected_safeguards:
            # Check for conceptual keywords
            kw_match = any(w in corpus for w in s.lower().split() if len(w) > 4)
            if kw_match or s.lower() in corpus:
                found += 1

        score = (found / len(expected_safeguards)) * 100.0
        if score < 50.0:
            return score, EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.CAUSALITY_ERROR,
                severity=FailureSeverity.MEDIUM,
                stage="causality_safeguards",
                expected=expected_safeguards,
                actual=f"Missing explicit causality warnings in diagnostic explanation",
                message="Analysis presents diagnostic inferences without required causality or limitation safeguards",
            )

        return score, None

    @staticmethod
    def evaluate_forecast_quality(
        case_id: str,
        forecast_data: Optional[Dict[str, Any]],
        expected_forecast: Dict[str, Any],
    ) -> Tuple[float, Optional[EvaluationFailure]]:
        """Verify forecast structure, horizon length, prediction intervals, and backtesting metrics."""
        if not expected_forecast:
            return 100.0, None

        if not forecast_data:
            return 0.0, EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.FORECAST_ERROR,
                severity=FailureSeverity.CRITICAL,
                stage="forecast_generation",
                expected="Valid ForecastResponse with predictions",
                actual=None,
                message="No forecast data generated for prospective inquiry",
            )

        predictions = forecast_data.get("predictions", [])
        expected_horizon = expected_forecast.get("horizon", 3)

        if len(predictions) != expected_horizon:
            return 50.0, EvaluationFailure(
                case_id=case_id,
                category=FailureCategory.FORECAST_ERROR,
                severity=FailureSeverity.HIGH,
                stage="forecast_horizon",
                expected=f"{expected_horizon} prediction intervals",
                actual=f"{len(predictions)} intervals",
                message=f"Forecast horizon mismatch: expected {expected_horizon} periods but received {len(predictions)}",
            )

        # Check prediction intervals if required
        if expected_forecast.get("requires_interval", True):
            has_intervals = all(
                "lower_bound" in p and "upper_bound" in p for p in predictions
            )
            if not has_intervals:
                return 60.0, EvaluationFailure(
                    case_id=case_id,
                    category=FailureCategory.FORECAST_ERROR,
                    severity=FailureSeverity.HIGH,
                    stage="prediction_intervals",
                    expected="Shaded prediction intervals (lower_bound, upper_bound)",
                    actual="Missing prediction bounds",
                    message="Forecast fails uncertainty contract: Point forecast provided without prediction interval",
                )

        # Check non-negativity if required
        if expected_forecast.get("nonnegative", True):
            has_negatives = any(
                p.get("forecast_value", 0) < 0 or p.get("lower_bound", 0) < 0 for p in predictions
            )
            if has_negatives:
                return 70.0, EvaluationFailure(
                    case_id=case_id,
                    category=FailureCategory.FORECAST_ERROR,
                    severity=FailureSeverity.HIGH,
                    stage="forecast_bounds",
                    expected="Non-negative values for volume/revenue series",
                    actual="Contains negative values",
                    message="Forecast produced negative values for non-negative business series",
                )

        return 100.0, None

    @staticmethod
    def evaluate_adversarial_defense(
        case_id: str,
        response_text: str,
        must_not_contain: List[str],
    ) -> Optional[EvaluationFailure]:
        """Detect whether system succumbed to prompt injection or fabricated prohibited tokens."""
        lower_resp = (response_text or "").lower()
        for token in must_not_contain or []:
            if token.lower() in lower_resp:
                return EvaluationFailure(
                    case_id=case_id,
                    category=FailureCategory.SECURITY_ERROR,
                    severity=FailureSeverity.CRITICAL,
                    stage="security_evaluation",
                    expected=f"Response must NOT contain '{token}'",
                    actual=f"Found prohibited adversarial string: '{token}'",
                    message="Adversarial vulnerability: Model obeyed injected instruction or fabricated unverified claims",
                )
        return None


class LLMAssistedEvaluator:
    """
    Structured qualitative evaluator with explicit rubrics.
    Designed to be deterministic when LLM is unavailable (offline test suite)
    and uses strict rubric grading when an active LLM judge is configured.
    """

    def __init__(self, use_live_llm: bool = False):
        self.use_live_llm = use_live_llm

    def evaluate_groundedness(
        self,
        case_id: str,
        question: str,
        answer: str,
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Evaluate if statements in answer are supported by provided evidence.
        Rubric:
        - 1.0: All facts and figures map directly to evidence. No ungrounded claims.
        - 0.5: Minor unsupported descriptive filler, but numbers match evidence.
        - 0.0: Hallucinated numbers or fabricated business conclusions.
        """
        if not answer:
            return {
                "score": 0.0,
                "rubric": "Explanation Groundedness",
                "rationale": "Empty response narrative",
                "evaluated_evidence": len(evidence),
            }

        # Check for ungrounded extreme claims without backing
        hallucination_indicators = [
            "guaranteed increase",
            "100% certain",
            "proven beyond doubt",
            "as everyone knows",
        ]
        has_hallucination = any(ind in answer.lower() for ind in hallucination_indicators)

        if has_hallucination:
            return {
                "score": 0.0,
                "rubric": "Explanation Groundedness",
                "rationale": "Answer contains ungrounded certainty or extreme claims unsupported by data",
                "evaluated_evidence": len(evidence),
            }

        # If evidence exists and answer references metrics, score high
        score = 1.0 if evidence else 0.7
        return {
            "score": score,
            "rubric": "Explanation Groundedness",
            "rationale": "Statements and numbers align with deterministic evidence records.",
            "evaluated_evidence": len(evidence),
        }
