-- E-Commerce business analysis queries
-- Target: MySQL 8.0+
--
-- Source grain: one row per invoice line in sales.
-- Revenue definition: ROUND(Quantity * UnitPrice, 2).
-- Sales analyses exclude invoice numbers prefixed with C (case-insensitive).
-- Negative adjustments on non-cancelled invoices remain in net revenue.
-- Category, region, and cost are not present in the supplied dataset.

USE ecommerce_analysis;

-- 1. Executive KPIs. Cancellation row share and invoice share are separate metrics.
WITH classified_lines AS (
    SELECT
        InvoiceNo,
        StockCode,
        CustomerID,
        Country,
        Quantity,
        InvoiceDate,
        ROUND(Quantity * UnitPrice, 2) AS LineRevenue,
        UPPER(InvoiceNo) LIKE 'C%' AS IsCancelled
    FROM sales
)
SELECT
    SUM(NOT IsCancelled) AS sales_line_count,
    COUNT(DISTINCT CASE WHEN NOT IsCancelled THEN InvoiceNo END) AS total_orders,
    COUNT(DISTINCT CASE WHEN NOT IsCancelled THEN CustomerID END) AS total_customers,
    COUNT(DISTINCT CASE WHEN NOT IsCancelled THEN StockCode END) AS total_products,
    COUNT(DISTINCT CASE WHEN NOT IsCancelled THEN Country END) AS total_countries,
    SUM(CASE WHEN NOT IsCancelled THEN LineRevenue ELSE 0 END) AS total_revenue,
    SUM(CASE WHEN NOT IsCancelled THEN Quantity ELSE 0 END) AS total_quantity,
    SUM(CASE WHEN IsCancelled THEN 1 ELSE 0 END) AS cancelled_line_count,
    COUNT(DISTINCT CASE WHEN IsCancelled THEN InvoiceNo END) AS cancelled_invoice_count,
    ROUND(
        SUM(CASE WHEN IsCancelled THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100,
        2
    ) AS cancelled_row_share_pct,
    ROUND(
        COUNT(DISTINCT CASE WHEN IsCancelled THEN InvoiceNo END)
        / NULLIF(COUNT(DISTINCT InvoiceNo), 0) * 100,
        2
    ) AS cancelled_invoice_share_pct,
    ROUND(
        SUM(CASE WHEN NOT IsCancelled THEN LineRevenue ELSE 0 END)
        / NULLIF(COUNT(DISTINCT CASE WHEN NOT IsCancelled THEN InvoiceNo END), 0),
        2
    ) AS average_order_value
FROM classified_lines;

-- 2. Calendar-complete monthly sales and month-over-month revenue change.
WITH RECURSIVE
date_bounds AS (
    SELECT
        CAST(DATE_FORMAT(MIN(InvoiceDate), '%Y-%m-01') AS DATE) AS first_month,
        CAST(DATE_FORMAT(MAX(InvoiceDate), '%Y-%m-01') AS DATE) AS last_month
    FROM sales
    WHERE UPPER(InvoiceNo) NOT LIKE 'C%'
),
calendar_months AS (
    SELECT first_month AS month_start
    FROM date_bounds
    WHERE first_month IS NOT NULL
    UNION ALL
    SELECT DATE_ADD(calendar_months.month_start, INTERVAL 1 MONTH)
    FROM calendar_months
    JOIN date_bounds ON calendar_months.month_start < date_bounds.last_month
),
monthly_sales AS (
    SELECT
        calendar_months.month_start,
        COALESCE(SUM(ROUND(sales.Quantity * sales.UnitPrice, 2)), 0) AS revenue,
        COUNT(DISTINCT sales.InvoiceNo) AS orders
    FROM calendar_months
    LEFT JOIN sales
        ON sales.InvoiceDate >= calendar_months.month_start
        AND sales.InvoiceDate < DATE_ADD(calendar_months.month_start, INTERVAL 1 MONTH)
        AND UPPER(sales.InvoiceNo) NOT LIKE 'C%'
    GROUP BY calendar_months.month_start
),
monthly_comparison AS (
    SELECT
        month_start,
        revenue,
        orders,
        LAG(revenue) OVER (ORDER BY month_start) AS previous_month_revenue
    FROM monthly_sales
)
SELECT
    month_start,
    YEAR(month_start) AS sales_year,
    MONTH(month_start) AS sales_month,
    revenue,
    orders,
    ROUND(revenue / NULLIF(orders, 0), 2) AS average_order_value,
    previous_month_revenue,
    revenue - previous_month_revenue AS revenue_change,
    ROUND(
        (revenue - previous_month_revenue) / NULLIF(previous_month_revenue, 0) * 100,
        2
    ) AS revenue_growth_pct
FROM monthly_comparison
ORDER BY month_start;

-- 3. Yearly sales trend. The latest year may be incomplete.
SELECT
    YEAR(InvoiceDate) AS sales_year,
    SUM(ROUND(Quantity * UnitPrice, 2)) AS revenue,
    COUNT(DISTINCT InvoiceNo) AS orders,
    COUNT(DISTINCT CustomerID) AS identified_customers
FROM sales
WHERE UPPER(InvoiceNo) NOT LIKE 'C%'
GROUP BY YEAR(InvoiceDate)
ORDER BY sales_year;

-- 4. Top 10 product codes by net revenue, using an INNER JOIN to a derived product lookup.
WITH product_description_frequency AS (
    SELECT
        StockCode,
        Description,
        COUNT(*) AS description_frequency
    FROM sales
    GROUP BY StockCode, Description
),
ranked_product_descriptions AS (
    SELECT
        StockCode,
        Description,
        ROW_NUMBER() OVER (
            PARTITION BY StockCode
            ORDER BY description_frequency DESC, Description
        ) AS description_rank
    FROM product_description_frequency
),
product_lookup AS (
    SELECT StockCode, Description
    FROM ranked_product_descriptions
    WHERE description_rank = 1
),
product_sales AS (
    SELECT
        StockCode,
        SUM(Quantity) AS net_quantity,
        COUNT(DISTINCT InvoiceNo) AS orders,
        SUM(ROUND(Quantity * UnitPrice, 2)) AS revenue
    FROM sales
    WHERE UPPER(InvoiceNo) NOT LIKE 'C%'
    GROUP BY StockCode
)
SELECT
    product_sales.StockCode,
    product_lookup.Description,
    product_sales.net_quantity,
    product_sales.orders,
    product_sales.revenue
FROM product_sales
INNER JOIN product_lookup
    ON product_sales.StockCode = product_lookup.StockCode
ORDER BY product_sales.revenue DESC
LIMIT 10;

-- 5. Products above the average product revenue (subquery example).
WITH product_sales AS (
    SELECT
        StockCode,
        SUM(ROUND(Quantity * UnitPrice, 2)) AS revenue
    FROM sales
    WHERE UPPER(InvoiceNo) NOT LIKE 'C%'
    GROUP BY StockCode
)
SELECT
    StockCode,
    revenue
FROM product_sales
WHERE revenue > (SELECT AVG(revenue) FROM product_sales)
ORDER BY revenue DESC;

-- 6. Top 10 identified customers by observed-period revenue and distinct orders.
SELECT
    CustomerID,
    COUNT(DISTINCT InvoiceNo) AS orders,
    SUM(Quantity) AS net_quantity,
    SUM(ROUND(Quantity * UnitPrice, 2)) AS observed_revenue
FROM sales
WHERE CustomerID IS NOT NULL
  AND UPPER(InvoiceNo) NOT LIKE 'C%'
GROUP BY CustomerID
ORDER BY observed_revenue DESC
LIMIT 10;

-- 7. Repeat-customer rate: identified customers with more than one distinct invoice.
WITH customer_orders AS (
    SELECT
        CustomerID,
        COUNT(DISTINCT InvoiceNo) AS order_count
    FROM sales
    WHERE CustomerID IS NOT NULL
      AND UPPER(InvoiceNo) NOT LIKE 'C%'
    GROUP BY CustomerID
)
SELECT
    COUNT(*) AS identified_customers,
    SUM(order_count > 1) AS repeat_customers,
    ROUND(AVG(order_count > 1) * 100, 2) AS repeat_customer_rate_pct
FROM customer_orders;

-- 8. Monthly new and returning identified customers.
WITH customer_months AS (
    SELECT
        CustomerID,
        DATE_FORMAT(InvoiceDate, '%Y-%m') AS activity_month
    FROM sales
    WHERE CustomerID IS NOT NULL
      AND UPPER(InvoiceNo) NOT LIKE 'C%'
    GROUP BY CustomerID, DATE_FORMAT(InvoiceDate, '%Y-%m')
),
first_purchase AS (
    SELECT
        CustomerID,
        MIN(activity_month) AS first_month
    FROM customer_months
    GROUP BY CustomerID
)
SELECT
    customer_months.activity_month,
    COUNT(DISTINCT customer_months.CustomerID) AS active_customers,
    COUNT(DISTINCT CASE
        WHEN customer_months.activity_month = first_purchase.first_month
        THEN customer_months.CustomerID
    END) AS new_customers,
    COUNT(DISTINCT CASE
        WHEN customer_months.activity_month > first_purchase.first_month
        THEN customer_months.CustomerID
    END) AS returning_customers
FROM customer_months
INNER JOIN first_purchase
    ON customer_months.CustomerID = first_purchase.CustomerID
GROUP BY customer_months.activity_month
ORDER BY customer_months.activity_month;

-- 9. Country performance. Country is the only available geographic field.
SELECT
    Country,
    SUM(ROUND(Quantity * UnitPrice, 2)) AS revenue,
    COUNT(DISTINCT InvoiceNo) AS orders,
    COUNT(DISTINCT CustomerID) AS identified_customers,
    SUM(Quantity) AS net_quantity
FROM sales
WHERE UPPER(InvoiceNo) NOT LIKE 'C%'
GROUP BY Country
ORDER BY revenue DESC;

-- 10. Top 3 product codes in each country (window ranking).
WITH product_country_sales AS (
    SELECT
        Country,
        StockCode,
        MAX(Description) AS Description,
        SUM(ROUND(Quantity * UnitPrice, 2)) AS revenue
    FROM sales
    WHERE UPPER(InvoiceNo) NOT LIKE 'C%'
    GROUP BY Country, StockCode
),
ranked_products AS (
    SELECT
        Country,
        StockCode,
        Description,
        revenue,
        ROW_NUMBER() OVER (
            PARTITION BY Country
            ORDER BY revenue DESC, StockCode
        ) AS product_rank
    FROM product_country_sales
)
SELECT Country, StockCode, Description, revenue, product_rank
FROM ranked_products
WHERE product_rank <= 3
ORDER BY Country, product_rank;

-- 11. RFM segments. Monetary value is historical revenue in this dataset, not predicted CLV.
WITH customer_metrics AS (
    SELECT
        CustomerID,
        DATEDIFF(
            DATE_ADD((SELECT MAX(DATE(InvoiceDate))
                      FROM sales
                      WHERE UPPER(InvoiceNo) NOT LIKE 'C%'), INTERVAL 1 DAY),
            MAX(DATE(InvoiceDate))
        ) AS recency_days,
        COUNT(DISTINCT InvoiceNo) AS frequency,
        SUM(ROUND(Quantity * UnitPrice, 2)) AS monetary
    FROM sales
    WHERE CustomerID IS NOT NULL
      AND UPPER(InvoiceNo) NOT LIKE 'C%'
    GROUP BY CustomerID
),
rfm_scores AS (
    SELECT
        CustomerID,
        recency_days,
        frequency,
        monetary,
        GREATEST(
            1,
            5 - FLOOR(PERCENT_RANK() OVER (ORDER BY recency_days ASC) * 5)
        ) AS r_score,
        LEAST(
            5,
            1 + FLOOR(PERCENT_RANK() OVER (ORDER BY frequency ASC) * 5)
        ) AS f_score,
        LEAST(
            5,
            1 + FLOOR(PERCENT_RANK() OVER (ORDER BY monetary ASC) * 5)
        ) AS m_score
    FROM customer_metrics
),
rfm_segments AS (
    SELECT
        *,
        CASE
            WHEN r_score >= 4 AND f_score >= 4 THEN 'Champions'
            WHEN f_score >= 4 THEN 'Loyal'
            WHEN r_score >= 4 AND f_score >= 2 THEN 'Potential Loyalists'
            WHEN r_score <= 2 AND f_score >= 2 THEN 'At Risk'
            WHEN f_score = 1 AND r_score >= 4 THEN 'New Customers'
            ELSE 'Needs Attention'
        END AS segment
    FROM rfm_scores
)
SELECT
    segment,
    COUNT(*) AS customers,
    SUM(monetary) AS historical_revenue,
    AVG(recency_days) AS average_recency_days,
    AVG(frequency) AS average_invoice_frequency
FROM rfm_segments
GROUP BY segment
ORDER BY historical_revenue DESC;

-- 12. Customers with no purchase in the 90 days before the last observed sale date.
-- This is a transparent inactivity flag, not a validated churn prediction.
WITH customer_last_purchase AS (
    SELECT
        CustomerID,
        MAX(DATE(InvoiceDate)) AS last_purchase_date,
        COUNT(DISTINCT InvoiceNo) AS observed_orders,
        SUM(ROUND(Quantity * UnitPrice, 2)) AS observed_revenue
    FROM sales
    WHERE CustomerID IS NOT NULL
      AND UPPER(InvoiceNo) NOT LIKE 'C%'
    GROUP BY CustomerID
),
data_snapshot AS (
    SELECT MAX(DATE(InvoiceDate)) AS snapshot_date
    FROM sales
    WHERE UPPER(InvoiceNo) NOT LIKE 'C%'
)
SELECT
    customer_last_purchase.CustomerID,
    customer_last_purchase.last_purchase_date,
    DATEDIFF(data_snapshot.snapshot_date, customer_last_purchase.last_purchase_date) AS days_since_purchase,
    customer_last_purchase.observed_orders,
    customer_last_purchase.observed_revenue
FROM customer_last_purchase
CROSS JOIN data_snapshot
WHERE customer_last_purchase.last_purchase_date
    < DATE_SUB(data_snapshot.snapshot_date, INTERVAL 90 DAY)
ORDER BY days_since_purchase DESC;

-- 13. LEFT JOIN example: transaction lines with no identified customer match.
WITH customer_lookup AS (
    SELECT DISTINCT CustomerID
    FROM sales
    WHERE CustomerID IS NOT NULL
)
SELECT
    sales.InvoiceNo,
    sales.StockCode,
    sales.InvoiceDate,
    sales.CustomerID,
    ROUND(sales.Quantity * sales.UnitPrice, 2) AS line_revenue
FROM sales
LEFT JOIN customer_lookup
    ON sales.CustomerID = customer_lookup.CustomerID
WHERE customer_lookup.CustomerID IS NULL
  AND UPPER(sales.InvoiceNo) NOT LIKE 'C%';

-- 14. Cancellation analysis. Do not mix line-row share with invoice-level share.
WITH invoice_status AS (
    SELECT
        InvoiceNo,
        UPPER(InvoiceNo) LIKE 'C%' AS IsCancelled,
        SUM(ROUND(Quantity * UnitPrice, 2)) AS invoice_revenue
    FROM sales
    GROUP BY InvoiceNo
)
SELECT
    COUNT(*) AS all_invoice_ids,
    SUM(IsCancelled) AS cancellation_invoice_ids,
    ROUND(AVG(IsCancelled) * 100, 2) AS cancellation_invoice_share_pct,
    SUM(CASE WHEN IsCancelled THEN invoice_revenue ELSE 0 END) AS cancellation_invoice_revenue
FROM invoice_status;
