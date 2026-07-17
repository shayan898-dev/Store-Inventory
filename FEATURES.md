# Store Inventory Pro - Feature Documentation

Welcome to the documentation for **Store Inventory Pro**. This document details all of the primary features, recent updates, and database layouts of the application.

---

## Table of Contents
1. [Core Features & Views](#1-core-features--views)
   - [Inventory Management](#inventory-management)
   - [Sales Checkout](#sales-checkout)
   - [Restock Logs](#restock-logs)
   - [Business Reports](#business-reports)
   - [Staff Management (New)](#staff-management-new)
2. [Expiry Date Tracking System](#2-expiry-date-tracking-system)
   - [Multi-Dropdown Date Selector](#multi-dropdown-date-selector)
   - [Smart Month-Name Mapping & Number Clamping](#smart-month-name-mapping--number-clamping)
   - [Auto-Formatting Days](#auto-formatting-days)
3. [Visual Layout & Alignments](#3-visual-layout--alignments)
   - [Reordered Columns](#reordered-columns)
   - [Center Alignment](#center-alignment)
4. [Database & System Architecture](#4-database--system-architecture)
   - [Automatic SQLite Migrations](#automatic-sqlite-migrations)
   - [Removed Mobile Bridge Backend](#removed-mobile-bridge-backend)

---

## 1. Core Features & Views

The application navigation sidebar includes five main sections:

### 📦 Inventory Management
- **Description**: Displays a table of all products in your store.
- **Key Functions**:
  - Add, edit, or delete products.
  - Track stock quantity and product prices.
  - Automatically flags **Low Stock** items in orange when the quantity is less than 5.
  - Search filter to instantly search by Product Name, Barcode, or Category.
  - Export the current inventory table directly to a CSV file.

### 🛒 Sales Checkout
- **Description**: The billing screen where transactions are registered.
- **Key Functions**:
  - Focuses automatically on the Barcode field for easy barcode scanning.
  - Search and select items to add to the cart.
  - Set quantities and review total checkout price.
  - Complete sales to automatically update inventory levels.

### 📥 Restock Logs
- **Description**: Logs every restock action to trace when items were added to the inventory.
- **Key Functions**:
  - Displays the transaction log showing barcode, item name, quantity added, remaining quantity, and timestamp.

### 📊 Business Reports
- **Description**: Visual dashboards to check your shop's performance.
- **Key Functions**:
  - Displays sales logs.
  - Generates revenue statistics, transaction histories, and graphical logs.

### 👥 Staff Management (New)
- **Description**: A dedicated view to register and track employees.
- **Key Functions**:
  - **Add / Edit / Delete Staff**: Record Name, Phone Number, Role (Staff, Manager, Cashier, Owner), and Working Status.
  - **Working Status**: Easily toggle and track who is currently `"Working"` or `"Not Working"`.
  - **Live Counters**: The status bar at the bottom displays real-time metrics, showing the total number of staff and how many are currently on shift.
  - **Search**: Case-insensitive filter to find staff members by name, phone number, or role.

---

## 2. Expiry Date Tracking System

To prevent selling expired goods, a dedicated tracking system is built directly into the Product Dialog:

### Multi-Dropdown Date Selector
- Instead of typing dates manually, you can select the Day (`01`-`31`), Month (`Jan`-`Dec`), and Year (from the current year up to 15 years in the future) using three adjacent dropdown menus.
- The dropdowns are editable, meaning you can type your date elements manually or select them from the dropdown list.
- If a product does not have an expiry date, typing `"N/A"` or leaving fields blank will save it as `"N/A"`.

### Smart Month-Name Mapping & Number Clamping
- When typing numbers in the Month field:
  - Entering **0 or below** automatically maps to `Jan`.
  - Entering a number **greater than 12** automatically maps to `Dec`.
  - Entering a number **between 1 and 12** maps to its corresponding month name (e.g. typing `5` maps to `May`, typing `10` maps to `Oct`).
  - Prefix matching is supported: typing full names (like `January` or `jan`) correctly maps to `Jan` (saved as `01`).

### Auto-Formatting Days
- If a single digit is manually entered in the Day field (e.g., `5`), it is automatically formatted as `05` on save to ensure uniform date structures (`YYYY-MM-DD`).

---

## 3. Visual Layout & Alignments

The tables have been refactored for readability:

### Reordered Columns
- The primary Inventory table has been re-arranged:
  1. **Product Name** is placed on the far left (first text column) so you can read it instantly.
  2. **Barcode** is placed on the far right.
  3. **Expiry Date** is inserted between Price and Barcode.

### Center Alignment
- All columns and headings in the Inventory and Staff tables are fully **center-aligned** (`anchor="center"`) for a clean, professional, and consistent layout.

---

## 4. Database & System Architecture

### Automatic SQLite Migrations
- The application automatically connects to a local SQLite database.
- It includes automatic schema migration logic. When the app is launched, it checks the database structure:
  - Creates the `staff` table if it doesn't exist.
  - Alters the `products` table to append the `expiry` column (defaulting to `"N/A"`) without losing any of your existing products.

### Removed Mobile Bridge Backend
- Removed the Flask and QR Code server modules to streamline performance. The app runs completely locally on your system, avoiding potential port conflicts or LAN network issues.
