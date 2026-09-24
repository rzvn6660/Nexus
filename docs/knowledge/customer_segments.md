# NEXUS Sample Knowledge Base: Customer Segments & Retention Policy

> [!NOTE]
> **SYNTHETIC DEMO DOCUMENT**: This document contains synthetic demonstration business knowledge created for testing the NEXUS Business Context RAG and Semantic Layer.

## Repeat Customer Definition
In NEXUS, a **Repeat Customer** is officially defined as any unique customer account that has completed two (2) or more distinct orders across their historical lifetime. Customers with exactly one completed transaction are classified as **One-Time Buyers**.

## Repeat Purchase Rate
The Repeat Purchase Rate is the proportion of transacting customers who have made repeat purchases: `(Repeat Customers / Total Unique Customers) * 100`.

## RFM Customer Segmentation
Customers are categorized into five analytical quintiles based on their RFM profile:
- **Champions / VIP**: Low recency (ordered recently), high frequency (multiple repeat orders), and top-tier monetary spend.
- **Loyal Customers**: Consistent order history and moderate-to-high spend.
- **Potential Loyalists**: Recent buyers with average order values who may convert to loyal buyers.
- **At-Risk Customers**: High past monetary value and order counts, but with high recency days (no recent purchase in 90+ days).
- **Lost / Dormant**: Inactive for over 180 days with low historical frequency.

## Active Customer Governance
An **Active Customer** is defined as any customer account that has placed at least one completed order within the active analysis window.
