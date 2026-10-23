"""macOS launchd installation kept separate from the ingestion engine."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.brollant.engine"
OLD_LABELS = ("com.loagendo.engine",)  # nombre anterior (Loagendo, hasta 17-10-2026)


def plist_data(root: Path, interval=900):
    if not 300 <= interval <= 86400: raise ValueError("El intervalo debe estar entre 300 y 86400 segundos")
    root = root.resolve()
    return {"Label": LABEL, "ProgramArguments": [sys.executable, str(root / "run.py"), "--run-jobs"],
            "WorkingDirectory": str(root), "StartInterval": interval,
            "StandardOutPath": str(root / "reports" / "automation.log"),
            "StandardErrorPath": str(root / "reports" / "automation-error.log"), "ProcessType": "Standard",  # 23-10-2026: con «Background» macOS frenaba la publicación ~5 veces (2 h 35 frente a 30 min)
            # launchd starts with a minimal PATH; the publish job needs node/npx (Homebrew) to reach Cloudflare.
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}}


def install(root: Path, interval=900, home=None, runner=subprocess.run):
    home = Path(home) if home else Path.home()
    path = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(plist_data(root, interval), fmt=plistlib.FMT_XML, sort_keys=True))
    domain = f"gui/{os.getuid()}"
    # Never unload an existing user job as a side effect of an install attempt.
    result = runner(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
    if result.returncode != 0: raise RuntimeError((result.stderr or result.stdout or "launchctl bootstrap falló").strip())
    runner(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], capture_output=True, text=True)
    return {"label": LABEL, "path": str(path), "interval_seconds": interval, "status": "installed"}
