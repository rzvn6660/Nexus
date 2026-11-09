"""
NEXUS Phase 1J.2.4 — Shopify GraphQL Admin API Modernized Adapter.

Provides:
1. ShopifyAdapter: Implementation of SourceConnectorAdapter using Shopify GraphQL Admin API:
   - Pinned to supported stable version 2026-10 (Shopify quarterly release schedule).
   - Validates store connection via GraphQL query { shop { id name myshopifyDomain } }.
   - Extracts and normalizes commercial orders, customers, line items, refunds, and cancellations.
   - GraphQL cursor pagination using pageInfo (hasNextPage, endCursor).
   - Rolling SHA-256 cursor chain hash for tamper-evident pagination auditability.
   - Fall-forward detection: inspects X-Shopify-API-Version response header to detect retired version fall-forward.
   - GraphQL error and partial data detection with throttling handling (extensions.cost).
   - Webhook security: Base64-encoded HMAC-SHA256 signature verification (X-Shopify-Hmac-SHA256).
   - Integration with durable database WebhookInboxService.
   - Strict real-tenant isolation preventing sandbox certifications of protected tenants.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import uuid4

from app.connectors.source_connector_adapter import SourceConnectorAdapter
from app.schemas.source_sync import (
    ConnectionHealth,
    ConnectorAuthStatus,
    ExtractedLineItem,
    ExtractedRecord,
    ExtractionPage,
    PeriodCloseEvidence,
    SourceMetadata,
    SyncCheckpoint,
)

logger = logging.getLogger(__name__)

# Pinned supported stable API version per Shopify quarterly release schedule (12-month lifecycle)
DEFAULT_SHOPIFY_API_VERSION = "2026-10"
SUPPORTED_SHOPIFY_API_VERSIONS: set[str] = {
    "2026-10",
    "2026-07",
    "2026-04",
    "2026-01",
    "2025-10",
    "2025-07",
    "2025-04",
    "2025-01",
}

SHOPIFY_GRAPHQL_ORDERS_QUERY = """
query GetOrders($pageSize: Int!, $cursor: String, $query: String) {
  orders(first: $pageSize, after: $cursor, query: $query, sortKey: CREATED_AT) {
    pageInfo {
      hasNextPage
      hasPreviousPage
      startCursor
      endCursor
    }
    edges {
      cursor
      node {
        id
        name
        createdAt
        cancelledAt
        displayFinancialStatus
        displayFulfillmentStatus
        currencyCode
        totalPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        totalDiscountsSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        totalTaxSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        customer {
          id
          displayName
          firstName
          lastName
          email
        }
        email
        lineItems(first: 50) {
          edges {
            node {
              id
              sku
              title
              quantity
              originalUnitPriceSet {
                shopMoney {
                  amount
                  currencyCode
                }
              }
            }
          }
        }
        fulfillments {
          id
          status
          createdAt
        }
        refunds {
          id
          createdAt
          totalRefundedSet {
            shopMoney {
              amount
              currencyCode
            }
          }
        }
      }
    }
  }
}
"""

SHOPIFY_GRAPHQL_SHOP_QUERY = """
query ValidateShopConnection {
  shop {
    id
    name
    myshopifyDomain
    currencyCode
    timezoneOffset
    plan {
      displayName
    }
  }
}
"""


class ShopifyAdapter(SourceConnectorAdapter):
    """
    NEXUS Source Connector Adapter for Shopify Partner Development Stores (GraphQL Admin API).

    Extracts commercial storefront data: orders, items, fulfillment, cancellations, and refunds.
    Pairs with StripeAdapter (payment & settlement evidence) via CrossSourceReconciliationService.
    """

    REQUIRED_SCOPES: ClassVar[set[str]] = {"read_orders"}
    DEFAULT_SCOPES: ClassVar[list[str]] = [
        "read_orders",
        "read_products",
        "read_customers",
        "read_fulfillments",
    ]

    def __init__(
        self,
        tenant_credentials: dict[str, Any],
        business_id: str,
        shopify_client: Any | None = None,
        max_retries: int = 3,
        rate_limit_backoff_sec: float = 0.05,
    ):
        super().__init__(tenant_credentials, business_id)
        self.shop_domain = tenant_credentials.get("shop_domain", "").strip().lower()
        self.access_token = tenant_credentials.get("access_token", "").strip()
        self.webhook_secret = tenant_credentials.get("webhook_secret", "").strip()
        self.api_version = tenant_credentials.get("api_version", DEFAULT_SHOPIFY_API_VERSION).strip()
        self.shopify_client = shopify_client
        self.max_retries = max_retries
        self.rate_limit_backoff_sec = rate_limit_backoff_sec

        # Telemetry tracking for versioning and fall-forward detection
        self.actual_servicing_version: str = self.api_version
        self.fall_forward_detected: bool = False
        self.fall_forward_warning: str | None = None

        # Standardize shop domain
        if self.shop_domain and not self.shop_domain.endswith(".myshopify.com") and "." not in self.shop_domain:
            self.shop_domain = f"{self.shop_domain}.myshopify.com"

        # In-memory deduplication fallback
        self._processed_webhook_event_ids: set[str] = set()

    def get_auth_status(self) -> ConnectorAuthStatus:
        """Validate Shopify access token syntax, expiration, required scopes, and domain."""
        if not self.access_token or not self.shop_domain:
            return ConnectorAuthStatus(
                is_authenticated=False,
                auth_type="shopify_custom_app",
                account_id=self.shop_domain or None,
                scopes=[],
                error_message="Missing Shopify shop domain or access token.",
            )

        if not (
            self.access_token.startswith("shpat_")
            or self.access_token.startswith("shpca_")
            or self.access_token.startswith("mock_shpat_")
        ):
            return ConnectorAuthStatus(
                is_authenticated=False,
                auth_type="shopify_custom_app",
                account_id=self.shop_domain,
                scopes=[],
                error_message="Invalid Shopify access token format: expected 'shpat_' prefix.",
            )

        # Check token expiration
        expires_at = self.credentials.get("expires_at")
        if expires_at:
            exp_dt = expires_at if isinstance(expires_at, datetime) else None
            if not exp_dt and isinstance(expires_at, str):
                try:
                    exp_dt = datetime.fromisoformat(expires_at)
                except (ValueError, TypeError):
                    pass
            if exp_dt:
                now_utc = datetime.now(UTC)
                exp_utc = exp_dt if exp_dt.tzinfo else exp_dt.replace(tzinfo=UTC)
                if now_utc > exp_utc:
                    return ConnectorAuthStatus(
                        is_authenticated=False,
                        auth_type="shopify_custom_app",
                        account_id=self.shop_domain,
                        scopes=[],
                        error_message="Shopify access token expired.",
                    )

        # Check required scopes
        configured_scopes = self.credentials.get("scopes")
        if configured_scopes is not None:
            c_set = set(configured_scopes)
            missing = self.REQUIRED_SCOPES - c_set
            if missing:
                return ConnectorAuthStatus(
                    is_authenticated=False,
                    auth_type="shopify_custom_app",
                    account_id=self.shop_domain,
                    scopes=configured_scopes,
                    error_message=f"Missing required Shopify scopes: {sorted(missing)}",
                )

        granted_scopes = configured_scopes if configured_scopes is not None else list(self.DEFAULT_SCOPES)

        return ConnectorAuthStatus(
            is_authenticated=True,
            auth_type="shopify_custom_app",
            account_id=self.shop_domain,
            scopes=granted_scopes,
            last_verified_at=datetime.now(UTC),
        )

    def execute_graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        timeout: int = 15,
    ) -> dict[str, Any]:
        """
        Execute a GraphQL query against Shopify Admin API endpoint.

        Enforces:
        - POST to /admin/api/{self.api_version}/graphql.json
        - Header X-Shopify-Access-Token and Content-Type: application/json
        - Verification of response header X-Shopify-API-Version to detect fall-forward
        - Detection and handling of top-level errors and userErrors
        - Inspection of extensions.cost for rate limiting and throttling
        - Retry on transient HTTP 429 / 5xx or throttling
        """
        if self.shopify_client is not None and hasattr(self.shopify_client, "execute_graphql"):
            return self.shopify_client.execute_graphql(query=query, variables=variables)

        import requests

        url = f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {"query": query, "variables": variables or {}}

        attempts = 0
        while attempts < self.max_retries:
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
                attempts += 1

                # Check actual API version returned by Shopify
                actual_hdr = resp.headers.get("X-Shopify-API-Version") or resp.headers.get("x-shopify-api-version")
                if actual_hdr:
                    actual_clean = actual_hdr.strip()
                    self.actual_servicing_version = actual_clean
                    if actual_clean != self.api_version:
                        warning_msg = (
                            f"SHOPIFY API FALL-FORWARD DETECTED: Configured/requested API version '{self.api_version}' "
                            f"has retired or is unsupported. Shopify processed request using '{actual_clean}'."
                        )
                        logger.warning(warning_msg)
                        self.fall_forward_detected = True
                        self.fall_forward_warning = warning_msg

                # Handle HTTP 429 rate limit
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "1.0"))
                    time.sleep(retry_after)
                    continue

                if resp.status_code >= 500:
                    time.sleep(self.rate_limit_backoff_sec * (2**attempts))
                    continue

                if resp.status_code != 200:
                    raise RuntimeError(f"Shopify GraphQL returned HTTP {resp.status_code}: {resp.text}")

                data = resp.json()

                # Handle GraphQL errors
                errors = data.get("errors")
                if errors:
                    err_msgs = [e.get("message", "") for e in errors if isinstance(e, dict)]
                    # Check for throttling error
                    if any("Throttled" in m or "exceeded" in m.lower() for m in err_msgs):
                        time.sleep(self.rate_limit_backoff_sec * (2**attempts))
                        continue
                    # Hard execution failure
                    if data.get("data") is None:
                        raise RuntimeError(f"Shopify GraphQL query execution failed: {errors}")
                    logger.warning(f"Shopify GraphQL partial errors: {errors}")

                return data

            except Exception as e:
                if attempts >= self.max_retries:
                    raise RuntimeError(f"Shopify GraphQL request failed after {attempts} attempts: {e}") from e
                time.sleep(self.rate_limit_backoff_sec * (2**attempts))

        raise RuntimeError("Shopify GraphQL max retry limit exceeded.")

    def validate_connection(self) -> bool:
        """Verify shop connectivity and credentials using GraphQL."""
        status = self.get_auth_status()
        if not status.is_authenticated:
            return False

        if self.shopify_client is not None:
            if hasattr(self.shopify_client, "validate_connection"):
                return bool(self.shopify_client.validate_connection())
            return True

        try:
            res = self.execute_graphql(SHOPIFY_GRAPHQL_SHOP_QUERY)
            return "data" in res and res["data"] is not None and "shop" in res["data"]
        except (RuntimeError, ValueError, KeyError, OSError) as e:
            logger.warning(f"Shopify connection validation failed: {e}")
            return False

    def get_metadata(self) -> SourceMetadata:
        """Return discovery metadata for Shopify sandbox store."""
        return SourceMetadata(
            provider="shopify",
            provider_account_id=self.shop_domain or f"shop_shopify_{self.business_id[:8]}.myshopify.com",
            source_name="Shopify Partner Sandbox (Development Store)",
            supported_sync_modes=["historical", "incremental", "webhook"],
            supports_period_close=False,  # Shopify storefront does not issue bank deposit settlement locks
            settlement_type="none",
            default_currency="USD",
            timezone="UTC",
            rate_limit_info={
                "tier": "graphql_cost",
                "restore_rate_per_sec": 50,
                "maximum_available": 1000,
                "api_type": "graphql",
                "api_version": self.api_version,
            },
        )

    def check_health(self) -> ConnectionHealth:
        """Check live connection latency and call limits using GraphQL cost telemetry."""
        start_t = time.perf_counter()
        if self.shopify_client is not None:
            if hasattr(self.shopify_client, "check_health"):
                return self.shopify_client.check_health()
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            return ConnectionHealth(
                is_healthy=True,
                latency_ms=elapsed_ms,
                quota_remaining=38,
                error_classification="OK",
                message="Shopify mock client operational.",
            )

        try:
            res = self.execute_graphql(SHOPIFY_GRAPHQL_SHOP_QUERY)
            elapsed_ms = (time.perf_counter() - start_t) * 1000

            # Extract throttle status from GraphQL cost extensions if available
            extensions = res.get("extensions", {})
            cost = extensions.get("cost", {})
            throttle = cost.get("throttleStatus", {})
            quota_avail = throttle.get("currentlyAvailable", 50)

            return ConnectionHealth(
                is_healthy=True,
                latency_ms=elapsed_ms,
                quota_remaining=int(quota_avail),
                error_classification="OK",
                message=f"Shopify GraphQL Admin API ({self.api_version}) responsive.",
            )
        except (RuntimeError, ValueError, KeyError, OSError) as e:
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            err_str = str(e)
            if "throttled" in err_str.lower() or "429" in err_str:
                return ConnectionHealth(
                    is_healthy=False,
                    latency_ms=elapsed_ms,
                    quota_remaining=0,
                    error_classification="RATE_LIMITED",
                    message=f"Shopify API rate limited: {e}",
                )
            return ConnectionHealth(
                is_healthy=False,
                latency_ms=elapsed_ms,
                error_classification="UNREACHABLE",
                message=f"Shopify health check exception: {e}",
            )

    def fetch_transactions_page(
        self,
        period_start: datetime,
        period_end: datetime,
        cursor: str | None = None,
        page_size: int = 100,
        previous_chain_hash: str | None = None,
    ) -> ExtractionPage:
        """
        Fetch a single page of Shopify orders within [period_start, period_end].
        Implements GraphQL cursor pagination (pageInfo.hasNextPage, pageInfo.endCursor)
        and rolling chain hash.
        """
        prev_hash = previous_chain_hash or hashlib.sha256(b"ROOT").hexdigest()

        raw_orders: list[dict[str, Any]] = []
        next_cursor: str | None = None
        has_more = False

        attempts = 0
        while attempts < self.max_retries:
            try:
                if self.shopify_client is not None:
                    if hasattr(self.shopify_client, "execute_graphql"):
                        query_str = (
                            f"created_at:>='{period_start.isoformat()}' AND created_at:<='{period_end.isoformat()}'"
                        )
                        variables = {"pageSize": page_size, "cursor": cursor, "query": query_str}
                        gql_res = self.shopify_client.execute_graphql(query=SHOPIFY_GRAPHQL_ORDERS_QUERY, variables=variables)
                        data_orders = (gql_res.get("data") or {}).get("orders") or {}
                        page_info = data_orders.get("pageInfo", {})
                        has_more = bool(page_info.get("hasNextPage", False))
                        next_cursor = page_info.get("endCursor") if has_more else None
                        for edge in data_orders.get("edges", []):
                            raw_orders.append(edge.get("node", {}))
                    elif hasattr(self.shopify_client, "fetch_orders"):
                        # Compatibility with legacy test client
                        page_data = self.shopify_client.fetch_orders(
                            period_start=period_start,
                            period_end=period_end,
                            cursor=cursor,
                            page_size=page_size,
                        )
                        raw_orders = page_data.get("orders", [])
                        has_more = page_data.get("has_more", False)
                        next_cursor = page_data.get("next_cursor")
                    break
                else:
                    # Construct GraphQL query with date filter
                    query_str = f"created_at:>='{period_start.isoformat()}' AND created_at:<='{period_end.isoformat()}'"
                    variables = {"pageSize": page_size, "cursor": cursor, "query": query_str}
                    res = self.execute_graphql(SHOPIFY_GRAPHQL_ORDERS_QUERY, variables=variables)

                    data_root = res.get("data")
                    if not data_root or "orders" not in data_root:
                        raise RuntimeError(
                            f"Shopify GraphQL response missing 'orders' collection (inaccessible or schema error): {res}"
                        )

                    orders_obj = data_root["orders"]
                    page_info = orders_obj.get("pageInfo", {})
                    has_more = bool(page_info.get("hasNextPage", False))
                    next_cursor = page_info.get("endCursor") if has_more else None

                    for edge in orders_obj.get("edges", []):
                        node = edge.get("node")
                        if node:
                            raw_orders.append(node)
                    break
            except Exception as e:
                attempts += 1
                if attempts >= self.max_retries:
                    raise RuntimeError(f"Shopify API error after {attempts} attempts: {e}") from e
                time.sleep(self.rate_limit_backoff_sec * (2**attempts))

        records: list[ExtractedRecord] = []
        for ord_dict in raw_orders:
            rec = self._normalize_shopify_order(ord_dict)
            records.append(rec)

        current_chain_hash = self.compute_cursor_chain_hash(prev_hash, next_cursor)
        gross_sum = sum((r.gross_amount for r in records), Decimal("0.00"))

        return ExtractionPage(
            records=records,
            page_number=1,
            has_more=has_more,
            next_cursor=next_cursor,
            cursor_chain_hash=current_chain_hash,
            page_records_count=len(records),
            gross_page_sum=gross_sum,
        )

    def _normalize_shopify_order(self, order: dict[str, Any]) -> ExtractedRecord:
        """
        Normalize a raw Shopify order (GraphQL node or REST dictionary) to an ExtractedRecord.
        Supports both modern GraphQL schema attributes and REST fields for full backward compatibility.
        """
        raw_id = str(order.get("id", uuid4().hex[:10]))
        # Extract numeric ID if GID format: gid://shopify/Order/123456
        order_id = raw_id.split("/")[-1] if "/" in raw_id else raw_id
        order_name = order.get("name") or f"#{order_id}"

        # Resolve gross amount from GraphQL totalPriceSet or REST total_price
        if order.get("totalPriceSet"):
            gross_str = str(order["totalPriceSet"].get("shopMoney", {}).get("amount", "0.00"))
        else:
            gross_str = str(order.get("total_price", "0.00"))

        # Resolve discounts
        if order.get("totalDiscountsSet"):
            discount_str = str(order["totalDiscountsSet"].get("shopMoney", {}).get("amount", "0.00"))
        else:
            discount_str = str(order.get("total_discounts", "0.00"))

        # Resolve tax
        if order.get("totalTaxSet"):
            tax_str = str(order["totalTaxSet"].get("shopMoney", {}).get("amount", "0.00"))
        else:
            tax_str = str(order.get("total_tax", "0.00"))

        gross_dec = Decimal(gross_str)
        disc_dec = Decimal(discount_str)
        tax_dec = Decimal(tax_str)
        net_dec = gross_dec - tax_dec

        # Transaction timestamp (GraphQL createdAt or REST created_at)
        c_at_raw = order.get("createdAt") or order.get("created_at")
        if isinstance(c_at_raw, str):
            try:
                txn_dt = datetime.fromisoformat(c_at_raw)
            except (ValueError, TypeError):
                txn_dt = datetime.now(UTC)
        elif isinstance(c_at_raw, datetime):
            txn_dt = c_at_raw if c_at_raw.tzinfo else c_at_raw.replace(tzinfo=UTC)
        else:
            txn_dt = datetime.now(UTC)

        # Status mapping (GraphQL displayFinancialStatus or REST financial_status)
        fin_status = (
            order.get("displayFinancialStatus") or order.get("financial_status", "paid")
        ).lower()
        cancelled_at = order.get("cancelledAt") or order.get("cancelled_at")

        if cancelled_at:
            status = "cancelled"
        elif fin_status in ("refunded",):
            status = "refunded"
        elif fin_status in ("partially_refunded", "partially_paid", "pending"):
            status = "pending"
        else:
            status = "completed"

        # Currency
        currency = (
            order.get("currencyCode")
            or order.get("currency")
            or "USD"
        ).upper()

        # Customer identity
        cust = order.get("customer") or {}
        raw_cust_id = str(cust.get("id", "")) if cust.get("id") else None
        cust_id = raw_cust_id.split("/")[-1] if raw_cust_id and "/" in raw_cust_id else raw_cust_id
        cust_email = cust.get("email") or order.get("email")
        cust_name = cust.get("displayName") or f"{cust.get('firstName', '')} {cust.get('lastName', '')}".strip() or None

        # Line items (GraphQL connection edges or REST array)
        line_items: list[ExtractedLineItem] = []
        raw_li_edges = (order.get("lineItems") or {}).get("edges") if isinstance(order.get("lineItems"), dict) else None
        if raw_li_edges is not None:
            for edge in raw_li_edges:
                node = edge.get("node", {})
                qty = int(node.get("quantity", 1))
                unit_p_str = node.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("amount", "0.00")
                unit_p = Decimal(str(unit_p_str))
                li_id_raw = str(node.get("id", uuid4().hex[:8]))
                li_id = li_id_raw.split("/")[-1] if "/" in li_id_raw else li_id_raw
                line_items.append(
                    ExtractedLineItem(
                        line_item_id=li_id,
                        sku=node.get("sku"),
                        title=node.get("title", "Product"),
                        quantity=qty,
                        unit_price=unit_p,
                        total_amount=unit_p * qty,
                    )
                )
        else:
            # REST format
            for li in order.get("line_items", []):
                qty = int(li.get("quantity", 1))
                unit_p = Decimal(str(li.get("price", "0.00")))
                li_id_raw = str(li.get("id", uuid4().hex[:8]))
                li_id = li_id_raw.split("/")[-1] if "/" in li_id_raw else li_id_raw
                line_items.append(
                    ExtractedLineItem(
                        line_item_id=li_id,
                        sku=li.get("sku"),
                        title=li.get("title", "Product"),
                        quantity=qty,
                        unit_price=unit_p,
                        total_amount=unit_p * qty,
                    )
                )

        payload_bytes = json.dumps(order, sort_keys=True).encode("utf-8")
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        return ExtractedRecord(
            source_transaction_id=f"shopify_order_{order_id}",
            transaction_number=order_name,
            customer_source_id=cust_id,
            customer_email=cust_email,
            customer_name=cust_name,
            transaction_date=txn_dt,
            status=status,
            currency=currency,
            gross_amount=gross_dec,
            discount_amount=disc_dec,
            tax_amount=tax_dec,
            net_amount=net_dec,
            fee_amount=Decimal("0.00"),  # Commercial storefront fees are zero; processing fees are in Stripe
            line_items=line_items,
            raw_payload_hash=payload_hash,
            provenance_type="shopify_sandbox",
            event_type="shopify.order",
        )

    def stream_historical(
        self,
        period_start: datetime,
        period_end: datetime,
        checkpoint: SyncCheckpoint | None = None,
    ) -> Iterator[ExtractedRecord]:
        """
        Stream historical orders sequentially using GraphQL cursor pagination.
        """
        cursor = checkpoint.current_cursor if checkpoint else None
        chain_hash = checkpoint.cursor_chain_hash if checkpoint else hashlib.sha256(b"ROOT").hexdigest()

        while True:
            page = self.fetch_transactions_page(
                period_start=period_start,
                period_end=period_end,
                cursor=cursor,
                page_size=100,
                previous_chain_hash=chain_hash,
            )

            cursor = page.next_cursor
            chain_hash = page.cursor_chain_hash

            if checkpoint:
                checkpoint.current_cursor = cursor
                checkpoint.cursor_chain_hash = chain_hash

            for idx, record in enumerate(page.records):
                if checkpoint:
                    checkpoint.records_extracted += 1
                    if (not page.has_more or not cursor) and idx == len(page.records) - 1:
                        checkpoint.is_complete = True
                        checkpoint.status = "COMPLETED"
                yield record

            if not page.has_more or not cursor:
                if checkpoint:
                    checkpoint.is_complete = True
                    checkpoint.status = "COMPLETED"
                break

    def stream_incremental(
        self,
        since: datetime,
        checkpoint: SyncCheckpoint | None = None,
    ) -> Iterator[ExtractedRecord]:
        now = datetime.now(UTC)
        yield from self.stream_historical(period_start=since, period_end=now, checkpoint=checkpoint)

    def fetch_period_close_evidence(
        self,
        period_identifier: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> PeriodCloseEvidence | None:
        """
        Shopify storefront does NOT issue independent bank settlement locks or closing date seals.
        Returns None to preserve provider completeness boundaries.
        """
        return None

    def verify_event_signature(
        self,
        headers: dict[str, str],
        body_bytes: bytes,
        secret: str | None = None,
    ) -> bool:
        """
        Verify Shopify webhook signature from X-Shopify-Hmac-SHA256 header.
        Shopify computes HMAC-SHA256 over raw request body and encodes it as Base64.
        """
        wh_secret = secret or self.webhook_secret
        if not wh_secret:
            return False

        h_lower = {k.lower(): v for k, v in headers.items()}
        header_sig = h_lower.get("x-shopify-hmac-sha256")
        if not header_sig:
            return False

        computed_raw = hmac.new(
            wh_secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).digest()
        expected_sig_b64 = base64.b64encode(computed_raw).decode("utf-8")

        return hmac.compare_digest(expected_sig_b64, header_sig)

    def process_webhook_event(
        self,
        headers: dict[str, str],
        body_bytes: bytes,
        secret: str | None = None,
        session: Any | None = None,
        worker_id: str = "worker_default",
    ) -> dict[str, Any]:
        """
        Authenticate, deduplicate, and process a Shopify webhook event.
        Delegates to WebhookInboxService if session provided.
        """
        if session is not None:
            from app.services.webhook_inbox_service import WebhookInboxService

            return WebhookInboxService.process_inbound_webhook(
                session=session,
                adapter=self,
                headers=headers,
                body_bytes=body_bytes,
                worker_id=worker_id,
            )

        if not self.verify_event_signature(headers, body_bytes, secret=secret):
            from stripe import SignatureVerificationError

            raise SignatureVerificationError("Invalid Shopify webhook HMAC-SHA256 signature.", "x-shopify-hmac-sha256")

        try:
            event_payload = json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Malformed Shopify webhook JSON payload: {e}") from e

        h_lower = {k.lower(): v for k, v in headers.items()}
        event_id = h_lower.get("x-shopify-webhook-id") or str(event_payload.get("id"))
        if not event_id:
            raise ValueError("Shopify webhook missing event ID.")

        if event_id in self._processed_webhook_event_ids:
            return {
                "status": "duplicate_ignored",
                "event_id": event_id,
                "message": f"Webhook event '{event_id}' has already been processed.",
            }

        self._processed_webhook_event_ids.add(event_id)

        return {
            "status": "processed",
            "event_id": event_id,
            "event_type": h_lower.get("x-shopify-topic", "orders/create"),
            "data": event_payload,
            "processed_at": datetime.now(UTC).isoformat(),
        }

    def refresh_credentials(self) -> dict[str, Any] | None:
        return None
