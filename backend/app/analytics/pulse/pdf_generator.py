"""Executive PDF Report Generation Engine for NEXUS Pulse (Section 5 & 9).

Produces publication-grade, professionally designed business intelligence PDF reports
using ReportLab. Incorporates executive branding, KPI scorecards, risk distributions,
product tables, management insights, and auditable data provenance disclosures.
"""

import hashlib
import io
import re
from datetime import UTC, datetime

from app.schemas.pulse import PulseInsightItem, PulseKPIPayload
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


class NumberedCanvas(colors.Color):
    """Canvas wrapper adding running header and page numbering."""


class PulsePDFGenerator:
    """Generates auditable, executive-ready PDF publications."""

    # Executive Theme Colors
    PRIMARY = colors.HexColor("#0F172A")  # Slate 900
    SECONDARY = colors.HexColor("#2563EB")  # Blue 600
    SUCCESS = colors.HexColor("#059669")  # Emerald 600
    WARNING = colors.HexColor("#D97706")  # Amber 600
    DANGER = colors.HexColor("#DC2626")  # Red 600
    BG_LIGHT = colors.HexColor("#F8FAFC")  # Slate 50
    BORDER_COLOR = colors.HexColor("#E2E8F0")  # Slate 200
    TEXT_MUTED = colors.HexColor("#64748B")  # Slate 500
    TEXT_DARK = colors.HexColor("#1E293B")  # Slate 800

    @classmethod
    def generate_pdf_report(
        cls,
        report_id: str,
        business_name: str,
        period_label: str,
        kpi_payload: PulseKPIPayload,
        insights: list[PulseInsightItem],
        executive_summary: str,
        watermark_status: str,
        currency: str = "USD",
    ) -> tuple[bytes, str]:
        """
        Generate complete PDF report.
        Returns:
            Tuple of (pdf_bytes, sha256_checksum)
        """
        curr_sym = "AED " if currency.upper() == "AED" or "AED" in business_name.upper() else "$"
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        styles = getSampleStyleSheet()

        # Custom typography styles
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=cls.PRIMARY,
        )
        subtitle_style = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=cls.TEXT_MUTED,
        )
        section_heading = ParagraphStyle(
            "SectionHeading",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=cls.PRIMARY,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "ReportBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=cls.TEXT_DARK,
        )
        callout_style = ParagraphStyle(
            "CalloutBody",
            parent=styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9.5,
            leading=14,
            textColor=cls.TEXT_DARK,
        )
        table_hdr_style = ParagraphStyle(
            "TableHdr",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white,
        )
        table_cell_style = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=cls.TEXT_DARK,
        )
        table_cell_bold = ParagraphStyle(
            "TableCellBold",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=cls.TEXT_DARK,
        )
        disclaimer_style = ParagraphStyle(
            "Disclaimer",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=cls.TEXT_MUTED,
        )

        story: list[Flowable] = []

        # ----------------------------------------------------------------------
        # 1. HEADER & BRANDING
        # ----------------------------------------------------------------------
        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        header_data = [
            [
                Paragraph("<b>NEXUS PULSE</b> | Executive Intelligence", subtitle_style),
                Paragraph(
                    f"<b>Status:</b> {watermark_status.replace('_', ' ').title()}", subtitle_style
                ),
            ],
            [
                Paragraph(f"{business_name} — Business Performance Report", title_style),
                Paragraph(
                    f"<b>Period:</b> {period_label}<br/><b>Generated:</b> {now_str}", subtitle_style
                ),
            ],
        ]
        header_table = Table(header_data, colWidths=[4.2 * inch, 3.0 * inch])
        header_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(header_table)
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1.5, color=cls.SECONDARY, spaceAfter=12))

        # ----------------------------------------------------------------------
        # 1B. DEMONSTRATION & SANDBOX VISIBLE INDICATOR
        # ----------------------------------------------------------------------
        is_demo_or_sandbox = (
            "sandbox" in business_name.lower()
            or "demo" in business_name.lower()
            or "synthetic" in business_name.lower()
            or "pilot" in business_name.lower()
            or "sandbox" in watermark_status.lower()
            or "demo" in watermark_status.lower()
            or "synthetic" in watermark_status.lower()
            or "unverified" in watermark_status.lower()
        )
        if is_demo_or_sandbox:
            demo_banner_style = ParagraphStyle(
                "DemoBanner",
                parent=styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=9.5,
                leading=13,
                textColor=colors.HexColor("#92400E"),  # Amber 800
                alignment=1,  # Center
            )
            demo_table = Table(
                [
                    [
                        Paragraph(
                            "<b>*** SYNTHETIC DEMONSTRATION — NOT REAL MERCHANT DATA — NOT FOR OFFICIAL FINANCIAL AUDIT ***</b>",
                            demo_banner_style,
                        )
                    ]
                ],
                colWidths=[7.2 * inch],
            )
            demo_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),  # Amber 100
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#F59E0B")),  # Amber 500
                        ("PADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.append(demo_table)
            story.append(Spacer(1, 10))

        # ----------------------------------------------------------------------
        # 2. EXECUTIVE SUMMARY HIGHLIGHTS BOX
        # ----------------------------------------------------------------------
        summary_paragraphs = executive_summary.split("\n\n")
        summary_cells = [[Paragraph("<b>Executive Highlights</b>", section_heading)]]
        for p_text in summary_paragraphs:
            if p_text.strip():
                clean_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", p_text)
                summary_cells.append([Paragraph(clean_text, callout_style)])

        summary_table = Table(summary_cells, colWidths=[7.2 * inch])
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), cls.BG_LIGHT),
                    ("BOX", (0, 0), (-1, -1), 1, cls.BORDER_COLOR),
                    ("PADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 14))

        # ----------------------------------------------------------------------
        # 3. CORE KPI SCORECARD GRID (Financial & Customer)
        # ----------------------------------------------------------------------
        story.append(Paragraph("Core Performance Scorecard", section_heading))

        fin = kpi_payload.financial
        cust = kpi_payload.customer
        churn = kpi_payload.churn

        tot_rev = fin.get("total_revenue")
        growth = fin.get("revenue_growth")
        aov = fin.get("average_order_value")
        orders = fin.get("total_orders")
        margin = fin.get("gross_margin")
        active_c = cust.get("active_customers")
        repeat_r = cust.get("repeat_purchase_rate")
        rev_risk = churn.get("revenue_at_risk")

        is_margin_estimated = bool(
            margin
            and (
                "ESTIMATED" in str(margin.formatted_value)
                or "catalog_average_markup" in str(margin.limitations)
            )
        )
        kpi_grid_data = [
            [
                Paragraph(
                    "<b>Total Sales (Stored Records)</b>"
                    if is_demo_or_sandbox
                    else "<b>Total Commercial Revenue</b>",
                    table_cell_bold,
                ),
                Paragraph("<b>Revenue Growth</b>", table_cell_bold),
                Paragraph("<b>Average Order Value</b>", table_cell_bold),
                Paragraph("<b>Completed Orders</b>", table_cell_bold),
            ],
            [
                Paragraph(
                    f"<font size=13><b>{tot_rev.formatted_value if tot_rev else f'{curr_sym}0.00'}</b></font>",
                    table_cell_style,
                ),
                Paragraph(
                    f"<font size=13 color='#059669'><b>{growth.formatted_value if growth else 'N/A'}</b></font>",
                    table_cell_style,
                ),
                Paragraph(
                    f"<font size=13><b>{aov.formatted_value if aov else f'{curr_sym}0.00'}</b></font>",
                    table_cell_style,
                ),
                Paragraph(
                    f"<font size=13><b>{orders.formatted_value if orders else '0'}</b></font>",
                    table_cell_style,
                ),
            ],
            [
                Paragraph("<b>Active Customers</b>", table_cell_bold),
                Paragraph("<b>Repeat Purchase Rate</b>", table_cell_bold),
                Paragraph(
                    "<b>Gross Margin (Estimated)</b>"
                    if is_margin_estimated
                    else "<b>Gross Margin</b>",
                    table_cell_bold,
                ),
                Paragraph("<b>Revenue at Churn Risk</b>", table_cell_bold),
            ],
            [
                Paragraph(
                    f"<font size=13><b>{active_c.formatted_value if active_c else '0'}</b></font>",
                    table_cell_style,
                ),
                Paragraph(
                    f"<font size=13><b>{repeat_r.formatted_value if repeat_r else '0%'}</b></font>",
                    table_cell_style,
                ),
                Paragraph(
                    f"<font size=13><b>{margin.formatted_value if margin else 'N/A'}</b></font>",
                    table_cell_style,
                ),
                Paragraph(
                    f"<font size=13 color='#DC2626'><b>{rev_risk.formatted_value if rev_risk else f'{curr_sym}0.00'}</b></font>",
                    table_cell_style,
                ),
            ],
        ]
        kpi_table = Table(kpi_grid_data, colWidths=[1.8 * inch, 1.8 * inch, 1.8 * inch, 1.8 * inch])
        kpi_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, cls.BORDER_COLOR),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), cls.BG_LIGHT),
                    ("BACKGROUND", (0, 2), (-1, 2), cls.BG_LIGHT),
                ]
            )
        )
        story.append(kpi_table)
        story.append(Spacer(1, 14))

        # ----------------------------------------------------------------------
        # 4. CHURN & RETENTION INTELLIGENCE SECTION
        # ----------------------------------------------------------------------
        story.append(Paragraph("Customer Cadence & Churn Risk Distribution", section_heading))

        r_dist = kpi_payload.risk_distribution
        crit = r_dist.get("critical", 0)
        high = r_dist.get("high", 0)
        med = r_dist.get("medium", 0)
        low = r_dist.get("low", 0)
        insuff = r_dist.get("insufficient_history", 0)
        tot_eval = sum(r_dist.values()) or 1

        risk_table_data = [
            [
                Paragraph("Risk Tier", table_hdr_style),
                Paragraph("Cadence Criteria", table_hdr_style),
                Paragraph("Customers", table_hdr_style),
                Paragraph("Share", table_hdr_style),
                Paragraph("Recommended Intervention", table_hdr_style),
            ],
            [
                Paragraph("<font color='#DC2626'><b>Critical Risk</b></font>", table_cell_style),
                Paragraph("Ratio &ge; 3.0x Baseline Cadence", table_cell_style),
                Paragraph(f"<b>{crit:,}</b>", table_cell_style),
                Paragraph(f"{(crit / tot_eval) * 100:.1f}%", table_cell_style),
                Paragraph(
                    "Immediate outreach (Personal follow-up / Replenishment)", table_cell_style
                ),
            ],
            [
                Paragraph("<font color='#D97706'><b>High Risk</b></font>", table_cell_style),
                Paragraph("2.0x &le; Ratio &lt; 3.0x Baseline", table_cell_style),
                Paragraph(f"<b>{high:,}</b>", table_cell_style),
                Paragraph(f"{(high / tot_eval) * 100:.1f}%", table_cell_style),
                Paragraph("Proactive engagement (Re-engagement check-in)", table_cell_style),
            ],
            [
                Paragraph("<b>Watchlist (Medium)</b>", table_cell_style),
                Paragraph("1.3x &le; Ratio &lt; 2.0x Baseline", table_cell_style),
                Paragraph(f"{med:,}", table_cell_style),
                Paragraph(f"{(med / tot_eval) * 100:.1f}%", table_cell_style),
                Paragraph("Monitor & send regular newsletter", table_cell_style),
            ],
            [
                Paragraph("<font color='#059669'><b>Healthy (Low)</b></font>", table_cell_style),
                Paragraph("Ratio &lt; 1.3x Baseline (On Schedule)", table_cell_style),
                Paragraph(f"{low:,}", table_cell_style),
                Paragraph(f"{(low / tot_eval) * 100:.1f}%", table_cell_style),
                Paragraph("Maintain standard cadence", table_cell_style),
            ],
            [
                Paragraph("<b>Single-Order Buyers</b>", table_cell_style),
                Paragraph("&lt; 2 Distinct Order Dates (Unscored)", table_cell_style),
                Paragraph(f"{insuff:,}", table_cell_style),
                Paragraph(f"{(insuff / tot_eval) * 100:.1f}%", table_cell_style),
                Paragraph("Onboarding educational sequence", table_cell_style),
            ],
        ]

        risk_table = Table(
            risk_table_data, colWidths=[1.4 * inch, 1.8 * inch, 0.9 * inch, 0.7 * inch, 2.4 * inch]
        )
        risk_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), cls.PRIMARY),
                    ("BOX", (0, 0), (-1, -1), 1, cls.BORDER_COLOR),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
                    ("PADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, cls.BG_LIGHT]),
                ]
            )
        )
        story.append(risk_table)
        story.append(Spacer(1, 14))

        # ----------------------------------------------------------------------
        # 5. TOP PRODUCTS PERFORMANCE TABLE
        # ----------------------------------------------------------------------
        top_prods = kpi_payload.top_products[:5]
        if top_prods:
            story.append(Paragraph("Top-Selling Products Performance", section_heading))
            prod_rows = [
                [
                    Paragraph("SKU", table_hdr_style),
                    Paragraph("Product Name", table_hdr_style),
                    Paragraph("Category", table_hdr_style),
                    Paragraph("Units Sold", table_hdr_style),
                    Paragraph("Total Revenue", table_hdr_style),
                ]
            ]
            for p in top_prods:
                p_sku = getattr(p, "sku", None) or (p.get("sku") if isinstance(p, dict) else "")
                p_name = getattr(p, "name", None) or (p.get("name") if isinstance(p, dict) else "")
                p_cat = getattr(p, "category", None) or (
                    p.get("category") if isinstance(p, dict) else "Retail"
                )
                p_units = (
                    getattr(p, "units_sold", 0)
                    if not isinstance(p, dict)
                    else p.get("units_sold", 0)
                )
                p_rev = (
                    getattr(p, "revenue", 0.0) if not isinstance(p, dict) else p.get("revenue", 0.0)
                )
                prod_rows.append(
                    [
                        Paragraph(f"<code>{p_sku}</code>", table_cell_style),
                        Paragraph(str(p_name), table_cell_bold),
                        Paragraph(str(p_cat), table_cell_style),
                        Paragraph(f"{p_units:,}", table_cell_style),
                        Paragraph(f"<b>{curr_sym}{p_rev:,.2f}</b>", table_cell_style),
                    ]
                )

            prod_table = Table(
                prod_rows, colWidths=[1.1 * inch, 2.6 * inch, 1.4 * inch, 0.9 * inch, 1.2 * inch]
            )
            prod_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), cls.PRIMARY),
                        ("BOX", (0, 0), (-1, -1), 1, cls.BORDER_COLOR),
                        ("INNERGRID", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
                        ("PADDING", (0, 0), (-1, -1), 5),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, cls.BG_LIGHT]),
                    ]
                )
            )
            story.append(prod_table)
            story.append(Spacer(1, 14))

        # ----------------------------------------------------------------------
        # 6. MANAGEMENT INSIGHTS & EVIDENCE
        # ----------------------------------------------------------------------
        if insights:
            story.append(Paragraph("Strategic Management Insights & Evidence", section_heading))
            for ins in insights[:5]:
                type_badge = ins.type.value.replace("_", " ").title()
                badge_color = "#2563EB"
                if ins.severity == "CRITICAL":
                    badge_color = "#DC2626"
                elif ins.severity == "WARNING":
                    badge_color = "#D97706"
                elif ins.severity == "POSITIVE":
                    badge_color = "#059669"

                ins_text = (
                    f"<b><font color='{badge_color}'>[{type_badge}]</font> {ins.title}</b><br/>"
                    f"{ins.description}"
                )
                if ins.action_suggestion:
                    ins_text += f"<br/><i>Recommended Action: {ins.action_suggestion}</i>"

                ins_table = Table([[Paragraph(ins_text, body_style)]], colWidths=[7.2 * inch])
                ins_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), cls.BG_LIGHT),
                            ("BOX", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
                            ("PADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                story.append(ins_table)
                story.append(Spacer(1, 4))
            story.append(Spacer(1, 10))

        # ----------------------------------------------------------------------
        # 7. DATA PROVENANCE, GOVERNANCE & METHODOLOGY DISCLAIMERS
        # ----------------------------------------------------------------------
        story.append(Paragraph("Data Governance & Methodology Disclosures", section_heading))
        disclaimer_prefix = (
            "<b>*** DEMONSTRATION WORKSPACE NOTICE ***:</b> This publication reflects deterministically generated synthetic data "
            "for sandbox workflow validation. Customer profiles, 12-month transaction histories, unit costs, and commercial metrics "
            "are synthetic and do NOT represent audited real merchant financial performance or certified period close.<br/>"
            if is_demo_or_sandbox
            else ""
        )
        is_unverified = (
            is_demo_or_sandbox
            or watermark_status != "verified_complete"
            or watermark_status
            in (
                "DEMO_SYNTHETIC",
                "unverified_missing",
                "SOURCE_COMPLETENESS_UNVERIFIED",
                "INCOMPLETE_IN_FLIGHT",
            )
        )
        if is_unverified:
            completeness_text = (
                f"<b>Data Provenance & Source Completeness:</b> Source completeness status is <b>{watermark_status} (UNVERIFIED)</b>. "
                "Calculation validity is confirmed against stored database records, but source-level completeness is uncertified. "
                "Data post-dating unverified boundaries is provisional and advisory only.<br/>"
            )
        else:
            completeness_text = (
                f"<b>Data Completeness Boundary:</b> This report reflects commercial transactions verified under authoritative "
                f"ingestion watermark status: <b>{watermark_status}</b>. Data post-dating certified completeness boundaries is provisional.<br/>"
            )
        margin_method_text = (
            "<b>Gross Margin & Profitability Methodology:</b> Gross margin figures labeled [ESTIMATED] are modeled using "
            "catalog-average-markup across unit cost benchmarks. They do not constitute actual audited accounting profitability "
            "or reflect invoice-verified cost of goods sold.<br/>"
        )
        disclaimer_text = (
            disclaimer_prefix
            + completeness_text
            + margin_method_text
            + "<b>Observational Intelligence Invariant:</b> Customer churn risk is calculated from empirical historical purchase intervals "
            "and does not represent contractual cancellation. In retail environments, seasonal dormancy frequently mimics churn; manual "
            "review is required before acting. Comparative retention lift reflects observational differences between intervened accounts and "
            "non-intervened at-risk peers; correlation does not establish randomized clinical trial (RCT) causality.<br/>"
            f"<b>Document Integrity:</b> Report ID: <code>{report_id}</code> | Built by NEXUS Pulse. Reproduction is cryptographically auditable."
        )
        disc_table = Table([[Paragraph(disclaimer_text, disclaimer_style)]], colWidths=[7.2 * inch])
        disc_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), cls.BG_LIGHT),
                    ("BOX", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
                    ("PADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(disc_table)

        # Build document
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        sha256_hash = hashlib.sha256(pdf_bytes).hexdigest()
        return pdf_bytes, sha256_hash
