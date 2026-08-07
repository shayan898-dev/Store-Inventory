"""
database_manager.py
--------------------
All SQLite operations for Inventory Manager Pro.

Tables:
    products    — master inventory (barcode PK, name, category, qty, price, timestamp)
    sales_log   — last 50 sale transactions
    restock_log — last 50 restock transactions

Usage:
    db = DatabaseManager()          # auto-creates / migrates tables
    db.add_product("123", "Milk", "Dairy", 50, 199.00)
"""

import sqlite3
import csv
import os
import sys
import threading
from datetime import datetime
from typing import Optional
import bcrypt


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_db_path() -> str:
    """
    Returns inventory.db path next to the running script / .exe.
    Works both in development and when frozen by PyInstaller.
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "inventory.db")


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------

class DatabaseManager:
    """Encapsulates every SQL operation for Inventory Manager Pro."""

    # Maximum transactions kept in each log table
    LOG_LIMIT = 50

    def __init__(self):
        self.db_path = get_db_path()
        self._lock   = threading.Lock()   # Serialises all write operations
        self.create_tables()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read performance
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    # ------------------------------------------------------------------
    # Schema setup & migration
    # ------------------------------------------------------------------

    def create_tables(self):
        """
        Creates all tables if they don't exist and migrates existing DBs
        to add new columns without data loss.
        """
        with self._connect() as conn:
            # ---- Products table ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    barcode   TEXT PRIMARY KEY,
                    name      TEXT NOT NULL,
                    category  TEXT NOT NULL DEFAULT 'General',
                    quantity  INTEGER NOT NULL DEFAULT 0,
                    price     REAL NOT NULL DEFAULT 0.0,
                    original_price REAL NOT NULL DEFAULT 0.0,
                    expiry    TEXT DEFAULT 'N/A',
                    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
                );
            """)

            # ---- Transactions table ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    tracking_id   TEXT PRIMARY KEY,
                    total_amount  REAL DEFAULT 0.0,
                    total_items   INTEGER DEFAULT 0,
                    total_profit  REAL DEFAULT 0.0,
                    discount_applied REAL DEFAULT 0.0,
                    discount_type TEXT DEFAULT 'None',
                    timestamp     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
                );
            """)

            # ---- Sales log table ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sales_log (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracking_id   TEXT DEFAULT 'LEGACY',
                    barcode       TEXT NOT NULL,
                    name          TEXT NOT NULL,
                    quantity_sold INTEGER NOT NULL,
                    quantity_refunded INTEGER DEFAULT 0,
                    unit_price    REAL DEFAULT 0.0,
                    total_amount  REAL DEFAULT 0.0,
                    remaining_qty INTEGER NOT NULL,
                    timestamp     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
                );
            """)

            # Automatic Schema Migrations for existing databases
            sales_log_cols = [row[1] for row in conn.execute("PRAGMA table_info(sales_log);").fetchall()]
            if "unit_price" not in sales_log_cols:
                conn.execute("ALTER TABLE sales_log ADD COLUMN unit_price REAL DEFAULT 0.0;")
            if "total_amount" not in sales_log_cols:
                conn.execute("ALTER TABLE sales_log ADD COLUMN total_amount REAL DEFAULT 0.0;")
            if "tracking_id" not in sales_log_cols:
                conn.execute("ALTER TABLE sales_log ADD COLUMN tracking_id TEXT DEFAULT 'LEGACY';")
            if "quantity_refunded" not in sales_log_cols:
                conn.execute("ALTER TABLE sales_log ADD COLUMN quantity_refunded INTEGER DEFAULT 0;")
                
            txn_cols = [row[1] for row in conn.execute("PRAGMA table_info(transactions);").fetchall()] if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions';").fetchone() else []
            if txn_cols and "total_profit" not in txn_cols:
                conn.execute("ALTER TABLE transactions ADD COLUMN total_profit REAL DEFAULT 0.0;")
            if txn_cols and "discount_applied" not in txn_cols:
                conn.execute("ALTER TABLE transactions ADD COLUMN discount_applied REAL DEFAULT 0.0;")
            if txn_cols and "discount_type" not in txn_cols:
                conn.execute("ALTER TABLE transactions ADD COLUMN discount_type TEXT DEFAULT 'None';")

            # ---- Daily Sales Summary table (EOD Aggregates) ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_sales_summary (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_date          TEXT UNIQUE NOT NULL,
                    total_transactions INTEGER NOT NULL DEFAULT 0,
                    total_items_sold   INTEGER NOT NULL DEFAULT 0,
                    total_revenue      REAL NOT NULL DEFAULT 0.0,
                    compiled_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
                );
            """)

            # ---- Restock log table ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS restock_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode         TEXT NOT NULL,
                    name            TEXT NOT NULL,
                    quantity_added  INTEGER NOT NULL,
                    remaining_qty   INTEGER NOT NULL,
                    timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
                );
            """)

            # ---- Staff table ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS staff (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    name      TEXT NOT NULL,
                    phone     TEXT NOT NULL DEFAULT '',
                    status    TEXT NOT NULL DEFAULT 'Active',
                    role      TEXT NOT NULL DEFAULT 'Staff',
                    salary    REAL DEFAULT 0.0,
                    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
                );
            """)

            # ---- Security & Users ----
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_permissions (
                    username TEXT,
                    permission_name TEXT,
                    PRIMARY KEY (username, permission_name)
                );
            ''')

            conn.execute("""
                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS role_permissions (
                    role_id INTEGER,
                    permission_id INTEGER,
                    PRIMARY KEY (role_id, permission_id),
                    FOREIGN KEY (role_id) REFERENCES roles(id),
                    FOREIGN KEY (permission_id) REFERENCES permissions(id)
                );
            """)
            
            # The new users table (migration handled below)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role_id INTEGER,
                    status TEXT DEFAULT 'Active',
                    FOREIGN KEY (role_id) REFERENCES roles(id)
                );
            """)
            
            # Configuration
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    category TEXT NOT NULL
                );
            """)
            
            # Audit Tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Seed default roles if empty
            cur = conn.execute("SELECT COUNT(*) FROM roles;")
            if cur.fetchone()[0] == 0:
                conn.execute("INSERT INTO roles (name, description) VALUES ('admin', 'System Administrator');")
                conn.execute("INSERT INTO roles (name, description) VALUES ('staff', 'Standard Staff Member');")
                conn.execute("INSERT INTO roles (name, description) VALUES ('manager', 'Store Manager');")
                conn.execute("INSERT INTO roles (name, description) VALUES ('cashier', 'Checkout Operator');")
                
                permissions = [
                    ("access_settings", "Access the Settings Dashboard"),
                    ("add_product", "Add new products"),
                    ("edit_product", "Edit existing products"),
                    ("delete_product", "Delete products"),
                    ("view_inventory", "View the inventory list"),
                    ("process_sale", "Process sales and print receipts"),
                    ("apply_discount", "Apply discounts to bills"),
                    ("process_refund", "Process refunds"),
                    ("process_restock", "Add stock to products"),
                    ("view_reports", "View financial and sales reports"),
                    ("view_transactions", "View past transactions"),
                    ("manage_staff", "Add, edit, or delete staff members and users")
                ]
                for p_name, p_desc in permissions:
                    conn.execute("INSERT INTO permissions (name, description) VALUES (?, ?);", (p_name, p_desc))
                    
                # Grant admin all permissions
                conn.execute("""
                    INSERT INTO role_permissions (role_id, permission_id) 
                    SELECT (SELECT id FROM roles WHERE name='admin'), id FROM permissions;
                """)
                # Grant staff basic permissions
                staff_perms = ['view_inventory', 'process_sale']
                for sp in staff_perms:
                    conn.execute("""
                        INSERT INTO role_permissions (role_id, permission_id) 
                        VALUES ((SELECT id FROM roles WHERE name='staff'), (SELECT id FROM permissions WHERE name=?));
                    """, (sp,))
                    
                # Grant manager permissions
                manager_perms = ['view_inventory', 'process_sale', 'edit_product', 'add_product', 'delete_product', 'apply_discount', 'process_refund', 'process_restock', 'view_reports', 'view_transactions', 'access_settings']
                for mp in manager_perms:
                    conn.execute("""
                        INSERT INTO role_permissions (role_id, permission_id) 
                        VALUES ((SELECT id FROM roles WHERE name='manager'), (SELECT id FROM permissions WHERE name=?));
                    """, (mp,))
                    
                # Grant cashier permissions
                cashier_perms = ['view_inventory', 'process_sale']
                for cp in cashier_perms:
                    conn.execute("""
                        INSERT INTO role_permissions (role_id, permission_id) 
                        VALUES ((SELECT id FROM roles WHERE name='cashier'), (SELECT id FROM permissions WHERE name=?));
                    """, (cp,))
                    
            # Seed default users if empty
            cur = conn.execute("SELECT COUNT(*) FROM users;")
            if cur.fetchone()[0] == 0:
                # We check if there's a legacy users table to migrate first in _migrate
                pass

            conn.commit()

            # ---- Migration: add new columns to existing DBs ----
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection):
        """Safely adds missing columns to an older database — never drops data."""
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(products);")}

        if "category" not in existing_cols:
            conn.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'General';")
            print("[DB] Migrated: added 'category' column")

        if "expiry" not in existing_cols:
            conn.execute("ALTER TABLE products ADD COLUMN expiry TEXT DEFAULT 'N/A';")
            print("[DB] Migrated: added 'expiry' column")

        if "original_price" not in existing_cols:
            conn.execute("ALTER TABLE products ADD COLUMN original_price REAL DEFAULT 0.0;")
            print("[DB] Migrated: added 'original_price' column")

        if "timestamp" not in existing_cols:
            # SQLite ALTER TABLE only accepts constant literals as DEFAULT —
            # existing rows get a placeholder; new rows use the CREATE TABLE default.
            conn.execute(
                "ALTER TABLE products ADD COLUMN timestamp TEXT NOT NULL "
                "DEFAULT '1970-01-01 00:00:00';"
            )
            print("[DB] Migrated: added 'timestamp' column")

        # Migrate staff table
        staff_cols = {row[1] for row in conn.execute("PRAGMA table_info(staff);")}
        if "salary" not in staff_cols:
            conn.execute("ALTER TABLE staff ADD COLUMN salary REAL DEFAULT 0.0;")
            print("[DB] Migrated: added 'salary' column to staff")

        # Migrate Users to RBAC
        user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users);")}
        if "password" in user_cols and "password_hash" not in user_cols:
            print("[DB] Migrating legacy users to RBAC...")
            # We must recreate the table
            conn.execute("ALTER TABLE users RENAME TO users_legacy;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role_id INTEGER,
                    status TEXT DEFAULT 'Active',
                    FOREIGN KEY (role_id) REFERENCES roles(id)
                );
            """)
            legacy_users = conn.execute("SELECT username, password, role FROM users_legacy").fetchall()
            for u in legacy_users:
                uname = u[0]
                upass = u[1]
                urole = u[2]
                
                # hash password
                phash = bcrypt.hashpw(upass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                
                # get role id
                r_id = conn.execute("SELECT id FROM roles WHERE name=?", (urole.lower(),)).fetchone()
                role_id = r_id[0] if r_id else 2 # default to staff
                
                conn.execute("INSERT INTO users (username, password_hash, role_id) VALUES (?, ?, ?);", (uname, phash, role_id))
                
            conn.execute("DROP TABLE users_legacy;")
            print("[DB] Successfully migrated users.")
            
        # Seed default users if empty (whether new or migrated with 0 rows)
        cur = conn.execute("SELECT COUNT(*) FROM users;")
        if cur.fetchone()[0] == 0:
            admin_hash = bcrypt.hashpw(b'admin', bcrypt.gensalt()).decode('utf-8')
            staff_hash = bcrypt.hashpw(b'staff', bcrypt.gensalt()).decode('utf-8')
            conn.execute("INSERT INTO users (username, password_hash, role_id) VALUES ('admin', ?, (SELECT id FROM roles WHERE name='admin'));", (admin_hash,))
            conn.execute("INSERT INTO users (username, password_hash, role_id) VALUES ('staff', ?, (SELECT id FROM roles WHERE name='staff'));", (staff_hash,))
            print("[DB] Seeded default users.")
                
        conn.commit()

    # ------------------------------------------------------------------
    # Products — Read
    # ------------------------------------------------------------------

    def get_all_products(self) -> list[dict]:
        """Returns all products sorted alphabetically by name."""
        sql = "SELECT barcode, name, category, quantity, price, expiry, timestamp FROM products ORDER BY name ASC;"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def search_products(self, query: str) -> list[dict]:
        """Case-insensitive filter by barcode, name, or category."""
        pattern = f"%{query}%"
        sql = """
            SELECT barcode, name, category, quantity, price, expiry, timestamp
            FROM products
            WHERE barcode LIKE ? OR name LIKE ? OR category LIKE ?
            ORDER BY name ASC;
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (pattern, pattern, pattern)).fetchall()]

    def find_by_barcode(self, barcode: str) -> Optional[dict]:
        """Exact barcode lookup. Returns dict or None."""
        sql = "SELECT barcode, name, category, quantity, price, expiry, timestamp FROM products WHERE barcode = ?;"
        with self._connect() as conn:
            row = conn.execute(sql, (barcode.strip(),)).fetchone()
        return dict(row) if row else None

    def get_low_stock_products(self, threshold: int = 5) -> list[dict]:
        """Returns products with quantity < threshold, sorted by qty ascending."""
        sql = """
            SELECT barcode, name, category, quantity, price
            FROM products WHERE quantity < ?
            ORDER BY quantity ASC;
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (threshold,)).fetchall()]

    def get_summary_stats(self) -> dict:
        """Aggregate stats for the Reports dashboard."""
        with self._connect() as conn:
            total_products  = conn.execute("SELECT COUNT(*) FROM products;").fetchone()[0]
            total_items     = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM products;").fetchone()[0]
            low_stock_count = conn.execute("SELECT COUNT(*) FROM products WHERE quantity < 5;").fetchone()[0]
            total_value     = conn.execute(
                "SELECT COALESCE(SUM(quantity * price), 0.0) FROM products;"
            ).fetchone()[0]
        return {
            "total_products":  total_products,
            "total_items":     int(total_items),
            "low_stock_count": low_stock_count,
            "total_value":     round(float(total_value), 2),
        }

    def get_categories(self) -> list[str]:
        """Returns distinct categories for the dropdown in the dialog."""
        sql = "SELECT DISTINCT category FROM products ORDER BY category ASC;"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        cats = [r[0] for r in rows if r[0]]
        # Always include these defaults even if no products yet
        defaults = ["General","Food & Beverage","Dairy","Bakery","Snacks",
                    "Beverages","Household","Personal Care","Electronics","Clothing"]
        for d in defaults:
            if d not in cats:
                cats.append(d)
        return sorted(cats)

    # ------------------------------------------------------------------
    # Products — Write
    # ------------------------------------------------------------------

    def add_product(self, barcode: str, name: str, category: str,
                    quantity: int, price: float, original_price: float = 0.0, expiry: str = "N/A", user_role: str = "staff") -> bool:
        """
        Inserts a new product.
        Returns True on success, False if barcode already exists.
        """
        if user_role != "admin":
            print("[DB] Access Denied: only admins can add products.")
            return False
        sql = """
            INSERT INTO products (barcode, name, category, quantity, price, original_price, expiry, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%S','now','localtime'));
        """
        try:
            with self._connect() as conn:
                conn.execute(sql, (barcode.strip(), name.strip(), category.strip(),
                                   int(quantity), float(price), float(original_price), expiry.strip()))
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False   # Duplicate barcode

    def update_product(self, barcode: str, name: str, category: str,
                       quantity: int, price: float, original_price: float = 0.0, expiry: str = "N/A", user_role: str = "staff") -> bool:
        """Updates an existing product. Returns True if a row was changed."""
        if user_role != "admin":
            print("[DB] Access Denied: only admins can update products.")
            return False
        sql = """
            UPDATE products
            SET name=?, category=?, quantity=?, price=?, original_price=?, expiry=?,
                timestamp=strftime('%Y-%m-%d %H:%M:%S','now','localtime')
            WHERE barcode=?;
        """
        with self._connect() as conn:
            cur = conn.execute(sql, (name.strip(), category.strip(),
                                     int(quantity), float(price), float(original_price), expiry.strip(), barcode.strip()))
            conn.commit()
        return cur.rowcount > 0

    def update_quantity(self, barcode: str, delta: int) -> tuple[bool, Optional[dict]]:
        """
        Legacy wrapper — kept for backward compatibility.
        Prefer update_stock() for new code.
        """
        status, product = self.update_stock(barcode, delta)
        return status == "ok", product

    def update_stock(self, barcode: str, amount: int) -> tuple[str, Optional[dict]]:
        """
        Thread-safe stock change.

        Parameters
        ----------
        barcode : str   — product barcode
        amount  : int   — positive = add stock, negative = sell stock

        Returns
        -------
        (status, updated_product_dict)

        status values
        -------------
        'ok'          — change applied, product returned
        'not_found'   — barcode not in DB, product is None
        'out_of_stock'— amount is negative and qty already 0, product returned as-is
        """
        with self._lock:
            product = self.find_by_barcode(barcode)
            if not product:
                return "not_found", None

            # Block selling when stock is 0
            if amount < 0 and product["quantity"] <= 0:
                return "out_of_stock", product

            new_qty = max(0, product["quantity"] + amount)
            with self._connect() as conn:
                conn.execute(
                    "UPDATE products SET quantity=?, "
                    "timestamp=strftime('%Y-%m-%d %H:%M:%S','now','localtime') "
                    "WHERE barcode=?;",
                    (new_qty, barcode.strip())
                )
                conn.commit()

            product["quantity"] = new_qty
            return "ok", product

    def delete_product(self, barcode: str, user_role: str = "staff") -> bool:
        """Permanently removes a product. Returns True if deleted."""
        if user_role != "admin":
            print("[DB] Access Denied: only admins can delete products.")
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM products WHERE barcode=?;", (barcode.strip(),))
            conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Transactions & Logs — Write
    # ------------------------------------------------------------------

    def create_transaction(self, tracking_id: str, total_amount: float, total_items: int, total_profit: float = 0.0, discount_applied: float = 0.0, discount_type: str = "None"):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO transactions (tracking_id, total_amount, total_items, total_profit, discount_applied, discount_type) VALUES (?, ?, ?, ?, ?, ?);",
                (tracking_id, total_amount, total_items, total_profit, discount_applied, discount_type)
            )
            conn.commit()

    def get_recent_transactions(self, limit: int = 50) -> list[dict]:
        sql = "SELECT tracking_id, total_amount, total_items, total_profit, discount_applied, discount_type, timestamp FROM transactions ORDER BY timestamp DESC LIMIT ?;"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (limit,)).fetchall()]

    def get_transactions_with_filters(self, tracking_id: str = "", date_range: str = "All Time", limit: int = 200) -> list[dict]:
        sql = "SELECT tracking_id, total_amount, total_items, total_profit, discount_applied, discount_type, timestamp FROM transactions WHERE 1=1"
        params = []
        
        if tracking_id:
            sql += " AND tracking_id LIKE ?"
            params.append(f"%{tracking_id}%")
            
        if date_range != "All Time":
            from datetime import datetime, timedelta
            now = datetime.now()
            if date_range == "Today":
                start_date = now.strftime("%Y-%m-%d 00:00:00")
            elif date_range == "This Week":
                start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
            elif date_range == "This Month":
                start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
            else:
                start_date = "1970-01-01 00:00:00"
            sql += " AND timestamp >= ?"
            params.append(start_date)
            
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]

    def get_transaction_items(self, tracking_id: str) -> list[dict]:
        sql = """
            SELECT id, tracking_id, barcode, name, quantity_sold, quantity_refunded, unit_price, total_amount
            FROM sales_log
            WHERE tracking_id = ?;
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (tracking_id,)).fetchall()]

    def _get_start_date(self, date_range: str) -> str:
        from datetime import datetime, timedelta
        now = datetime.now()
        if date_range == "Today":
            return now.strftime("%Y-%m-%d 00:00:00")
        elif date_range == "Last 7 Days":
            return (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        elif date_range == "This Month":
            return (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
        return "1970-01-01 00:00:00"

    def get_analytics_summary(self, date_range: str) -> dict:
        start_date = self._get_start_date(date_range)
        sql = """
            SELECT 
                COALESCE(SUM((s.quantity_sold - s.quantity_refunded) * s.unit_price), 0.0) as gross_revenue,
                COALESCE(SUM((s.quantity_sold - s.quantity_refunded) * (s.unit_price - p.original_price)), 0.0) as net_profit,
                COALESCE(SUM(s.quantity_sold - s.quantity_refunded), 0) as total_items_sold
            FROM sales_log s
            JOIN products p ON s.barcode = p.barcode
            WHERE s.timestamp >= ?
        """
        with self._connect() as conn:
            row = conn.execute(sql, (start_date,)).fetchone()
            return dict(row) if row else {"gross_revenue": 0.0, "net_profit": 0.0, "total_items_sold": 0}

    def get_top_performing_products(self, date_range: str) -> list[dict]:
        start_date = self._get_start_date(date_range)
        sql = """
            SELECT 
                p.name, 
                p.barcode,
                SUM(s.quantity_sold - s.quantity_refunded) as total_units_sold,
                SUM((s.quantity_sold - s.quantity_refunded) * s.unit_price) as total_revenue,
                SUM((s.quantity_sold - s.quantity_refunded) * (s.unit_price - p.original_price)) as total_profit
            FROM sales_log s
            JOIN products p ON s.barcode = p.barcode
            WHERE s.timestamp >= ?
            GROUP BY p.barcode
            HAVING total_units_sold > 0
            ORDER BY total_profit DESC
            LIMIT 50
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (start_date,)).fetchall()]

    def get_sold_out_analytics(self, date_range: str) -> list[dict]:
        start_date = self._get_start_date(date_range)
        sql = """
            SELECT 
                p.name, 
                p.barcode,
                SUM(s.quantity_sold - s.quantity_refunded) as total_units_sold,
                SUM((s.quantity_sold - s.quantity_refunded) * s.unit_price) as total_revenue,
                SUM((s.quantity_sold - s.quantity_refunded) * (s.unit_price - p.original_price)) as total_profit
            FROM sales_log s
            JOIN products p ON s.barcode = p.barcode
            WHERE p.quantity = 0 AND s.timestamp >= ?
            GROUP BY p.barcode
            HAVING total_units_sold > 0
            ORDER BY total_profit DESC
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (start_date,)).fetchall()]

    def process_refund_item(self, log_id: int, barcode: str, refund_qty: int) -> bool:
        """Processes a refund for a specific sales log entry, increasing stock and updating refunded qty."""
        with self._lock:
            try:
                with self._connect() as conn:
                    # Get product name and current qty
                    row = conn.execute("SELECT name, quantity FROM products WHERE barcode = ?;", (barcode,)).fetchone()
                    if not row:
                        return False
                    name = row["name"]
                    current_qty = row["quantity"]
                    new_qty = current_qty + refund_qty
                    
                    # Increment stock
                    conn.execute(
                        "UPDATE products SET quantity = ?, timestamp = strftime('%Y-%m-%d %H:%M:%S','now','localtime') WHERE barcode = ?;",
                        (new_qty, barcode)
                    )
                    # Increment refunded quantity in log
                    conn.execute(
                        "UPDATE sales_log SET quantity_refunded = quantity_refunded + ? WHERE id = ?;",
                        (refund_qty, log_id)
                    )
                    # Add to restock_log so it shows in return history
                    conn.execute(
                        "INSERT INTO restock_log (barcode, name, quantity_added, remaining_qty) VALUES (?, ?, ?, ?);",
                        (barcode, name, refund_qty, new_qty)
                    )
                    conn.commit()
                return True
            except Exception as e:
                print(f"[DB] Refund error: {e}")
                return False

    def log_sale(self, tracking_id: str, barcode: str, name: str, quantity_sold: int, remaining_qty: int,
                 unit_price: float = 0.0, total_amount: float = 0.0):
        """
        Records a sale event with pricing information.
        Automatically prunes the table to keep only the last LOG_LIMIT rows.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sales_log (tracking_id, barcode, name, quantity_sold, unit_price, total_amount, remaining_qty) "
                "VALUES (?, ?, ?, ?, ?, ?, ?);",
                (tracking_id, barcode, name, quantity_sold, unit_price, total_amount, remaining_qty)
            )
            # Keep only the most recent LOG_LIMIT records
            conn.execute(
                "DELETE FROM sales_log WHERE id NOT IN "
                "(SELECT id FROM sales_log ORDER BY id DESC LIMIT ?);",
                (self.LOG_LIMIT,)
            )
            conn.commit()

    def run_eod_wrapup(self, sale_date: str = None) -> tuple[bool, str, dict]:
        """
        End-of-Day (EOD) compilation function.
        Aggregates individual sales transactions for a given date (default: today)
        and saves a single daily summary record into daily_sales_summary.
        """
        if not sale_date:
            sale_date = datetime.now().strftime("%Y-%m-%d")

        with self._lock:
            try:
                with self._connect() as conn:
                    # Aggregate transaction metrics for the specified date
                    sql_aggregate = """
                        SELECT 
                            COUNT(*) as total_transactions,
                            COALESCE(SUM(total_items), 0) as total_items_sold,
                            COALESCE(SUM(total_amount), 0.0) as total_revenue
                        FROM transactions
                        WHERE strftime('%Y-%m-%d', timestamp) = ?;
                    """
                    row = conn.execute(sql_aggregate, (sale_date,)).fetchone()
                    
                    trans_count = row["total_transactions"]
                    items_sold  = row["total_items_sold"]
                    revenue     = row["total_revenue"]

                    # Upsert (Insert or Update on conflict) into daily_sales_summary
                    sql_upsert = """
                        INSERT INTO daily_sales_summary (sale_date, total_transactions, total_items_sold, total_revenue)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(sale_date) DO UPDATE SET
                            total_transactions = excluded.total_transactions,
                            total_items_sold  = excluded.total_items_sold,
                            total_revenue     = excluded.total_revenue,
                            compiled_at       = strftime('%Y-%m-%d %H:%M:%S','now','localtime');
                    """
                    conn.execute(sql_upsert, (sale_date, trans_count, items_sold, revenue))
                    conn.commit()

                summary = {
                    "sale_date": sale_date,
                    "total_transactions": trans_count,
                    "total_items_sold": items_sold,
                    "total_revenue": revenue
                }
                msg = f"EOD Wrap-Up compiled for {sale_date}: {trans_count} transactions, {items_sold} items sold, PKR {revenue:.2f} total revenue."
                return True, msg, summary

            except Exception as e:
                return False, f"EOD compilation failed: {e}", {}

    def get_monthly_sales_report(self, year_month: str = None) -> dict:
        """
        Queries the daily_sales_summary table for all days in a given month.
        Format: YYYY-MM (e.g. '2026-07'). Defaults to current month.
        """
        if not year_month:
            year_month = datetime.now().strftime("%Y-%m")

        with self._connect() as conn:
            sql = """
                SELECT sale_date, total_transactions, total_items_sold, total_revenue
                FROM daily_sales_summary
                WHERE strftime('%Y-%m', sale_date) = ?
                ORDER BY sale_date ASC;
            """
            rows = [dict(r) for r in conn.execute(sql, (year_month,)).fetchall()]

        total_revenue = sum(r["total_revenue"] for r in rows)
        total_items   = sum(r["total_items_sold"] for r in rows)
        total_trans   = sum(r["total_transactions"] for r in rows)

        return {
            "year_month": year_month,
            "total_revenue": total_revenue,
            "total_items_sold": total_items,
            "total_transactions": total_trans,
            "daily_breakdown": rows
        }

    def log_restock(self, barcode: str, name: str, quantity_added: int, remaining_qty: int):
        """
        Records a restock event.
        Automatically prunes to keep only the last LOG_LIMIT rows.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO restock_log (barcode, name, quantity_added, remaining_qty) "
                "VALUES (?, ?, ?, ?);",
                (barcode, name, quantity_added, remaining_qty)
            )
            conn.execute(
                "DELETE FROM restock_log WHERE id NOT IN "
                "(SELECT id FROM restock_log ORDER BY id DESC LIMIT ?);",
                (self.LOG_LIMIT,)
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Logs — Read
    # ------------------------------------------------------------------

    def get_recent_sales(self, limit: int = 20) -> list[dict]:
        """Returns the most recent sales, newest first."""
        sql = """
            SELECT barcode, name, quantity_sold, remaining_qty, timestamp
            FROM sales_log ORDER BY id DESC LIMIT ?;
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (limit,)).fetchall()]

    def get_recent_restocks(self, limit: int = 20) -> list[dict]:
        """Returns the most recent restocks, newest first."""
        sql = """
            SELECT barcode, name, quantity_added, remaining_qty, timestamp
            FROM restock_log ORDER BY id DESC LIMIT ?;
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (limit,)).fetchall()]

    def get_restock_log(self, limit: int = 50) -> list[dict]:
        """Alias for get_recent_restocks."""
        return self.get_recent_restocks(limit)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_to_csv(self, filepath: str) -> bool:
        """Exports the full products table to a CSV file."""
        try:
            products = self.get_all_products()
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["barcode", "name", "category", "quantity", "price", "expiry", "timestamp"]
                )
                writer.writeheader()
                writer.writerows(products)
            return True
        except Exception as e:
            print(f"[DB] Export error: {e}")
            return False

    # ------------------------------------------------------------------
    # Staff — Read & Write
    # ------------------------------------------------------------------

    def get_all_staff(self) -> list[dict]:
        """Returns all staff sorted alphabetically by name."""
        sql = "SELECT id, name, phone, status, role, salary, timestamp FROM staff ORDER BY name ASC;"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def search_staff(self, query: str) -> list[dict]:
        """Case-insensitive filter by name, phone, or role."""
        pattern = f"%{query}%"
        sql = """
            SELECT id, name, phone, status, role, salary, timestamp
            FROM staff
            WHERE name LIKE ? OR phone LIKE ? OR role LIKE ?
            ORDER BY name ASC;
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (pattern, pattern, pattern)).fetchall()]

    def add_staff(self, name: str, phone: str = "", status: str = "Active", role: str = "Staff", salary: float = 0.0) -> bool:
        """Inserts a new staff record."""
        sql = """
            INSERT INTO staff (name, phone, status, role, salary, timestamp)
            VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%S','now','localtime'));
        """
        try:
            with self._connect() as conn:
                conn.execute(sql, (name.strip(), phone.strip(), status.strip(), role.strip(), float(salary)))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error adding staff: {e}")
            return False

    def update_staff(self, sid: int, name: str, phone: str = "", status: str = "Active", role: str = "Staff", salary: float = 0.0) -> bool:
        """Updates an existing staff record."""
        sql = """
            UPDATE staff
            SET name=?, phone=?, status=?, role=?, salary=?,
                timestamp=strftime('%Y-%m-%d %H:%M:%S','now','localtime')
            WHERE id=?;
        """
        try:
            with self._connect() as conn:
                cur = conn.execute(sql, (name.strip(), phone.strip(), status.strip(), role.strip(), float(salary), int(sid)))
                conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            print(f"[DB] Error updating staff: {e}")
            return False

    def delete_staff(self, sid: int) -> bool:
        """Permanently removes a staff record."""
        try:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM staff WHERE id=?;", (int(sid),))
                conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            print(f"[DB] Error deleting staff: {e}")
            return False

    # ------------------------------------------------------------------
    # User Accounts (RBAC) — Read & Write
    # ------------------------------------------------------------------

    def authenticate_user(self, username: str, password: str) -> Optional[str]:
        """Verifies credentials. Returns 'Custom' if valid, else None."""
        sql = "SELECT password_hash, role_id FROM users WHERE username = ? AND status = 'Active';"
        with self._connect() as conn:
            row = conn.execute(sql, (username.strip().lower(),)).fetchone()
            if row:
                phash = row["password_hash"]
                if bcrypt.checkpw(password.encode('utf-8'), phash.encode('utf-8')):
                    r_id = row["role_id"]
                    if r_id:
                        r_name = conn.execute("SELECT name FROM roles WHERE id=?", (r_id,)).fetchone()
                        return r_name["name"] if r_name else "Custom"
                    return "Custom"
            return None

    def get_all_users(self) -> list[dict]:
        """Returns all login accounts and their permissions."""
        sql = '''
            SELECT username
            FROM users
            ORDER BY username ASC;
        '''
        with self._connect() as conn:
            users = [dict(r) for r in conn.execute(sql).fetchall()]
            for u in users:
                perms = conn.execute("SELECT permission_name FROM user_permissions WHERE username=?", (u["username"],)).fetchall()
                u["permissions"] = [p["permission_name"] for p in perms]
                u["role"] = "Custom" # For UI compatibility if needed temporarily
            return users

    def add_user(self, username: str, password: str, permissions: list) -> bool:
        """Adds a new user account with specific permissions."""
        try:
            uname = username.strip().lower()
            phash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            with self._connect() as conn:
                conn.execute("INSERT INTO users (username, password_hash, role_id) VALUES (?, ?, NULL);", 
                             (uname, phash))
                for p in permissions:
                    conn.execute("INSERT INTO user_permissions (username, permission_name) VALUES (?, ?)", (uname, p))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error adding user: {e}")
            return False

    def update_user(self, username: str, new_password: str | None, permissions: list) -> bool:
        """Updates an existing user account's permissions and optionally password."""
        try:
            uname = username.strip().lower()
            with self._connect() as conn:
                if new_password:
                    phash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?;",
                                 (phash, uname))
                
                # Replace permissions
                conn.execute("DELETE FROM user_permissions WHERE username = ?", (uname,))
                for p in permissions:
                    conn.execute("INSERT INTO user_permissions (username, permission_name) VALUES (?, ?)", (uname, p))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error updating user: {e}")
            return False

    def update_own_password(self, username: str, new_password: str) -> bool:
        """Allows a user to securely update their own password."""
        try:
            phash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            with self._connect() as conn:
                conn.execute("UPDATE users SET password_hash = ? WHERE username = ?;",
                             (phash, username.strip().lower()))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error updating own password: {e}")
            return False

    def delete_user(self, username: str) -> bool:
        """Deletes an existing user account."""
        sql1 = "DELETE FROM users WHERE username = ?;"
        sql2 = "DELETE FROM user_permissions WHERE username = ?;"
        try:
            uname = username.strip().lower()
            with self._connect() as conn:
                conn.execute(sql1, (uname,))
                conn.execute(sql2, (uname,))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error deleting user: {e}")
            return False

    def process_refund(self, barcode: str, qty_returned: int) -> tuple[bool, Optional[dict]]:
        """
        Increases stock for a returned item and logs the refund event.
        Returns (success_boolean, updated_product_dict).
        """
        if qty_returned <= 0:
            return False, None

        status, product = self.update_stock(barcode.strip(), qty_returned)
        if status == "ok" and product:
            self.log_restock(product["barcode"], product["name"], qty_returned, product["quantity"])
            return True, product
        return False, None

    # ------------------------------------------------------------------
    # Settings (Key-Value Configuration)
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        """Retrieves a configuration value."""
        sql = "SELECT value FROM settings WHERE key = ?;"
        with self._connect() as conn:
            row = conn.execute(sql, (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str, category: str = "General") -> bool:
        """Sets a configuration value."""
        sql = '''
            INSERT INTO settings (key, value, category) 
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, category = excluded.category;
        '''
        try:
            with self._connect() as conn:
                conn.execute(sql, (key, value, category))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error setting configuration: {e}")
            return False
