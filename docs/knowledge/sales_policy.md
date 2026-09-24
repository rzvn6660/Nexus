# NEXUS Sample Knowledge Base: Sales Policy & Reporting Governance

> [!NOTE]
> **SYNTHETIC DEMO DOCUMENT**: This document contains synthetic demonstration business knowledge created for testing the NEXUS Business Context RAG and Semantic Layer.

## Discount Terminology
Discounts in our retail operations include trade promotions, customer segment discounts (such as VIP loyalty discounts), and seasonal clearance reductions. All discounts are applied at line item level and recorded in the `discount_amount` column.

## Return Handling Assumptions
Sales transactions marked as completed are considered realized revenue. Returns and order cancellations processed within the reporting window are deducted from gross sales during period reconciliation.

## Reporting Period Definitions
- **Daily**: Calendar date from 00:00:00 to 23:59:59 UTC.
- **Weekly**: Standard 7-day Monday through Sunday cycle.
- **Monthly**: Full calendar month.
- **Quarterly**: Three-month operational periods (Q1: Jan-Mar, Q2: Apr-Jun, Q3: Jul-Sep, Q4: Oct-Dec).

## Approved Sales Terminology
- Use "Net Revenue" as the official business terminology when presenting top-line earnings to executives.
- Avoid using the ambiguous term "Turnover" without clarifying whether it refers to sales revenue or inventory turns.
- "Gross Sales" must only be quoted when discussing pre-discount volume.
