-- Recommended schema for loading the supplied transaction CSV.
-- Import cleaned_sales.csv into sales after running this file.
-- Keep CustomerID nullable: anonymous transactions are valid sales rows.

CREATE DATABASE IF NOT EXISTS ecommerce_analysis;
USE ecommerce_analysis;

CREATE TABLE IF NOT EXISTS sales (
    InvoiceNo VARCHAR(20) NOT NULL,
    StockCode VARCHAR(20) NOT NULL,
    Description VARCHAR(255) NULL,
    Quantity INT NOT NULL,
    InvoiceDate DATETIME NOT NULL,
    UnitPrice DECIMAL(12, 4) NOT NULL,
    CustomerID VARCHAR(20) NULL,
    Country VARCHAR(100) NULL,
    Revenue DECIMAL(14, 2) NOT NULL,
    INDEX idx_sales_invoice (InvoiceNo),
    INDEX idx_sales_date (InvoiceDate),
    INDEX idx_sales_customer (CustomerID),
    INDEX idx_sales_product (StockCode),
    INDEX idx_sales_country (Country)
);

-- Import data using MySQL Workbench's Table Data Import Wizard.
-- Map blank CustomerID cells to NULL, preserve InvoiceNo/StockCode/CustomerID as text,
-- and parse InvoiceDate as DATETIME. Then run business_analysis.sql.
