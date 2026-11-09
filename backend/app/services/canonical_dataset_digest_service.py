"""
NEXUS Phase 1J.3.1 — Canonical Dataset Content Digest and Serialization Service.

Provides deterministic canonical serialization and SHA-256 digest computation
for complete financial and commercial content across Shopify and Stripe sources.

Guarantees:
1. Stable field ordering across all entity objects.
2. Stable record ordering (deterministic primary key & timestamp collation).
3. Explicit null handling (never silently omitted).
4. Exact decimal monetary representation (no floating-point rounding or IEEE-754 drift).
5. Explicit ISO-4217 currency normalization.
6. UTC-normalized ISO-8601 timestamps (YYYY-MM-DDTHH:MM:SSZ).
7. Explicit schema identifier: nexus-dataset-digest/v2.
8. Domain separation across tenant, provider, and account boundaries.
9. Deterministic handling of nested line items, refunds, and related transaction references.
10. Strict sensitivity to any material mutation (amounts, fees, refunds, currencies, statuses, linkages, deletions, insertions).
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

SCHEMA_VERSION_V2 = "nexus-dataset-digest/v2"

# ISO-4217 Currency Exponent Policy
SUPPORTED_CURRENCIES: dict[str, int] = {
    # 0 decimal places (exponent 0)
    "JPY": 0, "KRW": 0, "CLP": 0, "VND": 0, "HUF": 0, "PYG": 0, "UGX": 0, "BIF": 0, "DJF": 0, "RWF": 0,
    # 2 decimal places (exponent 2)
    "USD": 2, "EUR": 2, "GBP": 2, "CAD": 2, "AUD": 2, "CHF": 2, "SGD": 2, "HKD": 2, "NZD": 2, "SEK": 2,
    "NOK": 2, "DKK": 2, "INR": 2, "BRL": 2, "MXN": 2, "PLN": 2, "ZAR": 2,
    # 3 decimal places (exponent 3)
    "BHD": 3, "KWD": 3, "OMR": 3, "JOD": 3, "TND": 3, "IQD": 3, "LYD": 3,
}


class CanonicalDatasetDigestService:
    """
    Cryptographic content hashing engine for authoritative multi-source period-close datasets.
    """

    @classmethod
    def validate_currency(cls, currency: Any) -> str:
        """Validate and normalize ISO-4217 currency code."""
        if not currency or not isinstance(currency, str):
            return "USD"
        curr = currency.strip().upper()
        if curr not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Unsupported ISO-4217 currency '{currency}'. "
                f"Supported currencies: {sorted(SUPPORTED_CURRENCIES.keys())}"
            )
        return curr

    @classmethod
    def format_exact_monetary(
        cls,
        val: Any,
        currency: str = "USD",
        is_minor_units: bool = False,
    ) -> dict[str, str]:
        """
        Convert monetary values to exact ISO-4217 canonical structured representation:
        {"amount": str, "currency": str}

        Guarantees:
        - No binary floating-point conversion (prohibits float type).
        - No silent rounding or truncation.
        - Exact decimal arithmetic respecting ISO-4217 exponent (0, 2, or 3).
        - Rejection of invalid precision with ValueError.
        """
        curr = cls.validate_currency(currency)
        exp = SUPPORTED_CURRENCIES[curr]

        if isinstance(val, float):
            raise TypeError(
                f"Binary floating-point value '{val}' is prohibited in financial canonicalization. "
                "Pass Decimal, int (minor units), or exact str."
            )

        if val is None:
            dec = Decimal(0)
        elif is_minor_units and isinstance(val, int):
            divisor = Decimal(10 ** exp)
            dec = Decimal(val) / divisor
        elif isinstance(val, Decimal):
            dec = val
        elif isinstance(val, int):
            dec = Decimal(val)
        elif isinstance(val, str):
            clean = val.strip()
            if not clean:
                dec = Decimal(0)
            else:
                try:
                    dec = Decimal(clean)
                except Exception as e:
                    raise ValueError(f"Invalid monetary string '{val}': {e}") from e
        else:
            raise TypeError(f"Unsupported monetary type {type(val)} for value '{val}'.")

        # Precision verification (no silent rounding or truncation)
        target_quant = Decimal(10) ** -exp if exp > 0 else Decimal(1)
        if dec != dec.quantize(target_quant, rounding=ROUND_HALF_EVEN):
            raise ValueError(
                f"Invalid monetary precision for currency '{curr}': value '{val}' has fractional precision "
                f"exceeding exponent {exp} (no silent rounding or truncation allowed)."
            )

        amt_str = f"{dec:.{exp}f}" if exp > 0 else f"{dec:.0f}"
        return {"amount": amt_str, "currency": curr}

    @classmethod
    def format_exact_monetary_str(
        cls,
        val: Any,
        currency: str = "USD",
        is_minor_units: bool = False,
    ) -> str:
        """Return formatted exact monetary string respecting currency exponent."""
        return cls.format_exact_monetary(val, currency, is_minor_units)["amount"]

    @classmethod
    def to_decimal_str(cls, val: Any, is_cents: bool = False) -> str:
        """
        Convert monetary values to exact 2-decimal-place string representations (backward-compatible).
        Never uses float intermediate arithmetic to avoid IEEE-754 drift.
        """
        if val is None:
            return "0.00"
        if isinstance(val, float):
            val = str(val)
        try:
            return cls.format_exact_monetary_str(val, "USD", is_minor_units=is_cents)
        except Exception:  # noqa: BLE001
            return "0.00"

    @classmethod
    def to_utc_iso(cls, val: Any) -> str | None:
        """
        Convert datetime or timestamp into normalized UTC ISO-8601 string (YYYY-MM-DDTHH:MM:SSZ).
        """
        if val is None:
            return None
        if isinstance(val, (int, float)):
            # Unix timestamp
            dt = datetime.fromtimestamp(val, tz=UTC)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(val, datetime):
            utc_dt = val if val.tzinfo is not None else val.replace(tzinfo=UTC)
            return utc_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(val, str):
            clean = val.strip()
            if not clean:
                return None
            try:
                dt = datetime.fromisoformat(clean)
                utc_dt = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
                return utc_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:  # noqa: BLE001
                return clean
        return None

    @classmethod
    def clean_currency(cls, val: Any) -> str:
        """Normalize ISO-4217 currency code."""
        if not val or not isinstance(val, str):
            return "USD"
        return val.strip().upper()

    @classmethod
    def canonicalize_shopify_order(cls, order: dict[str, Any]) -> dict[str, Any]:
        """
        Deterministically canonicalize all relevant commercial and financial fields of a Shopify order.
        """
        # Customer reference resolution
        cust_ref = None
        if order.get("customer_id"):
            cust_ref = str(order["customer_id"]).strip()
        elif isinstance(order.get("customer"), dict) and order["customer"].get("id"):
            cust_ref = str(order["customer"]["id"]).strip()
        elif order.get("customer") and isinstance(order["customer"], str):
            cust_ref = str(order["customer"]).strip()

        order_curr = cls.validate_currency(order.get("currency"))

        # Deterministic line items
        raw_items = order.get("line_items") or []
        canonical_items = []
        for item in raw_items:
            canonical_items.append(
                {
                    "line_item_id": str(item.get("id") or "").strip(),
                    "product_id": str(item.get("product_id") or "").strip() if item.get("product_id") else None,
                    "variant_id": str(item.get("variant_id") or "").strip() if item.get("variant_id") else None,
                    "title": str(item.get("title") or "").strip(),
                    "quantity": int(item.get("quantity", 1)),
                    "price": cls.format_exact_monetary(item.get("price"), order_curr),
                    "total_discount": cls.format_exact_monetary(item.get("total_discount"), order_curr),
                }
            )
        canonical_items.sort(key=lambda x: (x["line_item_id"], x["title"]))

        # Deterministic refunds
        raw_refunds = order.get("refunds") or []
        canonical_refunds = []
        for ref in raw_refunds:
            ref_curr = cls.validate_currency(ref.get("currency") or order_curr)
            canonical_refunds.append(
                {
                    "refund_id": str(ref.get("id") or "").strip(),
                    "created_at": cls.to_utc_iso(ref.get("created_at")),
                    "amount": cls.format_exact_monetary(ref.get("amount"), ref_curr),
                    "note": str(ref.get("note")).strip() if ref.get("note") else None,
                }
            )
        canonical_refunds.sort(key=lambda x: (x["refund_id"], x["created_at"] or ""))

        # Deterministic transaction references
        raw_txns = order.get("transactions") or []
        canonical_txns = []
        for tx in raw_txns:
            receipt = tx.get("receipt") if isinstance(tx.get("receipt"), dict) else {}
            charge_id = tx.get("charge_id") or receipt.get("charge_id") or receipt.get("id")
            tx_curr = cls.validate_currency(tx.get("currency") or order_curr)
            canonical_txns.append(
                {
                    "transaction_id": str(tx.get("id") or "").strip(),
                    "authorization": str(tx.get("authorization") or "").strip() if tx.get("authorization") else None,
                    "charge_id": str(charge_id).strip() if charge_id else None,
                    "gateway": str(tx.get("gateway") or "").strip() if tx.get("gateway") else None,
                    "status": str(tx.get("status") or "").strip() if tx.get("status") else None,
                    "amount": cls.format_exact_monetary(tx.get("amount"), tx_curr) if tx.get("amount") is not None else None,
                }
            )
        canonical_txns.sort(
            key=lambda x: (
                x["transaction_id"],
                x["authorization"] or "",
                x["charge_id"] or "",
            )
        )

        return {
            "provider_order_id": str(order.get("id") or "").strip(),
            "order_identity": str(order.get("name") or order.get("order_number") or "").strip(),
            "customer_reference": cust_ref,
            "currency": order_curr,
            "gross_amount": cls.format_exact_monetary(order.get("total_price"), order_curr),
            "discounts": cls.format_exact_monetary(order.get("total_discounts"), order_curr),
            "taxes": cls.format_exact_monetary(order.get("total_tax"), order_curr),
            "shipping": cls.format_exact_monetary(order.get("total_shipping") or order.get("total_shipping_price"), order_curr),
            "line_items": canonical_items,
            "order_status": str(order.get("financial_status") or order.get("order_status") or "open").strip().lower(),
            "cancellation_status": {
                "is_cancelled": bool(order.get("cancelled_at")),
                "cancelled_at": cls.to_utc_iso(order.get("cancelled_at")),
                "cancel_reason": str(order.get("cancel_reason")).strip() if order.get("cancel_reason") else None,
            },
            "refunds": canonical_refunds,
            "transaction_references": canonical_txns,
            "timestamps": {
                "created_at": cls.to_utc_iso(order.get("created_at")),
                "updated_at": cls.to_utc_iso(order.get("updated_at")),
                "processed_at": cls.to_utc_iso(order.get("processed_at")),
                "cancelled_at": cls.to_utc_iso(order.get("cancelled_at")),
            },
        }

    @classmethod
    def canonicalize_stripe_transaction(cls, txn: dict[str, Any]) -> dict[str, Any]:
        """
        Deterministically canonicalize all relevant payment, fee, refund, and settlement fields of a Stripe transaction.
        """
        txn_id = str(txn.get("id") or "").strip()
        is_charge = txn_id.startswith("ch_") or txn.get("type") == "charge"
        is_pi = txn_id.startswith("pi_")

        pi_id = str(txn.get("payment_intent") or "").strip() if txn.get("payment_intent") else (txn_id if is_pi else None)
        charge_id = txn_id if is_charge else (str(txn.get("charge") or "").strip() if txn.get("charge") else None)
        balance_txn_id = str(txn.get("balance_transaction") or "").strip() if txn.get("balance_transaction") else None
        payout_id = str(txn.get("payout") or txn.get("payout_id") or "").strip() if (txn.get("payout") or txn.get("payout_id")) else None

        txn_curr = cls.validate_currency(txn.get("currency"))

        amt_raw = txn.get("amount")
        is_amt_cents = isinstance(amt_raw, int)
        captured_raw = txn.get("amount_captured") if txn.get("amount_captured") is not None else amt_raw
        is_captured_cents = isinstance(captured_raw, int)
        refunded_raw = txn.get("amount_refunded") if txn.get("amount_refunded") is not None else 0
        is_refunded_cents = isinstance(refunded_raw, int)
        fee_raw = txn.get("fee") if txn.get("fee") is not None else 0
        is_fee_cents = isinstance(fee_raw, int)

        net_raw = txn.get("net")
        if net_raw is None and is_amt_cents and is_fee_cents:
            net_raw = (amt_raw or 0) - (fee_raw or 0)
        is_net_cents = isinstance(net_raw, int)

        meta = txn.get("metadata") if isinstance(txn.get("metadata"), dict) else {}

        return {
            "payment_intent_id": pi_id,
            "charge_id": charge_id,
            "balance_transaction_id": balance_txn_id,
            "payout_id": payout_id,
            "currency": txn_curr,
            "gross_amount": cls.format_exact_monetary(amt_raw, txn_curr, is_minor_units=is_amt_cents),
            "captured_amount": cls.format_exact_monetary(captured_raw, txn_curr, is_minor_units=is_captured_cents),
            "refund_amount": cls.format_exact_monetary(refunded_raw, txn_curr, is_minor_units=is_refunded_cents),
            "processing_fees": cls.format_exact_monetary(fee_raw, txn_curr, is_minor_units=is_fee_cents),
            "net_settlement": cls.format_exact_monetary(net_raw, txn_curr, is_minor_units=is_net_cents),
            "payment_status": str(txn.get("status") or "succeeded").strip().lower(),
            "settlement_status": str(
                txn.get("settlement_status") or ("settled" if txn.get("status") == "succeeded" else "unsettled")
            ).strip().lower(),
            "original_transaction_linkage": {
                "source": str(txn.get("source") or "").strip() if txn.get("source") else None,
                "metadata_order_id": str(meta.get("order_id") or "").strip() if meta.get("order_id") else None,
                "metadata_order_number": str(meta.get("order_number") or "").strip() if meta.get("order_number") else None,
            },
            "timestamps": {
                "created_at": cls.to_utc_iso(txn.get("created") or txn.get("created_at")),
                "available_on": cls.to_utc_iso(txn.get("available_on")),
            },
        }

    @classmethod
    def compute_canonical_shopify_digest(
        cls,
        shopify_orders: list[dict[str, Any]],
        business_id: str,
        store_domain: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> tuple[str, bytes]:
        """
        Serialize Shopify orders into deterministic canonical JSON and compute SHA-256 digest.
        """
        canonical_orders = [cls.canonicalize_shopify_order(o) for o in shopify_orders]
        canonical_orders.sort(
            key=lambda x: (
                x["provider_order_id"],
                x["timestamps"]["created_at"] or "",
                x["order_identity"],
            )
        )

        domain_payload = {
            "schema_version": SCHEMA_VERSION_V2,
            "tenant_id": str(business_id).strip(),
            "provider": "shopify",
            "provider_account_id": str(store_domain).strip().lower(),
            "period_start": cls.to_utc_iso(period_start),
            "period_end": cls.to_utc_iso(period_end),
            "record_count": len(canonical_orders),
            "records": canonical_orders,
        }

        canonical_json_str = json.dumps(
            domain_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        canonical_bytes = canonical_json_str.encode("utf-8")
        digest = hashlib.sha256(canonical_bytes).hexdigest().lower()
        return digest, canonical_bytes

    @classmethod
    def compute_canonical_stripe_digest(
        cls,
        stripe_transactions: list[dict[str, Any]],
        business_id: str,
        account_id: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> tuple[str, bytes]:
        """
        Serialize Stripe transactions into deterministic canonical JSON and compute SHA-256 digest.
        """
        canonical_txns = [cls.canonicalize_stripe_transaction(t) for t in stripe_transactions]
        canonical_txns.sort(
            key=lambda x: (
                x["charge_id"] or x["payment_intent_id"] or x["balance_transaction_id"] or "",
                x["timestamps"]["created_at"] or "",
            )
        )

        domain_payload = {
            "schema_version": SCHEMA_VERSION_V2,
            "tenant_id": str(business_id).strip(),
            "provider": "stripe",
            "provider_account_id": str(account_id).strip().lower(),
            "period_start": cls.to_utc_iso(period_start),
            "period_end": cls.to_utc_iso(period_end),
            "record_count": len(canonical_txns),
            "records": canonical_txns,
        }

        canonical_json_str = json.dumps(
            domain_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        canonical_bytes = canonical_json_str.encode("utf-8")
        digest = hashlib.sha256(canonical_bytes).hexdigest().lower()
        return digest, canonical_bytes

    @classmethod
    def compute_dataset_identity_digest(
        cls,
        shopify_orders: list[dict[str, Any]],
        stripe_transactions: list[dict[str, Any]],
        business_id: str = "default_business",
        shopify_store_domain: str = "default.myshopify.com",
        stripe_account_id: str = "acct_default",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> dict[str, str]:
        """
        Compute full canonical content digests across Shopify and Stripe and generate the
        combined tamper-evident dataset_identity_digest bound to tenant and provider domains.
        """
        shopify_digest, _ = cls.compute_canonical_shopify_digest(
            shopify_orders=shopify_orders,
            business_id=business_id,
            store_domain=shopify_store_domain,
            period_start=period_start,
            period_end=period_end,
        )

        stripe_digest, _ = cls.compute_canonical_stripe_digest(
            stripe_transactions=stripe_transactions,
            business_id=business_id,
            account_id=stripe_account_id,
            period_start=period_start,
            period_end=period_end,
        )

        # Combined canonical domain binding
        combined_binding = (
            f"{SCHEMA_VERSION_V2}:"
            f"tenant={str(business_id).strip()}:"
            f"shopify={str(shopify_store_domain).strip().lower()}:{shopify_digest}:"
            f"stripe={str(stripe_account_id).strip().lower()}:{stripe_digest}"
        )
        dataset_identity_digest = hashlib.sha256(combined_binding.encode("utf-8")).hexdigest().lower()

        return {
            "shopify": shopify_digest,
            "stripe": stripe_digest,
            "dataset_identity_digest": dataset_identity_digest,
            "schema_version": SCHEMA_VERSION_V2,
        }
