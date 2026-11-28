# CI and releasing a plugin

Read this when you set up CI for a plugin, cut a release, or need to know how
a plugin reaches homeCore's Catalog. The shared workflows are in
[hc-scripts](https://github.com/homeCore-io/hc-scripts)
(`.github/workflows/`); its README is the detail. The Catalog's index lives
in [registry](https://github.com/homeCore-io/registry).

## What can be released today

| Language | Package | Runs in | Workflow |
|---|---|---|---|
| Rust | static x86_64 musl binary, plus `ui/`, as `.tar.zst` | homeCore itself, as a child process | `rust-release.yml` |
| Python | wheelhouse `.tar.zst` for x86_64 and aarch64 | a plugin runtime container | `python-release.yml` |
| Node.js | the app and its `node_modules`, pure JavaScript, one `.tar.zst` for x86_64 and aarch64 | a Node.js plugin runtime | `node-release.yml` |
| .NET | none yet | | none |

A .NET plugin can be written and run against a homeCore you control (a
`[[plugins]]` entry, or a service of its own), but there is no artifact
format, workflow or runtime to put it in the Catalog.

## How the Catalog works

A release builds a package, attaches it to a GitHub Release, and notifies the
registry repository with a `repository_dispatch` (`publish-plugin`). The
registry adds the entry to `index.json` (keeping the newest three versions of
each plugin), signs the index with ed25519, and publishes it on GitHub Pages
at `https://homecore.io/registry/index.json`. The release job then polls the
served index until its entry appears, so a green release means an
installable plugin.

homeCore checks the index's signature against the public key in its
`[registry]` config, downloads the package, checks the package's sha256
against the signed index, and installs it: a native plugin under
`plugins/<id>/<version>/` beside homeCore, a Python or Node.js plugin into a
runtime.
People install and update from **Plugins → Catalog** in the web app.

Only the index is signed; each package is pinned by its sha256 in it.

The dispatch needs a token with access to the registry repository, which
only repositories in the homeCore-io organization hold. A plugin from
elsewhere needs a maintainer to publish it, or a registry of your own
(`scripts/gen-key.sh` in the registry repository, and each homeCore's
`[registry]` pointed at it).

## CI

Every caller of the shared CI workflows needs this permissions block. Without
it the run dies at startup with no jobs and no message, because the
workflows open and close a "CI failing" issue:

```yaml
permissions:
  contents: read
  issues: write
```

A Rust plugin in its own repository:

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push: { branches: [main, develop] }
  pull_request: { branches: [main] }
permissions:
  contents: read
  issues: write
jobs:
  ci:
    uses: homeCore-io/hc-scripts/.github/workflows/rust-ci.yml@main
```

`rust-ci.yml` runs `cargo fmt --all --check`, `cargo clippy --all-targets
--all-features -- -D warnings -A clippy::type_complexity` and
`cargo test --all-features` on the Rust version the release images ship. Do
not override `rust_version`: local green on a newer toolchain is not CI
green.

`node-ci.yml` runs the npm scripts a repository defines (`typecheck`, `lint`,
`format:check`, `test`, `build`). There is no shared Python CI; hc-mcp's
`ci.yml` (uv, Python 3.11 and 3.13, ruff, pytest) is a good copy.

If the plugin has `ui/`, add a job that runs `npm ci && npm run build` in
`ui/` and fails when `ui/dist/manifest.json` is missing. Commit
`ui/package-lock.json`.

## Releasing a Rust plugin in the homeCore repository

1. Bump `version` in `plugins/hc-<name>/Cargo.toml` on `develop`.
2. Merge to `main` and wait for CI on that commit to pass.
3. Push one tag: `hc-<name>-v<version>` (for example `hc-demo-v0.1.0`).

Core's `release.yml` matches `hc-*-v*` and calls `rust-release.yml`, which:

- fails if the tag's version differs from `Cargo.toml`;
- builds a static `x86_64-unknown-linux-musl` binary;
- builds `ui/` with `npm ci && npm run build` when `ui/package.json` exists;
- writes `plugin.toml` and packs it with the binary and `ui/` into
  `plugin.<name>-<version>-linux-x86_64.tar.zst`;
- attaches it (and a `.tar.gz` with the example config and README) to the
  GitHub Release and notifies the registry.

The generated `plugin.toml`:

```toml
id = "plugin.demo"     # from the binary name: hc-demo becomes plugin.demo
name = "Demo"
version = "0.1.0"
binary = "hc-demo"
ui = "ui"              # only when the plugin has ui/package.json
```

The plugin id is derived from the binary name. Keep the `plugin_id` your code
and config use equal to it.

What the Catalog shows comes from `Cargo.toml`:

```toml
[package]
description = "Demo lamps on the local network"   # the line under its name

[package.metadata.homecore]
name = "Demo"            # the name people see
category = "Lighting"    # Lighting, Climate, Media, Hubs, Weather, Tools, or a new one
```

Prove the pipeline without publishing: run core's `release.yml` by hand
(`workflow_dispatch`) with the plugin's name. It builds and packs, and makes
no Release and no registry entry. Tag last: once a release is out, fix
forward with a new version and never move a tag.

A Rust plugin in its own repository calls `rust-release.yml` directly on a
`v*` tag:

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ['v*']
  workflow_dispatch:
permissions:
  contents: write
jobs:
  release:
    uses: homeCore-io/hc-scripts/.github/workflows/rust-release.yml@main
    secrets: inherit
    with:
      binary_name: hc-demo
      config_example: config/config.toml.example
      publish_registry: true
```

## Releasing a Python plugin

Python plugins run in a **plugin runtime**: a container the operator runs
and adds in homeCore (Settings › Plugins › Runtimes), which installs each
plugin offline into its own environment and starts it with
`python -m <entrypoint> <config path>`. See
[Plugin Runtimes](https://homecore.io/docs/plugins/runtimes). The runtime
image is part of homeCore's release; a plugin release only produces what the
runtime installs.

`pyproject.toml` needs:

```toml
[project]
name = "hc-demo"
version = "0.1.0"
description = "Demo lamps on the local network"   # the Catalog's line
dependencies = ["homecore-plugin-sdk>=0.5.6"]     # required

[tool.homecore]
id = "plugin.demo"           # required
entrypoint = "hc_demo.plugin" # required
name = "Demo"
category = "Lighting"
```

Ship screens inside the wheel (for hatchling,
`[tool.hatch.build.targets.wheel.force-include] "ui" = "hc_demo/ui"`), where
the SDK's `ui.find_dir` looks.

The release workflow:

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ['v*']
  workflow_dispatch:
permissions:
  contents: write
jobs:
  release:
    uses: homeCore-io/hc-scripts/.github/workflows/python-release.yml@main
    with:
      plugin_dir: .
      sdk_ref: v0.5.6          # the SDK tag built into the package
      python_version: '3.13'  # the Python you develop and test on
    secrets: inherit
```

`python-release.yml` (`manylinux_2_28`, x86_64 and aarch64 by default). Each
plugin is built for one Python minor, and the runtime runs it on exactly that
one, fetched from the registry (3.12 to 3.15 today; the newest if
`python_version` is left out, and the build lists what it has if you ask for
another). Set it to the Python you test on; `uv python install 3.13` gives you
the same build the house runs. The workflow:

1. builds the SDK at `sdk_ref` and the plugin as wheels;
2. locks all their dependencies with hashes (`uv pip compile`) and downloads
   every one as a binary wheel for the target platform;
3. packs `plugin.toml` (id, name, version, description, `runtime = "python"`,
   abi, arch, entrypoint, package, SDK version), `requirements.lock` and
   `wheelhouse/` into
   `plugin.<name>-<version>-python-<abi>-<arch>.tar.zst`;
4. smoke-tests the x86_64 package: installs it offline in a clean
   environment, starts it against a scratch broker, and waits for it to
   register, publish its manifest or report active;
5. attaches the packages to the GitHub Release and notifies the registry,
   one entry per architecture.

The workflow does not check the tag against `pyproject.toml`; the version
comes from `pyproject.toml`, so bump it before tagging. Build and smoke-test
locally with `build-python-artifact.sh` and `smoke-python-artifact.sh` from
hc-scripts (they need `uv` and `zstd`).

## Releasing a Node.js plugin

Node.js plugins run in the **Node.js plugin runtime**
(`ghcr.io/homecore-io/hc-runtime-node`, host networking so mDNS works),
which unpacks each plugin and runs
`<node> app/<entrypoint> <config path>` with no npm and no network.
[hc-matter](https://github.com/homeCore-io/hc-matter) is the working example.

`package.json` needs a `homecore` block, and the SDK in `dependencies`:

```json
{
  "name": "hc-demo",
  "version": "0.1.0",
  "description": "Demo lamps on the local network",
  "main": "out/main.js",
  "files": ["out/**/*.js", "ui/dist/**"],
  "dependencies": {
    "homecore-plugin-sdk": "git+https://github.com/homeCore-io/hc-plugin-sdk-js.git#v0.4.7"
  },
  "homecore": {
    "id": "plugin.demo",
    "name": "Demo",
    "category": "Lighting",
    "ui": "ui/dist"
  }
}
```

- `homecore.id` is required (`plugin.<name>`). The entrypoint is
  `homecore.entrypoint`, else `main`, else `index.js`, and must be in the
  package: list built output in `files` and build before packing.
- Commit `package-lock.json`. The package is installed from it with
  `npm ci --omit=dev --omit=optional --ignore-scripts`, so nothing may need
  an install script or an optional dependency to work. If a dependency you
  need at run time is optional upstream (`@matter/nodejs` was), declare it
  directly.
- **Pure JavaScript only.** A `.node` addon ties a package to one CPU and
  Node ABI, so the build refuses it. That is what lets one file serve x86_64
  and aarch64.

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ['v*']
  workflow_dispatch:
permissions:
  contents: write
jobs:
  release:
    uses: homeCore-io/hc-scripts/.github/workflows/node-release.yml@main
    with:
      plugin_dir: .
      node_version: '24'   # the Node.js major it runs on
    secrets: inherit
```

`node-release.yml` builds the package, starts it on the registry's own build
of that Node.js against a scratch broker, attaches it to the GitHub Release
and lists the same file for each architecture in `arches`. The registry has
Node.js 24 and 26 today. Patch releases reach houses as Node.js updates from
the runtime's card; the plugin needs no release for them. The version comes
from `package.json`, so bump it before tagging. Run the same build and check
locally with hc-scripts' `build-node-artifact.sh` and
`smoke-node-artifact.sh` (its `--interpreter` is an unpacked homeCore Node.js
interpreter folder; give it as an absolute path).

A plugin from outside homeCore-io sets `publish_registry: false` (Python and
Node.js alike) and asks for a listing on the registry repository.

## Before you tag

- CI on the release commit is green.
- The version is bumped where the build reads it.
- The README says what the plugin publishes, its commands, actions, alerts,
  settings and screens.
- `ui/package-lock.json` is committed, and the UI build writes
  `dist/manifest.json`.
- The release notes say what someone running a house can now do, what they
  must change on upgrade, and what must be updated together (an older
  homeCore ignores slots and fields it doesn't know; an older app shows
  generic screens).
