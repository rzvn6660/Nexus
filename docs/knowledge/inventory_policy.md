# NEXUS Sample Knowledge Base: Inventory Policy & Thresholds

> [!NOTE]
> **SYNTHETIC DEMO DOCUMENT**: This document contains synthetic demonstration business knowledge created for testing the NEXUS Business Context RAG and Semantic Layer.

## Reorder Threshold Terminology
A product SKU is flagged with a **Reorder Alert** whenever its current on-hand stock quantity falls to or below its declared `reorder_level`. Safety stock buffer calculations are updated weekly.

## Stock Status Definitions
- **Healthy**: Current on-hand quantity exceeds 150% of the reorder threshold.
- **Low Stock**: Current on-hand quantity is greater than 0 but less than or equal to `reorder_level`.
- **Out of Stock**: Current on-hand quantity is exactly 0 units.

## Inventory Velocity Classification
- **Fast-Moving**: SKUs with an average daily burn rate exceeding 5 units per day.
- **Slow-Moving**: SKUs with positive sales velocity but below 1 unit per day.
- **Dormant**: SKUs with zero units fulfilled over the last 90 continuous days.

## Inventory Valuation Method
Inventory valuation in NEXUS follows direct unit cost valuation: `current_stock * cost_price`.
