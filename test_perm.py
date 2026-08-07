import sqlite3
import os
from security import SecurityManager

db_path = os.path.join(os.environ.get("APPDATA", ""), "InventoryManager", "inventory.db")
if not os.path.exists(db_path):
    db_path = "inventory.db"
    
class MockDB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

db = MockDB(db_path)
sec = SecurityManager(db)

role_id = sec.get_role_id_by_name("admin")
print("admin role_id:", role_id)
print("has view_inventory:", sec.has_permission(role_id, "view_inventory"))

roles = db.conn.execute("SELECT * FROM roles").fetchall()
print("roles:", [dict(r) for r in roles])

perms = db.conn.execute("SELECT * FROM role_permissions").fetchall()
print("role_permissions count:", len(perms))
if len(perms) > 0:
    print("first few:", [dict(p) for p in perms[:5]])
