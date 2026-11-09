"""Playwright Browser Acceptance & Validation Script for Harbor & Thread Synthetic Pilot.

Verifies:
1. Manager login via Web UI (Daniel Morgan).
2. LocalStorage authentication token & active tenant binding.
3. Pulse Reports & Publications navigation.
4. ReportLab PDF download via table action button.
5. ReportLab PDF download via detail preview modal action button.
6. Bit-for-bit length and SHA-256 cryptographic match against stored database records.
7. PDF text assertions: Synthetic demonstration disclosures, AED currency formatting, estimated gross margin label.
8. Multi-tenant security isolation (401 unauthenticated, 403 cross-tenant IDOR, 404 missing report).
"""

import hashlib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from io import BytesIO

import pypdf
import requests
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, text

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://nexus_staging_user:2HdXqcozgE-bBa6LjY9Qd0fj9PDtEZMkTuvj1q6QCqU@127.0.0.1:5433/nexus_staging_db",
)
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1:3001")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8001")

MANAGER_EMAIL = "daniel.morgan@harbor-thread.local"
MANAGER_PASSWORD = "Harbor#2026!DubaiPilot"

def main():
    print("=" * 80)
    print("NEXUS — HARBOR & THREAD BROWSER ACCEPTANCE & VERIFICATION")
    print("=" * 80)

    # 1. Fetch Harbor & Thread Business ID and latest report from database
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        biz_row = conn.execute(
            text("SELECT id, name, currency FROM businesses WHERE name LIKE 'Harbor & Thread%'")
        ).fetchone()
        assert biz_row is not None, "Harbor & Thread business not found in database!"
        biz_id = biz_row.id
        print(f"  Target Business: {biz_row.name} (ID: {biz_id}, Currency: {biz_row.currency})")

        report_row = conn.execute(
            text(
                "SELECT id, report_title, pdf_sha256, length(pdf_file_bytes) as pdf_len, access_token "
                "FROM pulse_generated_reports WHERE business_id = :biz_id ORDER BY created_at DESC"
            ),
            {"biz_id": biz_id},
        ).fetchone()
        assert report_row is not None, "No Pulse reports found for Harbor & Thread!"
        report_id = report_row.id
        print(f"  Target Report ID: {report_id}")
        print(f"  Report Title:     {report_row.report_title}")
        print(f"  DB PDF Length:    {report_row.pdf_len} bytes")
        print(f"  DB PDF SHA-256:   {report_row.pdf_sha256}")

    # 2. Browser Automation via Playwright Chromium
    print("\n[Step 2] Running Browser Automation via Playwright Chromium...")
    temp_dir = tempfile.mkdtemp(prefix="nexus_ht_acceptance_")
    table_dl_path = os.path.join(temp_dir, "harbor_thread_browser_table.pdf")
    modal_dl_path = os.path.join(temp_dir, "harbor_thread_browser_modal.pdf")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        page = context.new_page()

        # Login
        print(f"  Navigating to {FRONTEND_URL}/login...")
        page.goto(f"{FRONTEND_URL}/login")
        page.wait_for_selector("#login-email", timeout=10000)

        print(f"  Logging in as Daniel Morgan ({MANAGER_EMAIL})...")
        page.fill("#login-email", MANAGER_EMAIL)
        page.fill("#login-password", MANAGER_PASSWORD)
        with page.expect_response("**/api/v1/auth/login", timeout=10000):
            page.click("button[type='submit']")

        page.wait_for_url(f"{FRONTEND_URL}/**", timeout=10000)
        page.wait_for_timeout(2500)
        storage_token = page.evaluate("() => localStorage.getItem('nexus_access_token')")
        storage_biz_id = page.evaluate("() => localStorage.getItem('nexus_business_id')")
        print(f"  Verified session token exists: {bool(storage_token)}")
        print(f"  Verified active business in localStorage: {storage_biz_id}")
        assert storage_token, "Access token missing after login"
        assert storage_biz_id == biz_id, f"Expected biz_id {biz_id}, got {storage_biz_id}"

        # Navigate to Pulse
        print("\n  Navigating to /pulse...")
        page.goto(f"{FRONTEND_URL}/pulse")
        page.wait_for_selector("button:has-text('Reports & Publications')", timeout=10000)

        # Switch to Reports tab
        print("  Switching to Reports & Publications tab...")
        with page.expect_response("**/api/v1/pulse/reports*", timeout=10000):
            page.locator("button:has-text('Reports & Publications')").click()

        page.wait_for_selector("table", timeout=10000)

        # Download from Reports Table row button
        print("  Clicking PDF download button from reports table...")
        pdf_button = page.locator("button[title='Download ReportLab PDF']").first
        with page.expect_download(timeout=10000) as download_info:
            pdf_button.click()

        download = download_info.value
        download.save_as(table_dl_path)
        print(f"  Browser downloaded PDF saved to: {table_dl_path}")

        # Open Detail Modal and Download from Modal
        print("  Opening Report Detail Preview Modal...")
        view_button = page.locator("button[title='View structured digital report']").first
        view_button.click()
        page.wait_for_selector("button:has-text('Download PDF')", timeout=10000)

        print("  Clicking 'Download PDF' button in detail preview modal...")
        modal_dl_btn = page.locator("button:has-text('Download PDF')").first
        with page.expect_download(timeout=10000) as modal_download_info:
            modal_dl_btn.click()

        modal_download = modal_download_info.value
        modal_download.save_as(modal_dl_path)
        print(f"  Modal downloaded PDF saved to: {modal_dl_path}")

        # Navigate to Customer Retention
        print("\n  Navigating to /retention...")
        page.goto(f"{FRONTEND_URL}/retention")
        page.wait_for_timeout(2000)

        browser.close()

    # 3. PDF Binary Verification and Deep Text Inspection
    print("\n[Step 3] Verifying Downloaded PDF Integrity & Synthetic Disclosures...")
    for dl_path, label in [(table_dl_path, "Table Download"), (modal_dl_path, "Modal Download")]:
        with open(dl_path, "rb") as f:
            pdf_bytes = f.read()

        file_len = len(pdf_bytes)
        file_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        print(f"  [{label}] File size: {file_len} bytes")
        print(f"  [{label}] SHA-256:   {file_sha256}")
        assert file_len == report_row.pdf_len, f"Size mismatch: {file_len} vs {report_row.pdf_len}"
        assert file_sha256 == report_row.pdf_sha256, f"SHA-256 mismatch: {file_sha256} vs {report_row.pdf_sha256}"

        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
        full_text = "\n".join(p.extract_text() for p in reader.pages)

        # Disclosures & Provenance Checks
        assert "*** SYNTHETIC DEMONSTRATION — NOT REAL MERCHANT DATA" in full_text
        assert "NOT FOR OFFICIAL FINANCIAL AUDIT" in full_text
        assert "Harbor & Thread — NEXUS Synthetic Pilot" in full_text
        assert "AED" in full_text
        normalized_text = full_text.replace("\n", "").replace(" ", "")
        assert "[ESTIMATED-synthetic_labeled_costs]" in normalized_text
        assert "Gross margin figures labeled [ESTIMATED]" in full_text
        print(f"  [{label}] All synthetic disclaimers, AED currency, and margin disclosures confirmed!")

    # 4. Security Verification
    print("\n[Step 4] Running Security & Tenant Boundary Checks...")
    # Unauthenticated request must return 401
    resp_unauth = requests.get(
        f"{BACKEND_URL}/api/v1/pulse/reports/{report_id}/pdf",
        headers={"X-Business-ID": biz_id},
    )
    print(f"  Unauthenticated request status: {resp_unauth.status_code} (Expected: 401)")
    assert resp_unauth.status_code == 401

    # Cross-tenant IDOR: Login as Sarah Jenkins (Northstar) and attempt to access Harbor & Thread report
    token_resp = requests.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"email": "sarah.jenkins@northstar-sandbox.local", "password": "Northstar#2026!RetailManager"},
    )
    assert token_resp.status_code == 200
    northstar_token = token_resp.json()["access_token"]

    resp_cross = requests.get(
        f"{BACKEND_URL}/api/v1/pulse/reports/{report_id}/pdf",
        headers={"Authorization": f"Bearer {northstar_token}", "X-Business-ID": biz_id},
    )
    print(f"  Cross-tenant access status: {resp_cross.status_code} (Expected: 403 or 404)")
    assert resp_cross.status_code in (403, 404)

    # Missing report ID returns 404
    resp_missing = requests.get(
        f"{BACKEND_URL}/api/v1/pulse/reports/00000000-0000-0000-0000-000000000000/pdf",
        headers={"Authorization": f"Bearer {storage_token}", "X-Business-ID": biz_id},
    )
    print(f"  Missing report request status: {resp_missing.status_code} (Expected: 404)")
    assert resp_missing.status_code == 404

    # Cleanup temp directory
    try:
        import shutil
        shutil.rmtree(temp_dir)
    except Exception:
        pass

    print("\n" + "=" * 80)
    print("HARBOR & THREAD BROWSER ACCEPTANCE & SECURITY VERIFIED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    main()
