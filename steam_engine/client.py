"""SteamEngine — main entry point.

    from steam_engine import SteamEngine

    with SteamEngine.connect() as se:
        se.client.Apps.SetAppLaunchOptions(292030, "-fullscreen")
        apps = se.window.appStore.allApps.get()
"""

from __future__ import annotations

import json
from typing import Any

from . import cdp
from .enable import enable as _enable
from .jsproxy import JsProxy


class SteamEngine:
    def __init__(self, session: cdp.Session):
        self._session = session
        self._name_cache: dict[tuple[str, str], str | None] = {}
        # SteamClient.* — PascalCase bridge into the native client.
        self.client = JsProxy(self, "SteamClient", convert=True)
        # window.* — every store (collectionStore, appStore, downloadsStore, ...).
        self.window = JsProxy(self, "window")

    @classmethod
    def connect(cls, port: int = 1337) -> SteamEngine:
        """Attach to Steam's SharedJSContext via the remote-debugging port."""
        return cls(cdp.Session.connect(port))

    def __enter__(self) -> SteamEngine:
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._session.close()

    # ---- low level ------------------------------------------------------

    def eval(self, expression: str) -> Any:
        """Evaluate raw JS in SharedJSContext. Returns result.value."""
        return self._session.eval(expression)

    def eval_json(self, expression: str) -> Any:
        return self._session.eval_json(expression)

    def get(self, path: str) -> Any:
        return self._session.eval_json(f"JSON.stringify({path})")

    def _resolve_name(self, parent: str, name: str) -> str | None:
        """Find the real member name on `parent`, ignoring case/underscores —
        so `get_os_type` finds `GetOSType`."""
        key = name.replace("_", "").lower()
        cache_key = (parent, key)
        if cache_key not in self._name_cache:
            self._name_cache[cache_key] = self._session.eval_json(
                f"JSON.stringify(Object.getOwnPropertyNames({parent})"
                f".find(n=>n.toLowerCase()==={json.dumps(key)}) ?? null)"
            )
        return self._name_cache[cache_key]

    def call(self, path: str, *args: Any, convert: bool = False) -> Any:
        """Call `path(...args)`; args are JSON-serialized. Awaits promises.
        Returns the JSON-decoded result, or None for undefined/unserializable."""
        if convert:
            parent, _, leaf = path.rpartition(".")
            resolved = self._resolve_name(parent, leaf)
            if resolved:
                path = f"{parent}.{resolved}"
        arglist = ",".join(json.dumps(a) for a in args)
        expr = (
            "(async()=>{"
            f"const r = await {path}({arglist});"
            "try { return JSON.stringify({v: r === undefined ? null : r}); }"
            "catch { return JSON.stringify({v: null, unserializable: typeof r}); }"
            "})()"
        )
        out = self._session.eval(expr)
        return json.loads(out).get("v") if isinstance(out, str) else out

    # ---- enable / status ------------------------------------------------

    @staticmethod
    def status(port: int = 1337) -> dict:
        """Probe the debug endpoint without attaching a session."""
        try:
            targets = cdp.list_targets(port)
        except Exception as e:
            return {"reachable": False, "error": str(e), "port": port}
        return {
            "reachable": True,
            "port": port,
            "targets": len(targets),
            "shared_js_context": any(t.title == "SharedJSContext" for t in targets),
        }

    @staticmethod
    def enable(port: int = 1337, restart: bool = False) -> str:
        """Patch the webhelper wrapper so it opens the debug port (Linux)."""
        return _enable(port, restart)
