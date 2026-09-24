# NEXUS Synthetic Retail Dataset Design

## 1. Domain Context
To provide a realistic foundation for Phase 3 analytics without relying on proprietary customer data, NEXUS includes a **Deterministic Synthetic Retail Data Generator** (`RetailDataGenerator`).

The dataset models a regional wholesale and direct-to-consumer distributor operating across five major commercial hubs in the Pacific Northwest and Mountain regions.

---

## 2. Realistic Business Patterns

### 2.1 Product Catalog & Margins
The catalog spans 5 distinct commercial product categories:
- **Electronics**: Audio, cables, smart accessories. Margins: 35%–55%. Price: $15–$350.
- **Office Supplies**: Paper, organization, writing instruments. Margins: 45%–65%. Price: $4–$65.
- **Industrial Tools**: Hand tools, fasteners, safety gear. Margins: 30%–50%. Price: $12–$480.
- **Packaging & Shipping**: Cardboard cartons, cushioning, tape. Margins: 40%–60%. Price: $8–$110.
- **Workwear & Safety**: High-vis vests, work boots, gloves. Margins: 38%–52%. Price: $10–$180.

### 2.2 Customer Segmentation
| Segment | Share | Order Profile | Average Line Items | Order Quantities | Discount Pattern |
| :--- | :---: | :--- | :---: | :---: | :---: |
| **Retail** | 55% | Individual consumers | 1–3 items | 1–4 units | 0% (rare 5% promo) |
| **Wholesale** | 12% | Regional retailers | 4–12 items | 10–80 units | 5%–15% volume discount |
| **Corporate** | 18% | Commercial offices | 2–6 items | 5–30 units | 0%–10% contract discount |
| **VIP** | 15% | Frequent loyalists | 2–5 items | 1–6 units | 5%–10% loyalty discount |

### 2.3 Demand Seasonality
- **Q4 Holiday Acceleration**: Transactions increase by $\approx 50\%$ across November and December.
- **Late Summer Commercial Surge**: August and September experience a $\approx 20\%$ bump from back-to-school and corporate budget cycles.
- **Pareto Popularity**: Item popularity follows a power-law distribution ($w_i = \frac{1}{i^{0.8}}$), ensuring the top 20% of catalog items drive $\approx 80\%$ of volume.

### 2.4 Operating Overhead
- **Fixed Monthly Rent**: $4,500/month incurred on the 1st of each month.
- **Payroll**: $9,200 bi-weekly incurred on the 14th and 28th.
- **Utilities**: $1,100/month ($\pm 18\%$ variance reflecting seasonal winter/summer energy load).
- **Logistics & Freight**: $1,450/month ($\pm 35\%$ variable overhead correlating with order velocity).
- **Marketing**: $1,800/month ($\pm 25\%$ variable digital ad and trade campaign spend).
