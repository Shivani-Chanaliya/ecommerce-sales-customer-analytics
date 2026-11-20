"""Interactive Streamlit dashboard for the Online Retail analysis."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent
ANALYSIS_MODULE_DIR = PROJECT_ROOT / "python"
DATA_PATH = PROJECT_ROOT / "data" / "cleaned_sales.csv"
if str(ANALYSIS_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_MODULE_DIR))

from ecommerce_analysis import analyze_sales, prepare_sales_data


st.set_page_config(
    page_title="E-Commerce Sales Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner="Loading and analyzing transaction data...")
def load_analysis(path: str, modified_time: float) -> dict:
    del modified_time  # Included in the cache key so replacing the CSV triggers a refresh.
    raw_data = pd.read_csv(path, dtype={"InvoiceNo": "string", "StockCode": "string"})
    data, quality = prepare_sales_data(raw_data)
    return analyze_sales(data, quality)


def _format_currency(value: float) -> str:
    return f"£{value:,.2f}"


def _period_revenue(sales: pd.DataFrame, start: pd.Timestamp, end_exclusive: pd.Timestamp) -> float:
    mask = sales["InvoiceDate"].ge(start) & sales["InvoiceDate"].lt(end_exclusive)
    return float(sales.loc[mask, "Revenue"].sum())


def _filter_sales(
    data: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    country: str,
) -> pd.DataFrame:
    filtered = data.loc[
        (~data["IsCancelled"])
        & data["InvoiceDate"].ge(start_date)
        & data["InvoiceDate"].lt(end_date + pd.Timedelta(days=1))
    ]
    if country != "All countries":
        filtered = filtered.loc[filtered["Country"] == country]
    return filtered.copy()


def _repeat_customer_rate(sales: pd.DataFrame) -> float | None:
    identified = sales.loc[sales["CustomerID"].notna()]
    if identified.empty:
        return None
    order_counts = identified.groupby("CustomerID")["InvoiceNo"].nunique()
    return float(order_counts.gt(1).mean() * 100)


def _new_returning_customers(
    all_sales: pd.DataFrame,
    filtered_sales: pd.DataFrame,
    start_date: pd.Timestamp,
) -> tuple[int, int]:
    if filtered_sales.empty:
        return 0, 0

    customer_ids = filtered_sales["CustomerID"].dropna().unique()
    history = all_sales.loc[
        (~all_sales["IsCancelled"]) & all_sales["CustomerID"].isin(customer_ids)
    ]
    first_purchase = history.groupby("CustomerID")["InvoiceDate"].min()
    active_customers = filtered_sales["CustomerID"].dropna().unique()
    new_customers = int(first_purchase.reindex(active_customers).ge(start_date).sum())
    return new_customers, len(active_customers) - new_customers


def _show_empty(message: str = "No sales match the selected filters.") -> None:
    st.info(message)


st.markdown(
    """
    <style>
    .block-container {padding-top: 1.8rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #10243A, #173B50);
        border: 1px solid rgba(120, 190, 185, .2);
        padding: 1rem 1.1rem;
        border-radius: 12px;
    }
    [data-testid="stMetricLabel"] p {color: #C4D5DF;}
    [data-testid="stMetricValue"] {color: #F7FAFC;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("E-Commerce Sales Analytics")
st.caption(
    "A transaction-level view of sales, customers, products, and markets. "
    "Sales KPIs exclude cancellation-coded invoices; source rows remain available for quality analysis."
)

if not DATA_PATH.is_file():
    st.error(f"Required dataset not found: `{DATA_PATH.relative_to(PROJECT_ROOT)}`.")
    st.info("Deploy the repository with `data/cleaned_sales.csv` included.")
    st.stop()

try:
    analysis = load_analysis(str(DATA_PATH), DATA_PATH.stat().st_mtime)
except (OSError, ValueError, pd.errors.ParserError) as error:
    st.error(f"Could not load or validate the sales dataset: {error}")
    st.stop()

all_transactions = analysis["transactions"]
all_sales = analysis["sales"]
min_date = all_sales["OrderDate"].min().date()
max_date = all_sales["OrderDate"].max().date()
country_options = ["All countries", *sorted(all_sales["Country"].dropna().unique().tolist())]

with st.sidebar:
    st.header("Dashboard filters")
    selected_dates = st.date_input(
        "Invoice date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    selected_country = st.selectbox("Country", country_options)
    st.divider()
    st.caption("Sales analysis excludes invoice numbers beginning with C.")
    st.caption("Customer metrics exclude transactions without a CustomerID.")
    if st.button("Clear cached data and reload"):
        st.cache_data.clear()
        st.rerun()

if (
    not isinstance(selected_dates, (tuple, list))
    or len(selected_dates) != 2
    or any(value is None for value in selected_dates)
):
    st.info("Select both a start and end date to view the dashboard.")
    st.stop()

start_date = pd.Timestamp(selected_dates[0])
end_date = pd.Timestamp(selected_dates[1])
filtered_sales = _filter_sales(all_transactions, start_date, end_date, selected_country)
if filtered_sales.empty:
    _show_empty()
    st.stop()

period_days = (end_date - start_date).days + 1
previous_end = start_date
previous_start = start_date - pd.Timedelta(days=period_days)
growth_sales = all_sales
if selected_country != "All countries":
    growth_sales = growth_sales.loc[growth_sales["Country"] == selected_country]
current_revenue = float(filtered_sales["Revenue"].sum())
previous_revenue = _period_revenue(growth_sales, previous_start, previous_end)
growth_pct = (
    (current_revenue - previous_revenue) / previous_revenue * 100
    if previous_revenue
    else None
)
order_count = int(filtered_sales["InvoiceNo"].nunique())
customer_count = int(filtered_sales["CustomerID"].nunique())
repeat_rate = _repeat_customer_rate(filtered_sales)

tabs = st.tabs(
    [
        "Executive overview",
        "Product analysis",
        "Customer analysis",
        "Regional analysis",
        "Sales trends",
        "Data quality",
    ]
)

with tabs[0]:
    st.subheader("Executive sales overview")
    metric_columns = st.columns(5)
    metric_columns[0].metric("Revenue", _format_currency(current_revenue))
    metric_columns[1].metric("Orders", f"{order_count:,}")
    metric_columns[2].metric("Customers", f"{customer_count:,}")
    metric_columns[3].metric(
        "Average order value",
        _format_currency(current_revenue / order_count) if order_count else "—",
    )
    metric_columns[4].metric(
        "Revenue growth",
        f"{growth_pct:+.1f}%" if growth_pct is not None else "—",
        help=(
            f"Compared with the preceding {period_days}-day period "
            f"({previous_start.date()} to {(previous_end - pd.Timedelta(days=1)).date()})."
        ),
    )

    monthly = (
        filtered_sales.assign(YearMonth=filtered_sales["InvoiceDate"].dt.to_period("M").astype(str))
        .groupby("YearMonth", as_index=False)
        .agg(Revenue=("Revenue", "sum"))
        .sort_values("YearMonth")
        .set_index("YearMonth")
    )
    st.markdown("#### Monthly revenue")
    st.line_chart(monthly, y="Revenue", width="stretch", height=330)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Revenue by country")
        country_revenue = (
            filtered_sales.groupby("Country", as_index=False)["Revenue"]
            .sum()
            .nlargest(10, "Revenue")
            .sort_values("Revenue")
            .set_index("Country")
        )
        st.bar_chart(country_revenue, y="Revenue", width="stretch", height=300)
    with right:
        st.markdown("#### Customer repeat rate")
        st.metric(
            "Repeat customers in selected period",
            f"{repeat_rate:.1f}%" if repeat_rate is not None else "—",
            help="Identified customers with more than one distinct invoice in the selected date and country filters.",
        )
        st.caption(
            "Historical repeat behavior in the selected window; it does not establish why customers returned."
        )

with tabs[1]:
    st.subheader("Product performance")
    include_service_lines = st.checkbox(
        "Include postage/carriage-like descriptions",
        value=False,
        help="Description-based review flag only; it is not a validated product taxonomy.",
    )
    product_sales = (
        filtered_sales.groupby(["StockCode", "Description"], dropna=False, as_index=False)
        .agg(
            Revenue=("Revenue", "sum"),
            Quantity=("Quantity", "sum"),
            Orders=("InvoiceNo", "nunique"),
        )
    )
    service_codes = analysis["products"].set_index("StockCode")["ReviewAsServiceLine"]
    product_sales["ReviewAsServiceLine"] = (
        product_sales["StockCode"].map(service_codes).fillna(False).astype(bool)
    )
    if not include_service_lines:
        product_sales = product_sales.loc[~product_sales["ReviewAsServiceLine"]]
    if product_sales.empty:
        _show_empty("No product rows match these filters.")
    else:
        best_products = product_sales.nlargest(10, "Revenue").sort_values("Revenue")
        st.markdown("#### Top 10 product codes by revenue")
        st.bar_chart(
            best_products.set_index("Description")["Revenue"],
            horizontal=True,
            width="stretch",
            height=390,
        )
        best, lowest = st.columns(2)
        best_product = product_sales.loc[product_sales["Revenue"].idxmax()]
        lowest_product = product_sales.loc[product_sales["Revenue"].idxmin()]
        best.metric("Highest observed revenue", str(best_product["Description"]), _format_currency(best_product["Revenue"]))
        lowest.metric("Lowest observed revenue", str(lowest_product["Description"]), _format_currency(lowest_product["Revenue"]))
        st.caption(
            "Low observed revenue alone does not establish poor product performance; inventory, availability, margin, and product age are unavailable."
        )
        st.dataframe(product_sales.sort_values("Revenue", ascending=False), width="stretch", hide_index=True)
        st.download_button(
            "Download filtered product analysis",
            product_sales.to_csv(index=False).encode("utf-8"),
            file_name="filtered_product_analysis.csv",
            mime="text/csv",
        )

with tabs[2]:
    st.subheader("Customer behavior")
    new_customers, returning_customers = _new_returning_customers(
        all_sales,
        filtered_sales,
        start_date,
    )
    customer_metrics = st.columns(3)
    customer_metrics[0].metric(
        "Repeat customer rate",
        f"{repeat_rate:.1f}%" if repeat_rate is not None else "—",
    )
    customer_metrics[1].metric("New customers", f"{new_customers:,}")
    customer_metrics[2].metric("Returning customers", f"{returning_customers:,}")
    st.caption(
        "New means the first observed retailer purchase falls within the selected window; returning means active in the window with an earlier observed purchase. Country filters do not redefine a customer’s first purchase."
    )

    customer_ids = filtered_sales["CustomerID"].dropna().unique()
    rfm = analysis["customers"].loc[
        analysis["customers"]["CustomerID"].isin(customer_ids)
    ]
    if rfm.empty:
        _show_empty("No identified customers are available for the selected filters.")
    else:
        segment_summary = (
            rfm.groupby("Segment", as_index=False)
            .agg(Customers=("CustomerID", "nunique"), HistoricalRevenue=("Monetary", "sum"))
            .sort_values("HistoricalRevenue", ascending=False)
        )
        left, right = st.columns([1, 1.3])
        with left:
            st.markdown("#### RFM customer segments")
            st.bar_chart(
                segment_summary.set_index("Segment")["Customers"],
                width="stretch",
                height=300,
            )
        with right:
            st.markdown("#### Segment detail")
            st.dataframe(segment_summary, width="stretch", hide_index=True)
        st.info(
            "RFM scores and historical segment revenue use the full observation period and do not change with date filters. "
            "The customer list is limited to customers active in the selected filters."
        )
        st.markdown("#### Customer detail")
        customer_detail = rfm[
            [
                "CustomerID",
                "Segment",
                "RecencyDays",
                "Frequency",
                "Monetary",
                "RFM_Score",
            ]
        ].sort_values("Monetary", ascending=False)
        st.dataframe(customer_detail, width="stretch", hide_index=True)

with tabs[3]:
    st.subheader("Regional performance")
    st.caption("Country is the only geographic level available in the supplied dataset.")
    regional = (
        filtered_sales.groupby("Country", as_index=False)
        .agg(
            Revenue=("Revenue", "sum"),
            Orders=("InvoiceNo", "nunique"),
            Customers=("CustomerID", "nunique"),
            Quantity=("Quantity", "sum"),
        )
        .sort_values("Revenue", ascending=False)
    )
    if regional.empty:
        _show_empty("No country results match these filters.")
    else:
        top_country = regional.iloc[0]
        st.metric("Top country", top_country["Country"], _format_currency(top_country["Revenue"]))
        st.bar_chart(
            regional.head(15).sort_values("Revenue").set_index("Country")["Revenue"],
            horizontal=True,
            width="stretch",
            height=450,
        )
        st.dataframe(regional, width="stretch", hide_index=True)

with tabs[4]:
    st.subheader("Sales trends")
    trend = (
        filtered_sales.assign(
            YearMonth=filtered_sales["InvoiceDate"].dt.to_period("M"),
            Year=filtered_sales["InvoiceDate"].dt.year,
            Month=filtered_sales["InvoiceDate"].dt.month,
        )
        .groupby("YearMonth", as_index=False)
        .agg(Revenue=("Revenue", "sum"), Orders=("InvoiceNo", "nunique"))
        .sort_values("YearMonth")
    )
    trend["PreviousMonthRevenue"] = trend["Revenue"].shift(1)
    trend["GrowthPct"] = (
        (trend["Revenue"] - trend["PreviousMonthRevenue"])
        / trend["PreviousMonthRevenue"].replace(0, float("nan"))
        * 100
    )
    trend["YearMonth"] = trend["YearMonth"].astype(str)
    st.markdown("#### Monthly revenue and growth")
    st.line_chart(trend.set_index("YearMonth")["Revenue"], width="stretch", height=330)
    st.dataframe(trend, width="stretch", hide_index=True)

    annual = (
        filtered_sales.assign(Year=filtered_sales["InvoiceDate"].dt.year)
        .groupby("Year", as_index=False)
        .agg(Revenue=("Revenue", "sum"), Orders=("InvoiceNo", "nunique"))
        .sort_values("Year")
        .set_index("Year")
    )
    st.markdown("#### Yearly revenue")
    st.bar_chart(annual["Revenue"], width="stretch", height=260)
    st.caption(
        "The supplied data contains one complete year and a partial December 2011; "
        "monthly patterns should not be treated as proven recurring seasonality."
    )

with tabs[5]:
    st.subheader("Data quality and cancellations")
    quality = analysis["quality"]
    quality_items = [
        ("Source rows", quality["input_rows"]),
        ("Analysis rows after exact deduplication", quality["analysis_rows"]),
        ("Exact duplicates removed", quality["exact_duplicate_rows_removed"]),
        ("Rows with missing CustomerID", quality["missing_customer_id_rows"]),
        ("Rows with missing description", quality["missing_description_rows"]),
        ("Rows with nonpositive quantity", quality["nonpositive_quantity_rows"]),
        ("Rows with nonpositive unit price", quality["nonpositive_unit_price_rows"]),
        ("Source revenue mismatch rows", quality["source_revenue_mismatch_rows"]),
        ("Cancellation-coded rows", quality["cancelled_rows"]),
        ("Cancellation-coded invoices", quality["cancelled_invoice_count"]),
        ("First transaction", quality["first_invoice_date"]),
        ("Last transaction", quality["last_invoice_date"]),
    ]
    st.dataframe(
        pd.DataFrame(
            [(check, str(result)) for check, result in quality_items],
            columns=["Check", "Result"],
        ),
        width="stretch",
        hide_index=True,
    )
    kpis = analysis["kpis"]
    cancelled, share = st.columns(2)
    cancelled.metric("Cancellation-coded invoices", f"{kpis['cancelled_invoice_count']:,}")
    share.metric(
        "Cancellation invoice share",
        f"{kpis['cancelled_invoice_share_pct']:.1f}%",
        help="Cancellation-coded invoice IDs divided by all distinct invoice IDs. This is not the cancellation-coded row share.",
    )
    st.caption(
        f"Cancellation-coded rows are {kpis['cancelled_row_share_pct']:.1f}% of rows; "
        f"invoice-level cancellation share is {kpis['cancelled_invoice_share_pct']:.1f}%. "
        "These use different denominators."
    )
    st.download_button(
        "Download selected sales rows",
        filtered_sales.to_csv(index=False).encode("utf-8"),
        file_name="filtered_sales.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    f"Data snapshot: {min_date} to {max_date} · "
    "Revenue excludes cancellation-coded invoices · No cost data is available, so profit is not reported."
)
