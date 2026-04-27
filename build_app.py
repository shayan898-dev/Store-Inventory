"""
build_app.py
------------
Compiles Inventory Manager Pro into a single standalone .exe using PyInstaller.

Flags used:
  --onefile    -> single .exe, no folder
  --noconsole  -> no black terminal window (windowed app)
  --noupx      -> disables UPX compression (AV false-positive trigger)
  --noconfirm  -> overwrites dist/ without prompting

Usage:
    python build_app.py
"""

import subprocess
import sys
import os
import shutil

HERE     = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, "dist")
EXE_NAME = "InventoryManager"
EXE_PATH = os.path.join(DIST_DIR, f"{EXE_NAME}.exe")


def clean_old_build():
    for folder in ("build", "dist"):
        path = os.path.join(HERE, folder)
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"[clean] Removed old {folder}/")


def build():
    print("=" * 60)
    print("  Inventory Manager Pro -- PyInstaller Build")
    print("=" * 60)

    clean_old_build()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--noupx",
        "--noconfirm",
        "--name", EXE_NAME,
        "--add-data", f"database_manager.py{os.pathsep}.",
        "main.py",
    ]

    print("\nRunning PyInstaller...\n")
    subprocess.run(cmd, cwd=HERE)

    print("\n" + "=" * 60)
    if os.path.exists(EXE_PATH):
        size_mb = os.path.getsize(EXE_PATH) / (1024 * 1024)
        print(f"[OK] Build complete!")
        print(f"     Location : {EXE_PATH}")
        print(f"     Size     : {size_mb:.1f} MB")
        print(f"\n     -> Copy InventoryManager.exe anywhere -- no Python needed.")
        print(f"     -> inventory.db is created next to the .exe on first run.")
    else:
        print("[FAIL] Build failed -- check the output above.")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    build()
