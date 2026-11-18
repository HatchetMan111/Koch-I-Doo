import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

# Env VOR jedem Backend-Import setzen (db.py liest KOCHIDO_DATA beim Import)
_tmp = tempfile.mkdtemp(prefix="kochido-test-")
os.environ.setdefault("KOCHIDO_DATA", _tmp)
os.environ["KOCHIDO_DIST"] = str(ROOT / "frontend" / "dist")

sys.path.insert(0, str(BACKEND))
