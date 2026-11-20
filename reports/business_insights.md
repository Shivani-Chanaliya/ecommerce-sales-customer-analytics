# Business Insights

> All revenue uses non-cancelled invoices and line revenue recomputed as quantity × unit price, rounded to two decimals. The data ends on 2011-12-09T12:50:00; the latest month may be partial.

## Performance

- Revenue is £10,619,986.68 across 22,064 non-cancelled invoices; AOV is £481.33.
- November 2011 is the highest-revenue month at £1,503,866.78; February 2011 is the lowest at £522,545.56.
- United Kingdom contributes £8,979,619.97 (84.6% of revenue).

## Products and customers

- The highest-revenue stock code overall is DOT (DOTCOM POSTAGE), at £206,248.77.
- Excluding descriptions flagged by the transparent POSTAGE/CARRIAGE review rule, the highest-revenue product code is 22423 (REGENCY CAKESTAND 3 TIER), at £174,156.54. This rule is for product ranking only; service-line revenue remains in total revenue.
- 2,845 of 4,339 identified customers (65.6%) placed more than one non-cancelled invoice in this dataset.
- The top 10 identified customers represent 14.5% of total sales revenue.
- The largest RFM revenue segment is Champions at £5,759,202.78. RFM segments describe this observation window; they are not predicted customer lifetime value.
- The relative-RFM At Risk segment contains 555 customers and £532,291.11 in observed revenue; this is a prioritization flag, not a churn prediction.

## Risks and interpretation

- 135,037 transaction rows (25.2%) have no CustomerID, limiting customer-level attribution.
- 3,836 invoice IDs are cancellation-coded (14.8% of all distinct invoice IDs); this is not the same as the 1.7% cancellation-coded row share.
- Only one complete year is available, and the final December is partial. Treat seasonal patterns as descriptive, not a proven recurring seasonal effect.
- The data contains no cost or product-category field. Profit and category claims are not supported without additional validated data.
- The data contains no campaign, acquisition-channel, or customer-interaction fields, so it cannot establish causal drivers of repeat purchases.

## Actions to validate

- Improve CustomerID capture and monitor the missing-ID rate so repeat behavior can be measured more completely.
- Review inventory and campaign readiness ahead of the observed high-revenue month; validate the pattern against additional years before treating it as seasonality.
- Investigate top product lines and customer segments with margin, stock, and campaign data before allocating budget; revenue alone is not profit or causal evidence.
- Review service-like descriptions (for example postage) separately when interpreting product rankings; all lines remain included in total revenue.

## Method

- RFM snapshot date: 2011-12-10. Frequency is distinct non-cancelled invoice count; monetary value is historical net revenue in the observed period.
- Order outliers: 1.5 * IQR fences on non-cancelled invoice net revenue; flagged, not removed. 1,883 orders were flagged.
