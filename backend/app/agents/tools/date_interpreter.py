"""Deterministic Date Interpretation utility for NEXUS.

Converts natural language temporal phrases into exact, unambiguous date boundaries
and baseline comparison periods without requiring LLM date arithmetic.
"""

import calendar
import re
from datetime import date, timedelta
from typing import Any, ClassVar


class ParsedDateInterval(dict):
    """Dictionary supporting both dictionary key indexing and dot attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'ParsedDateInterval' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class DateInterpreter:
    """
    Deterministic parser for natural language date expressions.
    
    Transforms relative business terms ('last month', 'this quarter', 'August 2024')
    into explicit ISO-8601 date ranges and preceding comparison periods.
    """

    MONTH_MAP: ClassVar[dict[str, int]] = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }

    @classmethod
    def interpret(
        cls, query: str, reference_date: date | None = None
    ) -> dict[str, Any]:
        """
        Extract and resolve date intervals and comparison baselines from a user query.
        
        Args:
            query: The user query string
            reference_date: Anchor date for relative terms (defaults to date.today())
            
        Returns:
            Dict containing date_from, date_to, comparison_date_from, comparison_date_to,
            granularity, is_ambiguous, and matched_expression.
        """
        ref = reference_date or date.today()
        q_lower = query.lower()

        # 1. Check explicit ISO date range: YYYY-MM-DD to YYYY-MM-DD
        iso_range_match = re.search(
            r'(\d{4}-\d{2}-\d{2})\s*(?:to|through|until|--|-)\s*(\d{4}-\d{2}-\d{2})',
            q_lower
        )
        if iso_range_match:
            try:
                d_from = date.fromisoformat(iso_range_match.group(1))
                d_to = date.fromisoformat(iso_range_match.group(2))
                delta = d_to - d_from
                comp_to = d_from - timedelta(days=1)
                comp_from = comp_to - delta
                return cls._build_result(d_from, d_to, comp_from, comp_to, "range", "monthly")
            except ValueError:
                pass

        # 2. Check prospective/future forecast expressions
        next_m_match = re.search(r'next\s+(\d+)\s+months?', q_lower)
        if next_m_match or "next month" in q_lower or "upcoming month" in q_lower:
            n_months = int(next_m_match.group(1)) if next_m_match else 1
            start_m = (ref.month % 12) + 1
            start_y = ref.year + (1 if ref.month == 12 else 0)
            d_from = date(start_y, start_m, 1)

            end_m_raw = start_m + n_months - 1
            end_y = start_y + (end_m_raw - 1) // 12
            end_m = ((end_m_raw - 1) % 12) + 1
            _, last_day = calendar.monthrange(end_y, end_m)
            d_to = date(end_y, end_m, last_day)

            comp_to = d_from - timedelta(days=1)
            comp_from = comp_to - (d_to - d_from)

            res = cls._build_result(d_from, d_to, comp_from, comp_to, f"next_{n_months}_months", "monthly")
            res["is_forecast"] = True
            res["forecast_horizon"] = n_months
            return res

        if "next quarter" in q_lower:
            curr_q = (ref.month - 1) // 3 + 1
            next_q = (curr_q % 4) + 1
            year = ref.year + (1 if curr_q == 4 else 0)
            start_m = (next_q - 1) * 3 + 1
            end_m = start_m + 2
            _, last_day = calendar.monthrange(year, end_m)
            d_from = date(year, start_m, 1)
            d_to = date(year, end_m, last_day)
            comp_from = date(ref.year, (curr_q - 1) * 3 + 1, 1)
            _, comp_last_day = calendar.monthrange(ref.year, (curr_q - 1) * 3 + 3)
            comp_to = date(ref.year, (curr_q - 1) * 3 + 3, comp_last_day)
            res = cls._build_result(d_from, d_to, comp_from, comp_to, "next_quarter", "monthly")
            res["is_forecast"] = True
            res["forecast_horizon"] = 3
            return res

        next_days_match = re.search(r'next\s+(\d+)\s+days?', q_lower)
        if next_days_match:
            n_days = int(next_days_match.group(1))
            d_from = ref + timedelta(days=1)
            d_to = ref + timedelta(days=n_days)
            comp_to = ref
            comp_from = ref - timedelta(days=n_days - 1)
            res = cls._build_result(d_from, d_to, comp_from, comp_to, f"next_{n_days}_days", "daily")
            res["is_forecast"] = True
            res["forecast_horizon"] = n_days
            return res

        next_weeks_match = re.search(r'next\s+(\d+)\s+weeks?', q_lower)
        if next_weeks_match or "next week" in q_lower:
            n_weeks = int(next_weeks_match.group(1)) if next_weeks_match else 1
            d_from = ref + timedelta(days=1)
            d_to = ref + timedelta(days=n_weeks * 7)
            comp_to = ref
            comp_from = ref - timedelta(days=n_weeks * 7 - 1)
            res = cls._build_result(d_from, d_to, comp_from, comp_to, f"next_{n_weeks}_weeks", "weekly")
            res["is_forecast"] = True
            res["forecast_horizon"] = n_weeks
            return res

        # 3. Check "last month" / "previous month"
        if "last month" in q_lower or "previous month" in q_lower or "prior month" in q_lower:
            year = ref.year
            month = ref.month - 1
            if month == 0:
                month = 12
                year -= 1
            _, last_day = calendar.monthrange(year, month)
            d_from = date(year, month, 1)
            d_to = date(year, month, last_day)

            # Prior comparison month
            prev_year = year
            prev_month = month - 1
            if prev_month == 0:
                prev_month = 12
                prev_year -= 1
            _, prev_last_day = calendar.monthrange(prev_year, prev_month)
            comp_from = date(prev_year, prev_month, 1)
            comp_to = date(prev_year, prev_month, prev_last_day)

            return cls._build_result(d_from, d_to, comp_from, comp_to, "last_month", "daily")

        # 3. Check "this month" / "current month"
        if "this month" in q_lower or "current month" in q_lower:
            year = ref.year
            month = ref.month
            _, last_day = calendar.monthrange(year, month)
            d_from = date(year, month, 1)
            d_to = ref if ref.month == month else date(year, month, last_day)

            # Prior comparison month
            prev_year = year
            prev_month = month - 1
            if prev_month == 0:
                prev_month = 12
                prev_year -= 1
            _, prev_last_day = calendar.monthrange(prev_year, prev_month)
            comp_from = date(prev_year, prev_month, 1)
            comp_to = date(prev_year, prev_month, min(d_to.day, prev_last_day))

            return cls._build_result(d_from, d_to, comp_from, comp_to, "this_month", "daily")

        # 4. Check "last quarter" / "previous quarter"
        if "last quarter" in q_lower or "previous quarter" in q_lower:
            curr_quarter = (ref.month - 1) // 3 + 1
            last_q = curr_quarter - 1
            year = ref.year
            if last_q == 0:
                last_q = 4
                year -= 1
            start_m = (last_q - 1) * 3 + 1
            end_m = start_m + 2
            _, last_day = calendar.monthrange(year, end_m)
            d_from = date(year, start_m, 1)
            d_to = date(year, end_m, last_day)

            # Comparison quarter
            comp_q = last_q - 1
            comp_y = year
            if comp_q == 0:
                comp_q = 4
                comp_y -= 1
            comp_start_m = (comp_q - 1) * 3 + 1
            comp_end_m = comp_start_m + 2
            _, comp_last_day = calendar.monthrange(comp_y, comp_end_m)
            comp_from = date(comp_y, comp_start_m, 1)
            comp_to = date(comp_y, comp_end_m, comp_last_day)

            return cls._build_result(d_from, d_to, comp_from, comp_to, "last_quarter", "monthly")

        # 5. Check "this quarter"
        if "this quarter" in q_lower or "current quarter" in q_lower:
            curr_quarter = (ref.month - 1) // 3 + 1
            year = ref.year
            start_m = (curr_quarter - 1) * 3 + 1
            end_m = start_m + 2
            _, last_day = calendar.monthrange(year, end_m)
            d_from = date(year, start_m, 1)
            d_to = ref

            prev_q = curr_quarter - 1
            prev_y = year
            if prev_q == 0:
                prev_q = 4
                prev_y -= 1
            comp_start_m = (prev_q - 1) * 3 + 1
            comp_end_m = comp_start_m + 2
            _, comp_last_day = calendar.monthrange(prev_y, comp_end_m)
            comp_from = date(prev_y, comp_start_m, 1)
            comp_to = date(prev_y, comp_end_m, comp_last_day)

            return cls._build_result(d_from, d_to, comp_from, comp_to, "this_quarter", "monthly")

        # 6. Check "last year" / "previous year"
        if "last year" in q_lower or "previous year" in q_lower or "prior year" in q_lower:
            year = ref.year - 1
            d_from = date(year, 1, 1)
            d_to = date(year, 12, 31)
            comp_from = date(year - 1, 1, 1)
            comp_to = date(year - 1, 12, 31)
            return cls._build_result(d_from, d_to, comp_from, comp_to, "last_year", "monthly")

        # 7. Check "this year" / "current year"
        if "this year" in q_lower or "current year" in q_lower:
            year = ref.year
            d_from = date(year, 1, 1)
            d_to = ref
            comp_from = date(year - 1, 1, 1)
            comp_to = date(year - 1, min(ref.month, 12), min(ref.day, 28))
            return cls._build_result(d_from, d_to, comp_from, comp_to, "this_year", "monthly")

        # 8. Check "last N days" (e.g. "last 30 days", "past 7 days")
        days_match = re.search(r'(?:last|past)\s+(\d+)\s+days', q_lower)
        if days_match:
            n_days = int(days_match.group(1))
            d_to = ref
            d_from = ref - timedelta(days=n_days - 1)
            comp_to = d_from - timedelta(days=1)
            comp_from = comp_to - timedelta(days=n_days - 1)
            granularity = "daily" if n_days <= 60 else "weekly"
            return cls._build_result(d_from, d_to, comp_from, comp_to, f"last_{n_days}_days", granularity)

        # 9. Check specific Month Year (e.g. "August 2024", "Aug 2024", "2024-08")
        month_year_pattern = r'\b(' + '|'.join(cls.MONTH_MAP.keys()) + r')\s+(\d{4})\b'
        my_match = re.search(month_year_pattern, q_lower)
        if my_match:
            m_str, y_str = my_match.group(1), my_match.group(2)
            month = cls.MONTH_MAP[m_str]
            year = int(y_str)
            _, last_day = calendar.monthrange(year, month)
            d_from = date(year, month, 1)
            d_to = date(year, month, last_day)

            # Prior comparison month
            prev_year = year
            prev_month = month - 1
            if prev_month == 0:
                prev_month = 12
                prev_year -= 1
            _, prev_last_day = calendar.monthrange(prev_year, prev_month)
            comp_from = date(prev_year, prev_month, 1)
            comp_to = date(prev_year, prev_month, prev_last_day)

            return cls._build_result(d_from, d_to, comp_from, comp_to, f"{m_str}_{year}", "daily")

        # Check YYYY-MM
        ym_match = re.search(r'\b(\d{4})-(\d{2})\b', q_lower)
        if ym_match:
            year, month = int(ym_match.group(1)), int(ym_match.group(2))
            if 1 <= month <= 12:
                _, last_day = calendar.monthrange(year, month)
                d_from = date(year, month, 1)
                d_to = date(year, month, last_day)
                prev_year = year
                prev_month = month - 1
                if prev_month == 0:
                    prev_month = 12
                    prev_year -= 1
                _, prev_last_day = calendar.monthrange(prev_year, prev_month)
                comp_from = date(prev_year, prev_month, 1)
                comp_to = date(prev_year, prev_month, prev_last_day)
                return cls._build_result(d_from, d_to, comp_from, comp_to, f"{year}-{month:02d}", "daily")

        # 10. Check "today" or "yesterday"
        if "today" in q_lower:
            return cls._build_result(ref, ref, ref - timedelta(days=1), ref - timedelta(days=1), "today", "daily")
        if "yesterday" in q_lower:
            y_date = ref - timedelta(days=1)
            return cls._build_result(y_date, y_date, y_date - timedelta(days=1), y_date - timedelta(days=1), "yesterday", "daily")

        # 11. Standalone month name without year (default to ref year, e.g. "in August")
        for m_name, m_num in cls.MONTH_MAP.items():
            if re.search(r'\b' + m_name + r'\b', q_lower):
                year = ref.year
                _, last_day = calendar.monthrange(year, m_num)
                d_from = date(year, m_num, 1)
                d_to = date(year, m_num, last_day)

                prev_year = year
                prev_month = m_num - 1
                if prev_month == 0:
                    prev_month = 12
                    prev_year -= 1
                _, prev_last_day = calendar.monthrange(prev_year, prev_month)
                comp_from = date(prev_year, prev_month, 1)
                comp_to = date(prev_year, prev_month, prev_last_day)
                return cls._build_result(d_from, d_to, comp_from, comp_to, f"{m_name}_{year}", "daily")

        # 12. Check if comparison / variance query without explicit date: default to recent period baseline
        if any(term in q_lower for term in ["change", "variance", "decline", "increase", "growth", "why did", "pvm", "decomposition"]):
            year = ref.year
            month = ref.month - 1
            if month == 0:
                month = 12
                year -= 1
            _, last_day = calendar.monthrange(year, month)
            d_from = date(year, month, 1)
            d_to = date(year, month, last_day)

            prev_year = year
            prev_month = month - 1
            if prev_month == 0:
                prev_month = 12
                prev_year -= 1
            _, prev_last_day = calendar.monthrange(prev_year, prev_month)
            comp_from = date(prev_year, prev_month, 1)
            comp_to = date(prev_year, prev_month, prev_last_day)
            return cls._build_result(d_from, d_to, comp_from, comp_to, "recent_variance_baseline", "monthly")

        # 13. No date specified: Check if query has open-ended context or is all-time
        return ParsedDateInterval({
            "date_from": None,
            "date_to": None,
            "comparison_date_from": None,
            "comparison_date_to": None,
            "granularity": "monthly",
            "matched_expression": None,
            "is_ambiguous": False,
            "is_forecast": False,
            "forecast_horizon": None,
        })

    @classmethod
    def _build_result(
        cls,
        d_from: date,
        d_to: date,
        comp_from: date | None,
        comp_to: date | None,
        matched_expression: str,
        granularity: str = "monthly",
    ) -> ParsedDateInterval:
        return ParsedDateInterval({
            "date_from": d_from.isoformat(),
            "date_to": d_to.isoformat(),
            "comparison_date_from": comp_from.isoformat() if comp_from else None,
            "comparison_date_to": comp_to.isoformat() if comp_to else None,
            "granularity": granularity,
            "matched_expression": matched_expression,
            "is_ambiguous": False,
            "is_forecast": False,
            "forecast_horizon": None,
        })
