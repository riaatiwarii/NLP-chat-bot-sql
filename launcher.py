import sys
import os
import traceback
import multiprocessing
from pathlib import Path

# Mandatory for PyInstaller multiprocessing support on Windows
multiprocessing.freeze_support()

# Force UTF-8 encoding on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Handle PyInstaller frozen executable bundle path
if getattr(sys, 'frozen', False):
    bundle_dir = Path(sys._MEIPASS)
    os.chdir(os.path.dirname(sys.executable))
else:
    bundle_dir = Path(__file__).resolve().parent

sys.path.insert(0, str(bundle_dir))
sys.path.insert(0, str(bundle_dir / "backend"))

if __name__ == "__main__":
    print("=======================================================")
    print("  SBI CMS Central Gateway Server - Standalone Executable")
    print("=======================================================")
    
    try:
        import uvicorn
        from app.main import app
        
        import socket
        def get_working_port(default_port=8001):
            if "PORT" in os.environ:
                return int(os.environ["PORT"])
            for p in [default_port, 8000, 8002, 8003, 8004]:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    try:
                        s.bind(('0.0.0.0', p))
                        return p
                    except OSError:
                        continue
            return default_port

        port = get_working_port(8001)
        print(f"Starting server on http://0.0.0.0:{port} ...", flush=True)
        uvicorn.run(app, host="0.0.0.0", port=port)
    except KeyboardInterrupt:
        print("\n[INFO] Server stopped by user.", flush=True)
    except Exception as e:
        print("\n[CRITICAL ERROR] Server failed to start due to exception:", flush=True)
        traceback.print_exc()
    finally:
        print("\n" + "=" * 57)
        if sys.stdin and sys.stdin.isatty():
            try:
                input("Press ENTER to close this window...")
            except Exception:
                pass
