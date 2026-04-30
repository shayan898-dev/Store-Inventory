"""
build_app.py
------------
Compiles Inventory Manager Pro into a single standalone .exe.

Flags used:
  --onefile    -> single .exe
  --noconsole  -> no black terminal window
  --noupx      -> disables UPX compression (major AV false-positive trigger)
  --noconfirm  -> overwrites dist/ without prompting

New in this version:
  - Barcode2Win integration with auto-quantity entry
  - Streamlined build size

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
    print("=" * 62)
    print("  Inventory Manager Pro -- PyInstaller Build")
    print("  (Mobile Scanner Bridge Edition)")
    print("=" * 62)

    clean_old_build()

    sep = os.pathsep   # ';' on Windows, ':' on Unix

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--noupx",
        "--noconfirm",
        "--name", EXE_NAME,
        # Python source files to bundle
        "--add-data", f"database_manager.py{sep}.",
        # Collect all data/DLLs for bundled packages
        "--collect-all", "qrcode",
        "--collect-all", "flask",
        "--collect-all", "customtkinter",
        "main.py",
    ]

    print("\nRunning PyInstaller...\n")
    subprocess.run(cmd, cwd=HERE)

    print("\n" + "=" * 62)
    if os.path.exists(EXE_PATH):
        size_mb = os.path.getsize(EXE_PATH) / (1024 * 1024)
        print(f"[OK] Build complete!")
        print(f"     Location : {EXE_PATH}")
        print(f"     Size     : {size_mb:.1f} MB")
        print(f"\n     -> Copy InventoryManager.exe anywhere -- no Python needed.")
        print(f"     -> inventory.db is created next to the .exe on first run.")
        print(f"     -> Connect using Barcode2Win mobile app.")
    else:
        print("[FAIL] Build failed -- check the output above.")
        sys.exit(1)
    print("=" * 62)


if __name__ == "__main__":
    build()
