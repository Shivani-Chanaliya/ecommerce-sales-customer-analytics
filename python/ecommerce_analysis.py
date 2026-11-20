"""Reproducible analysis for the Online Retail transaction export."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "cleaned_sales.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"
VISUALIZATIONS_DIR = PROJECT_ROOT / "visualizations"

REQUIRED_COLUMNS = {
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
}


def _normalize_identifier(values: pd.Series, strip_integral_float: bool = False) -> pd.Series:
    normalized = values.astype("string").str.strip()
    normalized = normalized.mask(normalized.eq(""), pd.NA)
    if strip_integral_float:
        normalized = normalized.str.replace(r"(?<=\d)\.0$", "", regex=True)
    return normalized


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()


def prepare_sales_data(raw_data: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize types, remove exact duplicate rows, and retain valid return/cancel lines."""
    missing_columns = REQUIRED_COLUMNS.difference(raw_data.columns)
    if missing_columns:
        raise ValueError(f"Input is missing required columns: {sorted(missing_columns)}")

    data = raw_data.copy()
    input_rows = len(data)

    for column in ("InvoiceNo", "StockCode"):
        data[column] = _normalize_identifier(data[column])
        if data[column].isna().any():
            raise ValueError(f"{column} contains missing or blank transaction identifiers.")

    data["CustomerID"] = _normalize_identifier(data["CustomerID"], strip_integral_float=True)
    data["InvoiceDate"] = pd.to_datetime(data["InvoiceDate"], format="mixed", errors="coerce")
    if data["InvoiceDate"].isna().any():
        raise ValueError("InvoiceDate contains missing or invalid values.")

    for column in ("Quantity", "UnitPrice"):
        original = data[column]
        converted = pd.to_numeric(original, errors="coerce")
        invalid = original.notna() & converted.isna()
        if invalid.any() or converted.isna().any():
            raise ValueError(f"{column} contains missing or non-numeric values.")
        data[column] = converted

    source_revenue_mismatch_rows = 0
    source_revenue_invalid_rows = 0
    source_revenue_missing_rows = 0
    computed_revenue = (data["Quantity"] * data["UnitPrice"]).round(2)
    if "Revenue" in data.columns:
        source_revenue = pd.to_numeric(data["Revenue"], errors="coerce")
        source_revenue_invalid_rows = int(
            (data["Revenue"].notna() & source_revenue.isna()).sum()
        )
        source_revenue_missing_rows = int(source_revenue.isna().sum())
        mismatch = source_revenue.notna() & ~np.isclose(
            source_revenue.to_numpy(dtype=float),
            computed_revenue.to_numpy(dtype=float),
            atol=0.005,
            rtol=0,
        )
        source_revenue_mismatch_rows = int(mismatch.sum())
    data["Revenue"] = computed_revenue

    duplicate_rows = int(data.duplicated().sum())
    data = data.drop_duplicates().copy()
    data["IsCancelled"] = data["InvoiceNo"].str.upper().str.startswith("C")
    data["OrderDate"] = data["InvoiceDate"].dt.normalize()

    quality = {
        "input_rows": input_rows,
        "exact_duplicate_rows_removed": duplicate_rows,
        "analysis_rows": len(data),
        **{
            f"missing_{_snake_case(column)}_rows": int(data[column].isna().sum())
            for column in data.columns
        },
        "nonpositive_quantity_rows": int((data["Quantity"] <= 0).sum()),
        "nonpositive_unit_price_rows": int((data["UnitPrice"] <= 0).sum()),
        "source_revenue_mismatch_rows": source_revenue_mismatch_rows,
        "source_revenue_invalid_rows": source_revenue_invalid_rows,
        "source_revenue_missing_rows": source_revenue_missing_rows,
        "cancelled_rows": int(data["IsCancelled"].sum()),
        "cancelled_invoice_count": int(
            data.loc[data["IsCancelled"], "InvoiceNo"].nunique()
        ),
        "first_invoice_date": data["InvoiceDate"].min().isoformat(),
        "last_invoice_date": data["InvoiceDate"].max().isoformat(),
        "input_columns": len(raw_data.columns),
    }
    return data, quality


def _score_rfm(customers: pd.DataFrame) -> pd.DataFrame:
    result = customers.copy()
    if result.empty:
        for column in ("R_Score", "F_Score", "M_Score", "RFM_Score", "Segment"):
            result[column] = pd.Series(dtype="object")
        return result

    quantiles = min(5, len(result))

    def quantile_score(values: pd.Series, reverse: bool = False) -> pd.Series:
        percentile = values.rank(method="average", pct=True)
        scores = np.ceil(percentile * quantiles).clip(1, quantiles).astype(int)
        return quantiles + 1 - scores if reverse else scores

    result["R_Score"] = quantile_score(result["RecencyDays"], reverse=True)
    result["F_Score"] = quantile_score(result["Frequency"])
    result["M_Score"] = quantile_score(result["Monetary"])
    result["RFM_Score"] = (
        result["R_Score"].astype(str)
        + result["F_Score"].astype(str)
        + result["M_Score"].astype(str)
    )

    def segment(row: pd.Series) -> str:
        if row["R_Score"] >= 4 and row["F_Score"] >= 4:
            return "Champions"
        if row["F_Score"] >= 4:
            return "Loyal"
        if row["R_Score"] >= 4 and row["F_Score"] >= 2:
            return "Potential Loyalists"
        if row["R_Score"] <= 2 and row["F_Score"] >= 2:
            return "At Risk"
        if row["F_Score"] == 1 and row["R_Score"] >= 4:
            return "New Customers"
        return "Needs Attention"

    result["Segment"] = result.apply(segment, axis=1)
    return result


def _monthly_customer_activity(
    customer_orders: pd.DataFrame,
) -> pd.DataFrame:
    if customer_orders.empty:
        return pd.DataFrame(
            columns=["YearMonth", "ActiveCustomers", "NewCustomers", "ReturningCustomers"]
        )

    activity = customer_orders.copy()
    activity["YearMonth"] = activity["OrderDate"].dt.to_period("M")
    activity["FirstPurchaseMonth"] = activity["FirstPurchase"].dt.to_period("M")
    activity = activity.drop_duplicates(["CustomerID", "YearMonth"])
    activity["IsNewCustomer"] = activity["YearMonth"] == activity["FirstPurchaseMonth"]
    activity["IsReturningCustomer"] = activity["YearMonth"] > activity["FirstPurchaseMonth"]

    monthly = activity.groupby("YearMonth", as_index=False).agg(
        ActiveCustomers=("CustomerID", "nunique"),
        NewCustomers=("IsNewCustomer", "sum"),
        ReturningCustomers=("IsReturningCustomer", "sum"),
    )
    monthly["YearMonth"] = monthly["YearMonth"].astype(str)
    return monthly


def _cohort_retention(customer_orders: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "CohortMonth",
        "MonthsSinceFirstPurchase",
        "ActiveCustomers",
        "CohortSize",
        "RetentionPct",
    ]
    if customer_orders.empty:
        return pd.DataFrame(columns=columns)

    activity = customer_orders[["CustomerID", "OrderDate", "FirstPurchase"]].copy()
    activity["CohortMonth"] = activity["FirstPurchase"].dt.to_period("M")
    activity["ActivityMonth"] = activity["OrderDate"].dt.to_period("M")
    activity = activity.drop_duplicates(["CustomerID", "CohortMonth", "ActivityMonth"])
    activity["MonthsSinceFirstPurchase"] = (
        (activity["ActivityMonth"].dt.year - activity["CohortMonth"].dt.year) * 12
        + activity["ActivityMonth"].dt.month
        - activity["CohortMonth"].dt.month
    )

    counts = (
        activity.groupby(["CohortMonth", "MonthsSinceFirstPurchase"])["CustomerID"]
        .nunique()
        .rename("ActiveCustomers")
        .reset_index()
    )
    cohort_sizes = (
        counts.loc[counts["MonthsSinceFirstPurchase"] == 0, ["CohortMonth", "ActiveCustomers"]]
        .rename(columns={"ActiveCustomers": "CohortSize"})
    )
    result = counts.merge(cohort_sizes, on="CohortMonth", how="left", validate="many_to_one")
    result["RetentionPct"] = result["ActiveCustomers"] / result["CohortSize"] * 100
    result["CohortMonth"] = result["CohortMonth"].astype(str)
    return result[columns].sort_values(["CohortMonth", "MonthsSinceFirstPurchase"])


def _order_outliers(sales: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    order_values = (
        sales.groupby("InvoiceNo", as_index=False)
        .agg(OrderRevenue=("Revenue", "sum"))
        .sort_values("OrderRevenue")
    )
    if order_values.empty:
        return order_values.assign(IsOutlier=pd.Series(dtype=bool)), {}

    q1 = float(order_values["OrderRevenue"].quantile(0.25))
    q3 = float(order_values["OrderRevenue"].quantile(0.75))
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    order_values["IsOutlier"] = (
        (order_values["OrderRevenue"] < lower_bound)
        | (order_values["OrderRevenue"] > upper_bound)
    )
    return order_values, {
        "q1": q1,
        "q3": q3,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
    }


def analyze_sales(
    data: pd.DataFrame,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate business metrics on non-cancelled invoices, retaining returns/adjustments."""
    if data.empty:
        raise ValueError("No transaction rows are available for analysis.")

    sales = data.loc[~data["IsCancelled"]].copy()
    if sales.empty:
        raise ValueError("No non-cancelled invoices are available for analysis.")

    known_sales = sales.loc[sales["CustomerID"].notna()].copy()
    customer_summary = (
        known_sales.groupby("CustomerID", as_index=False)
        .agg(
            FirstPurchase=("InvoiceDate", "min"),
            LastPurchase=("InvoiceDate", "max"),
            Frequency=("InvoiceNo", "nunique"),
            Quantity=("Quantity", "sum"),
            Monetary=("Revenue", "sum"),
        )
    )
    snapshot_date = sales["InvoiceDate"].max().normalize() + pd.Timedelta(days=1)
    if not customer_summary.empty:
        customer_summary["RecencyDays"] = (
            snapshot_date - customer_summary["LastPurchase"].dt.normalize()
        ).dt.days

    customer_summary = _score_rfm(customer_summary)
    customer_orders = (
        known_sales.groupby(["CustomerID", "InvoiceNo"], as_index=False)
        .agg(OrderDate=("InvoiceDate", "min"))
        .merge(
            customer_summary[["CustomerID", "FirstPurchase"]],
            on="CustomerID",
            how="left",
            validate="many_to_one",
        )
    )

    monthly = (
        sales.assign(YearMonth=sales["InvoiceDate"].dt.to_period("M"))
        .groupby("YearMonth", as_index=False)
        .agg(
            Revenue=("Revenue", "sum"),
            Orders=("InvoiceNo", "nunique"),
            Quantity=("Quantity", "sum"),
        )
        .sort_values("YearMonth")
    )
    month_range = pd.period_range(monthly["YearMonth"].min(), monthly["YearMonth"].max(), freq="M")
    monthly = monthly.set_index("YearMonth").reindex(month_range, fill_value=0)
    monthly.index.name = "YearMonth"
    monthly = monthly.reset_index()
    monthly["PreviousMonthRevenue"] = monthly["Revenue"].shift(1)
    monthly["RevenueChange"] = monthly["Revenue"] - monthly["PreviousMonthRevenue"]
    monthly["RevenueGrowthPct"] = (
        monthly["RevenueChange"] / monthly["PreviousMonthRevenue"].replace(0, np.nan) * 100
    )
    monthly["Year"] = monthly["YearMonth"].dt.year
    monthly["Month"] = monthly["YearMonth"].dt.month

    annual = (
        sales.assign(Year=sales["InvoiceDate"].dt.year)
        .groupby("Year", as_index=False)
        .agg(
            Revenue=("Revenue", "sum"),
            Orders=("InvoiceNo", "nunique"),
            Customers=("CustomerID", "nunique"),
            Quantity=("Quantity", "sum"),
        )
        .sort_values("Year")
    )

    description = (
        data.groupby("StockCode", dropna=False)["Description"]
        .agg(lambda values: values.dropna().mode().iloc[0] if not values.dropna().mode().empty else pd.NA)
        .rename("Description")
    )
    product_summary = (
        sales.groupby("StockCode", as_index=False, dropna=False)
        .agg(
            Revenue=("Revenue", "sum"),
            Quantity=("Quantity", "sum"),
            Orders=("InvoiceNo", "nunique"),
        )
        .merge(description, on="StockCode", how="left", validate="one_to_one")
        .sort_values("Revenue", ascending=False)
    )
    product_summary["ReviewAsServiceLine"] = (
        product_summary["Description"]
        .astype("string")
        .str.contains(r"POSTAGE|CARRIAGE", case=False, na=False)
    )

    country_summary = (
        sales.groupby("Country", as_index=False, dropna=False)
        .agg(
            Revenue=("Revenue", "sum"),
            Orders=("InvoiceNo", "nunique"),
            Customers=("CustomerID", "nunique"),
            Quantity=("Quantity", "sum"),
        )
        .sort_values("Revenue", ascending=False)
    )

    monthly_customers = _monthly_customer_activity(customer_orders)
    order_outliers, outlier_bounds = _order_outliers(sales)

    repeat_customers = int((customer_summary["Frequency"] > 1).sum())
    identified_customers = int(customer_summary["CustomerID"].nunique())
    total_revenue = float(sales["Revenue"].sum())
    total_orders = int(sales["InvoiceNo"].nunique())
    cancelled_invoices = int(data.loc[data["IsCancelled"], "InvoiceNo"].nunique())
    all_invoices = int(data["InvoiceNo"].nunique())

    if customer_summary.empty:
        rfm_segments = pd.DataFrame(
            columns=["Segment", "Customers", "Revenue", "AverageRecencyDays", "AverageFrequency"]
        )
    else:
        rfm_segments = (
            customer_summary.groupby("Segment", as_index=False)
            .agg(
                Customers=("CustomerID", "nunique"),
                Revenue=("Monetary", "sum"),
                AverageRecencyDays=("RecencyDays", "mean"),
                AverageFrequency=("Frequency", "mean"),
            )
            .sort_values("Revenue", ascending=False)
        )

    kpis = {
        "revenue_basis": "Non-cancelled invoices; line revenue is Quantity * UnitPrice rounded to 2 decimals.",
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "total_customers": identified_customers,
        "average_order_value": total_revenue / total_orders if total_orders else None,
        "total_products": int(sales["StockCode"].nunique()),
        "total_countries": int(sales["Country"].nunique()),
        "total_quantity": float(sales["Quantity"].sum()),
        "repeat_customers": repeat_customers,
        "repeat_customer_rate_pct": (
            repeat_customers / identified_customers * 100 if identified_customers else None
        ),
        "cancelled_invoice_count": cancelled_invoices,
        "all_invoice_count": all_invoices,
        "cancelled_invoice_share_pct": (
            cancelled_invoices / all_invoices * 100 if all_invoices else None
        ),
        "cancelled_row_share_pct": float(data["IsCancelled"].mean() * 100),
        "customer_analysis_snapshot_date": snapshot_date.date().isoformat(),
        "identified_customer_revenue_share_top_10_pct": (
            float(customer_summary.nlargest(10, "Monetary")["Monetary"].sum() / total_revenue * 100)
            if not customer_summary.empty and total_revenue
            else None
        ),
        "outlier_order_count_iqr": int(order_outliers["IsOutlier"].sum()),
        "outlier_method": "1.5 * IQR fences on non-cancelled invoice net revenue; flagged, not removed.",
    }

    return {
        "transactions": data,
        "sales": sales,
        "kpis": kpis,
        "monthly": monthly,
        "annual": annual,
        "products": product_summary,
        "countries": country_summary,
        "customers": customer_summary,
        "rfm_segments": rfm_segments,
        "monthly_customers": monthly_customers,
        "cohort_retention": _cohort_retention(customer_orders),
        "order_outliers": order_outliers,
        "outlier_bounds": outlier_bounds,
        "quality": quality or {},
    }


def _write_charts(results: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", context="notebook")
    chart_paths: list[Path] = []

    monthly = results["monthly"]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    sns.lineplot(
        data=monthly,
        x=monthly["YearMonth"].astype(str),
        y="Revenue",
        marker="o",
        ax=ax,
    )
    ax.set(title="Monthly Revenue (Non-cancelled Invoices)", xlabel="Month", ylabel="Revenue (£)")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    path = output_dir / "monthly_revenue_trend.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    chart_paths.append(path)

    top_products = results["products"].nlargest(10, "Revenue").sort_values("Revenue")
    fig, ax = plt.subplots(figsize=(11, 6))
    sns.barplot(data=top_products, x="Revenue", y="Description", color="#2878B5", ax=ax)
    ax.set(title="Top 10 Product Codes by Revenue", xlabel="Revenue (£)", ylabel="Product description")
    fig.tight_layout()
    path = output_dir / "top_products_by_revenue.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    chart_paths.append(path)

    top_countries = results["countries"].dropna(subset=["Country"]).nlargest(10, "Revenue").sort_values("Revenue")
    fig, ax = plt.subplots(figsize=(10, 6))
    sns.barplot(data=top_countries, x="Revenue", y="Country", color="#36A37C", ax=ax)
    ax.set(title="Top 10 Countries by Revenue", xlabel="Revenue (£)", ylabel="Country")
    fig.tight_layout()
    path = output_dir / "country_revenue.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    chart_paths.append(path)

    segments = results["rfm_segments"].sort_values("Revenue", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    sns.barplot(data=segments, x="Segment", y="Revenue", color="#E39C37", ax=ax)
    ax.set(title="Customer Segment Revenue (Historical RFM)", xlabel="RFM segment", ylabel="Revenue (£)")
    ax.tick_params(axis="x", rotation=25)
    fig.tight_layout()
    path = output_dir / "rfm_segment_revenue.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    chart_paths.append(path)

    order_values = results["order_outliers"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    sns.boxplot(data=order_values, x="OrderRevenue", color="#8F6BB3", ax=ax)
    ax.set(title="Order Revenue Distribution (Outliers Flagged, Not Removed)", xlabel="Net order revenue (£)")
    fig.tight_layout()
    path = output_dir / "order_revenue_outliers.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    chart_paths.append(path)
    return chart_paths


def _format_money(value: float) -> str:
    return f"£{value:,.2f}"


def _write_business_insights(results: dict[str, Any], path: Path) -> None:
    kpis = results["kpis"]
    monthly = results["monthly"]
    products = results["products"]
    countries = results["countries"].dropna(subset=["Country"])
    segments = results["rfm_segments"]
    quality = results["quality"]

    best_month = monthly.loc[monthly["Revenue"].idxmax()]
    lowest_month = monthly.loc[monthly["Revenue"].idxmin()]
    top_product = products.iloc[0]
    merchandise_products = products.loc[~products["ReviewAsServiceLine"]]
    top_merchandise_product = merchandise_products.iloc[0] if not merchandise_products.empty else None
    top_country = countries.iloc[0]
    at_risk_segments = segments.loc[segments["Segment"] == "At Risk"]
    customer_missing_pct = (
        quality.get("missing_customer_id_rows", 0) / quality.get("analysis_rows", 1) * 100
    )
    month_label = lambda row: row["YearMonth"].strftime("%B %Y")

    lines = [
        "# Business Insights",
        "",
        f"> All revenue uses non-cancelled invoices and line revenue recomputed as quantity × unit price, rounded to two decimals. "
        f"The data ends on {quality.get('last_invoice_date', 'an unavailable date')}; the latest month may be partial.",
        "",
        "## Performance",
        "",
        f"- Revenue is {_format_money(kpis['total_revenue'])} across {kpis['total_orders']:,} non-cancelled invoices; "
        f"AOV is {_format_money(kpis['average_order_value'])}.",
        f"- {month_label(best_month)} is the highest-revenue month at {_format_money(float(best_month['Revenue']))}; "
        f"{month_label(lowest_month)} is the lowest at {_format_money(float(lowest_month['Revenue']))}.",
        f"- {top_country['Country']} contributes {_format_money(float(top_country['Revenue']))} "
        f"({float(top_country['Revenue']) / kpis['total_revenue'] * 100:.1f}% of revenue).",
        "",
        "## Products and customers",
        "",
        f"- The highest-revenue stock code overall is {top_product['StockCode']} "
        f"({top_product['Description'] if pd.notna(top_product['Description']) else 'description unavailable'}), "
        f"at {_format_money(float(top_product['Revenue']))}.",
    ]
    if top_merchandise_product is not None:
        lines.append(
            f"- Excluding descriptions flagged by the transparent POSTAGE/CARRIAGE review rule, "
            f"the highest-revenue product code is {top_merchandise_product['StockCode']} "
            f"({top_merchandise_product['Description'] if pd.notna(top_merchandise_product['Description']) else 'description unavailable'}), "
            f"at {_format_money(float(top_merchandise_product['Revenue']))}. This rule is for product ranking only; "
            "service-line revenue remains in total revenue."
        )
    lines.extend([
        f"- {kpis['repeat_customers']:,} of {kpis['total_customers']:,} identified customers "
        f"({kpis['repeat_customer_rate_pct']:.1f}%) placed more than one non-cancelled invoice in this dataset.",
        f"- The top 10 identified customers represent "
        f"{kpis['identified_customer_revenue_share_top_10_pct']:.1f}% of total sales revenue.",
        f"- The largest RFM revenue segment is {segments.iloc[0]['Segment']} "
        f"at {_format_money(float(segments.iloc[0]['Revenue']))}. RFM segments describe this observation window; "
        "they are not predicted customer lifetime value.",
    ])
    if not at_risk_segments.empty:
        at_risk = at_risk_segments.iloc[0]
        lines.append(
            f"- The relative-RFM At Risk segment contains {int(at_risk['Customers']):,} customers "
            f"and {_format_money(float(at_risk['Revenue']))} in observed revenue; this is a prioritization flag, "
            "not a churn prediction."
        )
    lines.extend([
        "",
        "## Risks and interpretation",
        "",
        f"- {quality.get('missing_customer_id_rows', 0):,} transaction rows "
        f"({customer_missing_pct:.1f}%) have no CustomerID, limiting customer-level attribution.",
        f"- {kpis['cancelled_invoice_count']:,} invoice IDs are cancellation-coded "
        f"({kpis['cancelled_invoice_share_pct']:.1f}% of all distinct invoice IDs); this is not the same as the "
        f"{kpis['cancelled_row_share_pct']:.1f}% cancellation-coded row share.",
        "- Only one complete year is available, and the final December is partial. Treat seasonal patterns as descriptive, not a proven recurring seasonal effect.",
        "- The data contains no cost or product-category field. Profit and category claims are not supported without additional validated data.",
        "- The data contains no campaign, acquisition-channel, or customer-interaction fields, so it cannot establish causal drivers of repeat purchases.",
        "",
        "## Actions to validate",
        "",
        "- Improve CustomerID capture and monitor the missing-ID rate so repeat behavior can be measured more completely.",
        "- Review inventory and campaign readiness ahead of the observed high-revenue month; validate the pattern against additional years before treating it as seasonality.",
        "- Investigate top product lines and customer segments with margin, stock, and campaign data before allocating budget; revenue alone is not profit or causal evidence.",
        "- Review service-like descriptions (for example postage) separately when interpreting product rankings; all lines remain included in total revenue.",
        "",
        "## Method",
        "",
        f"- RFM snapshot date: {kpis['customer_analysis_snapshot_date']}. Frequency is distinct non-cancelled invoice count; monetary value is historical net revenue in the observed period.",
        f"- Order outliers: {kpis['outlier_method']} {kpis['outlier_order_count_iqr']:,} orders were flagged.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_powerbi_tables(results: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    transactions = results["transactions"].copy()
    transactions["TransactionStatus"] = np.where(
        transactions["IsCancelled"], "Cancelled", "Sale"
    )
    transactions["OrderDate"] = transactions["OrderDate"].dt.strftime("%Y-%m-%d")
    transactions["InvoiceDate"] = transactions["InvoiceDate"].dt.strftime("%Y-%m-%d %H:%M:%S")
    fact_columns = [
        "InvoiceNo",
        "StockCode",
        "Description",
        "Quantity",
        "InvoiceDate",
        "OrderDate",
        "UnitPrice",
        "CustomerID",
        "Country",
        "Revenue",
        "TransactionStatus",
    ]
    tables = {
        "FactSales.csv": transactions[fact_columns],
        "DimCustomer.csv": results["customers"].rename(
            columns={"Frequency": "ObservedOrders", "Monetary": "ObservedRevenue"}
        ),
        "DimProduct.csv": results["products"][
            ["StockCode", "Description", "ReviewAsServiceLine"]
        ],
        "DimCountry.csv": (
            transactions[["Country"]]
            .dropna()
            .drop_duplicates()
            .sort_values("Country")
            .reset_index(drop=True)
        ),
        "FactCohortRetention.csv": results["cohort_retention"],
    }

    calendar_dates = pd.date_range(
        transactions["OrderDate"].min(),
        transactions["OrderDate"].max(),
        freq="D",
    )
    calendar = pd.DataFrame({"Date": calendar_dates})
    calendar["Year"] = calendar["Date"].dt.year
    calendar["MonthNumber"] = calendar["Date"].dt.month
    calendar["MonthName"] = calendar["Date"].dt.strftime("%B")
    calendar["Quarter"] = "Q" + calendar["Date"].dt.quarter.astype(str)
    calendar["YearMonth"] = calendar["Date"].dt.strftime("%Y-%m")
    calendar["YearMonthSort"] = calendar["Date"].dt.year * 100 + calendar["Date"].dt.month
    calendar["Date"] = calendar["Date"].dt.strftime("%Y-%m-%d")
    tables["DimDate.csv"] = calendar

    output_paths = []
    for filename, table in tables.items():
        path = output_dir / filename
        table.to_csv(path, index=False)
        output_paths.append(path)
    return output_paths


def run_analysis(
    input_path: Path = DEFAULT_INPUT,
    reports_dir: Path = REPORTS_DIR,
    visualizations_dir: Path = VISUALIZATIONS_DIR,
    powerbi_dir: Path = PROJECT_ROOT / "powerbi" / "data",
) -> dict[str, Any]:
    if not input_path.is_file():
        raise FileNotFoundError(f"Input CSV does not exist: {input_path}")

    raw_data = pd.read_csv(input_path, dtype={"InvoiceNo": "string", "StockCode": "string"})
    data, quality = prepare_sales_data(raw_data)
    results = analyze_sales(data, quality)

    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "business_kpis.json").write_text(
        json.dumps(results["kpis"], indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(
        [{"Metric": key, "Value": value} for key, value in quality.items()]
    ).to_csv(reports_dir / "data_quality_report.csv", index=False)

    for name in (
        "monthly",
        "annual",
        "products",
        "countries",
        "customers",
        "rfm_segments",
        "monthly_customers",
        "cohort_retention",
        "order_outliers",
    ):
        output = results[name].copy()
        if "YearMonth" in output.columns and isinstance(output["YearMonth"].dtype, pd.PeriodDtype):
            output["YearMonth"] = output["YearMonth"].astype(str)
        output.to_csv(reports_dir / f"{name}.csv", index=False)

    _write_business_insights(results, reports_dir / "business_insights.md")
    _write_charts(results, visualizations_dir)
    _write_powerbi_tables(results, powerbi_dir)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Transaction CSV path.")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR, help="Analysis output directory.")
    parser.add_argument(
        "--visualizations-dir",
        type=Path,
        default=VISUALIZATIONS_DIR,
        help="Chart output directory.",
    )
    parser.add_argument(
        "--powerbi-dir",
        type=Path,
        default=PROJECT_ROOT / "powerbi" / "data",
        help="Power BI model input directory.",
    )
    args = parser.parse_args()
    results = run_analysis(args.input, args.reports_dir, args.visualizations_dir, args.powerbi_dir)
    print(json.dumps(results["kpis"], indent=2))


if __name__ == "__main__":
    main()
