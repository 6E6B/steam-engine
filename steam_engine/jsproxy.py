"""Lazy JS path proxy — `se.client.Apps.RunGame(123)` evaluates
`SteamClient.Apps.RunGame(123)` in the page; `se.window.appStore.allApps.get()`
reads the property. Nothing is bound until called, so the entire
SteamClient.* / window.* surface is reachable without hand-written bindings."""

from __future__ import annotations

import json
from typing import Any, Protocol


class Engine(Protocol):
    """What a proxy needs from its host — any object providing these works,
    including test doubles."""

    def call(self, path: str, *args: Any, convert: bool = False) -> Any: ...
    def get(self, path: str) -> Any: ...
    def eval_json(self, expression: str) -> Any: ...


def _to_js_name(name: str, convert: bool) -> str:
    """snake_case/lowerCamel -> PascalCase, for SteamClient.* ergonomics."""
    if not convert:
        return name
    if "_" in name:
        return "".join(p.title() for p in name.split("_") if p)
    if name[:1].islower():
        return name[0].upper() + name[1:]
    return name


class JsProxy:
    __slots__ = ("_se", "_path", "_convert")

    def __init__(self, se: Engine, path: str, convert: bool = False):
        self._se = se
        self._path = path
        self._convert = convert

    def __getattr__(self, name: str) -> JsProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        return JsProxy(
            self._se, f"{self._path}.{_to_js_name(name, self._convert)}", self._convert
        )

    def __getitem__(self, key) -> JsProxy:
        return JsProxy(self._se, f"{self._path}[{json.dumps(key)}]", self._convert)

    def __call__(self, *args: Any) -> Any:
        return self._se.call(self._path, *args, convert=self._convert)

    def get(self) -> Any:
        """Read the property value (must be JSON-serializable)."""
        return self._se.get(self._path)

    def keys(self) -> list[str]:
        """Own property names — handy when .get() hits unserializable objects."""
        return self._se.eval_json(
            f"JSON.stringify(Object.getOwnPropertyNames({self._path}))"
        )

    def __repr__(self) -> str:
        return f"<JsProxy {self._path}>"
