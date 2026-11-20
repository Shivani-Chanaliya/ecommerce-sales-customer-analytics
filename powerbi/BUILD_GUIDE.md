# Power BI Model and Dashboard Build Guide

The source PBIX is preserved. Power BI Desktop was not available in the checked workspace paths, so this guide and the generated model files are **preparation, not a claim that the PBIX has been enhanced**.

Run the Python pipeline first. It writes these import-ready files to `powerbi/data/`:

- `FactSales.csv` — transaction-line fact table, including sale and cancellation-coded lines.
- `DimDate.csv` — continuous calendar with month sort keys.
- `DimCustomer.csv` — identified customers and historical RFM fields.
- `DimProduct.csv` — stock code, observed description, and a service-line review flag.
- `DimCountry.csv` — countries present in the transaction data.
- `FactCohortRetention.csv` — pre-aggregated cohort/month retention percentages.

## Import and prepare the model

1. In Power BI Desktop, import all six CSV files.
2. Set `FactSales[InvoiceNo]`, `FactSales[StockCode]`, and `FactSales[CustomerID]` to **Text**. Replace empty CustomerID strings with null so customer measures exclude them. Set `InvoiceDate` to Date/Time, `OrderDate` and `DimDate[Date]` to Date, and revenue/price to Decimal Number or Fixed Decimal Number.
3. Keep the existing `Revenue` column in `FactSales.csv`; the Python pipeline recomputes it as `ROUND(Quantity * UnitPrice, 2)`.
4. Create these one-to-many, single-direction relationships:
   - `DimDate[Date]` → `FactSales[OrderDate]`
   - `DimCustomer[CustomerID]` → `FactSales[CustomerID]`
   - `DimProduct[StockCode]` → `FactSales[StockCode]`
   - `DimCountry[Country]` → `FactSales[Country]`
5. Mark `DimDate` as the date table. Sort `DimDate[MonthName]` by `DimDate[MonthNumber]` and `DimDate[YearMonth]` by `DimDate[YearMonthSort]`.
6. Create the measures in `DAX_MEASURES.dax`. Format revenue and AOV as currency, and growth/repeat/cancellation rates as percentages.
7. Keep cancellation-coded invoices in the model for cancellation analysis. The sales measures filter them out; the cancellation measures include them.

## Five-page layout

### 1. Executive Overview

- Cards: Total Revenue, Total Orders, Total Customers, Average Order Value, Revenue Growth %.
- Line chart: monthly revenue by `DimDate[YearMonth]`.
- Bar chart: revenue by country, with UK share visible.
- Slicers: date, country.

### 2. Product Analysis

- Bar chart: top 10 stock codes by Total Revenue, filtered with Product Revenue Rank.
- Bar/table: revenue and quantity by product code and description.
- Include `DimProduct[ReviewAsServiceLine]` as a review/filter field so postage-like lines are not mistaken for merchandise.
- Show low-revenue products as “lowest observed revenue,” not as poor products without margin, inventory, and availability context.
- No category field is supplied; do not build a category chart until a validated mapping exists.

### 3. Customer Analysis

- Bar chart: revenue by the historical `DimCustomer[Segment]`.
- Cards: Repeat Customer Rate %, New Customers, Returning Customers, Average Historical Revenue per Customer.
- Cohort heatmap: `FactCohortRetention[CohortMonth]` by `MonthsSinceFirstPurchase`, colored by Cohort Retention %. The cohort table is pre-aggregated and does not respond to country/product slicers. Recent cohorts have fewer observed follow-up months; a missing cell is not zero retention.
- Add a Customer Detail drill-through page using `DimCustomer[CustomerID]`, with historical frequency, revenue, recency, and segment.
- RFM values are a snapshot for the dataset period, not a live churn model or predicted CLV.

### 4. Regional Analysis

- Use country as the available geographic level: revenue, orders, identified customers, and quantity by country.
- Add a country map only if Power BI resolves the country names reliably; otherwise use a sorted bar chart.
- Add a country drill-through page or table for product mix.
- The source contains no region/state field.

### 5. Sales Trends

- Line chart: monthly revenue by YearMonth; add a separate yearly revenue chart.
- Include Revenue Previous Month and Revenue Growth % in tooltips.
- Add month-of-year comparisons only as descriptive: there is one complete year and a partial December.

## Interactions and quality checks

- Sync date and country slicers across pages. Use a segment slicer on the customer page.
- Create a report-tooltip page with revenue, orders, AOV, and growth; enable it on the product, country, and monthly-trend visuals. Avoid showing profit because costs are absent.
- Apply conditional formatting to Revenue Growth % (positive/negative) with a neutral zero state.
- Enable drill-through on customer and product identifiers; retain a visible “Back” button.
- Reconcile the unfiltered cards with `reports/business_kpis.json`. Revenue should be about £10.62M, orders 22,064, customers 4,339, and AOV £481.33 under the documented non-cancelled-invoice basis.
- Save dashboard work as a new PBIX copy so the original `ecommerce_sales_customer_analytics.pbix` remains intact.
