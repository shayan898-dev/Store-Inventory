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
                    expiry    TEXT DEFAULT 'N/A',
                    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
                );
            """)

            # ---- Sales log table ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sales_log (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode       TEXT NOT NULL,
                    name          TEXT NOT NULL,
                    quantity_sold INTEGER NOT NULL,
                    remaining_qty INTEGER NOT NULL,
                    timestamp     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
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

            # ---- Users table ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT NOT NULL,
                    role     TEXT NOT NULL CHECK(role IN ('admin', 'staff'))
                );
            """)

            # Seed default users if empty
            cur = conn.execute("SELECT COUNT(*) FROM users;")
            if cur.fetchone()[0] == 0:
                conn.execute("INSERT INTO users (username, password, role) VALUES ('admin', 'admin', 'admin');")
                conn.execute("INSERT INTO users (username, password, role) VALUES ('staff', 'staff', 'staff');")

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
                    quantity: int, price: float, expiry: str = "N/A", user_role: str = "staff") -> bool:
        """
        Inserts a new product.
        Returns True on success, False if barcode already exists.
        """
        if user_role != "admin":
            print("[DB] Access Denied: only admins can add products.")
            return False
        sql = """
            INSERT INTO products (barcode, name, category, quantity, price, expiry, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%S','now','localtime'));
        """
        try:
            with self._connect() as conn:
                conn.execute(sql, (barcode.strip(), name.strip(), category.strip(),
                                   int(quantity), float(price), expiry.strip()))
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False   # Duplicate barcode

    def update_product(self, barcode: str, name: str, category: str,
                       quantity: int, price: float, expiry: str = "N/A", user_role: str = "staff") -> bool:
        """Updates an existing product. Returns True if a row was changed."""
        if user_role != "admin":
            print("[DB] Access Denied: only admins can update products.")
            return False
        sql = """
            UPDATE products
            SET name=?, category=?, quantity=?, price=?, expiry=?,
                timestamp=strftime('%Y-%m-%d %H:%M:%S','now','localtime')
            WHERE barcode=?;
        """
        with self._connect() as conn:
            cur = conn.execute(sql, (name.strip(), category.strip(),
                                     int(quantity), float(price), expiry.strip(), barcode.strip()))
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
                if new_qty == 0:
                    conn.execute("DELETE FROM products WHERE barcode=?;", (barcode.strip(),))
                else:
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
    # Logs — Write
    # ------------------------------------------------------------------

    def log_sale(self, barcode: str, name: str, quantity_sold: int, remaining_qty: int):
        """
        Records a sale event.
        Automatically prunes the table to keep only the last LOG_LIMIT rows.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sales_log (barcode, name, quantity_sold, remaining_qty) "
                "VALUES (?, ?, ?, ?);",
                (barcode, name, quantity_sold, remaining_qty)
            )
            # Keep only the most recent LOG_LIMIT records
            conn.execute(
                "DELETE FROM sales_log WHERE id NOT IN "
                "(SELECT id FROM sales_log ORDER BY id DESC LIMIT ?);",
                (self.LOG_LIMIT,)
            )
            conn.commit()

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
        """Verifies credentials. Returns the user's role ('admin' or 'staff') if valid, else None."""
        sql = "SELECT role FROM users WHERE username = ? AND password = ?;"
        with self._connect() as conn:
            row = conn.execute(sql, (username.strip().lower(), password.strip())).fetchone()
            return row["role"] if row else None

    def get_all_users(self) -> list[dict]:
        """Returns all login accounts sorted alphabetically."""
        sql = "SELECT username, role FROM users ORDER BY username ASC;"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def add_user(self, username: str, password: str, role: str) -> bool:
        """Adds a new user account."""
        sql = "INSERT INTO users (username, password, role) VALUES (?, ?, ?);"
        try:
            with self._connect() as conn:
                conn.execute(sql, (username.strip().lower(), password.strip(), role.strip().lower()))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error adding user: {e}")
            return False

    def delete_user(self, username: str) -> bool:
        """Deletes an existing user account."""
        sql = "DELETE FROM users WHERE username = ?;"
        try:
            with self._connect() as conn:
                conn.execute(sql, (username.strip().lower(),))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error deleting user: {e}")
            return False
