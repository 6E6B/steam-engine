"""Enable the CEF remote-debugging port on the Steam client."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WRAP = "ubuntu12_64/steamwebhelper_sniper_wrap.sh"
EXEC_LINE = 'exec ./steamwebhelper "$@"'


def _steam_dir() -> Path | None:
    home = Path.home()
    candidates = [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",  # flatpak
    ]
    for c in candidates:
        if (c / WRAP).exists():
            return c
    return None


def enable(port: int = 1337, restart: bool = False) -> str:
    """Patch steamwebhelper_sniper_wrap.sh to pass --remote-debugging-port.
    Returns a human-readable status message."""
    if sys.platform != "linux":
        raise RuntimeError(
            "on this platform, launch Steam with -cef-enable-debugging "
            "(Windows/macOS) or inject --remote-debugging-port into the "
            "steamwebhelper command line"
        )
    steam = _steam_dir()
    if steam is None:
        raise RuntimeError("could not locate " + WRAP)
    wrap = steam / WRAP
    body = wrap.read_text()
    if "--remote-debugging-port" in body:
        msg = f"{wrap} already patched"
    else:
        if EXEC_LINE not in body:
            raise RuntimeError(
                f"unexpected wrap script contents - edit {wrap} manually"
            )
        patched = (
            "exec ./steamwebhelper --remote-debugging-address=127.0.0.1 "
            f"--remote-debugging-port={port} \"$@\""
        )
        wrap.with_suffix(".sh.bak").write_text(body)
        wrap.write_text(body.replace(EXEC_LINE, patched))
        msg = f"patched {wrap}"
    if restart:
        # the browser process is the only one carrying -uimode in argv
        r = subprocess.run(["pkill", "-f", "steamwebhelper.*-uimode"])
        msg += (
            "; steamwebhelper killed - Steam will respawn it with the debug port"
            if r.returncode == 0
            else "; no running steamwebhelper found"
        )
    else:
        msg += "; restart Steam (or pass restart=True) to activate"
    return msg
