import bcrypt
import customtkinter as ctk

# Pre-defined permissions for our app
PERMISSIONS = {
    # System
    "access_settings": "Access the Settings Dashboard",
    # Inventory
    "add_product": "Add new products",
    "edit_product": "Edit existing products",
    "delete_product": "Delete products",
    "view_inventory": "View the inventory list",
    # Sales
    "process_sale": "Process sales and print receipts",
    "apply_discount": "Apply discounts to bills",
    # Refund
    "process_refund": "Process refunds",
    # Restock
    "process_restock": "Add stock to products",
    # Reports
    "view_reports": "View financial and sales reports",
    "view_transactions": "View past transactions",
    # Staff
    "manage_staff": "Add, edit, or delete staff members and users"
}

class SecurityManager:
    def __init__(self, db_manager):
        self.db = db_manager

    @staticmethod
    def hash_password(plaintext_password: str) -> str:
        """Hashes a plaintext password using bcrypt."""
        # bcrypt.hashpw requires bytes
        return bcrypt.hashpw(plaintext_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    @staticmethod
    def verify_password(plaintext_password: str, hashed_password: str) -> bool:
        """Verifies a plaintext password against a bcrypt hash."""
        try:
            return bcrypt.checkpw(plaintext_password.encode('utf-8'), hashed_password.encode('utf-8'))
        except ValueError:
            # Handles cases where hashed_password is not a valid bcrypt hash
            return False

    def has_permission(self, role_id: int, permission_name: str) -> bool:
        """Checks if a given role ID has a specific permission."""
        try:
            with self.db._connect() as conn:
                cur = conn.execute("""
                    SELECT 1 FROM role_permissions rp
                    JOIN permissions p ON rp.permission_id = p.id
                    WHERE rp.role_id = ? AND p.name = ?
                """, (role_id, permission_name))
                return cur.fetchone() is not None
        except Exception as e:
            print(f"Error checking permission: {e}")
            return False

    def get_role_by_id(self, role_id: int) -> str:
        """Gets the role name by its ID."""
        try:
            with self.db._connect() as conn:
                cur = conn.execute("SELECT name FROM roles WHERE id = ?", (role_id,))
                row = cur.fetchone()
                return row["name"] if row else ""
        except Exception:
            return ""

    def get_role_id_by_name(self, role_name: str) -> int:
        """Gets the role ID by its name."""
        try:
            with self.db._connect() as conn:
                cur = conn.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
                row = cur.fetchone()
                return row["id"] if row else -1
        except Exception:
            return -1

    def authenticate_admin(self, password: str) -> bool:
        """Authenticates specifically against any user with the 'admin' role."""
        try:
            with self.db._connect() as conn:
                cur = conn.execute("""
                    SELECT u.password_hash FROM users u
                    JOIN roles r ON u.role_id = r.id
                    WHERE r.name = 'admin' AND u.status = 'Active'
                """)
                
                for row in cur.fetchall():
                    hash_val = row["password_hash"]
                    if self.verify_password(password, hash_val):
                        return True
        except Exception:
            pass
            
        return False


class ManagerOverrideDialog(ctk.CTkToplevel):
    def __init__(self, master, security_manager: SecurityManager, action_name: str):
        super().__init__(master)
        self.title("Manager Override")
        self.geometry("340x220")
        self.resizable(False, False)
        self.grab_set()
        self.transient(master)
        
        self.security_manager = security_manager
        self.authorized = False
        
        # Center dialog
        self.update_idletasks()
        if master.winfo_ismapped():
            x = master.winfo_x() + (master.winfo_width() // 2) - 170
            y = master.winfo_y() + (master.winfo_height() // 2) - 110
            self.geometry(f"+{x}+{y}")
            
        # UI
        ctk.CTkLabel(self, text="Restricted Action", font=("Inter", 18, "bold"), text_color="#E0E0E0").pack(pady=(20, 5))
        ctk.CTkLabel(self, text=f"'{action_name}' requires manager approval.", font=("Inter", 12), text_color="#A0A0A0").pack(pady=(0, 15))
        
        self.pwd_entry = ctk.CTkEntry(self, placeholder_text="Enter Admin Password", show="•", width=220, height=36)
        self.pwd_entry.pack(pady=(0, 15))
        self.pwd_entry.bind("<Return>", lambda e: self._verify())
        
        self.error_label = ctk.CTkLabel(self, text="", font=("Inter", 11), text_color="#F85149")
        self.error_label.pack(pady=(0, 5))
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=40)
        
        ctk.CTkButton(btn_frame, text="Cancel", width=90, fg_color="#3B1A1A", hover_color="#F85149", command=self.destroy).pack(side="left")
        ctk.CTkButton(btn_frame, text="Authorize", width=120, fg_color="#2EA043", hover_color="#3FB950", command=self._verify).pack(side="right")
        
        self.pwd_entry.focus_set()
        
    def _verify(self):
        pwd = self.pwd_entry.get()
        if not pwd:
            self.error_label.configure(text="Password cannot be empty.")
            return
            
        if self.security_manager.authenticate_admin(pwd):
            self.authorized = True
            self.destroy()
        else:
            self.error_label.configure(text="Incorrect password. Access denied.")
            self.pwd_entry.delete(0, "end")
