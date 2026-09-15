"""Minimal synchronous Chrome DevTools Protocol client for Steam's CEF webhelper."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from websockets.sync.client import connect as ws_connect


@dataclass
class Target:
    kind: str
    title: str
    url: str
    ws_url: str


def list_targets(port: int = 1337) -> list[Target]:
    """GET http://127.0.0.1:<port>/json — all debuggable targets."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        raw = json.load(r)
    return [
        Target(
            kind=t.get("type", ""),
            title=t.get("title", ""),
            url=t.get("url", ""),
            ws_url=t.get("webSocketDebuggerUrl", ""),
        )
        for t in raw
    ]


def pick_ui_target(targets: list[Target]) -> Target | None:
    """The SharedJSContext page — where collectionStore/appStore/SteamClient live."""
    for t in targets:
        if t.title == "SharedJSContext":
            return t
    for t in targets:
        if "steamloopback.host" in t.url:
            return t
    return None


class Session:
    """A CDP session attached to one target. Sequential request/response only —
    events are discarded. Not thread-safe."""

    def __init__(self, ws):
        self._ws = ws
        self._id = 0

    @classmethod
    def connect(cls, port: int = 1337, target: Target | None = None) -> Session:
        if target is None:
            target = pick_ui_target(list_targets(port))
        if target is None or not target.ws_url:
            raise RuntimeError(
                "SharedJSContext target not found — is Steam running with "
                "--remote-debugging-port open?"
            )
        return cls(ws_connect(target.ws_url, open_timeout=10))

    def eval(self, expression: str):
        """Runtime.evaluate with returnByValue+awaitPromise. Returns result.value."""
        self._id += 1
        my_id = self._id
        self._ws.send(
            json.dumps(
                {
                    "id": my_id,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                }
            )
        )
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") != my_id:
                continue  # event or unrelated response
            result = msg.get("result", {})
            exc = result.get("exceptionDetails")
            if exc:
                desc = (
                    exc.get("exception", {}).get("description")
                    or exc.get("text")
                    or "js exception"
                )
                raise RuntimeError(f"JS exception: {desc}")
            return result.get("result", {}).get("value")

    def eval_json(self, expression: str):
        """Evaluate an expression that returns a JSON.stringify'ed string."""
        v = self.eval(expression)
        if not isinstance(v, str):
            raise RuntimeError(f"expected JSON string result, got {type(v).__name__}")
        return json.loads(v)

    def close(self):
        self._ws.close()
