# NEXUS Sample Knowledge Base: Retail KPI Definitions

> [!NOTE]
> **SYNTHETIC DEMO DOCUMENT**: This document contains synthetic demonstration business knowledge created for testing the NEXUS Business Context RAG and Semantic Layer. It does not represent actual GAAP standards or any specific legal corporate entity.

## Gross Sales
Gross sales represents the total unadjusted sales value before any deductions, discounts, allowances, or customer rebates. In NEXUS, it is calculated deterministically as the sum of unit prices multiplied by ordered quantities across all line items.

## Discounts
Total discounts include all promotional price concessions, voucher reductions, and discretionary sales markdowns. Discounts reduce top-line sales to produce net revenue.

## Net Revenue
Net revenue is the core top-line operational metric in NEXUS. It equals Gross Sales minus Total Discounts. It is synonymous with net sales and sales revenue.

## Gross Profit
Gross profit measures product-level profitability before operating overhead and administrative expenses. It is defined strictly as Net Revenue minus Cost of Goods Sold (COGS).

## Gross Margin
Gross margin (or gross profit margin) expresses gross profit as a percentage of net revenue: `(Gross Profit / Net Revenue) * 100`. It reflects how efficiently goods are sourced and priced.

## Average Order Value (AOV)
Average order value represents the mean net sales revenue generated per distinct customer order. Calculated as Net Revenue divided by Total Order Count.

## Cost of Goods Sold (COGS)
Cost of goods sold represents the total direct procurement cost of items sold during the period, calculated using unit cost prices at transaction time.

## Inventory Turnover
Inventory turnover is the ratio indicating how many times the company's average inventory is sold and replaced over a reporting period. Calculated as annualized COGS divided by average inventory valuation.

## Days Sales of Inventory (DSI)
Days sales of inventory (DSI) measures the average number of days required to turn current inventory into sales. Calculated as `(Average Inventory Value / Annualized COGS) * 365`.
