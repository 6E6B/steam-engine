# steam-engine

A driver for a running Steam client's internal JS — call any `SteamClient.*`
bridge method (~600 of them across 45 namespaces) or any `window.*` store
from Python, over Chrome DevTools Protocol.

Steam's UI runs in CEF. With `--remote-debugging-port` on `steamwebhelper`,
the `SharedJSContext` renderer (where `collectionStore`, `appStore`,
`SteamClient`, ... live) is reachable via CDP. Everything goes through
Steam's real code paths — cloud sync, versioning, tombstones — nothing
patches files on disk.

This package is just the transport + dynamic proxy. For a curated
collections API see the sibling project `steam-collections`.

## Setup (Linux)

```sh
pip install -e .
steam-engine enable --restart   # patches ubuntu12_64/steamwebhelper_sniper_wrap.sh
steam-engine status             # verify
```

On Windows/macOS, launch Steam with `-cef-enable-debugging` (or inject
`--remote-debugging-port` into the webhelper command line). Port defaults to
1337; override with `STEAM_CDP_PORT`.

## API

```python
from steam_engine import SteamEngine

with SteamEngine.connect() as se:
    # SteamClient.* — the native bridge. Names resolve case/underscore
    # insensitively, so get_os_type() finds GetOSType().
    se.client.Apps.SetAppLaunchOptions(292030, "-fullscreen")
    se.client.Apps.specify_compat_tool(105600, "proton_experimental")
    se.client.InstallFolder.GetInstallFolders()
    se.client.Downloads.queue_app_update(582010)

    # window.* — every store (collectionStore, appStore, downloadsStore, ...)
    apps = se.window.appStore.allApps.get()

    # escape hatch
    se.eval("collectionStore.userCollections.length")
```

`JsProxy` rules:

- `proxy.method(*args)` — calls `path(...)`; args JSON-serialized, promises
  awaited, result JSON-decoded (`None` for undefined/unserializable)
- `proxy.prop.get()` — read a JSON-serializable property
- `proxy.prop.keys()` — own property names (for unserializable objects)
- `proxy.prop[idx]` — index access

Also: `SteamEngine.status(port)`, `SteamEngine.enable(port, restart)`.

## CLI

```sh
steam-engine status              # probe endpoint
steam-engine targets             # list debuggable targets
steam-engine enable [--restart]  # patch webhelper wrapper (Linux)
steam-engine eval '<js>'         # raw JS in SharedJSContext
```

## Caveats

- Internal, undocumented API — names/arg shapes can change between client
  builds. The dynamic proxy absorbs most churn.
- Requires a running Steam client with the debug port patched.
- `steamwebhelper_sniper_wrap.sh` is regenerated on client updates —
  re-run `enable` (original backed up to `.sh.bak`).
- Debug port binds to 127.0.0.1 only.
