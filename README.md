# Inventory Manager Pro

A lightweight, offline-first desktop inventory management application built with Python and CustomTkinter.  
Data is stored locally in a SQLite database — **no internet connection or cloud account required**.

---

## Features

| Area | Details |
|---|---|
| **Inventory** | Add, edit, and delete products; barcode + name + category + qty + price; bulk-select with tick-boxes; CSV export; live search |
| **Sales Mode** | High-speed barcode scanning checkout; auto-clears field after each scan; live product card; colour-coded transaction log |
| **Restock Mode** | Scan a barcode → quantity dialog → stock updated immediately; persistent restock log |
| **Reports** | Summary stats cards (total products, total items, inventory value, low-stock alerts); scrollable low-stock list |
| **Persistence** | SQLite via `database_manager.py`; WAL mode; thread-safe writes; auto schema migration for older databases |
| **Packaging** | One-click PyInstaller build (`python build_app.py`) → single `.exe`, no Python needed on target machine |

---

## Screenshots

> The application uses a GitHub-inspired dark theme (CustomTkinter).

```
┌──────────┬───────────────────────────────────┐
│  SIDEBAR │  CONTENT (one view at a time)     │
│          │                                   │
│ 📦 Inv.  │  Active view renders here         │
│ 🛒 Sales │                                   │
│ 📥 Rest. │                                   │
│ 📊 Rep.  │                                   │
└──────────┴───────────────────────────────────┘
```

---

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

```
customtkinter>=5.2.0    # Modern dark-themed Tkinter widgets
Pillow>=10.0.0          # Image support (optional)
pyinstaller>=6.0.0      # Build to .exe (optional)
```

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/shayan898-dev/Store-Inventory.git
cd Store-Inventory

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the application
python main.py
```

The SQLite database (`inventory.db`) is created automatically next to `main.py` on first launch.

---

## Building a Standalone Executable (Windows)

```bash
python build_app.py
```

This uses PyInstaller to produce `dist/InventoryManager.exe`.  
Copy the `.exe` anywhere — no Python installation needed on the target machine.  
`inventory.db` is created next to the `.exe` on first run.

---

## Project Structure

```
Store-Inventory/
├── main.py               # GUI application (CustomTkinter)
├── database_manager.py   # All SQLite operations
├── build_app.py          # PyInstaller build helper
├── requirements.txt      # Python dependencies
└── InventoryManager.spec # PyInstaller spec (auto-generated)
```

---

## Database Schema

```sql
-- Master product catalogue
CREATE TABLE products (
    barcode   TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL DEFAULT 'General',
    quantity  INTEGER NOT NULL DEFAULT 0,
    price     REAL NOT NULL DEFAULT 0.0,
    timestamp TEXT NOT NULL
);

-- Last 50 sale events
CREATE TABLE sales_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode       TEXT NOT NULL,
    name          TEXT NOT NULL,
    quantity_sold INTEGER NOT NULL,
    remaining_qty INTEGER NOT NULL,
    timestamp     TEXT NOT NULL
);

-- Last 50 restock events
CREATE TABLE restock_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode        TEXT NOT NULL,
    name           TEXT NOT NULL,
    quantity_added INTEGER NOT NULL,
    remaining_qty  INTEGER NOT NULL,
    timestamp      TEXT NOT NULL
);
```

---

## Key Design Decisions

- **Thread-safe writes** — `DatabaseManager` uses `threading.Lock` around all stock mutations to prevent race conditions when a barcode scanner fires multiple events rapidly.
- **Ghost Focus loop** — In Sales and Restock views a 500 ms timer continuously returns keyboard focus to the barcode entry field, allowing 50+ items to be scanned without touching the mouse.
- **Schema migration** — `_migrate()` adds new columns to existing databases without data loss, making updates backward-compatible.
- **Barcode sanitisation** — `_sanitise_barcode()` strips control characters and non-ASCII bytes that some HID barcode adapters inject.

---

## License

This project is provided as-is for personal and educational use.
