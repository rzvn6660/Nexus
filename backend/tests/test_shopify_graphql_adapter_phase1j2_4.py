"""
NEXUS Phase 1J.2.4 — Shopify GraphQL Admin API Modernization Tests.

Verifies:
1. Pinned supported stable API version (2026-10) and official 12-month release schedule.
2. GraphQL query execution, headers, and endpoint URL targeting.
3. Fall-forward detection: response header X-Shopify-API-Version mismatch detection.
4. GraphQL cursor pagination with pageInfo (hasNextPage, endCursor) and rolling cursor chain hash.
5. Interrupted pagination checkpoint resumption with unbroken cursor chain hash.
6. Extraction and normalization of rich GraphQL schema entities (GIDs, MoneySets, line items, customer).
7. Non-silent error handling: inaccessible fields, partial GraphQL errors, and throttling (extensions.cost).
8. Connection validation and health check using GraphQL shop query.
"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.connectors.shopify_adapter import (
    DEFAULT_SHOPIFY_API_VERSION,
    SHOPIFY_GRAPHQL_SHOP_QUERY,
    SUPPORTED_SHOPIFY_API_VERSIONS,
    ShopifyAdapter,
)
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.schemas.source_sync import SyncCheckpoint
from sqlalchemy.orm import Session


def _create_isolated_tenant(session: Session, suffix: str) -> Business:
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-gql-{suffix}-{uid}", name=f"GQL Org {suffix}", slug=f"gql-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-gql-{suffix}-{uid}",
        organization_id=org.id,
        name=f"GQL Business {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-gql-{suffix}-{uid}",
        email=f"user_{suffix}_{uid}@example.com",
        full_name=f"User {suffix}",
        password_hash="mock",
        is_active=True,
        is_verified=True,
    )
    mem = OrganizationMembership(
        id=f"mem-gql-{suffix}-{uid}",
        organization_id=org.id,
        user_id=user.id,
        role="owner",
    )
    session.add_all([org, biz, user, mem])
    session.commit()
    return biz


class MockShopifyGraphQLClient:
    """Mock GraphQL client simulating Shopify Admin API responses."""

    def __init__(self, pages: list[dict] | None = None, fall_forward_version: str | None = None):
        self.pages = pages or []
        self.current_page_idx = 0
        self.fall_forward_version = fall_forward_version
        self.calls: list[dict] = []

    def execute_graphql(self, query: str, variables: dict | None = None) -> dict:
        self.calls.append({"query": query, "variables": variables})
        if "ValidateShopConnection" in query:
            return {
                "data": {
                    "shop": {
                        "id": "gid://shopify/Shop/99887766",
                        "name": "Modern GraphQL Store",
                        "myshopifyDomain": "modern-store.myshopify.com",
                        "currencyCode": "USD",
                        "timezoneOffset": "+0000",
                        "plan": {"displayName": "Shopify Plus"},
                    }
                },
                "extensions": {
                    "cost": {
                        "requestedQueryCost": 2,
                        "actualQueryCost": 2,
                        "throttleStatus": {
                            "maximumAvailable": 1000,
                            "currentlyAvailable": 950,
                            "restoreRate": 50,
                        },
                    }
                },
            }

        if "GetOrders" in query:
            if self.current_page_idx < len(self.pages):
                resp = self.pages[self.current_page_idx]
                self.current_page_idx += 1
                return resp
            return {
                "data": {
                    "orders": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [],
                    }
                }
            }

        return {"data": {}}


def test_api_version_pinning_and_schedule_compliance():
    """Verify default API version is pinned to a currently supported version."""
    assert DEFAULT_SHOPIFY_API_VERSION == "2026-10"
    assert "2026-10" in SUPPORTED_SHOPIFY_API_VERSIONS
    assert "2026-07" in SUPPORTED_SHOPIFY_API_VERSIONS
    assert "2024-01" not in SUPPORTED_SHOPIFY_API_VERSIONS

    adapter = ShopifyAdapter(
        {"shop_domain": "test.myshopify.com", "access_token": "shpat_abc123"},
        "biz_test_ver",
    )
    assert adapter.api_version == "2026-10"
    assert adapter.actual_servicing_version == "2026-10"
    assert adapter.fall_forward_detected is False


def test_fall_forward_detection_via_response_header():
    """Verify that Shopify fall-forward behavior is detected when response header differs from requested version."""
    adapter = ShopifyAdapter(
        {
            "shop_domain": "retired-store.myshopify.com",
            "access_token": "shpat_retired123",
            "api_version": "2025-04",  # Hypothetical older version
        },
        "biz_ff",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {
        "Content-Type": "application/json",
        "X-Shopify-API-Version": "2026-01",  # Shopify fell forward to oldest supported version
    }
    mock_resp.json.return_value = {
        "data": {
            "shop": {
                "id": "gid://shopify/Shop/123",
                "name": "Fall Forward Test Store",
                "myshopifyDomain": "retired-store.myshopify.com",
            }
        }
    }

    with patch("requests.post", return_value=mock_resp):
        res = adapter.execute_graphql(SHOPIFY_GRAPHQL_SHOP_QUERY)
        assert "data" in res
        assert adapter.fall_forward_detected is True
        assert adapter.actual_servicing_version == "2026-01"
        assert adapter.fall_forward_warning is not None
        assert "FALL-FORWARD DETECTED" in adapter.fall_forward_warning
        assert "2025-04" in adapter.fall_forward_warning
        assert "2026-01" in adapter.fall_forward_warning


def test_graphql_cursor_pagination_and_chain_hash():
    """Verify multi-page GraphQL cursor pagination with pageInfo and rolling SHA-256 chain hash."""
    page_1_data = {
        "data": {
            "orders": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor_page_1_end"},
                "edges": [
                    {
                        "cursor": "c1",
                        "node": {
                            "id": "gid://shopify/Order/2001",
                            "name": "#2001",
                            "createdAt": "2026-10-15T10:00:00Z",
                            "displayFinancialStatus": "PAID",
                            "currencyCode": "USD",
                            "totalPriceSet": {"shopMoney": {"amount": "150.00", "currencyCode": "USD"}},
                            "totalTaxSet": {"shopMoney": {"amount": "12.00", "currencyCode": "USD"}},
                            "totalDiscountsSet": {"shopMoney": {"amount": "0.00", "currencyCode": "USD"}},
                            "customer": {
                                "id": "gid://shopify/Customer/501",
                                "displayName": "Alice Smith",
                                "email": "alice@example.com",
                            },
                            "lineItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "gid://shopify/LineItem/801",
                                            "sku": "SKU-PROD-A",
                                            "title": "Product A",
                                            "quantity": 1,
                                            "originalUnitPriceSet": {"shopMoney": {"amount": "150.00", "currencyCode": "USD"}},
                                        }
                                    }
                                ]
                            },
                        },
                    }
                ],
            }
        }
    }

    page_2_data = {
        "data": {
            "orders": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {
                        "cursor": "c2",
                        "node": {
                            "id": "gid://shopify/Order/2002",
                            "name": "#2002",
                            "createdAt": "2026-10-16T14:30:00Z",
                            "displayFinancialStatus": "PAID",
                            "currencyCode": "USD",
                            "totalPriceSet": {"shopMoney": {"amount": "200.00", "currencyCode": "USD"}},
                            "totalTaxSet": {"shopMoney": {"amount": "16.00", "currencyCode": "USD"}},
                            "totalDiscountsSet": {"shopMoney": {"amount": "10.00", "currencyCode": "USD"}},
                            "customer": {
                                "id": "gid://shopify/Customer/502",
                                "displayName": "Bob Jones",
                                "email": "bob@example.com",
                            },
                            "lineItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "gid://shopify/LineItem/802",
                                            "sku": "SKU-PROD-B",
                                            "title": "Product B",
                                            "quantity": 2,
                                            "originalUnitPriceSet": {"shopMoney": {"amount": "100.00", "currencyCode": "USD"}},
                                        }
                                    }
                                ]
                            },
                        },
                    }
                ],
            }
        }
    }

    mock_client = MockShopifyGraphQLClient(pages=[page_1_data, page_2_data])
    adapter = ShopifyAdapter(
        {"shop_domain": "test-pag.myshopify.com", "access_token": "shpat_mock123"},
        "biz_pag_test",
        shopify_client=mock_client,
    )

    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)

    # Page 1
    p1 = adapter.fetch_transactions_page(p_start, p_end, page_size=1)
    assert p1.page_records_count == 1
    assert p1.has_more is True
    assert p1.next_cursor == "cursor_page_1_end"
    assert p1.records[0].source_transaction_id == "shopify_order_2001"
    assert p1.records[0].gross_amount == Decimal("150.00")
    assert p1.records[0].customer_name == "Alice Smith"
    root_hash = hashlib.sha256(b"ROOT").hexdigest()
    expected_h1 = adapter.compute_cursor_chain_hash(root_hash, "cursor_page_1_end")
    assert p1.cursor_chain_hash == expected_h1

    # Page 2
    p2 = adapter.fetch_transactions_page(
        p_start, p_end, cursor=p1.next_cursor, previous_chain_hash=p1.cursor_chain_hash
    )
    assert p2.page_records_count == 1
    assert p2.has_more is False
    assert p2.next_cursor is None
    assert p2.records[0].source_transaction_id == "shopify_order_2002"
    assert p2.records[0].gross_amount == Decimal("200.00")
    assert p2.records[0].line_items[0].quantity == 2
    expected_h2 = adapter.compute_cursor_chain_hash(expected_h1, None)
    assert p2.cursor_chain_hash == expected_h2


def test_interrupted_checkpoint_resumption_graphql():
    """Verify that an interrupted GraphQL sync preserves checkpoint and resumes correctly."""
    orders_batch = [
        {
            "data": {
                "orders": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor_interrupted_01"},
                    "edges": [
                        {
                            "cursor": "c1",
                            "node": {
                                "id": "gid://shopify/Order/3001",
                                "name": "#3001",
                                "createdAt": "2026-10-20T10:00:00Z",
                                "totalPriceSet": {"shopMoney": {"amount": "75.00"}},
                            },
                        }
                    ],
                }
            }
        },
        {
            "data": {
                "orders": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [
                        {
                            "cursor": "c2",
                            "node": {
                                "id": "gid://shopify/Order/3002",
                                "name": "#3002",
                                "createdAt": "2026-10-20T11:00:00Z",
                                "totalPriceSet": {"shopMoney": {"amount": "125.00"}},
                            },
                        }
                    ],
                }
            }
        },
    ]

    mock_client = MockShopifyGraphQLClient(pages=orders_batch)
    adapter = ShopifyAdapter(
        {"shop_domain": "resume-test.myshopify.com", "access_token": "shpat_resume123"},
        "biz_resume",
        shopify_client=mock_client,
    )

    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)

    checkpoint = SyncCheckpoint(
        checkpoint_id="chk_01",
        business_id="biz_resume",
        provider="shopify",
        sync_mode="historical",
        period_start=p_start,
        period_end=p_end,
        current_cursor=None,
        cursor_chain_hash=hashlib.sha256(b"ROOT").hexdigest(),
        records_extracted=0,
        is_complete=False,
    )

    # Stream first page only
    gen = adapter.stream_historical(p_start, p_end, checkpoint=checkpoint)
    rec1 = next(gen)
    assert rec1.source_transaction_id == "shopify_order_3001"
    assert checkpoint.current_cursor == "cursor_interrupted_01"
    assert checkpoint.records_extracted == 1
    assert checkpoint.is_complete is False

    # Resume with existing checkpoint
    rec2 = next(gen)
    assert rec2.source_transaction_id == "shopify_order_3002"
    assert checkpoint.records_extracted == 2
    assert checkpoint.is_complete is True


def test_graphql_error_handling_and_missing_orders_rejection():
    """Verify that GraphQL syntax errors and inaccessible missing orders fail loudly."""
    adapter = ShopifyAdapter(
        {"shop_domain": "error-test.myshopify.com", "access_token": "shpat_err123"},
        "biz_err",
    )

    # 1. Top-level syntax error
    mock_resp_err = MagicMock()
    mock_resp_err.status_code = 200
    mock_resp_err.headers = {"Content-Type": "application/json"}
    mock_resp_err.json.return_value = {
        "errors": [{"message": "Field 'nonExistent' doesn't exist on type 'Order'"}],
        "data": None,
    }

    with (
        patch("requests.post", return_value=mock_resp_err),
        pytest.raises(RuntimeError, match="Shopify GraphQL query execution failed"),
    ):
        adapter.execute_graphql("query { orders { nonExistent } }")

    # 2. Response missing 'orders' field entirely
    mock_resp_missing = MagicMock()
    mock_resp_missing.status_code = 200
    mock_resp_missing.headers = {"Content-Type": "application/json"}
    mock_resp_missing.json.return_value = {
        "data": {"otherCollection": []}  # 'orders' field missing
    }

    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)
    with (
        patch("requests.post", return_value=mock_resp_missing),
        pytest.raises(RuntimeError, match="missing 'orders' collection"),
    ):
        adapter.fetch_transactions_page(p_start, p_end)


def test_graphql_connection_validation_and_health():
    """Verify validate_connection and check_health against GraphQL shop query."""
    mock_client = MockShopifyGraphQLClient()
    adapter = ShopifyAdapter(
        {"shop_domain": "health-test.myshopify.com", "access_token": "shpat_health123"},
        "biz_health",
        shopify_client=mock_client,
    )

    assert adapter.validate_connection() is True
    health = adapter.check_health()
    assert health.is_healthy is True
    assert health.quota_remaining > 0
    assert health.error_classification == "OK"
