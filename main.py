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
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
from datetime import datetime, timedelta

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
TV_COLS = ("check", "name", "quantity", "price", "expiry", "barcode")

# Preset categories for the dropdown
CATEGORIES = [
    "General", "Food & Beverage", "Dairy", "Bakery", "Snacks",
    "Beverages", "Household", "Personal Care", "Electronics", "Clothing",
]

# Mobile bridge server port removed


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

class HoverTooltip:
    def __init__(self, widget):
        self.widget = widget
        self.tw = None

    def show(self, text, x, y):
        self.hide()
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x+15}+{y+15}")
        
        label = tk.Label(self.tw, text=text, justify='left',
                         background="#21262D", relief='solid', borderwidth=1,
                         font=(FONT, 10), fg="white", padx=8, pady=4)
        label.pack()

    def hide(self):
        if self.tw:
            self.tw.destroy()
            self.tw = None

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
        self.geometry("440x670")
        self.resizable(False, False)
        self.configure(fg_color=C_CARD)
        self.grab_set()
        self.focus_set()

        cats = categories or CATEGORIES

        # Register validations
        vcmd_int = self.register(self._validate_int)
        vcmd_float = self.register(self._validate_float)

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
                                       fg_color=C_CARD2, border_color=C_BORDER,
                                       validate="key", validatecommand=(vcmd_int, "%P"))
        self.e_barcode.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # ---- Name ----
        _lbl("Product Name *")
        self.e_name = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                    fg_color=C_CARD2, border_color=C_BORDER)
        self.e_name.pack(fill="x")

        # ---- Quantity ----
        _lbl("Quantity *")
        self.e_qty = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                   fg_color=C_CARD2, border_color=C_BORDER,
                                   validate="key", validatecommand=(vcmd_int, "%P"))
        self.e_qty.pack(fill="x")

        # ---- Original Price ----
        _lbl("Original Price (PKR) *")
        self.e_orig_price = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                     fg_color=C_CARD2, border_color=C_BORDER,
                                     validate="key", validatecommand=(vcmd_float, "%P"))
        self.e_orig_price.pack(fill="x")

        # ---- Selling Price ----
        _lbl("Selling Price (PKR) *")
        self.e_price = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                     fg_color=C_CARD2, border_color=C_BORDER,
                                     validate="key", validatecommand=(vcmd_float, "%P"))
        self.e_price.pack(fill="x")

        # ---- Expiry Date ----
        _lbl("Expiry Date")
        
        # Expiry container frame (dropdowns packed directly here)
        self.exp_frame = ctk.CTkFrame(form, fg_color="transparent")
        self.exp_frame.pack(fill="x", pady=2)
        
        # Month, Day, Year dropdowns next to each other
        today = datetime.now()
        self.days = [f"{i:02d}" for i in range(1, 32)]
        self.months_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        current_year = today.year
        self.years = [str(y) for y in range(current_year, current_year + 16)]
        
        self.e_expiry_day = ctk.CTkComboBox(
            self.exp_frame, values=self.days, width=80, height=34, font=(FONT, 12),
            fg_color=C_CARD2, border_color=C_BORDER,
            button_color=C_CARD2, button_hover_color=C_BORDER,
            dropdown_fg_color=C_CARD2
        )
        self.e_expiry_day.set(f"{today.day:02d}")
        self.e_expiry_day.pack(side="left", padx=(0, 4), fill="x", expand=True)
        self.e_expiry_day._entry.configure(validate="key", validatecommand=(vcmd_int, "%P"))
        
        self.e_expiry_month = ctk.CTkComboBox(
            self.exp_frame, values=self.months_names, width=95, height=34, font=(FONT, 12),
            fg_color=C_CARD2, border_color=C_BORDER,
            button_color=C_CARD2, button_hover_color=C_BORDER,
            dropdown_fg_color=C_CARD2
        )
        self.e_expiry_month.set(self.months_names[today.month - 1])
        self.e_expiry_month.pack(side="left", padx=4, fill="x", expand=True)
        
        # Bind key release and focus out to month selector for auto-conversion
        self.e_expiry_month.bind("<KeyRelease>", self._on_month_key)
        self.e_expiry_month.bind("<FocusOut>", self._on_month_focus_out)
        if hasattr(self.e_expiry_month, "_entry"):
            self.e_expiry_month._entry.bind("<KeyRelease>", self._on_month_key)
            self.e_expiry_month._entry.bind("<FocusOut>", self._on_month_focus_out)
        
        self.e_expiry_year = ctk.CTkComboBox(
            self.exp_frame, values=self.years, width=90, height=34, font=(FONT, 12),
            fg_color=C_CARD2, border_color=C_BORDER,
            button_color=C_CARD2, button_hover_color=C_BORDER,
            dropdown_fg_color=C_CARD2
        )
        self.e_expiry_year.set(str(current_year))
        self.e_expiry_year.pack(side="left", padx=(4, 0), fill="x", expand=True)
        self.e_expiry_year._entry.configure(validate="key", validatecommand=(vcmd_int, "%P"))

        # Pre-fill when editing
        self._is_edit = bool(product)
        if product:
            self.e_barcode.insert(0, product.get("barcode", ""))
            self.e_name.insert(0, product.get("name", ""))
            self.e_barcode.configure(state="disabled")   # PK — immutable
            self.e_qty.insert(0, str(product.get("quantity", 0)))
            self.e_orig_price.insert(0, str(product.get("original_price", 0.0)))
            self.e_price.insert(0, str(product.get("price", 0.0)))
            
            # Parse expiry date
            exp = product.get("expiry", "N/A")
            if exp and exp != "N/A":
                parts = exp.split("-")
                if len(parts) == 3:
                    try:
                        y_val, m_val, d_val = parts[0], parts[1], parts[2]
                        self.e_expiry_year.set(y_val)
                        m_int = int(m_val)
                        if 1 <= m_int <= 12:
                            self.e_expiry_month.set(self.months_names[m_int - 1])
                        self.e_expiry_day.set(d_val)
                    except ValueError:
                        pass
            else:
                self.e_expiry_day.set("N/A")
                self.e_expiry_month.set("N/A")
                self.e_expiry_year.set("N/A")
        
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

    def _on_month_key(self, event):
        self.after(50, self._check_month_input)

    def _check_month_input(self):
        val = self.e_expiry_month.get().strip()
        if val.isdigit():
            m_int = int(val)
            if m_int == 0 and len(val) >= 2:
                self.e_expiry_month.set(self.months_names[0]) # Jan
            elif m_int <= 0 and len(val) >= 2:
                self.e_expiry_month.set(self.months_names[0]) # Jan
            elif m_int > 12:
                self.e_expiry_month.set(self.months_names[11]) # Dec
            elif 2 <= m_int <= 9:
                self.e_expiry_month.set(self.months_names[m_int - 1])
            elif len(val) >= 2 and 1 <= m_int <= 12:
                self.e_expiry_month.set(self.months_names[m_int - 1])

    def _on_month_focus_out(self, event):
        val = self.e_expiry_month.get().strip()
        if val.isdigit():
            m_int = int(val)
            if m_int <= 0:
                self.e_expiry_month.set(self.months_names[0]) # Jan
            elif m_int > 12:
                self.e_expiry_month.set(self.months_names[11]) # Dec
            elif 1 <= m_int <= 12:
                self.e_expiry_month.set(self.months_names[m_int - 1])

    def _scan_b2w(self):
        self.e_barcode.focus_set()
        self.e_barcode.configure(border_color=C_SUCCESS)
        self.after(500, lambda: self.e_barcode.configure(border_color=C_BORDER))

    def _save(self):
        barcode   = self.e_barcode.get().strip()
        name      = self.e_name.get().strip()
        category  = "General"
        qty_raw   = self.e_qty.get().strip()
        orig_price_raw = self.e_orig_price.get().strip()
        price_raw = self.e_price.get().strip()

        # Construct expiry date
        month_val = self.e_expiry_month.get().strip()
        if month_val.isdigit():
            m_int = int(month_val)
            if m_int <= 0:
                month_val = self.months_names[0] # Jan
            elif m_int > 12:
                month_val = self.months_names[11] # Dec
            elif 1 <= m_int <= 12:
                month_val = self.months_names[m_int - 1]
            self.e_expiry_month.set(month_val)

        day = self.e_expiry_day.get().strip()
        # Format day to 2 digits if it's a number
        if day.isdigit():
            day = f"{int(day):02d}"
            self.e_expiry_day.set(day)

        month_name = month_val
        year = self.e_expiry_year.get().strip()

        if not day or not month_name or not year or day == "N/A" or month_name == "N/A" or year == "N/A":
            expiry = "N/A"
        else:
            try:
                m_idx = self.months_names.index(month_name) + 1
                month = f"{m_idx:02d}"
            except ValueError:
                # If they typed a custom month name (e.g. "January" or full name),
                # let's try prefix matching
                matched = False
                for idx, m_n in enumerate(self.months_names):
                    if month_name.lower().startswith(m_n.lower()):
                        month = f"{idx + 1:02d}"
                        matched = True
                        break
                if not matched:
                    month = "01"
            expiry = f"{year}-{month}-{day}"

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
            orig_price = float(orig_price_raw)
            assert orig_price >= 0
            price = float(price_raw)
            assert price >= 0
        except (ValueError, AssertionError):
            messagebox.showerror("Invalid Price", "Price must be a number ≥ 0.", parent=self)
            return

        self.result = {"barcode": barcode, "name": name, "category": category,
                       "quantity": qty, "price": price, "original_price": orig_price, "expiry": expiry}
        self.destroy()

    def _validate_int(self, P):
        if P == "":
            return True
        return P.isdigit()

    def _validate_float(self, P):
        if P == "" or P == ".":
            return True
        try:
            float(P)
            return True
        except ValueError:
            return False


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
        vcmd_int = self.register(lambda P: P == "" or P.isdigit())
        self.qty_entry = ctk.CTkEntry(frm, height=40, font=(FONT, 16, "bold"),
                                       fg_color=C_CARD2, border_color=C_ACCENT,
                                       justify="center", validate="key", validatecommand=(vcmd_int, "%P"))
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


class RefundQtyDialog(ctk.CTkToplevel):
    """Small modal asking how many units of the product are being returned."""

    def __init__(self, parent, product: dict):
        super().__init__(parent)
        self.result = None
        self._creation_time = time.time()
        self.title("Refund Quantity")
        self.geometry("340x240")
        self.resizable(False, False)
        self.configure(fg_color=C_CARD)

        self.update_idletasks()
        try:
            x = parent.winfo_x() + (parent.winfo_width() // 2) - 170
            y = parent.winfo_y() + (parent.winfo_height() // 2) - 120
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self.grab_set()
        self.focus_set()

        ctk.CTkLabel(self, text="↩  Process Refund", font=(FONT, 16, "bold")).pack(pady=(20, 4))
        ctk.CTkLabel(self, text=f"{product['name']} (Stock: {product['quantity']})", font=(FONT, 12),
                     text_color=C_TEXT_DIM).pack(pady=(0, 12))

        frm = ctk.CTkFrame(self, fg_color="transparent")
        frm.pack(fill="x", padx=32)
        ctk.CTkLabel(frm, text="Quantity returned by customer:", font=(FONT, 12),
                     text_color=C_TEXT_DIM, anchor="w").pack(fill="x")
        vcmd_int = self.register(lambda P: P == "" or P.isdigit())
        self.qty_entry = ctk.CTkEntry(frm, height=40, font=(FONT, 16, "bold"),
                                       fg_color=C_CARD2, border_color=C_ACCENT,
                                       justify="center", validate="key", validatecommand=(vcmd_int, "%P"))
        self.qty_entry.insert(0, "1")
        self.qty_entry.pack(fill="x", pady=4)
        self.qty_entry.focus_set()
        self.qty_entry.select_range(0, "end")

        ctk.CTkButton(self, text="↩  Confirm Return", fg_color=C_ACCENT,
                      hover_color=C_ACCENT_HVR, font=(FONT, 13, "bold"),
                      command=self._confirm).pack(pady=16, padx=32, fill="x")
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self, event=None):
        if time.time() - self._creation_time < 0.25:
            return  # Prevent scanner's trailing Enter key from auto-confirming
        try:
            qty_str = self.qty_entry.get().strip()
            qty = int(qty_str)
            assert qty > 0
            self.result = qty
            self.destroy()
        except (ValueError, AssertionError):
            messagebox.showerror("Invalid Quantity", "Please enter a valid quantity greater than 0.", parent=self)
            self.qty_entry.delete(0, "end")
            self.qty_entry.insert(0, "1")
            self.qty_entry.focus_set()
            self.qty_entry.select_range(0, "end")


class SaleQtyDialog(ctk.CTkToplevel):
    """Small modal asking how many units to add to the bill."""

    def __init__(self, parent, product: dict, max_qty: int):
        super().__init__(parent)
        self.result = None
        self._creation_time = time.time()
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
        vcmd_int = self.register(lambda P: P == "" or P.isdigit())
        self.qty_entry = ctk.CTkEntry(frm, height=40, font=(FONT, 16, "bold"),
                                       fg_color=C_CARD2, border_color=C_ACCENT,
                                       justify="center", validate="key", validatecommand=(vcmd_int, "%P"))
        self.qty_entry.insert(0, "1")
        self.qty_entry.pack(fill="x", pady=4)
        self.qty_entry.focus_set()
        self.qty_entry.select_range(0, "end")

        ctk.CTkButton(self, text="✔  Add", fg_color=C_SUCCESS,
                      hover_color="#2EA043", font=(FONT, 13, "bold"),
                      command=self._confirm).pack(pady=16, padx=32, fill="x")
        self.bind("<Return>", lambda e: self._confirm())

    def _confirm(self, event=None):
        if time.time() - self._creation_time < 0.25:
            return  # Prevent scanner's trailing Enter key from auto-confirming
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


class StaffDialog(ctk.CTkToplevel):
    """
    Modal dialog for Add / Edit staff.
    Result is stored in self.result dict (or None if cancelled).
    """

    def __init__(self, parent, title="Add Record", staff: dict = None):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.geometry("440x550")
        self.resizable(False, False)
        self.configure(fg_color=C_CARD)
        self.grab_set()
        self.focus_set()

        # Register validations
        vcmd_int = self.register(lambda P: P == "" or P.isdigit())
        vcmd_float = self.register(self._validate_float)

        # Title label
        ctk.CTkLabel(self, text=title, font=(FONT, 18, "bold")).pack(pady=(24, 14))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=32)

        def _lbl(text):
            ctk.CTkLabel(form, text=text, font=(FONT, 12),
                         text_color=C_TEXT_DIM, anchor="w").pack(fill="x", pady=(8, 2))

        # ---- Name ----
        _lbl("Name *")
        self.e_name = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                    fg_color=C_CARD2, border_color=C_BORDER)
        self.e_name.pack(fill="x")

        # ---- Phone ----
        _lbl("Phone Number")
        self.e_phone = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                     fg_color=C_CARD2, border_color=C_BORDER,
                                     validate="key", validatecommand=(vcmd_int, "%P"))
        self.e_phone.pack(fill="x")

        # ---- Role (combobox) ----
        _lbl("Role")
        roles = ["Staff", "Manager", "Cashier", "Owner"]
        self.e_role = ctk.CTkComboBox(
            form, values=roles, height=38, font=(FONT, 13),
            fg_color=C_CARD2, border_color=C_BORDER,
            button_color=C_CARD2, button_hover_color=C_BORDER,
            dropdown_fg_color=C_CARD2
        )
        self.e_role.set(roles[0])
        self.e_role.pack(fill="x")

        # ---- Status (combobox) ----
        _lbl("Working Status")
        statuses = ["Working", "Not Working", "Active", "Inactive"]
        self.e_status = ctk.CTkComboBox(
            form, values=statuses, height=38, font=(FONT, 13),
            fg_color=C_CARD2, border_color=C_BORDER,
            button_color=C_CARD2, button_hover_color=C_BORDER,
            dropdown_fg_color=C_CARD2
        )
        self.e_status.set(statuses[0])
        self.e_status.pack(fill="x")

        # ---- Salary ----
        _lbl("Salary")
        self.e_salary = ctk.CTkEntry(form, height=38, font=(FONT, 13),
                                      fg_color=C_CARD2, border_color=C_BORDER,
                                      validate="key", validatecommand=(vcmd_float, "%P"))
        self.e_salary.pack(fill="x")

        # Pre-fill when editing
        self._is_edit = bool(staff)
        if staff:
            self.e_name.insert(0, staff.get("name", ""))
            self.e_phone.insert(0, staff.get("phone", ""))
            self.e_role.set(staff.get("role", "Staff"))
            self.e_status.set(staff.get("status", "Active"))
            self.e_salary.insert(0, str(staff.get("salary", 0.0)))
        else:
            self.e_salary.insert(0, "0.0")

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=32, pady=22)
        ctk.CTkButton(btn_row, text="Cancel", fg_color=C_CARD2,
                      hover_color=C_BORDER, command=self.destroy, width=120).pack(side="left")
        ctk.CTkButton(btn_row, text="Save", fg_color=C_ACCENT,
                      hover_color=C_ACCENT_HVR, command=self._save, width=120).pack(side="right")

        self.e_name.focus_set()
        self.bind("<Return>", lambda e: self._save())

    def _validate_float(self, P):
        if P == "" or P == ".":
            return True
        try:
            float(P)
            return True
        except ValueError:
            return False

    def _save(self):
        name   = self.e_name.get().strip()
        phone  = self.e_phone.get().strip()
        role   = self.e_role.get().strip() or "Staff"
        status = self.e_status.get().strip() or "Active"
        sal_raw = self.e_salary.get().strip() or "0"

        if not name:
            messagebox.showerror("Required Field", "Name is required.", parent=self)
            return

        try:
            salary = float(sal_raw)
            assert salary >= 0
        except (ValueError, AssertionError):
            messagebox.showerror("Invalid Salary", "Salary must be a positive number.", parent=self)
            return

        self.result = {"name": name, "phone": phone, "role": role, "status": status, "salary": salary}
        self.destroy()


class LoginApp(ctk.CTk):
    """Modern, sleek Login window using CustomTkinter styles."""

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.authenticated = False
        self.username = ""
        self.role = ""

        self.title("Store Inventory Pro - Login")
        self.geometry("380x420")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)

        # Center on screen
        self.update_idletasks()
        w = self.winfo_screenwidth()
        h = self.winfo_screenheight()
        x = (w // 2) - 190
        y = (h // 2) - 210
        self.geometry(f"+{x}+{y}")

        # Title / Logo
        ctk.CTkLabel(self, text="🏪  InvManager Pro", font=(FONT, 20, "bold"), text_color=C_TEXT).pack(pady=(40, 4))
        ctk.CTkLabel(self, text="Sign in to your account", font=(FONT, 12), text_color=C_TEXT_DIM).pack(pady=(0, 24))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=40)

        # Username
        ctk.CTkLabel(form, text="Username", font=(FONT, 12), text_color=C_TEXT_DIM, anchor="w").pack(fill="x", pady=(8, 2))
        self.e_user = ctk.CTkEntry(form, height=40, font=(FONT, 13), fg_color=C_CARD, border_color=C_BORDER)
        self.e_user.pack(fill="x")

        # Password
        ctk.CTkLabel(form, text="Password", font=(FONT, 12), text_color=C_TEXT_DIM, anchor="w").pack(fill="x", pady=(12, 2))
        self.e_pass = ctk.CTkEntry(form, height=40, show="*", font=(FONT, 13), fg_color=C_CARD, border_color=C_BORDER)
        self.e_pass.pack(fill="x")

        # Submit button
        self.btn_login = ctk.CTkButton(self, text="Sign In", fg_color=C_ACCENT, hover_color=C_ACCENT_HVR,
                                      height=44, font=(FONT, 13, "bold"), command=self._login)
        self.btn_login.pack(pady=32, padx=40, fill="x")

        self.bind("<Return>", lambda e: self._login())
        self.e_user.focus_set()

    def _login(self):
        username = self.e_user.get().strip()
        password = self.e_pass.get().strip()

        if not username or not password:
            messagebox.showerror("Error", "Please fill in all fields.", parent=self)
            return

        role = self.db.authenticate_user(username, password)
        if role:
            self.authenticated = True
            self.username = username
            self.role = role
            self.destroy()
        else:
            messagebox.showerror("Unauthorized", "Invalid username or password.", parent=self)


class ManageUsersDialog(ctk.CTkToplevel):
    """Modal window to add and delete user logins (accessible by Admin only)."""

    def __init__(self, parent, db: DatabaseManager):
        super().__init__(parent)
        self.db = db
        self.title("Manage User Logins")
        self.geometry("500x480")
        self.resizable(False, False)
        self.configure(fg_color=C_CARD)
        self.grab_set()
        self.focus_set()

        # Title
        ctk.CTkLabel(self, text="🔑  User Login Accounts", font=(FONT, 18, "bold")).pack(pady=(20, 10))

        # Form Frame
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=28, pady=10)

        # Fields: Username, Password, Role
        ctk.CTkLabel(form, text="New Username", font=(FONT, 11), text_color=C_TEXT_DIM).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ctk.CTkLabel(form, text="Password", font=(FONT, 11), text_color=C_TEXT_DIM).grid(row=0, column=1, padx=4, pady=2, sticky="w")
        ctk.CTkLabel(form, text="Role", font=(FONT, 11), text_color=C_TEXT_DIM).grid(row=0, column=2, padx=4, pady=2, sticky="w")

        self.e_user = ctk.CTkEntry(form, width=130, height=34, font=(FONT, 12), fg_color=C_CARD2, border_color=C_BORDER)
        self.e_user.grid(row=1, column=0, padx=4, pady=2)

        self.e_pass = ctk.CTkEntry(form, width=130, height=34, font=(FONT, 12), fg_color=C_CARD2, border_color=C_BORDER)
        self.e_pass.grid(row=1, column=1, padx=4, pady=2)

        self.e_role = ctk.CTkComboBox(form, values=["staff", "admin"], width=90, height=34, font=(FONT, 12),
                                      fg_color=C_CARD2, border_color=C_BORDER)
        self.e_role.set("staff")
        self.e_role.grid(row=1, column=2, padx=4, pady=2)

        ctk.CTkButton(form, text="＋ Add", fg_color=C_ACCENT, hover_color=C_ACCENT_HVR, width=70, height=34,
                      command=self._add_user).grid(row=1, column=3, padx=4, pady=2)

        # List Frame
        list_frame = ctk.CTkFrame(self, fg_color=C_CARD2, corner_radius=8)
        list_frame.pack(fill="both", expand=True, padx=28, pady=(10, 20))

        # Scrollbar and Treeview for Users
        vsb = ttk.Scrollbar(list_frame)
        vsb.pack(side="right", fill="y")

        self.tree = ttk.Treeview(list_frame, columns=("username", "role"), show="headings",
                                 style="T.Treeview", yscrollcommand=vsb.set, selectmode="browse")
        vsb.configure(command=self.tree.yview)

        self.tree.heading("username", text="Username", anchor="center")
        self.tree.heading("role", text="Access Role", anchor="center")
        self.tree.column("username", width=220, anchor="center")
        self.tree.column("role", width=180, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=2, pady=2)

        # Delete Button
        ctk.CTkButton(self, text="🗑  Delete Selected User", fg_color="#3B1A1A", hover_color=C_DANGER,
                      height=36, command=self._delete_user).pack(pady=(0, 20))

        self._refresh_users()

    def _refresh_users(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for u in self.db.get_all_users():
            self.tree.insert("", "end", iid=u["username"], values=(u["username"], u["role"].capitalize()))

    def _add_user(self):
        user = self.e_user.get().strip().lower()
        pwd = self.e_pass.get().strip()
        role = self.e_role.get().strip().lower()

        if not user or not pwd:
            messagebox.showerror("Error", "Username and password cannot be empty.", parent=self)
            return

        if self.db.add_user(user, pwd, role):
            self._refresh_users()
            self.e_user.delete(0, "end")
            self.e_pass.delete(0, "end")
            messagebox.showinfo("Success", f"User '{user}' added successfully.", parent=self)
        else:
            messagebox.showerror("Error", f"Could not add user. Username may already exist.", parent=self)

    def _delete_user(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a user to delete.", parent=self)
            return
        username = sel[0]

        if username in ("admin", "staff"):
            messagebox.showerror("Forbidden", "Default users 'admin' and 'staff' cannot be deleted.", parent=self)
            return

        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete user '{username}'?", parent=self):
            if self.db.delete_user(username):
                self._refresh_users()
                messagebox.showinfo("Deleted", f"User '{username}' deleted.", parent=self)
            else:
                messagebox.showerror("Error", "Could not delete user.", parent=self)


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

    def __init__(self, db: DatabaseManager, username: str, user_role: str):
        super().__init__()
        self.db = db
        self.username = username
        self.user_role = user_role

        # Window
        self.title(f"Inventory Manager Pro (Logged in as: {self.username} [{self.user_role.capitalize()}])")
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
        self._current_bill: dict = {}

        self._build_sidebar()
        self._build_content()
        self._apply_tree_style()

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

    # Mobile scanner bridge functions removed

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

    def _start_b2w_refund(self):
        self._refund_entry.focus_set()
        if hasattr(self, "_cam_status_refund") and self._cam_status_refund:
            self._cam_status_refund.configure(text="Ready for Barcode2win...", text_color=C_SUCCESS)
            self.after(4000, lambda: self._cam_status_refund.configure(text=""))

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
        nav_items = [
            ("inventory", "📦", "Inventory"),
            ("sales",     "🛒", "Sales"),
            ("refund",    "↩", "Refund"),
        ]
        if self.user_role == "admin":
            nav_items.extend([
                ("restock",      "📥", "Restock"),
                ("transactions", "🧾", "Transactions"),
                ("reports",      "📊", "Reports"),
                ("staff",        "👥", "Staff"),
            ])

        for name, icon, label in nav_items:
            btn = SidebarButton(sb, text=label, icon=icon,
                                command=lambda v=name: self.show_view(v))
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_btns[name] = btn

        # Mobile Link button removed

        ctk.CTkLabel(sb, text="SQLite  •  Local Only", font=(FONT, 10),
                     text_color=C_TEXT_DIM).pack(side="bottom", pady=16)

    # _open_mobile_link_window removed

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
        if self.user_role != "admin" and name in ("restock", "reports", "staff"):
            messagebox.showerror("Permission Denied", "You do not have permission to access this section.")
            return

        if self._active_view in ("sales", "restock", "refund"):
            self._scan_focus_active = False

        for n, b in self._nav_btns.items():
            b.set_active(n == name)

        for f in self._views.values():
            f.pack_forget()

        if name not in self._views:
            self._views[name] = getattr(self, f"_build_{name}_view")()

        self._views[name].pack(fill="both", expand=True)
        self._active_view = name

        if name in ("sales", "restock", "refund"):
            self._scan_focus_active = True
            self._scan_focus_tick()

        if name == "inventory":
            self._inv_refresh()
        elif name == "reports":
            self._reports_refresh()
        elif name == "sales":
            self._sales_load_log()
        elif name == "refund":
            self._refund_load_log()
        elif name == "restock":
            self._restock_load_log()
        elif name == "staff":
            self._staff_refresh()
        elif name == "transactions":
            self._transactions_refresh()

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

        if self.user_role == "admin":
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
            "name":     ("Product Name", 260, "center"),
            "quantity": ("Qty",           65, "center"),
            "price":    ("Price (PKR)",  140, "center"),
            "expiry":   ("Expiry Date",  130, "center"),
            "barcode":  ("Barcode",      160, "center"),
        }
        for col, (heading, width, anchor) in cols.items():
            self._inv_tree.heading(col, text=heading, anchor="center")
            self._inv_tree.column(col, width=width, minwidth=30, anchor="center")

        self._inv_tree.bind("<Button-1>", self._tree_click)
        self._inv_tree.tag_configure("out_of_stock", foreground="#ff4c4c", font=(FONT, 11, "bold"))
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
            if p["quantity"] <= 0:
                tag = "out_of_stock"
            elif p["quantity"] < 5:
                tag = "low"
            else:
                tag = "normal"
            if 0 < p["quantity"] < 5:
                low_n += 1
            chk = "☑" if p["barcode"] in self._checked_barcodes else "☐"
            
            qty_display = "OUT OF STOCK" if p["quantity"] <= 0 else p["quantity"]
            
            self._inv_tree.insert("", "end", iid=p["barcode"], tags=(tag,),
                                   values=(chk, p["name"],
                                           qty_display, format_price(p["price"]),
                                           p.get("expiry", "N/A"), p["barcode"]))

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
                                     d["quantity"], d["price"], d.get("original_price", 0.0), d.get("expiry", "N/A"),
                                     user_role=self.user_role)
            if ok:
                self._search_var.set("")
                self._inv_refresh()
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
                                   d["quantity"], d["price"], d.get("original_price", 0.0), d.get("expiry", "N/A"),
                                   user_role=self.user_role)
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
                self.db.delete_product(bc, user_role=self.user_role)
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

        ctk.CTkLabel(scan_card, text="READY TO SCAN / SEARCH BY NAME",
                     font=(FONT, 10, "bold"), text_color=C_TEXT_DIM).pack(pady=(16, 4))

        # Idle border is subtle grey — flashes green/red on result
        self._sale_entry = FlashEntry(
            scan_card,
            placeholder_text="Scan barcode or type name...",
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
        self._sale_entry.bind("<Down>", lambda e: self.sales_results_tree.focus_set() if self.results_frame.winfo_manager() else None)

        # Search results frame
        self.results_frame = ctk.CTkFrame(left, fg_color=C_CARD, corner_radius=14,
                                           border_width=1, border_color=C_BORDER)
        # Hidden by default

        ctk.CTkLabel(self.results_frame, text="🔍  Search Results", font=(FONT, 11, "bold"), text_color=C_TEXT_DIM).pack(pady=(8, 2))

        vsb = ttk.Scrollbar(self.results_frame)
        vsb.pack(side="right", fill="y")

        self.sales_results_tree = ttk.Treeview(
            self.results_frame, columns=("name", "price", "stock"), show="headings",
            style="T.Treeview", yscrollcommand=vsb.set, selectmode="browse", height=5
        )
        vsb.configure(command=self.sales_results_tree.yview)

        self.sales_results_tree.heading("name", text="Product Name", anchor="center")
        self.sales_results_tree.heading("price", text="Price", anchor="center")
        self.sales_results_tree.heading("stock", text="Stock", anchor="center")

        self.sales_results_tree.column("name", width=200, anchor="center")
        self.sales_results_tree.column("price", width=80, anchor="center")
        self.sales_results_tree.column("stock", width=60, anchor="center")

        self.sales_results_tree.pack(fill="both", expand=True, padx=8, pady=(2, 8))

        self.sales_results_tree.bind("<Double-1>", self._on_result_double_click)
        self.sales_results_tree.bind("<Return>", self._on_result_double_click)



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

        # Top section of footer for totals
        totals_frame = ctk.CTkFrame(footer, fg_color="transparent")
        totals_frame.pack(fill="x", padx=16, pady=(12, 0))
        
        self._bill_subtotal_lbl = ctk.CTkLabel(totals_frame, text="Subtotal: PKR 0.00",
                                               font=(FONT, 13), text_color=C_TEXT_DIM)
        self._bill_subtotal_lbl.pack(side="top", anchor="e")
        
        self._bill_discount_lbl = ctk.CTkLabel(totals_frame, text="Discount: - PKR 0.00",
                                               font=(FONT, 13), text_color=C_DANGER)
        self._bill_discount_lbl.pack(side="top", anchor="e")

        # Bottom section of footer for buttons and discount input
        controls_frame = ctk.CTkFrame(footer, fg_color="transparent")
        controls_frame.pack(fill="x", padx=16, pady=(8, 16))

        # Left side: Total Price
        self._bill_total_lbl = ctk.CTkLabel(controls_frame, text="Total: PKR 0.00",
                                            font=(FONT, 18, "bold"), text_color=C_ACCENT)
        self._bill_total_lbl.pack(side="left")

        # Right side: Buttons
        ctk.CTkButton(controls_frame, text="Confirm Bill", font=(FONT, 13, "bold"),
                      fg_color=C_SUCCESS, hover_color="#2EA043", width=120, height=40,
                      command=self._confirm_bill).pack(side="right", padx=(10, 0))
                      
        ctk.CTkButton(controls_frame, text="Clear Bill", font=(FONT, 13, "bold"),
                      fg_color="#3B1A1A", hover_color=C_DANGER, width=100, height=40,
                      command=self._clear_bill).pack(side="right", padx=(10, 0))

        # Right side (before buttons): Discount Input
        self._discount_var = ctk.StringVar(value="")
        self._discount_var.trace_add("write", lambda *args: self._refresh_bill_ui())
        
        self._discount_entry = ctk.CTkEntry(controls_frame, textvariable=self._discount_var,
                                            width=80, height=34, font=(FONT, 12),
                                            placeholder_text="0.00",
                                            fg_color=C_BG, border_color=C_BORDER)
        self._discount_entry.pack(side="right", padx=(10, 0))

        self._discount_type = ctk.StringVar(value="Flat")
        self._discount_type.trace_add("write", lambda *args: self._refresh_bill_ui())
        
        ctk.CTkComboBox(controls_frame, variable=self._discount_type,
                        values=["Flat", "%"], width=70, height=34,
                        font=(FONT, 12), fg_color=C_CARD, border_color=C_BORDER,
                        state="readonly").pack(side="right")

        return frame

    # ── Ghost Focus Loop ──────────────────────────────────────────────

    def _sales_load_log(self):
        """Reset the Current Bill when the Sales view is opened."""
        if not hasattr(self, "_sale_log"):
            return
        self._clear_bill()

    # ── Core sale processor ───────────────────────────────────────────

    def _on_sale_key_release(self, event):
        if event.keysym in ("Return", "Tab", "Down", "Up"):
            return
        if hasattr(self, "_sale_debounce") and self._sale_debounce:
            self.after_cancel(self._sale_debounce)
        self._sale_debounce = self.after(300, self._check_sales_search)

    def _check_sales_search(self):
        query = self._sale_entry.get().strip()
        if not query:
            self._hide_sales_results()
            return

        # 1. Check if it's an exact barcode match
        product = self.db.find_by_barcode(query)
        if product:
            # Clear entry and process automatically
            self._sale_entry.delete(0, "end")
            self._hide_sales_results()
            self._process_sale(barcode=query)
            return

        # 2. Otherwise search products by name
        results = self.db.search_products(query)
        if results:
            self._show_sales_results(results)
        else:
            self._hide_sales_results()

    def _show_sales_results(self, products):
        if not self.results_frame.winfo_manager():
            self.results_frame.pack(fill="both", expand=False, pady=(0, 12))

        for row in self.sales_results_tree.get_children():
            self.sales_results_tree.delete(row)

        for p in products:
            price_val = f"{p['price']:.2f}"
            self.sales_results_tree.insert("", "end", iid=p["barcode"],
                                           values=(p["name"], price_val, p["quantity"]))

    def _hide_sales_results(self):
        if self.results_frame.winfo_manager():
            self.results_frame.pack_forget()

    def _on_result_double_click(self, event=None):
        sel = self.sales_results_tree.selection()
        if not sel:
            return
        barcode = sel[0]
        self._sale_entry.delete(0, "end")
        self._hide_sales_results()
        self._process_sale(barcode=barcode)

    def _process_sale(self, _=None, barcode: str | None = None):
        if hasattr(self, "_sale_debounce") and self._sale_debounce:
            self.after_cancel(self._sale_debounce)
            self._sale_debounce = None

        if barcode is None:
            raw = self._sale_entry.get()
            self._sale_entry.delete(0, "end")
        else:
            raw = barcode

        self._hide_sales_results()

        bc = _sanitise_barcode(raw)
        if not bc:
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
        if self.user_role != "admin":
            messagebox.showerror("Permission Denied", "Only administrators can add new products.")
            return
        cats = self.db.get_categories()
        # Pre-populate only the barcode field
        stub = {"barcode": barcode, "name": "", "category": "General",
                "quantity": 0, "original_price": 0.0, "price": 0.0}
        dlg = ProductDialog(self, "Add New Product", product=stub, categories=cats)
        # Unlock barcode field so it shows but allow editing name etc.
        dlg.e_barcode.configure(state="normal")
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            ok = self.db.add_product(d["barcode"], d["name"], d["category"],
                                     d["quantity"], d["price"], d.get("original_price", 0.0), d.get("expiry", "N/A"),
                                     user_role=self.user_role)
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

    def _get_discount_val(self) -> float:
        if not hasattr(self, "_discount_var"):
            return 0.0
        val_str = self._discount_var.get().strip()
        if not val_str:
            return 0.0
        try:
            val = float(val_str)
            return val if val > 0 else 0.0
        except ValueError:
            return 0.0

    def _refresh_bill_ui(self):
        for w in self._sale_log_rows:
            w.destroy()
        self._sale_log_rows.clear()
        
        subtotal_price = 0.0
        total_items = 0
        
        for bc, item in self._current_bill.items():
            subtotal = item["qty"] * item["price"]
            subtotal_price += subtotal
            total_items += item["qty"]
            self._sale_log_insert_row(
                qty=item["qty"],
                name=item["name"],
                price=format_price(item["price"]),
                subtotal=format_price(subtotal)
            )
            
        discount_val = self._get_discount_val()
        discount_amt = 0.0
        discount_text = "- PKR 0.00"
        
        if discount_val > 0:
            if self._discount_type.get() == "Flat":
                discount_amt = min(discount_val, subtotal_price)
                discount_text = f"- {format_price(discount_amt)}"
            else: # Percentage
                pct = min(discount_val, 100.0)
                discount_amt = subtotal_price * (pct / 100.0)
                discount_text = f"- {pct}% ({format_price(discount_amt)})"
                
        final_total = max(0.0, subtotal_price - discount_amt)
        
        self._bill_subtotal_lbl.configure(text=f"Subtotal: {format_price(subtotal_price)}")
        self._bill_discount_lbl.configure(text=f"Discount: {discount_text}")
        self._bill_total_lbl.configure(text=f"Total: {format_price(final_total)}")
        
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
        if hasattr(self, "_discount_var"):
            self._discount_var.set("")
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
            
        import uuid
        tracking_id = "TRK-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + str(uuid.uuid4().hex[:4]).upper()
        
        subtotal_amount = 0.0
        total_items = 0
        total_profit = 0.0
        
        for bc, item in self._current_bill.items():
            qty = item["qty"]
            sell_price = item["price"]
            subtotal_amount += qty * sell_price
            total_items += qty
            
            # Fetch original price for profit calc
            product = self.db.find_by_barcode(bc)
            if product:
                orig_price = product.get("original_price", 0.0)
                total_profit += (sell_price - orig_price) * qty

        # Apply Discount
        discount_val = self._get_discount_val()
        discount_amt = 0.0
        discount_type_str = "None"
        
        if discount_val > 0:
            if self._discount_type.get() == "Flat":
                discount_amt = min(discount_val, subtotal_amount)
                discount_type_str = f"Flat (PKR {discount_val})"
            else:
                pct = min(discount_val, 100.0)
                discount_amt = subtotal_amount * (pct / 100.0)
                discount_type_str = f"Percentage ({pct}%)"
                
        final_total = max(0.0, subtotal_amount - discount_amt)
        final_profit = total_profit - discount_amt
        
        self.db.create_transaction(tracking_id, final_total, total_items, final_profit, discount_amt, discount_type_str)
            
        for bc, item in self._current_bill.items():
            status, product = self.db.update_stock(bc, -item["qty"])
            if status == "ok":
                unit_price = item["price"]
                subtotal = item["qty"] * unit_price
                self.db.log_sale(tracking_id, bc, product["name"], item["qty"], product["quantity"],
                                 unit_price=unit_price, total_amount=subtotal)
                
        self._toast(f"✅  Bill Confirmed: {total_items} items sold. ID: {tracking_id}")
        play_beep(True)
        self._clear_bill()
        
        if "inventory" in self._views:
            self._inv_refresh(self._search_var.get()
                              if hasattr(self, "_search_var") else "")
        if hasattr(self, "_oos_tree"):
            self._restock_refresh_dashboard()

    # Alias kept so nothing else breaks
    def _on_sale_scan(self, event=None):
        self._process_sale(event)


    # ==================================================================
    #  REFUND VIEW  —  Product Refund & Returns Interface
    # ==================================================================

    def _build_refund_view(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.content, fg_color=C_BG, corner_radius=0)

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(24, 0))
        ctk.CTkLabel(hdr, text="↩  Product Refund & Returns",
                     font=(FONT, 22, "bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(hdr, text="● RETURN MODE",
                     font=(FONT, 11, "bold"), text_color=C_ACCENT).pack(side="left", padx=12)

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

        ctk.CTkLabel(scan_card, text="ENTER TRANSACTION TRACKING ID",
                     font=(FONT, 10, "bold"), text_color=C_TEXT_DIM).pack(pady=(16, 4))

        self._refund_entry = FlashEntry(
            scan_card,
            placeholder_text="e.g. TRK-20231025...",
            height=64,
            font=(FONT, 22, "bold"),
            fg_color=C_CARD2,
            border_color=C_BORDER,
            border_width=2,
            justify="center",
        )
        self._refund_entry.pack(fill="x", padx=20, pady=(0, 10))
        self._refund_entry.bind("<Return>", self._on_tracking_id_scan)

        # Search results frame for refund name search
        self.refund_results_frame = ctk.CTkFrame(left, fg_color=C_CARD, corner_radius=14,
                                                 border_width=1, border_color=C_BORDER)
        self.refund_results_frame.pack(fill="both", expand=True, pady=(0, 12))

        ctk.CTkLabel(self.refund_results_frame, text="🔍  Transaction Items (Double Click to Refund)", font=(FONT, 11, "bold"), text_color=C_TEXT_DIM).pack(pady=(12, 4))

        vsb = ttk.Scrollbar(self.refund_results_frame)
        vsb.pack(side="right", fill="y", pady=10)

        self.refund_results_tree = ttk.Treeview(
            self.refund_results_frame, columns=("id", "name", "qty_bought", "qty_refunded", "barcode"), show="headings",
            style="T.Treeview", yscrollcommand=vsb.set, selectmode="browse", height=8
        )
        vsb.configure(command=self.refund_results_tree.yview)

        self.refund_results_tree.heading("id", text="Log ID", anchor="center")
        self.refund_results_tree.heading("name", text="Product Name", anchor="w")
        self.refund_results_tree.heading("qty_bought", text="Bought", anchor="center")
        self.refund_results_tree.heading("qty_refunded", text="Refunded", anchor="center")
        self.refund_results_tree.heading("barcode", text="Barcode", anchor="center")

        self.refund_results_tree.column("id", width=0, stretch=tk.NO) # Hidden
        self.refund_results_tree.column("name", width=180, anchor="w")
        self.refund_results_tree.column("qty_bought", width=70, anchor="center")
        self.refund_results_tree.column("qty_refunded", width=70, anchor="center")
        self.refund_results_tree.column("barcode", width=0, stretch=tk.NO) # Hidden

        self.refund_results_tree.pack(fill="both", expand=True, padx=12, pady=(2, 12))

        self.refund_results_tree.bind("<Double-1>", self._refund_tree_double_click)
        self.refund_results_tree.bind("<Return>", self._refund_tree_double_click)

        # ════════════ RIGHT PANEL ═════════════════════════════════════
        right = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=14,
                             border_width=1, border_color=C_BORDER)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        log_hdr = ctk.CTkFrame(right, fg_color="transparent")
        log_hdr.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(log_hdr, text="📋  Return History Log",
                     font=(FONT, 14, "bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(log_hdr, text="Recent Returns",
                     font=(FONT, 11), text_color=C_TEXT_DIM).pack(side="right")

        vsb_rf = ttk.Scrollbar(right)
        vsb_rf.pack(side="right", fill="y", padx=(0, 4), pady=(0, 16))

        rf_cols = ("time", "barcode", "name", "qty", "stock")
        self._rf_tree = ttk.Treeview(
            right, columns=rf_cols, show="headings",
            style="T.Treeview", yscrollcommand=vsb_rf.set, selectmode="browse"
        )
        vsb_rf.configure(command=self._rf_tree.yview)

        cols = {
            "time":    ("Time",         90,  "center"),
            "barcode": ("Barcode",      130, "center"),
            "name":    ("Product Name", 180, "center"),
            "qty":     ("Returned",     80,  "center"),
            "stock":   ("New Stock",    80,  "center"),
        }
        for col, (heading, width, anchor) in cols.items():
            self._rf_tree.heading(col, text=heading, anchor="center")
            self._rf_tree.column(col, width=width, minwidth=30, anchor="center")

        self._rf_tree.tag_configure("odd",  background=C_CARD)
        self._rf_tree.tag_configure("even", background=C_CARD2)
        self._rf_tree.pack(fill="both", expand=True, padx=(16, 0), pady=(0, 16))

        self._refund_load_log()
        return frame

    def _refund_load_log(self):
        if not hasattr(self, "_rf_tree"):
            return
        for item in self._rf_tree.get_children():
            self._rf_tree.delete(item)

        rows = self.db.get_recent_restocks(limit=50)
        for idx, r in enumerate(rows):
            t_str = r["timestamp"].split(" ")[1] if " " in r["timestamp"] else r["timestamp"]
            tag = "even" if idx % 2 == 0 else "odd"
            self._rf_tree.insert("", "end",
                                  values=(t_str, r["barcode"], r["name"],
                                          f"+{r['quantity_added']}", r["remaining_qty"]),
                                  tags=(tag,))

    def _on_tracking_id_scan(self, event=None):
        tracking_id = self._refund_entry.get().strip()
        if not tracking_id:
            return
        
        items = self.db.get_transaction_items(tracking_id)
        
        for row in self.refund_results_tree.get_children():
            self.refund_results_tree.delete(row)
            
        if not items:
            self._refund_entry.flash_custom("#dc3545", 300)
            play_beep(False)
            self._toast("Tracking ID not found.", ms=2000)
            return
            
        self._refund_entry.flash_custom("#28a745", 300)
        play_beep(True)
        
        for item in items:
            self.refund_results_tree.insert("", "end", iid=item["id"],
                                            values=(item["id"], item["name"], item["quantity_sold"],
                                                    item["quantity_refunded"], item["barcode"]))

    def _refund_tree_double_click(self, event=None):
        sel = self.refund_results_tree.selection()
        if not sel:
            return
        log_id_str = sel[0]
        
        item_values = self.refund_results_tree.item(log_id_str, "values")
        if not item_values:
            return
            
        log_id = int(item_values[0])
        name = item_values[1]
        qty_bought = int(item_values[2])
        qty_refunded = int(item_values[3])
        barcode = item_values[4]
        
        max_refund = qty_bought - qty_refunded
        if max_refund <= 0:
            messagebox.showinfo("Fully Refunded", f"{name} has already been fully refunded for this transaction.")
            return
            
        dlg = ctk.CTkInputDialog(text=f"Refunding: {name}\nMax available to refund: {max_refund}\n\nEnter quantity to refund:", title="Refund Item")
        result = dlg.get_input()
        
        if not result:
            return
            
        try:
            refund_qty = int(result)
            if refund_qty <= 0:
                raise ValueError
            if refund_qty > max_refund:
                messagebox.showerror("Invalid Quantity", f"Cannot refund more than {max_refund}.")
                return
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid positive number.")
            return
            
        ok = self.db.process_refund_item(log_id, barcode, refund_qty)
        if ok:
            play_beep(True)
            self._toast(f"✅ Refunded {refund_qty} of {name}")
            self._refund_load_log()
            if hasattr(self, "_inv_tree"):
                self._inv_refresh()
                
            new_refunded = qty_refunded + refund_qty
            self.refund_results_tree.item(log_id_str, values=(log_id, name, qty_bought, new_refunded, barcode))
        else:
            messagebox.showerror("Error", "Could not process refund.")


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

        ctk.CTkLabel(frame, text="⚠ Out of Stock", font=(FONT, 14, "bold"),
                     text_color=C_DANGER).pack(anchor="w", padx=28, pady=(6, 4))
        
        oos_tbl = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=12)
        oos_tbl.pack(fill="x", padx=28, pady=(0, 10))
        self._oos_tree = ttk.Treeview(oos_tbl, columns=("name", "barcode"), show="headings", height=4, style="T.Treeview")
        self._oos_tree.heading("name", text="Out of Stock Items", anchor="w")
        self._oos_tree.heading("barcode", text="Barcode", anchor="center")
        self._oos_tree.column("name", width=350, anchor="w")
        self._oos_tree.column("barcode", width=150, anchor="center")
        self._oos_tree.tag_configure("oos", foreground="#ff4c4c", font=(FONT, 11, "bold"))
        self._oos_tree.pack(fill="both", expand=True, padx=2, pady=2)

        ctk.CTkLabel(frame, text="Restock Log", font=(FONT, 14, "bold"),
                     text_color=C_TEXT).pack(anchor="w", padx=28, pady=(6, 4))
        self._restock_log = ctk.CTkScrollableFrame(frame, fg_color=C_CARD,
                                                    corner_radius=12, height=180)
        self._restock_log.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        self._restock_log_rows: list = []

        self._restock_refresh_dashboard()
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

    def _restock_refresh_dashboard(self):
        if not hasattr(self, "_oos_tree"):
            return
        for row in self._oos_tree.get_children():
            self._oos_tree.delete(row)
        
        products = self.db.get_all_products()
        for p in products:
            if p["quantity"] <= 0:
                self._oos_tree.insert("", "end", values=(p["name"], p["barcode"]), tags=("oos",))

    def _on_restock_key_release(self, event):
        if event.keysym in ("Return", "Tab"):
            return
        if hasattr(self, "_restock_debounce") and self._restock_debounce:
            self.after_cancel(self._restock_debounce)
        self._restock_debounce = self.after(600, self._check_auto_restock)

    def _check_auto_restock(self):
        raw = self._restock_entry.get().strip()
        if not raw: return
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
        if not bc:
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
            if hasattr(self, "_oos_tree"):
                self._restock_refresh_dashboard()
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

        # Header Row + EOD Button
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(24, 10))
        ctk.CTkLabel(hdr, text="📊  Sales & Inventory Reports", font=(FONT, 22, "bold"),
                     text_color=C_TEXT).pack(side="left")

        # EOD Compilation Button
        ctk.CTkButton(
            hdr,
            text="🌙  Run End-of-Day (EOD) Wrap-Up",
            font=(FONT, 12, "bold"),
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HVR,
            height=38,
            command=self._on_run_eod_click
        ).pack(side="right")

        # --- NEW DATE FILTER ---
        ctk.CTkLabel(hdr, text="Date Range:", font=(FONT, 12)).pack(side="right", padx=(20, 10))
        self._report_date_var = ctk.StringVar(value="All Time")
        date_combo = ctk.CTkComboBox(hdr, variable=self._report_date_var,
                                     values=["Today", "Last 7 Days", "This Month", "All Time"],
                                     width=140, height=34, font=(FONT, 12),
                                     fg_color=C_CARD2, border_color=C_BORDER,
                                     command=lambda _: self._reports_refresh())
        date_combo.pack(side="right")

        # --- SUMMARY CARDS ---
        grid = ctk.CTkFrame(frame, fg_color="transparent")
        grid.pack(fill="x", padx=28, pady=(0, 10))
        for i in range(3):
            grid.columnconfigure(i, weight=1, uniform="stat")

        self._stat_gross = StatCard(grid, "Gross Revenue",   "…", "💵", C_SUCCESS)
        self._stat_net   = StatCard(grid, "Net Profit",      "…", "📈", C_ACCENT)
        self._stat_sold  = StatCard(grid, "Total Items Sold", "…", "📦", "#A371F7")

        self._stat_gross.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._stat_net.grid(  row=0, column=1, sticky="nsew", padx=2)
        self._stat_sold.grid( row=0, column=2, sticky="nsew", padx=(4, 0))

        # --- TOP PERFORMING PRODUCTS ---
        ctk.CTkLabel(frame, text="⭐  Top Performing Products", font=(FONT, 16, "bold"),
                     text_color=C_TEXT).pack(anchor="w", padx=28, pady=(14, 4))

        top_frame = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=12)
        top_frame.pack(fill="x", padx=28, pady=(0, 10))
        
        vsb_top = ttk.Scrollbar(top_frame)
        vsb_top.pack(side="right", fill="y")
        
        self._top_tree = ttk.Treeview(
            top_frame, columns=("name", "barcode", "sold", "revenue", "profit"), show="headings",
            style="T.Treeview", yscrollcommand=vsb_top.set, height=5
        )
        vsb_top.configure(command=self._top_tree.yview)
        
        self._top_tree.heading("name",    text="Product Name", anchor="w")
        self._top_tree.heading("barcode", text="Barcode",      anchor="center")
        self._top_tree.heading("sold",    text="Units Sold",   anchor="center")
        self._top_tree.heading("revenue", text="Revenue",      anchor="center")
        self._top_tree.heading("profit",  text="Profit",       anchor="center")
        
        self._top_tree.column("name",    width=250, anchor="w")
        self._top_tree.column("barcode", width=120, anchor="center")
        self._top_tree.column("sold",    width=100, anchor="center")
        self._top_tree.column("revenue", width=120, anchor="center")
        self._top_tree.column("profit",  width=120, anchor="center")
        self._top_tree.pack(fill="both", expand=True, padx=2, pady=2)

        # --- OUT OF STOCK ANALYTICS ---
        ctk.CTkLabel(frame, text="⚠  Out of Stock Analytics (Lifetime Profit)", font=(FONT, 16, "bold"),
                     text_color=C_WARNING).pack(anchor="w", padx=28, pady=(14, 4))

        oos_frame = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=12)
        oos_frame.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        
        vsb_oos = ttk.Scrollbar(oos_frame)
        vsb_oos.pack(side="right", fill="y")
        
        self._oos_analytics_tree = ttk.Treeview(
            oos_frame, columns=("name", "barcode", "sold", "revenue", "profit"), show="headings",
            style="T.Treeview", yscrollcommand=vsb_oos.set, height=5
        )
        vsb_oos.configure(command=self._oos_analytics_tree.yview)
        
        self._oos_analytics_tree.heading("name",    text="Product Name", anchor="w")
        self._oos_analytics_tree.heading("barcode", text="Barcode",      anchor="center")
        self._oos_analytics_tree.heading("sold",    text="Units Sold",   anchor="center")
        self._oos_analytics_tree.heading("revenue", text="Revenue",      anchor="center")
        self._oos_analytics_tree.heading("profit",  text="Profit",       anchor="center")
        
        self._oos_analytics_tree.column("name",    width=250, anchor="w")
        self._oos_analytics_tree.column("barcode", width=120, anchor="center")
        self._oos_analytics_tree.column("sold",    width=100, anchor="center")
        self._oos_analytics_tree.column("revenue", width=120, anchor="center")
        self._oos_analytics_tree.column("profit",  width=120, anchor="center")
        self._oos_analytics_tree.pack(fill="both", expand=True, padx=2, pady=2)

        self._reports_refresh()
        return frame

    def _on_run_eod_click(self):
        """Triggers the End-of-Day math compilation for today's sales."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        if messagebox.askyesno("Confirm EOD Wrap-Up",
                              f"Run End-of-Day (EOD) compilation for today ({today_str})?\n\n"
                              "This will aggregate all today's transactions into a single daily summary record.",
                              parent=self):
            ok, msg, summary = self.db.run_eod_wrapup(today_str)
            if ok:
                messagebox.showinfo("EOD Wrap-Up Complete", msg, parent=self)
                self._reports_refresh()
            else:
                messagebox.showerror("EOD Error", msg, parent=self)

    def _reports_refresh(self):
        if not hasattr(self, "_stat_gross"):
            return

        date_range = self._report_date_var.get() if hasattr(self, "_report_date_var") else "All Time"

        # 1. Summary Stats
        summary = self.db.get_analytics_summary(date_range)
        self._stat_gross.update(format_price(summary["gross_revenue"]))
        self._stat_net.update(format_price(summary["net_profit"]))
        self._stat_sold.update(f"{summary['total_items_sold']:,}")

        # 2. Top Performing Products
        for row in self._top_tree.get_children():
            self._top_tree.delete(row)
        top_products = self.db.get_top_performing_products(date_range)
        for p in top_products:
            self._top_tree.insert("", "end",
                                  values=(p["name"],
                                          p["barcode"],
                                          p["total_units_sold"],
                                          format_price(p["total_revenue"]),
                                          format_price(p["total_profit"])))

        # 3. Out of Stock Analytics
        for row in self._oos_analytics_tree.get_children():
            self._oos_analytics_tree.delete(row)
        oos_products = self.db.get_sold_out_analytics(date_range)
        for p in oos_products:
            self._oos_analytics_tree.insert("", "end",
                                            values=(p["name"],
                                                    p["barcode"],
                                                    p["total_units_sold"],
                                                    format_price(p["total_revenue"]),
                                                    format_price(p["total_profit"])))

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
        elif self._active_view == "refund"  and hasattr(self, "_refund_entry"):
            target = self._refund_entry

        if target:
            try:
                # Step 1: Is any dialog/popup open?
                dialog_open = any(
                    isinstance(w, ctk.CTkToplevel) and w.winfo_viewable()
                    for w in self.winfo_children()
                )
                if not dialog_open:
                    # Step 2: Does the entry already have focus?
                    current_focus = self.focus_get()
                    if current_focus:
                        focus_path = str(current_focus)
                        allowed = [str(target)]
                        if self._active_view == "sales" and hasattr(self, "_discount_entry"):
                            allowed.append(str(self._discount_entry))
                            
                        # If current focus is not inside any of the allowed CustomTkinter widgets
                        if not any(focus_path.startswith(a) for a in allowed):
                            target.focus_set()
                    else:
                        target.focus_set()
            except Exception:
                pass   # Silently ignore transient Tk state errors

        # Schedule next check
        self.after(500, self._scan_focus_tick)


    # ==================================================================
    #  TRANSACTIONS VIEW
    # ==================================================================

    def _build_transactions_view(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.content, fg_color=C_BG, corner_radius=0)

        # Header row
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(28, 10))
        ctk.CTkLabel(hdr, text="🧾  Transaction History", font=(FONT, 22, "bold"),
                     text_color=C_TEXT).pack(side="left")

        # Filters Row
        filters_frame = ctk.CTkFrame(frame, fg_color="transparent")
        filters_frame.pack(fill="x", padx=28, pady=(0, 15))
        
        # Search Box
        ctk.CTkLabel(filters_frame, text="Search Tracking ID:", font=(FONT, 12)).pack(side="left", padx=(0, 10))
        self._txn_search_var = ctk.StringVar()
        self._txn_search_var.trace_add("write", lambda *args: self._transactions_refresh())
        search_entry = ctk.CTkEntry(filters_frame, textvariable=self._txn_search_var,
                                    width=200, height=34, font=(FONT, 13),
                                    fg_color=C_CARD2, border_color=C_BORDER,
                                    placeholder_text="e.g. TRK-2026...")
        search_entry.pack(side="left")
        
        # Date Filter
        ctk.CTkLabel(filters_frame, text="Date Range:", font=(FONT, 12)).pack(side="left", padx=(20, 10))
        self._txn_date_var = ctk.StringVar(value="All Time")
        date_combo = ctk.CTkComboBox(filters_frame, variable=self._txn_date_var,
                                     values=["Today", "This Week", "This Month", "All Time"],
                                     width=140, height=34, font=(FONT, 12),
                                     fg_color=C_CARD2, border_color=C_BORDER,
                                     command=lambda _: self._transactions_refresh())
        date_combo.pack(side="left")
        
        ctk.CTkLabel(filters_frame, text="* Double-click a row to process a refund", font=(FONT, 12, "italic"), text_color=C_TEXT_DIM).pack(side="right")

        # Transactions Table
        txn_frame = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=12)
        txn_frame.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        vsb_txn = ttk.Scrollbar(txn_frame)
        vsb_txn.pack(side="right", fill="y")

        self._txn_history_tree = ttk.Treeview(
            txn_frame, columns=("id", "amount", "items", "profit", "date"), show="headings",
            style="T.Treeview", yscrollcommand=vsb_txn.set
        )
        vsb_txn.configure(command=self._txn_history_tree.yview)

        self._txn_history_tree.heading("id",     text="Tracking ID",   anchor="center")
        self._txn_history_tree.heading("amount", text="Total Amount",  anchor="center")
        self._txn_history_tree.heading("items",  text="Total Items",   anchor="center")
        self._txn_history_tree.heading("profit", text="Total Profit",  anchor="center")
        self._txn_history_tree.heading("date",   text="Date & Time",   anchor="center")

        self._txn_history_tree.column("id",     width=200, anchor="center")
        self._txn_history_tree.column("amount", width=120, anchor="center")
        self._txn_history_tree.column("items",  width=100, anchor="center")
        self._txn_history_tree.column("profit", width=120, anchor="center")
        self._txn_history_tree.column("date",   width=160, anchor="center")
        self._txn_history_tree.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Bindings
        self._txn_history_tooltip = HoverTooltip(self._txn_history_tree)
        self._txn_history_tree.bind("<Motion>", self._on_txn_history_hover)
        self._txn_history_tree.bind("<Leave>", self._on_txn_history_leave)
        self._txn_history_tree.bind("<Double-1>", self._on_txn_history_double_click)
        
        self._cached_txn_history_items = {}

        self._transactions_refresh()
        return frame
        
    def _transactions_refresh(self):
        if not hasattr(self, "_txn_history_tree"):
            return
            
        for row in self._txn_history_tree.get_children():
            self._txn_history_tree.delete(row)
            
        search_query = self._txn_search_var.get().strip() if hasattr(self, "_txn_search_var") else ""
        date_filter = self._txn_date_var.get() if hasattr(self, "_txn_date_var") else "All Time"
        
        txns = self.db.get_transactions_with_filters(search_query, date_filter)
        
        for txn in txns:
            self._txn_history_tree.insert("", "end",
                                          values=(txn["tracking_id"],
                                                  format_price(txn["total_amount"]),
                                                  txn["total_items"],
                                                  format_price(txn["total_profit"]),
                                                  txn["timestamp"]))

    def _on_txn_history_hover(self, event):
        item_id = self._txn_history_tree.identify_row(event.y)
        if not item_id:
            self._txn_history_tooltip.hide()
            return
            
        tracking_id = self._txn_history_tree.item(item_id, "values")[0]
        
        if tracking_id not in self._cached_txn_history_items:
            items = self.db.get_transaction_items(tracking_id)
            if not items:
                self._cached_txn_history_items[tracking_id] = "No items recorded."
            else:
                lines = [f"• {i['name']} (x{i['quantity_sold']}) = {format_price(i['total_amount'])}" for i in items]
                self._cached_txn_history_items[tracking_id] = "\n".join(lines)
                
        text = self._cached_txn_history_items[tracking_id]
        self._txn_history_tooltip.show(text, event.x_root, event.y_root)

    def _on_txn_history_leave(self, event):
        self._txn_history_tooltip.hide()
        
    def _on_txn_history_double_click(self, event):
        item_id = self._txn_history_tree.identify_row(event.y)
        if not item_id:
            return
            
        tracking_id = self._txn_history_tree.item(item_id, "values")[0]
        
        # Navigate to Refund view and auto-fill
        self.show_view("refund")
        if hasattr(self, "_refund_entry"):
            self._refund_entry.delete(0, "end")
            self._refund_entry.insert(0, tracking_id)
            # Trigger the search
            self._on_tracking_id_scan()


    # ==================================================================
    #  STAFF VIEW
    # ==================================================================

    def _build_staff_view(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.content, fg_color=C_BG, corner_radius=0)

        # Header row
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(28, 0))
        ctk.CTkLabel(hdr, text="👥  Staff Management", font=(FONT, 22, "bold"),
                     text_color=C_TEXT).pack(side="left")

        btns = ctk.CTkFrame(hdr, fg_color="transparent")
        btns.pack(side="right")

        def _btn(parent, text, color, hover, cmd, pad=(0, 8)):
            ctk.CTkButton(parent, text=text, fg_color=color, hover_color=hover,
                          height=36, corner_radius=8, font=(FONT, 12),
                          command=cmd).pack(side="left", padx=pad)

        _btn(btns, "＋  Add",       C_ACCENT,   C_ACCENT_HVR, self._staff_add)
        _btn(btns, "✏  Edit",      C_CARD2,    C_BORDER,     self._staff_edit)
        _btn(btns, "🗑  Delete",    "#3B1A1A",  C_DANGER,     self._staff_delete)
        _btn(btns, "🔑  User Logins", C_CARD2,  C_BORDER,     self._manage_users, pad=(0, 0))

        # Search bar
        sf = ctk.CTkFrame(frame, fg_color="transparent")
        sf.pack(fill="x", padx=28, pady=(14, 0))
        ctk.CTkLabel(sf, text="🔍", font=(FONT, 15), text_color=C_TEXT_DIM).pack(side="left", padx=(0, 8))
        self._staff_search_var = tk.StringVar()
        self._staff_search_var.trace_add("write", self._staff_search_changed)
        ctk.CTkEntry(sf, textvariable=self._staff_search_var,
                     placeholder_text="Search by name, phone or role…",
                     height=40, font=(FONT, 13), fg_color=C_CARD,
                     border_color=C_BORDER).pack(side="left", fill="x", expand=True)

        # Treeview
        tbl = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=12)
        tbl.pack(fill="both", expand=True, padx=28, pady=14)
        vsb = ttk.Scrollbar(tbl)
        vsb.pack(side="right", fill="y")

        staff_cols = ("name", "phone", "role", "salary", "status", "date")
        self._staff_tree = ttk.Treeview(tbl, columns=staff_cols, show="headings",
                                         style="T.Treeview",
                                         yscrollcommand=vsb.set, selectmode="browse")
        vsb.configure(command=self._staff_tree.yview)

        cols = {
            "name":     ("Name",          200, "center"),
            "phone":    ("Phone Number",  140, "center"),
            "role":     ("Role",          110, "center"),
            "salary":   ("Salary",        110, "center"),
            "status":   ("Status",        110, "center"),
            "date":     ("Added Date",    160, "center"),
        }
        for col, (heading, width, anchor) in cols.items():
            self._staff_tree.heading(col, text=heading, anchor="center")
            self._staff_tree.column(col, width=width, minwidth=30, anchor="center")

        self._staff_tree.pack(fill="both", expand=True, padx=2, pady=2)

        # Status bar
        self._staff_status = ctk.CTkLabel(frame, text="", font=(FONT, 11), text_color=C_TEXT_DIM)
        self._staff_status.pack(anchor="w", padx=28, pady=(0, 10))

        self._staff_refresh()
        return frame

    # ---- Staff helpers ----

    def _staff_refresh(self, query: str = ""):
        if not hasattr(self, "_staff_tree"):
            return

        for row in self._staff_tree.get_children():
            self._staff_tree.delete(row)

        records = self.db.search_staff(query) if query else self.db.get_all_staff()

        for r in records:
            sal_val = f"{r.get('salary', 0.0):.2f}"
            self._staff_tree.insert("", "end", iid=str(r["id"]),
                                    values=(r["name"], r["phone"], r["role"], sal_val, r["status"], r["timestamp"]))

        total = len(records)
        working_count = sum(1 for r in records if r["status"].lower() == "working")
        
        status_text = f"{total} staff member{'s' if total != 1 else ''}"
        if working_count:
            status_text += f"  •  💼 {working_count} Currently Working"
            
        self._staff_status.configure(text=status_text)

    def _staff_search_changed(self, *_):
        if hasattr(self, "_staff_search_after") and self._staff_search_after:
            self.after_cancel(self._staff_search_after)
        self._staff_search_after = self.after(300, lambda: self._staff_refresh(self._staff_search_var.get()))

    def _staff_sel_id(self) -> int | None:
        sel = self._staff_tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a record first.")
            return None
        return int(sel[0])

    def _staff_add(self):
        dlg = StaffDialog(self, "Add New Staff Member")
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            ok = self.db.add_staff(d["name"], d["phone"], d["status"], d["role"], d["salary"])
            if ok:
                self._staff_refresh(self._staff_search_var.get() if hasattr(self, "_staff_search_var") else "")
                self._toast("✅  Staff record added!")
            else:
                messagebox.showerror("Error", "Could not add staff record.")

    def _staff_edit(self):
        sid = self._staff_sel_id()
        if not sid:
            return
            
        records = self.db.get_all_staff()
        record = next((r for r in records if r["id"] == sid), None)
        if not record:
            return

        dlg = StaffDialog(self, "Edit Staff Member", staff=record)
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            ok = self.db.update_staff(sid, d["name"], d["phone"], d["status"], d["role"], d["salary"])
            if ok:
                self._staff_refresh(self._staff_search_var.get() if hasattr(self, "_staff_search_var") else "")
                self._toast("✅  Staff record updated!")
            else:
                messagebox.showerror("Error", "Could not update staff record.")

    def _staff_delete(self):
        sid = self._staff_sel_id()
        if not sid:
            return

        records = self.db.get_all_staff()
        record = next((r for r in records if r["id"] == sid), None)
        name = record["name"] if record else "selected record"

        if messagebox.askyesno("Confirm Delete", f"Delete '{name}'?\n\nThis cannot be undone."):
            ok = self.db.delete_staff(sid)
            if ok:
                self._staff_refresh(self._staff_search_var.get() if hasattr(self, "_staff_search_var") else "")
                self._toast("🗑  Staff record deleted.")
            else:
                messagebox.showerror("Error", "Could not delete staff record.")

    def _manage_users(self):
        dlg = ManageUsersDialog(self, self.db)
        self.wait_window(dlg)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Initialize DB first
    db = DatabaseManager()

    # Show Login App first
    login_app = LoginApp(db)
    login_app.mainloop()

    # If authenticated, launch main app
    if login_app.authenticated:
        app = InventoryApp(db, login_app.username, login_app.role)
        app.mainloop()
