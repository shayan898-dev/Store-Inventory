import sys
import os
import time
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
import requests

# ---------------------------------------------------------------------------
# Global theme setup
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C_BG         = "#0F1117"
C_SIDEBAR    = "#161B22"
C_CARD       = "#1C2128"
C_CARD2      = "#21262D"
C_ACCENT     = "#2F81F7"
C_SUCCESS    = "#3FB950"
C_DANGER     = "#F85149"
C_TEXT       = "#E6EDF3"
C_TEXT_DIM   = "#8B949E"
C_BORDER     = "#30363D"

FONT = "Segoe UI"

# ---------------------------------------------------------------------------
# Config Management
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
    return {}

def save_config(config_data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config_data, f, indent=4)

# ---------------------------------------------------------------------------
# Setup / Login App
# ---------------------------------------------------------------------------
class StaffSetupApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Staff Terminal Setup")
        self.geometry("500x400")
        self.configure(fg_color=C_BG)
        self.config_data = load_config()
        self.api_url = self.config_data.get("API_BASE_URL", "http://localhost:3000")
        
        self.success = False
        self.staff_username = None
        self.api_base_url = None
        
        self._build_ui()
        
    def _build_ui(self):
        ctk.CTkLabel(self, text="Staff Terminal Setup", font=(FONT, 24, "bold"), text_color=C_TEXT).pack(pady=(40, 20))
        
        frame = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=10)
        frame.pack(padx=40, pady=10, fill="both", expand=True)
        
        ctk.CTkLabel(frame, text="Admin Server IP (API_BASE_URL)", font=(FONT, 12, "bold"), text_color=C_TEXT_DIM).pack(anchor="w", padx=20, pady=(20, 5))
        self.ip_entry = ctk.CTkEntry(frame, width=300, font=(FONT, 14))
        self.ip_entry.insert(0, self.api_url)
        self.ip_entry.pack(padx=20, pady=(0, 15))
        
        ctk.CTkLabel(frame, text="Staff Username", font=(FONT, 12, "bold"), text_color=C_TEXT_DIM).pack(anchor="w", padx=20, pady=(10, 5))
        self.user_entry = ctk.CTkEntry(frame, width=300, font=(FONT, 14))
        self.user_entry.pack(padx=20, pady=(0, 20))
        
        self.status_lbl = ctk.CTkLabel(frame, text="", text_color=C_DANGER, font=(FONT, 12))
        self.status_lbl.pack(pady=5)
        
        ctk.CTkButton(frame, text="Connect & Login", fg_color=C_SUCCESS, hover_color="#2EA043", font=(FONT, 14, "bold"), command=self._do_login).pack(pady=(10, 20))
        
    def _do_login(self):
        url = self.ip_entry.get().strip()
        user = self.user_entry.get().strip()
        if not user:
            self.status_lbl.configure(text="Please enter a username.", text_color=C_DANGER)
            return
            
        self.status_lbl.configure(text="Connecting to server...", text_color=C_TEXT_DIM)
        
        def _connect():
            try:
                resp = requests.post(f"{url}/api/auth/login", json={"username": user}, timeout=5)
                if resp.status_code == 200:
                    self.config_data["API_BASE_URL"] = url
                    save_config(self.config_data)
                    self.success = True
                    self.staff_username = user
                    self.api_base_url = url
                    self.after(0, self.destroy)
                else:
                    err = resp.json().get("error", "Unknown auth error")
                    self.after(0, lambda: self.status_lbl.configure(text=f"Auth Failed: {err}", text_color=C_DANGER))
            except requests.exceptions.RequestException as e:
                self.after(0, lambda: self.status_lbl.configure(text=f"Server unreachable: {e}", text_color=C_DANGER))
                
        threading.Thread(target=_connect, daemon=True).start()

# ---------------------------------------------------------------------------
# Main Staff Terminal App
# ---------------------------------------------------------------------------
class StaffTerminalApp(ctk.CTk):
    def __init__(self, api_url: str, username: str):
        super().__init__()
        self.api_url = api_url
        self.username = username
        self.title(f"Staff Terminal - {self.username}")
        self.geometry("1100x700")
        self.configure(fg_color=C_BG)
        
        self._current_bill = {} # barcode -> {name, price, qty}
        self._active_view = None
        
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True)
        
        self._views = {}
        self.show_view("sales")
        
    def _toast(self, msg: str, ms: int = 3000):
        lbl = ctk.CTkLabel(self, text=msg, font=(FONT, 14), fg_color=C_CARD2, corner_radius=10, text_color=C_TEXT, padx=20, pady=10)
        lbl.place(relx=0.5, rely=0.95, anchor="center")
        self.after(ms, lbl.destroy)
        
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=200, fg_color=C_SIDEBAR, corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)
        
        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(24, 10))
        ctk.CTkLabel(logo, text="🏪 Staff Terminal", font=(FONT, 16, "bold"), text_color=C_TEXT).pack(anchor="w")
        
        ctk.CTkButton(sb, text="🛒 Sales & POS", fg_color=C_CARD, text_color=C_TEXT, anchor="w", command=lambda: self.show_view("sales")).pack(fill="x", padx=12, pady=5)
        ctk.CTkButton(sb, text="↩ Refunds", fg_color=C_CARD, text_color=C_TEXT, anchor="w", command=lambda: self.show_view("refunds")).pack(fill="x", padx=12, pady=5)
        ctk.CTkButton(sb, text="📦 View Inventory", fg_color=C_CARD, text_color=C_TEXT, anchor="w", command=lambda: self.show_view("inventory")).pack(fill="x", padx=12, pady=5)
        
        ctk.CTkLabel(sb, text=f"Logged in as:\n{self.username}", font=(FONT, 12), text_color=C_TEXT_DIM).pack(side="bottom", pady=20)
        
    def show_view(self, name):
        for f in self._views.values():
            f.pack_forget()
        if name not in self._views:
            if name == "sales":
                self._views[name] = self._build_sales_view()
            elif name == "refunds":
                self._views[name] = self._build_refund_view()
            elif name == "inventory":
                self._views[name] = self._build_inventory_view()
        self._views[name].pack(fill="both", expand=True)
        self._active_view = name
        
    # =========================================================================
    # SALES VIEW
    # =========================================================================
    def _build_sales_view(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        
        # Left Panel (Scan)
        left = ctk.CTkFrame(frame, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        
        scan_card = ctk.CTkFrame(left, fg_color=C_CARD, corner_radius=10)
        scan_card.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(scan_card, text="SCAN OR SEARCH ITEM", font=(FONT, 12, "bold"), text_color=C_TEXT_DIM).pack(pady=(15, 5))
        self.scan_entry = ctk.CTkEntry(scan_card, font=(FONT, 18), height=50)
        self.scan_entry.pack(fill="x", padx=20, pady=(0, 15))
        self.scan_entry.bind("<Return>", self._on_scan)
        self.scan_entry.bind("<KeyRelease>", self._on_sale_key_release)
        self.scan_entry.bind("<Down>", lambda e: self.sales_results_tree.focus_set() if self.results_frame.winfo_manager() else None)
        
        self.results_frame = ctk.CTkFrame(left, fg_color=C_CARD, corner_radius=10)
        ctk.CTkLabel(self.results_frame, text="🔍 Search Results", font=(FONT, 11, "bold"), text_color=C_TEXT_DIM).pack(pady=(8, 2))
        
        self.sales_results_tree = ttk.Treeview(
            self.results_frame, columns=("name", "price", "stock"), show="headings", height=5
        )
        self.sales_results_tree.heading("name", text="Product Name")
        self.sales_results_tree.heading("price", text="Price")
        self.sales_results_tree.heading("stock", text="Stock")
        self.sales_results_tree.column("name", width=200)
        self.sales_results_tree.column("price", width=80)
        self.sales_results_tree.column("stock", width=60)
        self.sales_results_tree.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        
        self.sales_results_tree.bind("<Double-1>", self._on_result_double_click)
        self.sales_results_tree.bind("<Return>", self._on_result_double_click)
        
        self._sale_debounce = None
        self._search_results_cache = {}
        # Live Product Info
        self.prod_card = ctk.CTkFrame(left, fg_color=C_CARD, corner_radius=10)
        self.prod_card.pack(fill="both", expand=True)
        self.pc_status = ctk.CTkLabel(self.prod_card, text="Ready to scan", font=(FONT, 16), text_color=C_TEXT_DIM)
        self.pc_status.pack(pady=20)
        
        # Right Panel (Cart)
        right = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=10)
        right.pack(side="right", fill="both", expand=True, padx=(0, 20), pady=20)
        
        ctk.CTkLabel(right, text="Current Bill", font=(FONT, 16, "bold")).pack(pady=10)
        
        cols = ("Name", "Price", "Qty", "Total")
        self.cart_tree = ttk.Treeview(right, columns=cols, show="headings", height=15)
        for c in cols:
            self.cart_tree.heading(c, text=c)
        self.cart_tree.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.total_lbl = ctk.CTkLabel(right, text="Total: PKR 0.00", font=(FONT, 20, "bold"), text_color=C_SUCCESS)
        self.total_lbl.pack(pady=10)
        
        ctk.CTkButton(right, text="Send Bill to Admin", fg_color=C_SUCCESS, font=(FONT, 16, "bold"), height=50, command=self._checkout).pack(fill="x", padx=10, pady=10)
        
        return frame
        
    def _on_scan(self, event=None):
        if self._sale_debounce:
            self.after_cancel(self._sale_debounce)
            self._sale_debounce = None
            
        query = self.scan_entry.get().strip()
        self.scan_entry.delete(0, "end")
        
        if self.results_frame.winfo_manager():
            self.results_frame.pack_forget()
            
        if not query:
            return
            
        self.pc_status.configure(text="Looking up...", text_color=C_TEXT_DIM)
        
        def _lookup():
            try:
                # First try exact barcode match
                resp = requests.get(f"{self.api_url}/api/inventory/{query}", timeout=5)
                if resp.status_code == 200:
                    item = resp.json()
                    self.after(0, self._add_to_cart, item)
                else:
                    # If not found, try manual search by name
                    search_resp = requests.get(f"{self.api_url}/api/inventory?q={query}", timeout=5)
                    if search_resp.status_code == 200 and len(search_resp.json()) > 0:
                        # Auto-add the first match for simplicity in dummy terminal
                        item = search_resp.json()[0]
                        self.after(0, self._add_to_cart, item)
                    else:
                        self.after(0, lambda: self.pc_status.configure(text="Item Not Found!", text_color=C_DANGER))
            except requests.exceptions.RequestException as e:
                self.after(0, lambda: self.pc_status.configure(text=f"Server Offline", text_color=C_DANGER))
                self.after(0, lambda: self._toast("Network Error - Cannot reach Admin Server"))
                
        threading.Thread(target=_lookup, daemon=True).start()
        
    def _on_sale_key_release(self, event):
        if event.keysym in ("Return", "Down", "Up"):
            return
        
        if self._sale_debounce:
            self.after_cancel(self._sale_debounce)
            
        raw = self.scan_entry.get().strip()
        if not raw:
            if self.results_frame.winfo_manager():
                self.results_frame.pack_forget()
            return
            
        self._sale_debounce = self.after(300, lambda: self._fetch_search_results(raw))
        
    def _fetch_search_results(self, query):
        def _fetch():
            try:
                resp = requests.get(f"{self.api_url}/api/inventory?q={query}", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    self.after(0, lambda: self._show_search_results(data))
            except requests.exceptions.RequestException:
                pass # Fail silently for live search to not spam errors
        threading.Thread(target=_fetch, daemon=True).start()
        
    def _show_search_results(self, data):
        if not data:
            if self.results_frame.winfo_manager():
                self.results_frame.pack_forget()
            return
            
        for row in self.sales_results_tree.get_children():
            self.sales_results_tree.delete(row)
            
        self._search_results_cache.clear()
        
        for p in data:
            self._search_results_cache[p["barcode"]] = p
            self.sales_results_tree.insert("", "end", iid=p["barcode"], values=(
                p["name"], f"PKR {p['price']}", p.get("stock_count", 0)
            ))
            
        if not self.results_frame.winfo_manager():
            self.results_frame.pack(fill="both", expand=True, pady=(0, 20), before=self.prod_card)
            
    def _on_result_double_click(self, event=None):
        sel = self.sales_results_tree.selection()
        if not sel:
            return
        barcode = sel[0]
        product = self._search_results_cache.get(barcode)
        if product:
            self.results_frame.pack_forget()
            self.scan_entry.delete(0, "end")
            self._add_to_cart(product)
        
    def _add_to_cart(self, product):
        bc = product["barcode"]
        if bc in self._current_bill:
            self._current_bill[bc]["qty"] += 1
        else:
            self._current_bill[bc] = {
                "barcode": bc,
                "name": product["name"],
                "price": float(product["price"]),
                "qty": 1
            }
        
        self.pc_status.configure(text=f"Added: {product['name']}", text_color=C_SUCCESS)
        self._update_cart_ui()
        
    def _update_cart_ui(self):
        for item in self.cart_tree.get_children():
            self.cart_tree.delete(item)
            
        total = 0.0
        for bc, item in self._current_bill.items():
            sub = item["price"] * item["qty"]
            total += sub
            self.cart_tree.insert("", "end", values=(item["name"], f"PKR {item['price']:.2f}", item["qty"], f"PKR {sub:.2f}"))
            
        self.total_lbl.configure(text=f"Total: PKR {total:.2f}")
        
    def _checkout(self):
        if not self._current_bill:
            self._toast("Cart is empty!")
            return
            
        total_amount = sum(i["price"] * i["qty"] for i in self._current_bill.values())
        payload = {
            "staff_username": self.username,
            "total_amount": total_amount,
            "discount_applied": 0.00,
            "cart_items": [
                {"barcode": v["barcode"], "name": v["name"], "quantity": v["qty"], "price": v["price"]}
                for v in self._current_bill.values()
            ]
        }
        
        def _send_bill():
            try:
                resp = requests.post(f"{self.api_url}/api/bills", json=payload, timeout=5)
                if resp.status_code == 201:
                    self.after(0, self._checkout_success)
                else:
                    self.after(0, lambda: self._toast("Failed to send bill!"))
            except requests.exceptions.RequestException:
                self.after(0, lambda: self._toast("Network Error - Could not send bill"))
                
        self._toast("Sending bill to Admin...")
        threading.Thread(target=_send_bill, daemon=True).start()
        
    def _checkout_success(self):
        self._current_bill.clear()
        self._update_cart_ui()
        self.pc_status.configure(text="Bill Sent to Admin Successfully!", text_color=C_SUCCESS)
        self._toast("✅ Bill Sent to Admin!")

    # =========================================================================
    # INVENTORY VIEW (Read-Only)
    # =========================================================================
    def _build_inventory_view(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        
        top = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=10)
        top.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(top, text="📦 Store Inventory", font=(FONT, 20, "bold"), text_color=C_TEXT).pack(side="left", padx=20, pady=20)
        
        self.inv_status = ctk.CTkLabel(top, text="Loading...", font=(FONT, 14), text_color=C_TEXT_DIM)
        self.inv_status.pack(side="right", padx=20, pady=20)
        
        cols = ("Barcode", "Name", "Category", "Price", "Stock")
        self.inv_tree = ttk.Treeview(frame, columns=cols, show="headings", height=20)
        for c in cols:
            self.inv_tree.heading(c, text=c)
            self.inv_tree.column(c, anchor="center")
        self.inv_tree.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        def _fetch():
            try:
                resp = requests.get(f"{self.api_url}/api/inventory", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    self.after(0, lambda: self._populate_inv_tree(data))
                else:
                    self.after(0, lambda: self.inv_status.configure(text="Failed to load inventory", text_color=C_DANGER))
            except requests.exceptions.RequestException:
                self.after(0, lambda: self.inv_status.configure(text="Network Error", text_color=C_DANGER))
                
        threading.Thread(target=_fetch, daemon=True).start()
        
        return frame
        
    def _populate_inv_tree(self, data):
        for item in self.inv_tree.get_children():
            self.inv_tree.delete(item)
            
        for p in data:
            self.inv_tree.insert("", "end", values=(
                p["barcode"], p["name"], p.get("category", "N/A"),
                f"PKR {p['price']}", p.get("stock_count", 0)
            ))
            
        self.inv_status.configure(text=f"Loaded {len(data)} items", text_color=C_SUCCESS)

    # =========================================================================
    # REFUNDS VIEW
    # =========================================================================
    def _build_refund_view(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        
        top = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=10)
        top.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(top, text="Lookup Transaction ID", font=(FONT, 14)).pack(side="left", padx=20, pady=20)
        self.refund_entry = ctk.CTkEntry(top, width=300)
        self.refund_entry.pack(side="left", padx=10)
        ctk.CTkButton(top, text="Search", command=self._lookup_refund).pack(side="left", padx=10)
        
        self.refund_info = ctk.CTkLabel(frame, text="", font=(FONT, 14), text_color=C_TEXT_DIM)
        self.refund_info.pack(pady=20)
        
        self.refund_btn = ctk.CTkButton(frame, text="Process Full Refund", fg_color=C_DANGER, hover_color="#B32B25", font=(FONT, 14, "bold"), command=self._process_refund)
        # Hidden initially
        
        self._current_refund_tx = None
        return frame
        
    def _lookup_refund(self):
        tx_id = self.refund_entry.get().strip()
        if not tx_id:
            return
            
        self.refund_info.configure(text="Searching...", text_color=C_TEXT_DIM)
        self.refund_btn.pack_forget()
        
        def _search():
            try:
                resp = requests.get(f"{self.api_url}/api/transactions/{tx_id}", timeout=5)
                if resp.status_code == 200:
                    tx = resp.json()
                    self.after(0, self._show_refund_details, tx)
                else:
                    self.after(0, lambda: self.refund_info.configure(text="Transaction not found.", text_color=C_DANGER))
            except requests.exceptions.RequestException:
                self.after(0, lambda: self.refund_info.configure(text="Network Error - Server Offline", text_color=C_DANGER))
                
        threading.Thread(target=_search, daemon=True).start()
        
    def _show_refund_details(self, tx):
        self._current_refund_tx = tx
        self.refund_info.configure(text=f"Found Transaction: {tx['transaction_id']}\nTotal: PKR {tx['total_amount']}\nStatus: {tx['status']}", text_color=C_SUCCESS)
        if tx['status'] == "COMPLETED":
            self.refund_btn.pack(pady=20)
        else:
            self.refund_info.configure(text=self.refund_info.cget("text") + "\n(Already Refunded or Invalid)", text_color=C_WARNING)
            
    def _process_refund(self):
        if not self._current_refund_tx:
            return
            
        tx = self._current_refund_tx
        items = tx["cart_items"]
        if isinstance(items, str):
            items = json.loads(items)
            
        payload = {
            "transaction_id": tx["transaction_id"],
            "refund_amount": tx["total_amount"],
            "items_to_refund": [{"barcode": i["barcode"], "quantity": i["quantity"]} for i in items]
        }
        
        def _refund():
            try:
                resp = requests.post(f"{self.api_url}/api/transactions/refund", json=payload, timeout=5)
                if resp.status_code == 200:
                    self.after(0, lambda: self._toast("✅ Refund Processed!"))
                    self.after(0, lambda: self.refund_info.configure(text="Refund Successful", text_color=C_SUCCESS))
                    self.after(0, self.refund_btn.pack_forget)
                else:
                    err = resp.json().get("error", "Failed")
                    self.after(0, lambda: self._toast(f"Error: {err}"))
            except requests.exceptions.RequestException:
                self.after(0, lambda: self._toast("Network Error - Could not process refund"))
                
        threading.Thread(target=_refund, daemon=True).start()


if __name__ == "__main__":
    setup = StaffSetupApp()
    setup.mainloop()
    
    if setup.success:
        app = StaffTerminalApp(setup.api_base_url, setup.staff_username)
        app.mainloop()
