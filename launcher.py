import sys
import os
import multiprocessing
from pathlib import Path

# Mandatory for PyInstaller multiprocessing support on Windows
multiprocessing.freeze_support()

# Handle PyInstaller frozen executable bundle path
if getattr(sys, 'frozen', False):
    bundle_dir = Path(sys._MEIPASS)
else:
    bundle_dir = Path(__file__).resolve().parent

sys.path.insert(0, str(bundle_dir))
sys.path.insert(0, str(bundle_dir / "backend"))

import uvicorn
from app.main import app

if __name__ == "__main__":
    print("=======================================================")
    print("  SBI CMS Central Gateway Server - Standalone Executable")
    print("=======================================================")
    print("Starting server on http://0.0.0.0:8001 ...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
