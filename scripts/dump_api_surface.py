"""Dump the live Steam client API surface (SteamClient.* + window.* globals).

Connects to a running Steam client over CDP and introspects the
SharedJSContext object graph. Writes an MkDocs site under docs/:

  docs/index.md              — overview + category index
  docs/api/<category>.md     — one page per category
  docs/data/api_surface.json — raw machine-readable dump (also hosted)

Build locally with `mkdocs serve`; deploy with `mkdocs gh-deploy` or the
included GitHub Actions workflow.

Usage: .venv/bin/python scripts/dump_api_surface.py [--port 1337]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from steam_engine import SteamEngine  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Members of each top-level object are collected by walking its prototype
# chain (ES-class stores keep methods on the prototype, state on the
# instance). Members that are plain objects may hold sub-namespaces
# (SteamClient.Messaging.Foo); WALK_DEPTH controls recursion into those.
WALKER_JS = """
(() => {
  const SKIP = new Set([
    'constructor', 'prototype', '__proto__', 'arguments', 'caller', 'callee',
    '$mobx', 'mobxGuid', 'isMobXObservable', 'isMobXAtom',
    '__mobxDidRunLazyInitializers', '__mobxDecorators', 'mobxDecorators',
    '__mobxInstanceCount', '__mobxGlobals',
    '__annotationsHash__', '__initializer', 'toString', 'toLocaleString',
    'valueOf', 'hasOwnProperty', 'isPrototypeOf', 'propertyIsEnumerable',
    '__defineGetter__', '__defineSetter__', '__lookupGetter__',
    '__lookupSetter__',
  ]);
  const isNamespaceLike = (v) => {
    if (v === null || typeof v !== 'object') return false;
    if (Array.isArray(v) || v instanceof Map || v instanceof Set) return false;
    if (v instanceof Date || v instanceof RegExp || v instanceof Promise)
      return false;
    const cn = v.constructor && v.constructor.name;
    // plain objects and module-namespace objects only
    return cn === 'Object' || cn === undefined ||
           Object.getPrototypeOf(v) === null;
  };
  const describe = (node, path, depth, maxDepth, out, visiting) => {
    const members = [];
    const seen = new Set();
    let o = node;
    while (o && o !== Object.prototype && o !== Function.prototype &&
           o !== Array.prototype) {
      for (const n of Object.getOwnPropertyNames(o)) {
        if (!seen.has(n)) {
          seen.add(n);
          members.push([n, o === node ? 0 : 1]);
        }
      }
      o = Object.getPrototypeOf(o);
    }
    const result = [];
    for (const [n, where] of members) {
      if (SKIP.has(n) || n.startsWith('$mobx') || n.startsWith('__mobx'))
        continue;
      const d = Object.getOwnPropertyDescriptor(
        where === 0 ? node : Object.getPrototypeOf(node), n);
      let v, threw = false;
      try { v = node[n]; } catch (e) { threw = true; }
      if (threw) { result.push({name: n, kind: 'getter-throws'}); continue; }
      const t = typeof v;
      const m = {name: n, kind: t === 'function' ? 'fn'
                             : v === null ? 'null'
                             : t === 'object' ? 'obj' : 'val'};
      if (where) m.proto = true;
      if (d && d.get && !d.value) m.accessor = true;
      if (m.kind === 'fn') {
        m.arity = v.length;
        m.native = /\\[native code\\]/.test(Function.prototype.toString.call(v));
      } else if (m.kind === 'obj') {
        if (Array.isArray(v)) { m.kind = 'array'; m.len = v.length; }
        else if (v instanceof Map) { m.kind = 'map'; m.len = v.size; }
        else if (v instanceof Set) { m.kind = 'set'; m.len = v.size; }
        else {
          try { m.nkeys = Object.getOwnPropertyNames(v).length; } catch (e) {}
          if (depth < maxDepth && isNamespaceLike(v) && !visiting.has(v)) {
            visiting.add(v);
            m.sub = describe(v, path + '.' + n, depth + 1, maxDepth, out,
                             visiting);
            visiting.delete(v);
          }
        }
      } else if (m.kind === 'val') {
        try {
          let s = JSON.stringify(v);
          if (s === undefined) s = String(v);
          m.v = s.length > 80 ? s.slice(0, 80) + '…' : s;
        } catch (e) { m.v = '<unserializable>'; }
      }
      result.push(m);
    }
    return result;
  };
  return {describe, isNamespaceLike};
})()
"""

# Walk a set of root paths; returns {path: members}.
DUMP_JS = """
((roots, maxDepth) => {
  const W = %s;
  const out = {};
  for (const path of roots) {
    let node;
    try { node = eval(path); } catch (e) {
      out[path] = {error: 'eval failed: ' + e};
      continue;
    }
    if (node === undefined || node === null) {
      out[path] = {error: 'undefined'};
      continue;
    }
    const t = typeof node;
    if (t !== 'object' && t !== 'function') {
      out[path] = {value_root: node};
      continue;
    }
    if (t === 'function') {
      out[path] = {function_root: true,
                   arity: node.length,
                   native: /\\[native code\\]/.test(
                     Function.prototype.toString.call(node))};
      continue;
    }
    try {
      out[path] = {members: W.describe(node, path, 0, maxDepth, out,
                                      new Set([node]))};
    } catch (e) { out[path] = {error: String(e)}; }
  }
  return JSON.stringify(out);
})(%s, %d)
"""


def dump(se: SteamEngine, roots: list[str], max_depth: int) -> dict:
    expr = DUMP_JS % (WALKER_JS, json.dumps(roots), max_depth)
    return se.eval_json(expr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=1337)
    ap.add_argument("--out", type=Path, default=ROOT / "docs")
    args = ap.parse_args()

    with SteamEngine.connect(args.port) as se:
        # SteamClient.* — one level of nested namespaces.
        surface = dump(se, ["SteamClient"], max_depth=2)["SteamClient"]

        # Steam-injected window globals: diff against a blank iframe.
        injected = se.eval_json(
            "JSON.stringify((() => {"
            "const f = document.createElement('iframe');"
            "document.body.appendChild(f);"
            "const base = new Set(Object.getOwnPropertyNames(f.contentWindow));"
            "f.remove();"
            "return Object.getOwnPropertyNames(window)"
            ".filter(n => !base.has(n));"
            "})())"
        )
        win = dump(se, [f"window[{json.dumps(n)}]" for n in injected],
                   max_depth=1)

    data = {"steamclient": surface, "window": win}
    written = write_site(data, args.out)
    n_fns = count_fns(data)
    print(f"wrote {len(written)} pages under {args.out} — "
          f"{n_fns} functions across "
          f"{len(surface.get('members', []))} SteamClient namespaces, "
          f"{len(win)} window globals")
    return 0


def count_fns(data: dict) -> int:
    def walk(members):
        n = 0
        for m in members or []:
            if m["kind"] == "fn":
                n += 1
            n += walk(m.get("sub"))
        return n
    total = walk(data["steamclient"].get("members"))
    for v in data["window"].values():
        total += walk(v.get("members"))
    return total


# Thematic grouping for the index. Explicit names (not regex) so a Steam
# update that adds/renames namespaces lands in "Other" instead of being
# silently misfiled.
CATEGORIES = [
    ("Games, apps & library", "games-apps-library",
     {"SteamClient": ["Apps", "Installs", "Downloads", "InstallFolder",
                      "Updates", "Compat", "Cloud", "CloudStorage",
                      "GameSessions", "GameNotes", "GameRecording", "Stats",
                      "Screenshots", "Music"],
      "window": ["appStore", "collectionStore", "appInfoStore",
                 "appDetailsStore", "appDetailsCache", "appActivityStore",
                 "appAchievementProgressCache", "gameReleaseStore",
                 "trendingStore", "appSpotlightStore", "showcaseStore",
                 "StoreItemCache", "downloadsStore", "installFolderStore",
                 "UpdateStore", "SuspendResumeStore", "workshopStore",
                 "screenshotStore", "appReviewStore", "playNextStore",
                 "cloudStorage", "cloudStorageInternalState"]}),
    ("Friends, chat & community", "friends-chat-community",
     {"SteamClient": ["Friends", "FriendSettings", "Messaging", "WebChat",
                      "FamilySharing", "Notifications", "ClientNotifications",
                      "CommunityItems", "Customization", "SharedConnection"],
      "window": ["friendStore", "g_ClanStore", "communityStore",
                 "userProfileStore", "badgeStore", "partnerEventStore",
                 "g_PartnerEventStore", "g_PartnerEventSummaryStore",
                 "libraryEventStore", "g_EventCalendarTrackingStore",
                 "g_CreatorHomeStore", "g_CreatorHomeListInfoStore",
                 "g_EventCalendarDevFeatures", "g_FriendsUIApp",
                 "__FriendsUIBrowserContext"]}),
    ("System, hardware & input", "system-hardware-input",
     {"SteamClient": ["System", "Input", "OpenVR", "RemotePlay", "Streaming",
                      "Broadcast"],
      "window": ["SystemDisplayManagerStore", "SystemNetworkStore",
                 "SystemReportStore", "RemotePlayStore_SteamUI",
                 "streamingStore", "controllerConfiguratorStore",
                 "ControllerStore", "vrAudioSettingsStore", "vrGamepadInput",
                 "VRPathProperties", "protoPathProperties",
                 "protoPathPropertyDebug", "g_GRS", "ShowVROverlay"]}),
    ("Account, auth & storage", "account-auth-storage",
     {"SteamClient": ["User", "Auth", "Parental", "Storage", "RoamingStorage",
                      "MachineStorage"],
      "window": ["loginStore", "securitystore", "subscriberAgreementStore"]}),
    ("UI, browser & window management", "ui-browser-window",
     {"SteamClient": ["Browser", "BrowserView", "Overlay", "UI", "URL",
                      "Window", "WebUITransport", "Settings"],
      "window": ["uiStore", "overlayStore", "settingsStore",
                 "settingsZooStore", "urlStore", "searchstore", "dragStore",
                 "multiSelectStore", "tempNavStore", "FocusedAppWindowStore",
                 "NotificationStore", "uiBroadcastWatchStore", "App",
                 "SteamUIStore", "g_PopupManager", "MainWindowBrowserManager",
                 "g_WindowFocusCoordinator", "BrowserAndBackstackInstances",
                 "FocusNavController", "SetHoverPresentation",
                 "SetBackgroundInterval", "SetBackgroundTimeout",
                 "ClearBackgroundInterval", "ClearBackgroundTimeout"]}),
    ("Networking & services", "networking-services",
     {"SteamClient": ["ServerBrowser"],
      "window": ["cm", "steamAjaxRequest", "serverBrowserStore",
                 "LocalizationManager", "g_LogManager"]}),
    ("Debug & misc helpers", "debug-misc-helpers",
     {"SteamClient": ["Console", "_internal", "SteamChina"],
      "window": ["CLSTAMP", "EnableSteamConsole", "consoleStore",
                 "webpackChunksteamui", "__mobxInstanceCount",
                 "__mobxGlobals", "toJS", "jsonit", "libraryScrollListener",
                 "lastScrollTime", "ResetNewContentRollup",
                 "DebugLogEnable", "DebugLogDisable", "DebugLogEnableAll",
                 "DebugLogDisableAll", "DebugLogEnableBacktrace",
                 "DebugLogDisableBacktrace", "DebugLogNames",
                 "DebugLogEnabled", "DEBUG_GetDesiredSteamUIWindows",
                 "DEBUG_SuppressWindowType", "SetVoiceEchoLocalMic",
                 "SetVoiceLogDetails", "SetVoiceForceReconnectingStatus",
                 "SetVoiceForceConnectingStatus",
                 "SetVoiceAutoShowVideoStream"]}),
]


# ---- rendering -----------------------------------------------------------

HEADER = """<!--
AUTO-GENERATED by scripts/dump_api_surface.py from a live Steam client.
Names/membership change between Steam builds — regenerate, don't hand-edit.
-->
"""

REG_RX = re.compile(r"^Register")
EVENT_RX = re.compile(r"^(RegisterFor|On[A-Z]|Add.*Listener)")


def _steamclient_block(ns: dict) -> list[str]:
    """`## SteamClient.X` section for a category page."""
    out = [f"## `SteamClient.{ns['name']}`", ""]
    subs = ns.get("sub") or []
    fns = [m["name"] for m in subs if m["kind"] == "fn"]
    objs = [m for m in subs if m["kind"] == "obj"]
    vals = [m for m in subs if m["kind"] == "val"]
    ev = sorted(n for n in fns if EVENT_RX.match(n) or REG_RX.match(n))
    rest = sorted(set(fns) - set(ev))
    if rest:
        out.append("**Methods:** " + ", ".join(f"`{n}`" for n in rest))
        out.append("")
    if ev:
        out.append("**Event subscriptions:** "
                   + ", ".join(f"`{n}`" for n in ev))
        out.append("")
    for o in objs:
        out.append(f"**`{o['name']}`** (object"
                   + (f", {o['nkeys']} keys" if o.get("nkeys") else "")
                   + ")")
        if o.get("sub"):
            sfns = sorted(m["name"] for m in o["sub"] if m["kind"] == "fn")
            out.append("  - "
                       + (", ".join(f"`{n}`" for n in sfns) if sfns
                          else f"(no functions; {o.get('nkeys', '?')} keys)"))
        out.append("")
    if vals:
        out.append("**Values:** " + ", ".join(
            f"`{m['name']}`={m.get('v', '?')}" for m in vals))
        out.append("")
    if not (rest or ev or objs or vals):
        out.append("*(no members found)*")
        out.append("")
    return out


def _window_block(label: str, g: dict) -> list[str]:
    """`## label` section for a window global."""
    if g.get("function_root"):
        return [f"## `{label}()`", "",
                f"Global function — arity {g['arity']}"
                f"{', native' if g.get('native') else ''}.", ""]
    if "value_root" in g:
        return [f"## `{label}`", "",
                f"Global value: `{json.dumps(g['value_root'])}`", ""]
    if "error" in g:
        return [f"## `{label}`", "", f"*{g['error']}*", ""]

    members = g.get("members", [])
    fns = sorted(m["name"] for m in members if m["kind"] == "fn")
    state = sorted(m["name"] for m in members
                   if m["kind"] in ("val", "array", "map", "set")
                   or (m["kind"] == "obj" and "sub" not in m))
    out = [f"## `{label}`", ""]
    if fns:
        out.append("**Methods:** " + ", ".join(f"`{n}`" for n in fns))
        out.append("")
    for m in sorted((m for m in members
                     if m["kind"] == "obj" and "sub" in m),
                    key=lambda m: m["name"]):
        sfns = sorted(x["name"] for x in m["sub"] if x["kind"] == "fn")
        if sfns:
            out.append(f"**`{m['name']}`** — "
                       + ", ".join(f"`{n}`" for n in sfns))
            out.append("")
    if state:
        out.append("**State:** " + ", ".join(f"`{n}`" for n in state))
        out.append("")
    if not fns and not state:
        out.append("*(no callable or readable members found)*")
        out.append("")
    return out


def write_site(data: dict, docs: Path) -> list[str]:
    """Emit index.md + api/<category>.md + data/api_surface.json.
    Returns the list of written page paths (for the summary)."""
    sc_by_name = {m["name"]: m for m in data["steamclient"].get("members", [])
                  if m["kind"] == "obj" and "sub" in m}
    win_by_label = {k[8:-2]: v for k, v in data["window"].items()}

    api_dir = docs / "api"
    data_dir = docs / "data"
    api_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "api_surface.json").write_text(json.dumps(data, indent=2))

    used_sc: set[str] = set()
    used_win: set[str] = set()
    written: list[str] = []
    index_rows: list[tuple[str, str, int, int]] = []

    def emit(slug: str, title: str, sc_list: list[str],
             win_list: list[str]) -> None:
        body = [HEADER, f"# {title}", ""]
        for n in sc_list:
            body += _steamclient_block(sc_by_name[n])
        for n in win_list:
            body += _window_block(n, win_by_label[n])
        if not sc_list and not win_list:
            body.append("*Nothing here in this build.*")
            body.append("")
        (api_dir / f"{slug}.md").write_text("\n".join(body) + "\n")
        written.append(f"api/{slug}.md")
        index_rows.append((title, f"api/{slug}.md",
                           len(sc_list), len(win_list)))

    for title, slug, groups in CATEGORIES:
        sc_list = [n for n in groups["SteamClient"] if n in sc_by_name]
        win_list = [n for n in groups["window"] if n in win_by_label]
        used_sc.update(sc_list)
        used_win.update(win_list)
        emit(slug, title, sc_list, win_list)

    other_sc = sorted(set(sc_by_name) - used_sc)
    other_win = sorted(set(win_by_label) - used_win)
    emit("other", "Other / uncategorized", other_sc, other_win)

    # ---- index ----------------------------------------------------------
    def _n_fns(members) -> int:
        return sum((1 if m["kind"] == "fn" else 0) + _n_fns(m.get("sub"))
                   for m in members or [])

    n_sc_fns = _n_fns(data["steamclient"].get("members"))
    n_win_fns = sum(_n_fns(v.get("members"))
                    + (1 if v.get("function_root") else 0)
                    for v in data["window"].values())
    idx = [HEADER,
           "# Steam client API surface",
           "",
           "Everything callable or readable in a running Steam client's "
           "`SharedJSContext`, dumped live over CDP.",
           "",
           "## Call convention",
           "",
           "```python",
           "from steam_engine import SteamEngine",
           "",
           "with SteamEngine.connect() as se:",
           "    se.client.Apps.SetAppLaunchOptions(292030, \"-fullscreen\")",
           "    apps = se.window.appStore.allApps.get()",
           "```",
           "",
           "- `se.client.<Ns>.<method>(*args)` → `SteamClient.<Ns>.<method>`",
           "- `se.window.<global>.<method>(*args)` / `.get()` / `.keys()`",
           "- `RegisterFor*` methods return `{unregister}` handles",
           "- arg types are not recoverable (native/minified shims) — "
           "probe carefully",
           "",
           f"**{n_sc_fns}** `SteamClient.*` functions across "
           f"**{len(sc_by_name)}** namespaces; **{n_win_fns}** functions on "
           f"**{len(win_by_label)}** injected window globals. "
           "Raw dump: [data/api_surface.json](data/api_surface.json).",
           "",
           "## Categories",
           "",
           "| Category | SteamClient namespaces | window globals |",
           "|---|---|---|"]
    for title, path, nsc, nwin in index_rows:
        idx.append(f"| [{title}]({path}) | {nsc} | {nwin} |")
    idx.append("")
    (docs / "index.md").write_text("\n".join(idx) + "\n")
    written.insert(0, "index.md")
    return written


if __name__ == "__main__":
    sys.exit(main())
