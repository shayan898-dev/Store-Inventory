# Store Inventory Management System (Client-Server Architecture)

A multi-terminal desktop Inventory & POS (Point of Sale) system built with **Python (CustomTkinter)** and backed by a centralized **Node.js (Express) + MySQL** server.

---

## 🏗 System Architecture

- **Backend Server (`server/`)**: Node.js + Express + MySQL REST API managing inventory counts, atomic transactions, bill approvals, and stock deductions.
- **Manager Application (`main.py`)**: Full admin dashboard for inventory management, approvals, analytics, and stock adjustments.
- **Staff Cashier Terminal (`staff_main.py`)**: Fast barcode scanning, bill creation, and returns processing for point-of-sale cashiers.
- **Configuration (`config.json`)**: Configures client connection endpoints to the backend API.

---

## 💻 Setup on Another System (Step-by-Step)

Follow these steps whenever you download or clone this project onto a new computer:

### 1. Prerequisites
Make sure the following tools are installed:
- **Git**
- **Python 3.10+** (Tested on Python 3.10 - 3.14)
- **Node.js 18+** & `npm`
- **MySQL Server** (e.g. MySQL Community Server or XAMPP)

---

### 2. Clone the Repository
```bash
git clone https://github.com/shayan898-dev/Store-Inventory.git
cd Store-Inventory
git checkout server-client
```

---

### 3. Setup MySQL Database
1. Open your MySQL client (Command Line, MySQL Workbench, or phpMyAdmin).
2. Execute the schema script located in the repository root:
   ```bash
   mysql -u root -p < store_inventory_schema.sql
   ```
   *(Or open `store_inventory_schema.sql` and run its contents in MySQL Workbench).*

---

### 4. Setup & Start the Central Backend Server
1. Navigate into the `server` folder:
   ```bash
   cd server
   ```
2. Install Node dependencies (this installs fresh, OS-compatible binaries):
   ```bash
   npm install
   ```
3. *(Optional)* If your MySQL user or password is not default, set environment variables or edit `server/server.js`:
   ```bash
   # Optional: default password is '#170I@MHUM@N' on localhost
   set DB_HOST=localhost
   set DB_USER=root
   set DB_PASSWORD=your_password
   set DB_NAME=store_inventory
   ```
4. *(Optional — First Time Migration)* If you have products in an existing `inventory.db` SQLite file that you want to migrate into MySQL:
   ```bash
   node migrate_to_mysql.js
   ```
5. Start the server:
   ```bash
   node server.js
   ```
   *The server will start listening at `http://localhost:3000`.*

---

### 5. Setup the Python Client Environment
Open a **new terminal window** in the project root directory:

1. Create and activate a Python virtual environment:
   - **Windows:**
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\activate
     ```
   - **macOS / Linux:**
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

### 6. Run the Applications

Ensure `config.json` points to your backend server URL (default: `http://127.0.0.1:3000`). If running the client on a different computer in the same local network (LAN), change `127.0.0.1` to the server computer's LAN IP (e.g. `http://192.168.1.50:3000`).

- **To run the Manager / Admin App:**
  ```bash
  python main.py
  ```

- **To run the Staff POS Terminal:**
  ```bash
  python staff_main.py
  ```

---

## 🛠 Standalone Executable Build (Optional)
To build a standalone `.exe` using PyInstaller:
```bash
python build_app.py
```
Or:
```bash
pyinstaller InventoryManager.spec
```
