-- store_inventory_schema.sql
-- Run this script in your MySQL instance to create the database and tables.

CREATE DATABASE IF NOT EXISTS store_inventory;
USE store_inventory;

CREATE TABLE IF NOT EXISTS inventory (
    barcode VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    price DECIMAL(10, 2) NOT NULL,
    original_price DECIMAL(10, 2) DEFAULT 0.00,
    expiry VARCHAR(50) DEFAULT 'N/A',
    stock_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pending_bills (
    bill_id VARCHAR(36) PRIMARY KEY,
    staff_username VARCHAR(100),
    total_amount DECIMAL(10, 2) NOT NULL,
    discount_applied DECIMAL(10, 2) DEFAULT 0.00,
    cart_items JSON NOT NULL,
    status VARCHAR(50) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id VARCHAR(36) PRIMARY KEY,
    staff_username VARCHAR(100),
    total_amount DECIMAL(10, 2) NOT NULL,
    discount_applied DECIMAL(10, 2) DEFAULT 0.00,
    refund_amount DECIMAL(10, 2) DEFAULT 0.00,
    cart_items JSON NOT NULL,
    status VARCHAR(50) DEFAULT 'COMPLETED',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indices for performance
CREATE INDEX idx_pending_bills_status ON pending_bills(status);
CREATE INDEX idx_transactions_created_at ON transactions(created_at);
