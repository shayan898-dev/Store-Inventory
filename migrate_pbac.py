import sqlite3

def migrate():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row

    # Create new user_permissions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            username TEXT,
            permission_name TEXT,
            PRIMARY KEY (username, permission_name)
        );
    """)

    # New PBAC modules
    ALL_PERMS = [
        "pos_checkout", "manage_inventory", "apply_discounts",
        "process_refunds", "view_history", "config_hardware", "system_admin"
    ]

    # Map existing roles to new PBAC perms
    ROLE_MAPPING = {
        "admin": ALL_PERMS,
        "manager": ["pos_checkout", "manage_inventory", "apply_discounts", "process_refunds", "view_history"],
        "staff": ["pos_checkout", "manage_inventory"],
        "cashier": ["pos_checkout"]
    }

    users = conn.execute("SELECT u.username, r.name as role_name FROM users u LEFT JOIN roles r ON u.role_id = r.id").fetchall()
    
    for u in users:
        username = u["username"]
        role = u["role_name"] or "cashier"
        perms = ROLE_MAPPING.get(role, ["pos_checkout"])
        
        for p in perms:
            try:
                conn.execute("INSERT INTO user_permissions (username, permission_name) VALUES (?, ?)", (username, p))
            except sqlite3.IntegrityError:
                pass # Already exists

    conn.commit()
    print("Migration successful.")

if __name__ == "__main__":
    migrate()
