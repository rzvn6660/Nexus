# Diagnostic Strategies

NEXUS implements modular diagnostic strategies corresponding to distinct business operational domains:

## 1. Revenue Investigation (`revenue_decline`, `revenue_growth`)
- Measures macro net sales variance against the comparison baseline.
- Decomposes variance by merchandise category to assess concentration.
- Evaluates Price/Volume/Mix decomposition to quantify unit pricing vs sales volume vs demand mix.
- Adaptively branches to SKU-level variance if top category concentration exceeds 35%.

## 2. Profit Investigation (`profit_decline`, `profit_growth`)
- Audits Gross Profit and Net Profit against Cost of Goods Sold (COGS) and Operating Expenses (OPEX).
- Analyzes operating overhead partitioned into fixed recurring costs vs variable operational costs.
- Traces commercial margin conversion through Price/Volume/Mix.

## 3. Margin Investigation (`margin_change`)
- Measures Gross Margin percentage changes and Average Order Value (AOV).
- Dissects realized unit selling price variations from merchandise mix shifts.
- Cross-references low-margin category breakdowns.

## 4. Product Investigation (`product_performance_change`)
- Evaluates product rankings across revenue, volume, and gross margin.
- Analyzes SKU-level variance contributions.
- Categorizes catalog velocity into high, medium, slow, and dormant tiers.

## 5. Customer Investigation (`customer_change`)
- Quantifies repeat purchase rate and repeat customer proportions.
- Analyzes spend distribution across customer tiers (VIP, Regular, At-Risk).
- Evaluates RFM migration patterns and cohort retention drop-offs.

## 6. Inventory Investigation (`inventory_issue`)
- Audits real-time inventory valuation, low-stock alerts, and stockout counts.
- Evaluates Inventory Turnover ratio and Days Sales of Inventory (DSI).
- Identifies working capital tied up in dormant inventory.

## 7. Expense Investigation (`expense_change`)
- Partitions overhead expenses into recurring vs variable categories.
- Evaluates OPEX-to-revenue ratio movements.
