"""
main.py
-------
Inventory Manager Pro — Main Application (v2)

New in v2:
  • Category field on all products (dropdown + custom entry)
  • Persistent sales_log & restock_log loaded from SQLite on view open
  • Category column in Inventory treeview
  • Schema auto-migration (safe for existing databases)

Launch:   python main.py
Build:    python build_app.py
"""

import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
import threading
import socket
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string
import qrcode

from database_manager import DatabaseManager


# ---------------------------------------------------------------------------
# Global theme setup
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ---- Colour palette (GitHub-inspired dark) ----
C_BG         = "#0F1117"
C_SIDEBAR    = "#161B22"
C_CARD       = "#1C2128"
C_CARD2      = "#21262D"
C_ACCENT     = "#2F81F7"
C_ACCENT_HVR = "#388BFD"
C_SUCCESS    = "#3FB950"
C_WARNING    = "#D29922"
C_DANGER     = "#F85149"
C_TEXT       = "#E6EDF3"
C_TEXT_DIM   = "#8B949E"
C_BORDER     = "#30363D"
C_ROW_LOW    = "#2D1F00"
C_ROW_NORMAL = "#1C2128"

FONT         = "Segoe UI"

# Treeview columns (check column is the tick-box selector)
TV_COLS = ("check", "barcode", "name", "category", "quantity", "price")

# Preset categories for the dropdown
CATEGORIES = [
    "General", "Food & Beverage", "Dairy", "Bakery", "Snacks",
    "Beverages", "Household", "Personal Care", "Electronics", "Clothing",
]

MOBILE_BRIDGE_PORT = 5000


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def format_price(v: float) -> str:
    return f"PKR {v:,.2f}"


def play_beep(success: bool = True):
    """
    Audio feedback — calibrated for Barcode2win / HID scanners.
      Success : 1 000 Hz for 150 ms  (short, pleasant blip)
      Failure :   400 Hz for 400 ms  (low, unmistakable buzz)
    Falls back to terminal bell on non-Windows platforms.
    """
    try:
        import winsound
        if success:
            winsound.Beep(1000, 150)   # spec: 1kHz / 150ms
        else:
            winsound.Beep(400,  400)   # spec: 400Hz / 400ms
    except Exception:
        print("\a", end="", flush=True)


def ts_now() -> str:
    return datetime.now().strftime("%H:%M:%S")

import re as _re

def _sanitise_barcode(raw: str) -> str:
    """
    Strip whitespace and any hidden / control characters that
    Barcode2win or wireless HID adapters may append to the code.
    Keeps only printable ASCII (letters, digits, hyphens, dots).
    """
    cleaned = raw.strip()
    # Remove all non-printable and non-ASCII characters
    cleaned = _re.sub(r'[^\x20-\x7E]', '', cleaned)
    # Strip any remaining leading/trailing spaces
    return cleaned.strip()
# ---------------------------------------------------------------------------

class SidebarButton(ctk.CTkButton):
    def __init__(self, master, text, icon="", **kwargs):
        super().__init__(
            master,
            text=f"  {icon}  {text}",
            anchor="w",
            height=44,
            corner_radius=8,
            fg_color="transparent",
            hover_color=C_CARD2,
            text_color=C_TEXT_DIM,
            font=(FONT, 13),
            **kwargs,
        )

    def set_active(self, active: bool):
        self.configure(
            fg_color=C_ACCENT if active else "transparent",
            text_color=C_TEXT if active else C_TEXT_DIM,
        )


class StatCard(ctk.CTkFrame):
    def __init__(self, master, title, value, icon, color=C_ACCENT, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=12,
                         border_width=1, border_color=C_BORDER, **kwargs)
        ctk.CTkLabel(self, text=icon, font=(FONT, 26)).pack(anchor="w", padx=20, pady=(18, 2))
        self.val = ctk.CTkLabel(self, text=str(value), font=(FONT, 28, "bold"), text_color=color)
        self.val.pack(anchor="w", padx=20)
        ctk.CTkLabel(self, text=title, font=(FONT, 11), text_color=C_TEXT_DIM).pack(
            anchor="w", padx=20, pady=(2, 18)
        )

    def update(self, value):
        self.val.configure(text=str(value))


class FlashEntry(ctk.CTkEntry):
    """Barcode entry that flashes a colour for a precise duration then reverts."""

    # Revert colour — grey when idle (high-contrast spec: subtle grey)
    IDLE_BORDER = C_BORDER

    def flash(self, success: bool):
        """Legacy helper used by Restock view."""
        color = "#28a745" if success else "#dc3545"
        ms    = 400       if success else 600
        self.flash_custom(color, ms)

    def flash_custom(self, color: str, duration_ms: int):
        """Flash border to `color` for exactly `duration_ms` milliseconds."""
        self.configure(border_color=color, border_width=2)
        self.after(duration_ms,
                   lambda: self.configure(border_color=self.IDLE_BORDER, border_width=2))


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------



class ProductDialog(ctk.CTkToplevel):
    """
    Modal dialog for Add / Edit product.
    Result is stored in self.result dict (or None if cancelled).
    """

    def __init__(self, parent, title="Add Product", product: dict = None,
                 categories: list = None):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.geometry("440x580")
        self.resizable(False, False)
        self.configure(fg_color=C_CARD)
        self.grab_set()
        self.focus_set()

        cats = categories or CATEGORIES

        # Title label
        ctk.CTkLabel(self, text=title, font=(FONT, 18, "bold")).pack(pady=(24, 14))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=32)

        def _lbl(text):
            ctk.CTkLabel(form, text=text, font=(FONT, 12),
                         text_color=C_TEXT_DIM, anchor="w").pack(fill="x", pady=(8, 2))

        # ---- Barcode ----
        _lbl("Barcode *")
        bc_row = ctk.CTkFrame(form, fg_color="transparent")
        bc_row.pack(fill="x")
        self.e_barcode = ctk.CTkEntry(bc_row, height=38, font=(FONT, 13),
                                       fg_color=C_CARD2, border_color=C_BORDER)
        self.e_barcode.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # ---- Name ----
        _lbl("Product Name *")
        self.e_name = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                    fg_color=C_CARD2, border_color=C_BORDER)
        self.e_name.pack(fill="x")

        # ---- Category (combo box) ----
        _lbl("Category")
        self.e_category = ctk.CTkComboBox(
            form, values=cats, height=38, font=(FONT, 13),
            fg_color=C_CARD2, border_color=C_BORDER,
            button_color=C_CARD2, button_hover_color=C_BORDER,
            dropdown_fg_color=C_CARD2,
        )
        self.e_category.set(cats[0])
        self.e_category.pack(fill="x")

        # ---- Quantity ----
        _lbl("Quantity *")
        self.e_qty = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                   fg_color=C_CARD2, border_color=C_BORDER)
        self.e_qty.pack(fill="x")

        # ---- Price ----
        _lbl("Price (PKR) *")
        self.e_price = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                     fg_color=C_CARD2, border_color=C_BORDER)
        self.e_price.pack(fill="x")

        # Pre-fill when editing
        self._is_edit = bool(product)
        if product:
            self.e_barcode.insert(0, product.get("barcode", ""))
            self.e_barcode.configure(state="disabled")   # PK — immutable
            self.e_name.insert(0, product.get("name", ""))
            cat = product.get("category", "General")
            if cat not in cats:
                cats.insert(0, cat)
                self.e_category.configure(values=cats)
            self.e_category.set(cat)
            self.e_qty.insert(0, str(product.get("quantity", 0)))
            self.e_price.insert(0, str(product.get("price", 0.0)))

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=32, pady=22)
        ctk.CTkButton(btn_row, text="Cancel", fg_color=C_CARD2,
                      hover_color=C_BORDER, command=self.destroy, width=120).pack(side="left")
        ctk.CTkButton(btn_row, text="Save", fg_color=C_ACCENT,
                      hover_color=C_ACCENT_HVR, command=self._save, width=120).pack(side="right")

        if not self._is_edit:
            self.e_barcode.focus_set()
        self.bind("<Return>", lambda e: self._save())

    # ----------------------------------------------------------------

    def _scan_b2w(self):
        self.e_barcode.focus_set()
        self.e_barcode.configure(border_color=C_SUCCESS)
        self.after(500, lambda: self.e_barcode.configure(border_color=C_BORDER))

    def _save(self):
        barcode   = self.e_barcode.get().strip()
        name      = self.e_name.get().strip()
        category  = self.e_category.get().strip() or "General"
        qty_raw   = self.e_qty.get().strip()
        price_raw = self.e_price.get().strip()

        if not barcode or not name:
            messagebox.showerror("Required Fields", "Barcode and Product Name are required.", parent=self)
            return
        try:
            qty = int(qty_raw)
            assert qty >= 0
        except (ValueError, AssertionError):
            messagebox.showerror("Invalid Quantity", "Quantity must be a whole number ≥ 0.", parent=self)
            return
        try:
            price = float(price_raw)
            assert price >= 0
        except (ValueError, AssertionError):
            messagebox.showerror("Invalid Price", "Price must be a number ≥ 0.", parent=self)
            return

        self.result = {"barcode": barcode, "name": name, "category": category,
                       "quantity": qty, "price": price}
        self.destroy()


class RestockQtyDialog(ctk.CTkToplevel):
    """Small modal asking how many units to restock."""

    def __init__(self, parent, product: dict):
        super().__init__(parent)
        self.result = None
        self.title("Restock Quantity")
        self.geometry("320x230")
        self.resizable(False, False)
        self.configure(fg_color=C_CARD)
        self.grab_set()
        self.focus_set()

        ctk.CTkLabel(self, text="📦  Restocking", font=(FONT, 16, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(self, text=product["name"], font=(FONT, 13),
                     text_color=C_TEXT_DIM).pack(pady=(0, 14))

        frm = ctk.CTkFrame(self, fg_color="transparent")
        frm.pack(fill="x", padx=32)
        ctk.CTkLabel(frm, text="Units to add:", font=(FONT, 12),
                     text_color=C_TEXT_DIM, anchor="w").pack(fill="x")
        self.qty_entry = ctk.CTkEntry(frm, height=40, font=(FONT, 16, "bold"),
                                       fg_color=C_CARD2, border_color=C_ACCENT,
                                       justify="center")
        self.qty_entry.insert(0, "1")
        self.qty_entry.pack(fill="x", pady=4)
        self.qty_entry.focus_set()
        self.qty_entry.select_range(0, "end")

        ctk.CTkButton(self, text="✔  Confirm", fg_color=C_SUCCESS,
                      hover_color="#2EA043", font=(FONT, 13, "bold"),
                      command=self._confirm).pack(pady=16, padx=32, fill="x")
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self):
        try:
            qty_str = self.qty_entry.get().strip()
            if len(qty_str) > 4:
                messagebox.showerror("Invalid", "Scanning is paused until quantity is set.", parent=self)
                self.qty_entry.delete(0, "end")
                self.qty_entry.insert(0, "1")
                self.qty_entry.focus_set()
                self.qty_entry.select_range(0, "end")
                return
            qty = int(qty_str)
            assert qty > 0
            self.result = qty
            self.destroy()
        except (ValueError, AssertionError):
            messagebox.showerror("Invalid", "Enter a positive whole number.", parent=self)

class SaleQtyDialog(ctk.CTkToplevel):
    """Small modal asking how many units to add to the bill."""

    def __init__(self, parent, product: dict, max_qty: int):
        super().__init__(parent)
        self.result = None
        self.title("Add to Bill")
        self.geometry("320x230")
        self.resizable(False, False)
        self.configure(fg_color=C_CARD)
        
        self.update_idletasks()
        try:
            x = parent.winfo_x() + (parent.winfo_width() // 2) - 160
            y = parent.winfo_y() + (parent.winfo_height() // 2) - 115
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self.grab_set()
        self.focus_set()
        self.max_qty = max_qty

        ctk.CTkLabel(self, text="🛒  Add to Bill", font=(FONT, 16, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(self, text=product["name"], font=(FONT, 13),
                     text_color=C_TEXT_DIM).pack(pady=(0, 14))

        frm = ctk.CTkFrame(self, fg_color="transparent")
        frm.pack(fill="x", padx=32)
        ctk.CTkLabel(frm, text=f"Quantity (max {max_qty}):", font=(FONT, 12),
                     text_color=C_TEXT_DIM, anchor="w").pack(fill="x")
        self.qty_entry = ctk.CTkEntry(frm, height=40, font=(FONT, 16, "bold"),
                                       fg_color=C_CARD2, border_color=C_ACCENT,
                                       justify="center")
        self.qty_entry.insert(0, "1")
        self.qty_entry.pack(fill="x", pady=4)
        self.qty_entry.focus_set()
        self.qty_entry.select_range(0, "end")

        ctk.CTkButton(self, text="✔  Add", fg_color=C_SUCCESS,
                      hover_color="#2EA043", font=(FONT, 13, "bold"),
                      command=self._confirm).pack(pady=16, padx=32, fill="x")
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self):
        try:
            qty_str = self.qty_entry.get().strip()
            if len(qty_str) > 4:
                messagebox.showerror("Invalid", "Scanning is paused until quantity is set.", parent=self)
                self.qty_entry.delete(0, "end")
                self.qty_entry.insert(0, "1")
                self.qty_entry.focus_set()
                self.qty_entry.select_range(0, "end")
                return
            qty = int(qty_str)
            assert qty > 0
            if qty > self.max_qty:
                messagebox.showerror("Insufficient Stock", f"Only {self.max_qty} units available.", parent=self)
                return
            self.result = qty
            self.destroy()
        except (ValueError, AssertionError):
            messagebox.showerror("Invalid", "Enter a positive whole number.", parent=self)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class InventoryApp(ctk.CTk):
    """
    Root window.

    Layout:
        ┌──────────┬───────────────────────────────────┐
        │  SIDEBAR │  CONTENT (one view at a time)     │
        └──────────┴───────────────────────────────────┘
    """

    def __init__(self):
        super().__init__()
        self.db = DatabaseManager()

        # Window
        self.title("Inventory Manager Pro")
        self.geometry("1260x780")
        self.minsize(980, 620)
        self.configure(fg_color=C_BG)

        # Try to set icon
        icon = self._asset("icon.ico")
        if os.path.exists(icon):
            self.iconbitmap(icon)

        # App state
        self._active_view: str | None  = None
        self._search_after: int | None = None
        self._checked_barcodes: set    = set()
        self._scan_focus_active: bool  = False
        self._mobile_bridge_port: int = MOBILE_BRIDGE_PORT
        self._mobile_bridge_host: str = "0.0.0.0"
        self._mobile_local_ip: str = self._get_local_ip()
        self._mobile_qr_image = None
        self._current_bill: dict = {}

        self._build_sidebar()
        self._build_content()
        self._apply_tree_style()
        self._start_mobile_bridge_server()

        self.show_view("inventory")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _asset(self, filename: str) -> str:
        base = sys._MEIPASS if getattr(sys, "frozen", False) \
               else os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "assets", filename)

    def _toast(self, msg: str, ms: int = 2800):
        lbl = ctk.CTkLabel(self, text=msg, font=(FONT, 13),
                            fg_color=C_CARD2, corner_radius=10,
                            text_color=C_TEXT, padx=20, pady=10)
        lbl.place(relx=0.5, rely=0.95, anchor="center")
        self.after(ms, lbl.destroy)

    def _get_local_ip(self) -> str:
        """Best-effort LAN IP detection for mobile QR link."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            sock.close()

    @property
    def _mobile_base_url(self) -> str:
        return f"http://{self._mobile_local_ip}:{self._mobile_bridge_port}"

    def _start_mobile_bridge_server(self):
        """Starts a lightweight Flask server in a daemon thread."""
        self._mobile_flask_app = Flask(__name__)

        @self._mobile_flask_app.get("/")
        def mobile_index():
            return render_template_string(self._mobile_scanner_html())

        @self._mobile_flask_app.post("/scan")
        def mobile_scan():
            payload = request.get_json(silent=True) or request.form
            barcode = _sanitise_barcode(str(payload.get("barcode", "")))
            if len(barcode) < 2:
                return jsonify({"ok": False, "error": "Invalid barcode"}), 400

            # Route to Tk main thread safely.
            self.after(0, lambda b=barcode: self._handle_mobile_scan(b))
            return jsonify({"ok": True, "barcode": barcode})

        @self._mobile_flask_app.get("/health")
        def mobile_health():
            return jsonify({"ok": True, "url": self._mobile_base_url})

        def _run_server():
            try:
                self._mobile_flask_app.run(
                    host=self._mobile_bridge_host,
                    port=self._mobile_bridge_port,
                    debug=False,
                    use_reloader=False,
                )
            except OSError as exc:
                print(f"[MobileBridge] Failed to start server: {exc}")

        self._mobile_thread = threading.Thread(
            target=_run_server,
            name="MobileScannerBridge",
            daemon=True,
        )
        self._mobile_thread.start()

    def _mobile_scanner_html(self) -> str:
        """Mobile-optimised barcode scanner page powered by ZXing."""
        return """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <title>Inventory Mobile Scanner</title>
    <style>
        :root {
            --bg: #0f172a;
            --panel: #1e293b;
            --text: #e2e8f0;
            --muted: #94a3b8;
            --ok: #22c55e;
            --warn: #f59e0b;
            --accent: #38bdf8;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            font-family: "Segoe UI", Tahoma, sans-serif;
            color: var(--text);
            background:
                radial-gradient(1200px 400px at 0% -10%, #1d4ed8 0%, transparent 55%),
                radial-gradient(1000px 300px at 100% 110%, #0ea5e9 0%, transparent 55%),
                var(--bg);
            padding: 16px;
        }
        .wrap {
            max-width: 560px;
            margin: 0 auto;
            display: grid;
            gap: 12px;
        }
        .card {
            background: color-mix(in srgb, var(--panel) 92%, black);
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 14px;
        }
        h1 {
            margin: 0 0 6px;
            font-size: 1.15rem;
            font-weight: 700;
        }
        p { margin: 0; color: var(--muted); line-height: 1.45; }
        video {
            width: 100%;
            border-radius: 12px;
            background: #000;
            border: 1px solid #475569;
        }
        .row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 10px;
        }
        button {
            border: 0;
            border-radius: 10px;
            padding: 10px 14px;
            color: #00111a;
            background: var(--accent);
            font-weight: 700;
        }
        .badge {
            margin-left: auto;
            font-size: 0.82rem;
            font-weight: 700;
            padding: 5px 10px;
            border-radius: 999px;
            background: #334155;
            color: var(--text);
        }
        .ok { background: #14532d; color: #86efac; }
        .warn { background: #78350f; color: #fcd34d; }
        code {
            display: block;
            margin-top: 8px;
            padding: 10px;
            background: #0b1220;
            border: 1px solid #334155;
            border-radius: 10px;
            color: #a5f3fc;
            overflow-wrap: anywhere;
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="card">
            <h1>Inventory Mobile Scanner</h1>
            <p>Point your camera at a barcode. Detected codes are sent instantly to the desktop app.</p>
            <code id="serverUrl"></code>
        </div>

        <div class="card">
            <video id="preview" playsinline></video>
            <div class="row">
                <button id="startBtn" type="button">Start Camera</button>
                <span id="stateBadge" class="badge warn">idle</span>
            </div>
            <p id="lastScan" style="margin-top:10px;">Last scan: none</p>
        </div>
    </div>

    <script src="https://unpkg.com/@zxing/library@0.20.0/umd/index.min.js"></script>
    <script>
        const baseUrl = window.location.origin;
        const preview = document.getElementById("preview");
        const startBtn = document.getElementById("startBtn");
        const stateBadge = document.getElementById("stateBadge");
        const lastScan = document.getElementById("lastScan");
        const serverUrl = document.getElementById("serverUrl");
        serverUrl.textContent = "Desktop bridge: " + baseUrl;

        const reader = new ZXing.BrowserMultiFormatReader();
        let lastSentCode = "";
        let lastSentAt = 0;

        const setState = (label, cls) => {
            stateBadge.textContent = label;
            stateBadge.className = "badge " + cls;
        };

        const sendScan = async (barcode) => {
            const now = Date.now();
            if (barcode === lastSentCode && (now - lastSentAt) < 1200) {
                return;
            }
            lastSentCode = barcode;
            lastSentAt = now;

            try {
                const response = await fetch(baseUrl + "/scan", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ barcode })
                });
                if (!response.ok) {
                    setState("send failed", "warn");
                    return;
                }
                if (navigator.vibrate) navigator.vibrate(80);
                lastScan.textContent = "Last scan: " + barcode;
                setState("sent", "ok");
            } catch (error) {
                setState("offline", "warn");
            }
        };

        const startScan = async () => {
            setState("starting", "warn");
            try {
                const devices = await ZXing.BrowserCodeReader.listVideoInputDevices();
                const preferred = devices.find((d) => /back|rear|environment/i.test(d.label));
                const deviceId = (preferred || devices[0])?.deviceId;
                await reader.decodeFromVideoDevice(deviceId, preview, (result) => {
                    if (!result) return;
                    const code = String(result.getText() || "").trim();
                    if (!code) return;
                    sendScan(code);
                });
                setState("scanning", "ok");
            } catch (error) {
                setState("camera blocked", "warn");
            }
        };

        startBtn.addEventListener("click", startScan);
    </script>
</body>
</html>
        """

    def _handle_mobile_scan(self, barcode: str):
        """Dispatch mobile scans into the active desktop workflow."""
        grab = self.grab_current()
        if grab and hasattr(grab, "qty_entry"):
            self._toast("Scanning is paused until quantity is set.", ms=2200)
            return
            
        if grab and hasattr(grab, "e_barcode") and str(grab.e_barcode.cget("state")) != "disabled":
            grab.e_barcode.delete(0, "end")
            grab.e_barcode.insert(0, barcode)
            grab.e_name.focus_set()
            return

        if self._active_view == "sales":
            self._process_sale(barcode=barcode)
        elif self._active_view == "restock":
            self._on_restock_scan(barcode=barcode)
        else:
            self._toast("Open Sales or Restock mode to accept mobile scans.", ms=2200)

    def _start_b2w_sale(self):
        self._sale_entry.focus_set()
        if hasattr(self, "_cam_status_sale") and self._cam_status_sale:
            self._cam_status_sale.configure(text="Ready for Barcode2win...", text_color=C_SUCCESS)
            self.after(4000, lambda: self._cam_status_sale.configure(text=""))

    def _start_b2w_restock(self):
        self._restock_entry.focus_set()
        if hasattr(self, "_cam_status_restock") and self._cam_status_restock:
            self._cam_status_restock.configure(text="Ready for Barcode2win...", text_color=C_SUCCESS)
            self.after(4000, lambda: self._cam_status_restock.configure(text=""))

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=224, fg_color=C_SIDEBAR, corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # Logo
        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(24, 8))
        ctk.CTkLabel(logo, text="🏪  InvManager", font=(FONT, 16, "bold"),
                     text_color=C_TEXT).pack(anchor="w")
        ctk.CTkLabel(logo, text="Inventory Pro  v2", font=(FONT, 10),
                     text_color=C_TEXT_DIM).pack(anchor="w")

        ctk.CTkFrame(sb, height=1, fg_color=C_BORDER).pack(fill="x", padx=16, pady=10)

        self._nav_btns: dict[str, SidebarButton] = {}
        for name, icon, label in [
            ("inventory", "📦", "Inventory"),
            ("sales",     "🛒", "Sales"),
            ("restock",   "📥", "Restock"),
            ("reports",   "📊", "Reports"),
        ]:
            btn = SidebarButton(sb, text=label, icon=icon,
                                command=lambda v=name: self.show_view(v))
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_btns[name] = btn

        ctk.CTkButton(
            sb,
            text="  📱  Mobile Link",
            anchor="w",
            height=42,
            corner_radius=8,
            fg_color=C_CARD,
            hover_color=C_CARD2,
            text_color=C_TEXT,
            font=(FONT, 13, "bold"),
            command=self._open_mobile_link_window,
        ).pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(sb, text="SQLite  •  Local Only", font=(FONT, 10),
                     text_color=C_TEXT_DIM).pack(side="bottom", pady=16)

    def _open_mobile_link_window(self):
        """Shows QR code and URL for connecting a phone scanner."""
        self._mobile_local_ip = self._get_local_ip()
        url = self._mobile_base_url

        win = ctk.CTkToplevel(self)
        win.title("Mobile Scanner Bridge")
        win.geometry("380x520")
        win.resizable(False, False)
        win.configure(fg_color=C_CARD)
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text="📱  Mobile Scanner Bridge",
            font=(FONT, 18, "bold"),
            text_color=C_TEXT,
        ).pack(pady=(22, 6))

        ctk.CTkLabel(
            win,
            text="Scan this QR code from your phone on the same Wi-Fi network.",
            font=(FONT, 12),
            text_color=C_TEXT_DIM,
            wraplength=320,
            justify="center",
        ).pack(padx=20, pady=(0, 12))

        qr_img = qrcode.make(url).convert("RGB")
        self._mobile_qr_image = ctk.CTkImage(light_image=qr_img, dark_image=qr_img, size=(240, 240))
        ctk.CTkLabel(win, text="", image=self._mobile_qr_image).pack(pady=(6, 10))

        url_entry = ctk.CTkEntry(
            win,
            height=38,
            font=(FONT, 12),
            fg_color=C_CARD2,
            border_color=C_BORDER,
            justify="center",
        )
        url_entry.insert(0, url)
        url_entry.configure(state="readonly")
        url_entry.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(
            win,
            text="Tip: Keep desktop on Sales or Restock view while scanning.",
            font=(FONT, 11),
            text_color=C_TEXT_DIM,
        ).pack(pady=(0, 16))

        ctk.CTkButton(
            win,
            text="Close",
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HVR,
            command=win.destroy,
            width=120,
        ).pack(pady=(0, 18))

    # ------------------------------------------------------------------
    # Content area
    # ------------------------------------------------------------------

    def _build_content(self):
        self.content = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True)
        self._views: dict[str, ctk.CTkFrame] = {}

    def _apply_tree_style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("T.Treeview", background=C_CARD, foreground=C_TEXT,
                    fieldbackground=C_CARD, rowheight=36, borderwidth=0,
                    font=(FONT, 12))
        s.configure("T.Treeview.Heading", background=C_CARD2, foreground=C_TEXT_DIM,
                    borderwidth=0, font=(FONT, 11, "bold"))
        s.map("T.Treeview",
              background=[("selected", C_ACCENT)],
              foreground=[("selected", "#fff")])
        s.map("T.Treeview.Heading", background=[("active", C_BORDER)])

    # ------------------------------------------------------------------
    # View router
    # ------------------------------------------------------------------

    def show_view(self, name: str):
        if self._active_view in ("sales", "restock"):
            self._scan_focus_active = False

        for n, b in self._nav_btns.items():
            b.set_active(n == name)

        for f in self._views.values():
            f.pack_forget()

        if name not in self._views:
            self._views[name] = getattr(self, f"_build_{name}_view")()

        self._views[name].pack(fill="both", expand=True)
        self._active_view = name

        if name in ("sales", "restock"):
            self._scan_focus_active = True
            self._scan_focus_tick()

        if name == "inventory":
            self._inv_refresh()
        elif name == "reports":
            self._reports_refresh()
        elif name == "sales":
            self._sales_load_log()
        elif name == "restock":
            self._restock_load_log()

    # ==================================================================
    #  INVENTORY VIEW
    # ==================================================================

    def _build_inventory_view(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.content, fg_color=C_BG, corner_radius=0)

        # Header row
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(28, 0))
        ctk.CTkLabel(hdr, text="📦  Inventory", font=(FONT, 22, "bold"),
                     text_color=C_TEXT).pack(side="left")

        btns = ctk.CTkFrame(hdr, fg_color="transparent")
        btns.pack(side="right")

        def _btn(parent, text, color, hover, cmd, pad=(0, 8)):
            ctk.CTkButton(parent, text=text, fg_color=color, hover_color=hover,
                          height=36, corner_radius=8, font=(FONT, 12),
                          command=cmd).pack(side="left", padx=pad)

        _btn(btns, "＋  Add",       C_ACCENT,   C_ACCENT_HVR, self._inv_add)
        _btn(btns, "✏  Edit",      C_CARD2,    C_BORDER,     self._inv_edit)
        _btn(btns, "🗑  Delete",    "#3B1A1A",  C_DANGER,     self._inv_delete)
        _btn(btns, "☑  Select All",C_CARD2,    C_BORDER,     self._toggle_select_all)
        _btn(btns, "⬇  Export CSV",C_CARD2,    C_BORDER,     self._inv_export, pad=(0, 0))

        # Search bar
        sf = ctk.CTkFrame(frame, fg_color="transparent")
        sf.pack(fill="x", padx=28, pady=(14, 0))
        ctk.CTkLabel(sf, text="🔍", font=(FONT, 15), text_color=C_TEXT_DIM).pack(side="left", padx=(0, 8))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._inv_search_changed)
        ctk.CTkEntry(sf, textvariable=self._search_var,
                     placeholder_text="Search by name, barcode or category…",
                     height=40, font=(FONT, 13), fg_color=C_CARD,
                     border_color=C_BORDER).pack(side="left", fill="x", expand=True)

        # Legend
        leg = ctk.CTkFrame(frame, fg_color="transparent")
        leg.pack(fill="x", padx=28, pady=(6, 0))
        ctk.CTkFrame(leg, width=14, height=14, fg_color=C_WARNING, corner_radius=3).pack(side="left")
        ctk.CTkLabel(leg, text=" Low stock  (qty < 5)", font=(FONT, 11),
                     text_color=C_TEXT_DIM).pack(side="left")

        # Treeview
        tbl = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=12)
        tbl.pack(fill="both", expand=True, padx=28, pady=10)
        vsb = ttk.Scrollbar(tbl)
        vsb.pack(side="right", fill="y")

        self._inv_tree = ttk.Treeview(tbl, columns=TV_COLS, show="headings",
                                       style="T.Treeview",
                                       yscrollcommand=vsb.set, selectmode="browse")
        vsb.configure(command=self._inv_tree.yview)

        cols = {
            "check":    ("☐",            40,  "center"),
            "barcode":  ("Barcode",      160, "w"),
            "name":     ("Product Name", 260, "w"),
            "category": ("Category",     120, "w"),
            "quantity": ("Qty",           65, "center"),
            "price":    ("Price (PKR)",  140, "e"),
        }
        for col, (heading, width, anchor) in cols.items():
            self._inv_tree.heading(col, text=heading, anchor=anchor)
            self._inv_tree.column(col, width=width, minwidth=30, anchor=anchor)

        self._inv_tree.bind("<Button-1>", self._tree_click)
        self._inv_tree.tag_configure("low",    background="#2D2000", foreground="#D29922")
        self._inv_tree.tag_configure("normal", background=C_ROW_NORMAL)
        self._inv_tree.pack(fill="both", expand=True, padx=2, pady=2)

        # Status bar
        self._inv_status = ctk.CTkLabel(frame, text="", font=(FONT, 11), text_color=C_TEXT_DIM)
        self._inv_status.pack(anchor="w", padx=28, pady=(0, 10))

        self._inv_refresh()
        return frame

    # ---- Inventory helpers ----

    def _inv_refresh(self, query: str = ""):
        if not hasattr(self, "_inv_tree"):
            return

        for row in self._inv_tree.get_children():
            self._inv_tree.delete(row)

        products = self.db.search_products(query) if query else self.db.get_all_products()

        # Remove stale checked barcodes
        visible = {p["barcode"] for p in products}
        self._checked_barcodes &= visible

        low_n = 0
        for p in products:
            tag = "low" if p["quantity"] < 5 else "normal"
            if p["quantity"] < 5:
                low_n += 1
            chk = "☑" if p["barcode"] in self._checked_barcodes else "☐"
            self._inv_tree.insert("", "end", iid=p["barcode"], tags=(tag,),
                                   values=(chk, p["barcode"], p["name"],
                                           p.get("category", "General"),
                                           p["quantity"], format_price(p["price"])))

        self._sync_check_header()
        total   = len(products)
        checked = len(self._checked_barcodes)
        s = f"{total} product{'s' if total != 1 else ''}"
        if checked: s += f"  •  ✔ {checked} selected"
        if low_n:   s += f"  •  ⚠ {low_n} low stock"
        self._inv_status.configure(text=s)

    def _inv_search_changed(self, *_):
        if self._search_after:
            self.after_cancel(self._search_after)
        self._search_after = self.after(300, lambda: self._inv_refresh(self._search_var.get()))

    def _inv_sel_barcode(self) -> str | None:
        sel = self._inv_tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a product first.")
            return None
        return sel[0]

    def _inv_add(self):
        cats = self.db.get_categories()
        dlg = ProductDialog(self, "Add New Product", categories=cats)
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            ok = self.db.add_product(d["barcode"], d["name"], d["category"],
                                     d["quantity"], d["price"])
            if ok:
                self._inv_refresh(self._search_var.get())
                self._toast("✅  Product added successfully!")
            else:
                messagebox.showerror("Duplicate Barcode",
                                     f"Barcode '{d['barcode']}' already exists.\n"
                                     "Use Edit to update it.")

    def _inv_edit(self):
        bc = self._inv_sel_barcode()
        if not bc:
            return
        product = self.db.find_by_barcode(bc)
        cats = self.db.get_categories()
        dlg = ProductDialog(self, "Edit Product", product=product, categories=cats)
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            self.db.update_product(d["barcode"], d["name"], d["category"],
                                   d["quantity"], d["price"])
            self._inv_refresh(self._search_var.get())
            self._toast("✅  Product updated!")

    def _inv_delete(self):
        targets = list(self._checked_barcodes)
        if not targets:
            bc = self._inv_sel_barcode()
            if not bc:
                return
            targets = [bc]

        if len(targets) == 1:
            p = self.db.find_by_barcode(targets[0])
            msg = f"Delete '{p['name']}'?\n\nThis cannot be undone."
        else:
            msg = f"Delete {len(targets)} selected product(s)?\n\nThis cannot be undone."

        if messagebox.askyesno("Confirm Delete", msg):
            for bc in targets:
                self.db.delete_product(bc)
            self._checked_barcodes.clear()
            self._inv_refresh(self._search_var.get())
            self._toast(f"🗑  {len(targets)} product(s) deleted.")

    def _inv_export(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"inventory_{ts}.csv",
            title="Export Inventory to CSV",
        )
        if path:
            if self.db.export_to_csv(path):
                messagebox.showinfo("Export Done", f"Saved to:\n{path}")
            else:
                messagebox.showerror("Export Failed", "Could not write file — check permissions.")

    # ---- Checkbox helpers ----

    def _tree_click(self, event):
        region = self._inv_tree.identify_region(event.x, event.y)
        col    = self._inv_tree.identify_column(event.x)
        if col != "#1":
            return
        if region == "heading":
            self._toggle_select_all()
        elif region == "cell":
            row = self._inv_tree.identify_row(event.y)
            if row:
                self._toggle_check(row)

    def _toggle_check(self, barcode: str):
        if barcode in self._checked_barcodes:
            self._checked_barcodes.discard(barcode)
            char = "☐"
        else:
            self._checked_barcodes.add(barcode)
            char = "☑"
        vals = list(self._inv_tree.item(barcode, "values"))
        vals[0] = char
        self._inv_tree.item(barcode, values=vals)
        self._sync_check_header()
        self._inv_update_status()

    def _toggle_select_all(self):
        all_ids = self._inv_tree.get_children()
        if not all_ids:
            return
        all_checked = all(i in self._checked_barcodes for i in all_ids)
        for iid in all_ids:
            vals = list(self._inv_tree.item(iid, "values"))
            if all_checked:
                self._checked_barcodes.discard(iid)
                vals[0] = "☐"
            else:
                self._checked_barcodes.add(iid)
                vals[0] = "☑"
            self._inv_tree.item(iid, values=vals)
        self._sync_check_header()
        self._inv_update_status()

    def _sync_check_header(self):
        if not hasattr(self, "_inv_tree"):
            return
        ids = self._inv_tree.get_children()
        if not ids:
            sym = "☐"
        elif all(i in self._checked_barcodes for i in ids):
            sym = "☑"
        elif self._checked_barcodes:
            sym = "▪"
        else:
            sym = "☐"
        self._inv_tree.heading("check", text=sym)

    def _inv_update_status(self):
        if not hasattr(self, "_inv_status"):
            return
        ids   = self._inv_tree.get_children()
        total = len(ids)
        chk   = len(self._checked_barcodes)
        low   = sum(1 for i in ids if "low" in self._inv_tree.item(i, "tags"))
        s = f"{total} product{'s' if total != 1 else ''}"
        if chk: s += f"  •  ✔ {chk} selected"
        if low: s += f"  •  ⚠ {low} low stock"
        self._inv_status.configure(text=s)

    # ==================================================================
    #  SALES VIEW  —  High-Speed Checkout Interface
    # ==================================================================

    def _build_sales_view(self) -> ctk.CTkFrame:
        """
        Layout (two panels side-by-side):
        ┌─────────────────────────┬──────────────────────────────┐
        │  LEFT  — Scan + Card    │  RIGHT  — Transaction Log    │
        │  ┌───────────────────┐  │  Time | Barcode | Name | St. │
        │  │ SCAN ENTRY (big)  │  │  ─────────────────────────── │
        │  └───────────────────┘  │  row …                       │
        │  ┌───────────────────┐  │  row …                       │
        │  │ LIVE PRODUCT CARD │  │                              │
        │  │  Name  Price  Qty │  │                              │
        │  └───────────────────┘  │                              │
        └─────────────────────────┴──────────────────────────────┘
        """
        frame = ctk.CTkFrame(self.content, fg_color=C_BG, corner_radius=0)

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(24, 0))
        ctk.CTkLabel(hdr, text="🛒  Sales Mode",
                     font=(FONT, 22, "bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(hdr, text="● LIVE",
                     font=(FONT, 11, "bold"), text_color=C_SUCCESS).pack(side="left", padx=12)

        # ── Two-panel body ────────────────────────────────────────────
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=14)
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=6)
        body.rowconfigure(0, weight=1)

        # ════════════ LEFT PANEL ══════════════════════════════════════
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # ── Focus-zone: scan entry ────────────────────────────────────
        scan_card = ctk.CTkFrame(left, fg_color=C_CARD, corner_radius=14,
                                  border_width=1, border_color=C_BORDER)
        scan_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(scan_card, text="READY TO SCAN",
                     font=(FONT, 10, "bold"), text_color=C_TEXT_DIM).pack(pady=(16, 4))

        # Idle border is subtle grey — flashes green/red on result
        self._sale_entry = FlashEntry(
            scan_card,
            placeholder_text="Barcode ready...",
            height=64,
            font=(FONT, 22, "bold"),
            fg_color=C_CARD2,
            border_color=C_BORDER,
            border_width=2,
            justify="center",
        )
        self._sale_entry.pack(fill="x", padx=20, pady=(0, 10))
        self._sale_entry.bind("<Return>", self._process_sale)
        self._sale_entry.bind("<KeyRelease>", self._on_sale_key_release)



        # ── Live Product Card ─────────────────────────────────────────
        self._prod_card = ctk.CTkFrame(left, fg_color=C_CARD, corner_radius=14,
                                        border_width=1, border_color=C_BORDER)
        self._prod_card.pack(fill="both", expand=True)

        ctk.CTkLabel(self._prod_card, text="",
                     font=(FONT, 11), text_color=C_TEXT_DIM).pack(pady=(20, 0))
        self._pc_status = ctk.CTkLabel(self._prod_card,
                                        text="Scan a product to begin",
                                        font=(FONT, 13), text_color=C_TEXT_DIM)
        self._pc_status.pack(pady=(0, 6))
        self._pc_name = ctk.CTkLabel(self._prod_card, text="—",
                                      font=(FONT, 20, "bold"), text_color=C_TEXT,
                                      wraplength=300)
        self._pc_name.pack(padx=20)
        self._pc_price = ctk.CTkLabel(self._prod_card, text="",
                                       font=(FONT, 15), text_color=C_ACCENT)
        self._pc_price.pack(pady=(6, 0))
        self._pc_stock = ctk.CTkLabel(self._prod_card, text="",
                                       font=(FONT, 13, "bold"), text_color=C_TEXT_DIM)
        self._pc_stock.pack(pady=(4, 20))

        # ════════════ RIGHT PANEL — Transaction Log ═══════════════════
        right = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=14,
                              border_width=1, border_color=C_BORDER)
        right.grid(row=0, column=1, sticky="nsew")

        log_hdr = ctk.CTkFrame(right, fg_color=C_CARD2, corner_radius=0)
        log_hdr.pack(fill="x")
        ctk.CTkLabel(log_hdr, text="Current Bill",
                     font=(FONT, 13, "bold"), text_color=C_TEXT).pack(
            side="left", padx=16, pady=12)
        self._sale_count_lbl = ctk.CTkLabel(log_hdr, text="0 items",
                                             font=(FONT, 11), text_color=C_TEXT_DIM)
        self._sale_count_lbl.pack(side="right", padx=16)

        # Column header row
        col_hdr = ctk.CTkFrame(right, fg_color="#161B22")
        col_hdr.pack(fill="x")
        ctk.CTkLabel(col_hdr, text="Qty",    font=(FONT, 10, "bold"),
                     text_color=C_TEXT_DIM, width=40,  anchor="center").pack(
            side="left", padx=(12, 4), pady=5)
        ctk.CTkLabel(col_hdr, text="Name", font=(FONT, 10, "bold"),
                     text_color=C_TEXT_DIM, anchor="w").pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkLabel(col_hdr, text="Subtotal",  font=(FONT, 10, "bold"),
                     text_color=C_TEXT_DIM, width=90,  anchor="e").pack(
            side="right", padx=(4, 12))
        ctk.CTkLabel(col_hdr, text="Price", font=(FONT, 10, "bold"),
                     text_color=C_TEXT_DIM, width=80, anchor="e").pack(
            side="right", padx=(0, 4))

        # Scrollable bill
        self._sale_log = ctk.CTkScrollableFrame(right, fg_color="transparent",
                                                  corner_radius=0)
        self._sale_log.pack(fill="both", expand=True)
        self._sale_log_rows: list      = []
        self._sale_session_count: int  = 0
        
        # Footer
        footer = ctk.CTkFrame(right, fg_color=C_CARD2, corner_radius=0)
        footer.pack(fill="x", side="bottom")
        
        self._bill_total_lbl = ctk.CTkLabel(footer, text="Total Price: PKR 0.00",
                                            font=(FONT, 18, "bold"), text_color=C_ACCENT)
        self._bill_total_lbl.pack(side="left", padx=16, pady=16)
        
        ctk.CTkButton(footer, text="Confirm Bill", font=(FONT, 13, "bold"),
                      fg_color=C_SUCCESS, hover_color="#2EA043", width=120, height=40,
                      command=self._confirm_bill).pack(side="right", padx=(0, 16), pady=16)
                      
        ctk.CTkButton(footer, text="Clear Bill", font=(FONT, 13, "bold"),
                      fg_color="#3B1A1A", hover_color=C_DANGER, width=100, height=40,
                      command=self._clear_bill).pack(side="right", padx=16, pady=16)

        return frame

    # ── Ghost Focus Loop ──────────────────────────────────────────────

    def _sales_load_log(self):
        """Reset the Current Bill when the Sales view is opened."""
        if not hasattr(self, "_sale_log"):
            return
        self._clear_bill()

    # ── Core sale processor ───────────────────────────────────────────

    def _on_sale_key_release(self, event):
        if event.keysym in ("Return", "Tab"):
            return
        if hasattr(self, "_sale_debounce") and self._sale_debounce:
            self.after_cancel(self._sale_debounce)
        self._sale_debounce = self.after(600, self._check_auto_sale)

    def _check_auto_sale(self):
        raw = self._sale_entry.get().strip()
        if len(raw) < 2: return
        product = self.db.find_by_barcode(raw)
        if product or len(raw) >= 5:
            self._sale_entry.delete(0, "end")
            self._process_sale(barcode=raw)

    def _process_sale(self, _=None, barcode: str | None = None):
        if barcode is None:
            raw = self._sale_entry.get()
            self._sale_entry.delete(0, "end")
        else:
            raw = barcode

        bc = _sanitise_barcode(raw)
        if len(bc) < 2:
            return

        self._dismiss_notfound_shortcut()

        product = self.db.find_by_barcode(bc)

        if not product:
            self._sale_entry.flash_custom("#dc3545", 300)
            play_beep(False)
            self._pc_update_card(
                status="Product Not Found",
                name=bc,
                price="",
                stock="Barcode not in inventory.",
                status_color=C_DANGER,
                name_color=C_TEXT_DIM,
                stock_color=C_TEXT_DIM,
            )
            self._dismiss_notfound_shortcut()
            return

        # Check if adding one more would exceed stock
        current_in_bill = self._current_bill.get(bc, {}).get("qty", 0)
        remaining = product["quantity"] - current_in_bill

        if remaining <= 0:
            self._sale_entry.flash_custom("#dc3545", 300)
            play_beep(False)
            self._pc_update_card(
                status="OUT OF STOCK",
                name=product["name"],
                price=format_price(product["price"]),
                stock=f"Only {product['quantity']} in stock",
                status_color=C_DANGER,
                stock_color=C_DANGER,
            )
            self._toast(f"⚠  INSUFFICIENT STOCK:  {product['name']}", ms=3000)
            self.after(50, self._sale_entry.focus_set)
            return

        dlg = SaleQtyDialog(self, product, remaining)
        self.wait_window(dlg)
        
        self.after(50, self._sale_entry.focus_set)
        
        if not dlg.result:
            return
            
        qty_to_add = dlg.result

        # Add to bill
        if bc not in self._current_bill:
            self._current_bill[bc] = {
                "name": product["name"],
                "price": product["price"],
                "qty": 0,
                "stock": product["quantity"]
            }
        self._current_bill[bc]["qty"] += qty_to_add
        
        self._sale_entry.flash_custom("#28a745", 300)
        play_beep(True)

        new_remaining = remaining - qty_to_add
        
        if new_remaining == 0:
            stock_txt, stock_col = "0 left — NOW OUT OF STOCK", C_DANGER
        elif new_remaining < 5:
            stock_txt, stock_col = f"{new_remaining} units left  ⚠  Low Stock", C_WARNING
        else:
            stock_txt, stock_col = f"{new_remaining} units remaining", C_SUCCESS

        self._pc_update_card(
            status="Added to Bill",
            name=product["name"],
            price=format_price(product["price"]),
            stock=stock_txt,
            status_color=C_SUCCESS,
            stock_color=stock_col,
        )
        
        self._refresh_bill_ui()

    # ── "Not Found" shortcut button ───────────────────────────────────

    def _show_notfound_shortcut(self, barcode: str):
        """
        Shows a floating button below the scan card.
        Clicking it opens the Add Product dialog with the barcode pre-filled.
        """
        self._dismiss_notfound_shortcut()   # Remove any previous one first

        btn = ctk.CTkButton(
            self._prod_card,
            text=f"  ＋  Add  '{barcode}'  to Inventory",
            font=(FONT, 12, "bold"),
            fg_color="#1f3560",
            hover_color=C_ACCENT,
            corner_radius=8,
            height=38,
            command=lambda bc=barcode: self._notfound_add(bc),
        )
        btn.pack(padx=20, pady=(0, 16))
        self._notfound_btn = btn

    def _dismiss_notfound_shortcut(self):
        btn = getattr(self, "_notfound_btn", None)
        if btn:
            try:
                btn.destroy()
            except Exception:
                pass
            self._notfound_btn = None

    def _notfound_add(self, barcode: str):
        """Opens Add Product dialog pre-filled with the not-found barcode."""
        self._dismiss_notfound_shortcut()
        cats = self.db.get_categories()
        # Pre-populate only the barcode field
        stub = {"barcode": barcode, "name": "", "category": "General",
                "quantity": 0, "price": 0.0}
        dlg = ProductDialog(self, "Add New Product", product=stub, categories=cats)
        # Unlock barcode field so it shows but allow editing name etc.
        dlg.e_barcode.configure(state="normal")
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            ok = self.db.add_product(d["barcode"], d["name"], d["category"],
                                     d["quantity"], d["price"])
            if ok:
                self._toast(f"✅  Product added: {d['name']}")
                if "inventory" in self._views:
                    self._inv_refresh()
            else:
                messagebox.showerror("Duplicate",
                                     f"Barcode '{d['barcode']}' already exists.")

    # ── Live Product Card ─────────────────────────────────────────────

    def _pc_update_card(self, *, status, name, price, stock,
                         status_color=None, name_color=None, stock_color=None):
        self._pc_status.configure(text=status,
                                   text_color=status_color or C_TEXT_DIM)
        self._pc_name.configure(text=name,
                                 text_color=name_color or C_TEXT)
        self._pc_price.configure(text=price)
        self._pc_stock.configure(text=stock,
                                  text_color=stock_color or C_TEXT_DIM)

    # ── Transaction log ───────────────────────────────────────────────

    def _refresh_bill_ui(self):
        for w in self._sale_log_rows:
            w.destroy()
        self._sale_log_rows.clear()
        
        total_price = 0.0
        total_items = 0
        
        for bc, item in self._current_bill.items():
            subtotal = item["qty"] * item["price"]
            total_price += subtotal
            total_items += item["qty"]
            self._sale_log_insert_row(
                qty=item["qty"],
                name=item["name"],
                price=format_price(item["price"]),
                subtotal=format_price(subtotal)
            )
            
        self._bill_total_lbl.configure(text=f"Total Price: {format_price(total_price)}")
        self._sale_count_lbl.configure(text=f"{total_items} items")
        self._sale_session_count = total_items

    def _sale_log_insert_row(self, qty: int, name: str, price: str, subtotal: str):
        row = ctk.CTkFrame(self._sale_log, fg_color=C_CARD2, corner_radius=7)
        row.pack(fill="x", padx=6, pady=(3, 0))

        # Qty
        ctk.CTkLabel(row, text=f"{qty}x", font=(FONT, 12, "bold"),
                     text_color=C_ACCENT, width=40, anchor="center").pack(
            side="left", padx=(10, 4), pady=8)
        # Name
        ctk.CTkLabel(row, text=name, font=(FONT, 12),
                     text_color=C_TEXT, anchor="w").pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        # Subtotal
        ctk.CTkLabel(row, text=subtotal, font=(FONT, 12, "bold"),
                     text_color=C_TEXT, width=90, anchor="e").pack(
            side="right", padx=(4, 12), pady=8)
        # Price
        ctk.CTkLabel(row, text=price, font=(FONT, 11),
                     text_color=C_TEXT_DIM, width=80, anchor="e").pack(
            side="right", padx=(0, 4), pady=8)

        self._sale_log_rows.append(row)

    def _clear_bill(self):
        self._current_bill.clear()
        self._refresh_bill_ui()
        self._pc_update_card(
            status="Scan a product to begin",
            name="—",
            price="",
            stock="",
            status_color=C_TEXT_DIM,
            name_color=C_TEXT,
            stock_color=C_TEXT_DIM,
        )

    def _confirm_bill(self):
        if not self._current_bill:
            self._toast("⚠  Bill is empty!", ms=2000)
            return
            
        for bc, item in self._current_bill.items():
            status, product = self.db.update_stock(bc, -item["qty"])
            if status == "ok":
                self.db.log_sale(bc, product["name"], item["qty"], product["quantity"])
                
        self._toast(f"✅  Bill Confirmed: {self._sale_session_count} items sold.")
        play_beep(True)
        self._clear_bill()
        
        if "inventory" in self._views:
            self._inv_refresh(self._search_var.get()
                              if hasattr(self, "_search_var") else "")

    # Alias kept so nothing else breaks
    def _on_sale_scan(self, event=None):
        self._process_sale(event)




    # ==================================================================
    #  RESTOCK VIEW
    # ==================================================================

    def _build_restock_view(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.content, fg_color=C_BG, corner_radius=0)

        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(28, 0))
        ctk.CTkLabel(hdr, text="📥  Restock Mode", font=(FONT, 22, "bold"),
                     text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(hdr, text="● LIVE", font=(FONT, 11, "bold"),
                     text_color=C_WARNING).pack(side="left", padx=12)

        card = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=16,
                             border_width=1, border_color=C_BORDER)
        card.pack(fill="x", padx=28, pady=16)
        ctk.CTkLabel(card, text="Scan a barcode — a quantity dialog will appear.",
                     font=(FONT, 13), text_color=C_TEXT_DIM).pack(pady=(18, 6))
        self._restock_entry = FlashEntry(card, placeholder_text="▌ Barcode ready…",
                                          height=52, font=(FONT, 18, "bold"),
                                          fg_color=C_CARD2, border_color=C_WARNING,
                                          border_width=1, justify="center")
        self._restock_entry.pack(fill="x", padx=24, pady=(0, 10))
        self._restock_entry.bind("<Return>", self._on_restock_scan)
        self._restock_entry.bind("<KeyRelease>", self._on_restock_key_release)



        res = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=16,
                           border_width=1, border_color=C_BORDER)
        res.pack(fill="x", padx=28, pady=(0, 10))
        self._restock_result = ctk.CTkLabel(res, text="Waiting for scan…",
                                             font=(FONT, 15), text_color=C_TEXT_DIM)
        self._restock_result.pack(pady=18)

        ctk.CTkLabel(frame, text="Restock Log", font=(FONT, 14, "bold"),
                     text_color=C_TEXT).pack(anchor="w", padx=28, pady=(6, 4))
        self._restock_log = ctk.CTkScrollableFrame(frame, fg_color=C_CARD,
                                                    corner_radius=12, height=250)
        self._restock_log.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        self._restock_log_rows: list = []

        return frame

    def _restock_load_log(self):
        """Populate restock log from DB when view is opened."""
        if not hasattr(self, "_restock_log"):
            return
        for w in self._restock_log_rows:
            w.destroy()
        self._restock_log_rows.clear()

        for entry in reversed(self.db.get_recent_restocks(limit=20)):
            ts  = entry["timestamp"].split(" ")[-1][:8]
            msg = (f"📥  RESTOCKED: {entry['name']}  "
                   f"+{entry['quantity_added']} → {entry['remaining_qty']} in stock")
            self._restock_log_add_row(ts, msg, C_SUCCESS, prepend=False)

    def _on_restock_key_release(self, event):
        if event.keysym in ("Return", "Tab"):
            return
        if hasattr(self, "_restock_debounce") and self._restock_debounce:
            self.after_cancel(self._restock_debounce)
        self._restock_debounce = self.after(600, self._check_auto_restock)

    def _check_auto_restock(self):
        raw = self._restock_entry.get().strip()
        if len(raw) < 2: return
        product = self.db.find_by_barcode(raw)
        if product or len(raw) >= 5:
            self._restock_entry.delete(0, "end")
            self._on_restock_scan(barcode=raw)

    def _on_restock_scan(self, _=None, barcode: str | None = None):
        """
        Restock scan handler — optimised for Barcode2win / HID.

        Flow:
          1. Sanitise input, clear field immediately.
          2. Lookup product — if not found: red flash + toast.
          3. Open centred CTkToplevel with auto-focused qty field.
          4. On confirm: update_stock(bc, +qty), blue flash, log row.
        """
        if barcode is None:
            raw = self._restock_entry.get()
            self._restock_entry.delete(0, "end")   # Auto-clear
        else:
            raw = barcode

        bc = _sanitise_barcode(raw)
        if len(bc) < 2:
            return

        product = self.db.find_by_barcode(bc)
        if not product:
            self._restock_entry.flash_custom("#dc3545", 300)  # Red 300ms
            play_beep(False)
            self._restock_result.configure(
                text=f"Not Found: '{bc}'",
                text_color=C_DANGER)
            return

        qty_dlg = RestockQtyDialog(self, product)
        self.wait_window(qty_dlg)
        if qty_dlg.result is None:
            return

        qty    = qty_dlg.result
        status, updated = self.db.update_stock(bc, qty)   # thread-safe

        if status == "ok":
            self._restock_entry.flash_custom("#2F81F7", 300)  # Blue 300ms
            play_beep(True)
            self.db.log_restock(bc, product["name"], qty, updated["quantity"])
            msg = (f"RESTOCKED: {updated['name']}  "
                   f"+{qty} -> {updated['quantity']} in stock")
            self._restock_result.configure(text=msg, text_color=C_SUCCESS)
            self._restock_log_add_row(
                ts_now(), msg, C_SUCCESS)

            if "inventory" in self._views:
                self._inv_refresh(
                    self._search_var.get() if hasattr(self, "_search_var") else "")
        else:
            self._restock_entry.flash_custom("#dc3545", 300)
            play_beep(False)
            self._restock_result.configure(
                text="Restock failed — please retry.", text_color=C_DANGER)

    def _restock_log_add_row(self, ts: str, text: str, color: str, prepend: bool = True):
        row = ctk.CTkFrame(self._restock_log, fg_color=C_CARD2, corner_radius=8)
        if prepend:
            row.pack(fill="x", padx=4, pady=3,
                     before=self._restock_log_rows[0] if self._restock_log_rows else None)
        else:
            row.pack(fill="x", padx=4, pady=3)
        ctk.CTkLabel(row, text=ts, font=(FONT, 11), text_color=C_TEXT_DIM,
                     width=72).pack(side="left", padx=(10, 4))
        ctk.CTkLabel(row, text=text, font=(FONT, 12), text_color=color,
                     anchor="w").pack(side="left", fill="x", expand=True, padx=(0, 10))
        self._restock_log_rows.append(row)
        if len(self._restock_log_rows) > 20:
            self._restock_log_rows.pop(0).destroy()

    # ==================================================================
    #  REPORTS VIEW
    # ==================================================================

    def _build_reports_view(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.content, fg_color=C_BG, corner_radius=0)

        ctk.CTkLabel(frame, text="📊  Reports", font=(FONT, 22, "bold"),
                     text_color=C_TEXT).pack(anchor="w", padx=28, pady=(28, 14))

        # Stat cards grid
        grid = ctk.CTkFrame(frame, fg_color="transparent")
        grid.pack(fill="x", padx=28)
        for i in range(4):
            grid.columnconfigure(i, weight=1, uniform="stat")

        self._stat_products = StatCard(grid, "Total Products",   "…", "📦", C_ACCENT)
        self._stat_items    = StatCard(grid, "Total Items",      "…", "🔢", C_SUCCESS)
        self._stat_low      = StatCard(grid, "Low Stock Alerts", "…", "⚠", C_WARNING)
        self._stat_value    = StatCard(grid, "Inventory Value",  "…", "💰", "#A371F7")

        self._stat_products.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._stat_items.grid(   row=0, column=1, sticky="nsew", padx=3)
        self._stat_low.grid(     row=0, column=2, sticky="nsew", padx=3)
        self._stat_value.grid(   row=0, column=3, sticky="nsew", padx=(6, 0))

        # Low stock list
        ctk.CTkLabel(frame, text="⚠  Low Stock Products",
                     font=(FONT, 16, "bold"), text_color=C_WARNING).pack(
            anchor="w", padx=28, pady=(22, 8))

        self._low_scroll = ctk.CTkScrollableFrame(frame, fg_color=C_CARD,
                                                   corner_radius=12, height=300)
        self._low_scroll.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self._low_rows: list = []

        self._reports_refresh()
        return frame

    def _reports_refresh(self):
        if not hasattr(self, "_stat_products"):
            return

        st = self.db.get_summary_stats()
        self._stat_products.update(st["total_products"])
        self._stat_items.update(f"{st['total_items']:,}")
        self._stat_low.update(st["low_stock_count"])
        self._stat_value.update(format_price(st["total_value"]))

        for w in self._low_rows:
            w.destroy()
        self._low_rows.clear()

        low = self.db.get_low_stock_products(threshold=5)
        if not low:
            lbl = ctk.CTkLabel(self._low_scroll,
                               text="🎉  All products are well stocked!",
                               font=(FONT, 13), text_color=C_SUCCESS)
            lbl.pack(pady=20)
            self._low_rows.append(lbl)
            return

        for p in low:
            row = ctk.CTkFrame(self._low_scroll, fg_color=C_ROW_LOW,
                               corner_radius=8, border_width=1, border_color=C_WARNING)
            row.pack(fill="x", padx=4, pady=4)

            ctk.CTkLabel(row, text=p["barcode"], font=(FONT, 11),
                         text_color=C_TEXT_DIM, width=150, anchor="w").pack(
                side="left", padx=(12, 6), pady=10)
            ctk.CTkLabel(row, text=p["name"], font=(FONT, 13),
                         text_color=C_TEXT, anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=p.get("category", "General"), font=(FONT, 11),
                         text_color=C_TEXT_DIM, width=110, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"  {p['quantity']} left  ",
                         font=(FONT, 12, "bold"), text_color="#111",
                         fg_color=C_WARNING, corner_radius=6).pack(
                side="right", padx=12, pady=8)

            self._low_rows.append(row)

    # ==================================================================
    #  Ghost Focus Loop  (500ms check_focus pattern)
    # ==================================================================

    def _scan_focus_tick(self):
        """
        Ghost Focus implementation.

        Every 500ms:
          1. Check if a CTkToplevel dialog is open — if yes, do nothing
             (never steal focus from a modal / confirmation dialog).
          2. Check if the barcode entry already has focus — if yes, skip.
          3. Otherwise force entry.focus_set().

        This allows scanning 50+ items in a row without ever clicking the screen.
        """
        if not self._scan_focus_active:
            return

        # Identify the active scanner target
        target = None
        if self._active_view == "sales"   and hasattr(self, "_sale_entry"):
            target = self._sale_entry
        elif self._active_view == "restock" and hasattr(self, "_restock_entry"):
            target = self._restock_entry

        if target:
            try:
                # Step 1: Is any dialog/popup open?
                dialog_open = any(
                    isinstance(w, ctk.CTkToplevel) and w.winfo_viewable()
                    for w in self.winfo_children()
                )
                if not dialog_open:
                    # Step 2: Does the entry already have focus?
                    if self.focus_get() is not target:
                        # Step 3: Force focus
                        target.focus_set()
            except Exception:
                pass   # Silently ignore transient Tk state errors

        # Schedule next check
        self.after(500, self._scan_focus_tick)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = InventoryApp()
    app.mainloop()
