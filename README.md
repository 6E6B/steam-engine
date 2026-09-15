# steam-engine

Call a running Steam client’s internal JavaScript API from Python.

`steam-engine` connects to Steam’s CEF renderer over Chrome DevTools Protocol. It exposes `SteamClient.*` methods and `window.*` stores through a Python proxy, so operations run through Steam itself.

For a higher-level collections API, see the sibling project `steam-collections`.

## Get started

Install from the repository, then enable debugging in Steam:

```sh
pip install -e .
steam-engine enable --restart
steam-engine status
```

`enable` is Linux-only. It patches `ubuntu12_64/steamwebhelper_sniper_wrap.sh` and backs up the original to `.sh.bak`. Steam updates can replace this wrapper; run `enable` again if the connection stops working.

On Windows or macOS, launch Steam with `-cef-enable-debugging` or add `--remote-debugging-port` to the webhelper command line.

The default port is `1337`. Set `STEAM_CDP_PORT` to use another port.

## Use from Python

Steam must be running with debugging enabled.

```python
from steam_engine import SteamEngine

with SteamEngine.connect() as se:
    # Call Steam's native bridge.
    se.client.Apps.SetAppLaunchOptions(292030, "-fullscreen")

    # Snake_case works too.
    se.client.Apps.specify_compat_tool(105600, "proton_experimental")

    # Read a JavaScript property.
    apps = se.window.appStore.allApps.get()

    # Run JavaScript directly.
    count = se.eval("collectionStore.userCollections.length")
```

The proxy supports:

| Syntax                | Behavior                                                     |
| --------------------- | ------------------------------------------------------------ |
| `proxy.method(*args)` | Call a method with JSON-serialized arguments; await promises |
| `proxy.prop.get()`    | Read a JSON-serializable property                            |
| `proxy.prop.keys()`   | List own property names                                      |
| `proxy.prop[index]`   | Access an indexed value                                      |

Method names ignore case and underscores. Results are JSON-decoded; `undefined` and unserializable results become `None`.

## Use from the terminal

```sh
steam-engine status             # Check the connection
steam-engine targets            # List debuggable targets
steam-engine enable --restart   # Enable debugging and restart Steam (Linux)
steam-engine eval 'collectionStore.userCollections.length'
```

## API reference

The generated reference in `docs/` lists the discovered methods and stores. To refresh and browse it:

```sh
python scripts/dump_api_surface.py
mkdocs serve
```

Raw data is available at `docs/data/api_surface.json`.

Steam’s internal API is undocumented. Method names and arguments can change between client builds.

