# Workspace layout and scripts

Public page with the full tree and the crate dependency order:
https://homecore.io/docs/development/workspace

## The repos

The workspace root is a plain directory. Each subdirectory below is its
own git repo, listed in `hc-scripts/workspace.toml` (the source of truth)
and cloned by `hc-scripts/workspace-clone.sh` on `develop`.

| Path | Repo | What it is |
|---|---|---|
| `core/` | homeCore | The server (`homecore/`), its crates (`crates/hc-*`), the Rust SDK (`sdk/rust`, crate `plugin-sdk-rs`), the plugin screen types (`sdk/ui`), the runtime host, and every Rust plugin (`plugins/hc-*`). One cargo workspace, one `Cargo.lock`. |
| `hc-scripts/` | hc-scripts | `workspace-clone.sh`, `run-dev.sh`, `deploy.sh`, `build-archive.sh`, the workspace `Justfile`, and the reusable GitHub Actions workflows every repo calls. |
| `clients/hc-web-svelte/` | hc-web-svelte | The web app (SvelteKit) and the Node UI server it runs in. |
| `clients/hc-tui/` | hc-tui | Terminal UI (Rust, its own lockfile). |
| `clients/hc-mcp/` | hc-mcp | MCP server and the app's Assistant plugin (Python). |
| `sdks/hc-plugin-sdk-py/`, `-js/`, `-dotnet/` | one repo each | Plugin SDKs for Python, Node.js and .NET. |
| `plugins/hc-matter/` | hc-matter | Matter bridge (TypeScript). |
| `plugins-py/` | hc-plugins-py | Every Python plugin, in one repo. |
| `extensions/` | hc-extensions | UI extensions for the web app (drawings and cards). |
| `homeCore-io.github.io/` | homeCore-io.github.io | The docs site (Docusaurus). |

Retired, kept for history only: `clients/hc-web-flutter`,
`clients/hc-web-lit`, `clients/hc-web-leptos`. Do not develop against them.
Anything that mentions `sdks/hc-plugin-sdk-rs`, `plugins/Cargo.toml` or a
`[patch]` table predates the move of the Rust SDK and plugins into `core/`.

The Docker images and compose files live in a separate repo,
`homeCore-io/docker`, which `workspace-clone.sh` does not clone. You only
need it to work on the container stack.

## Keeping repos current

```bash
./hc-scripts/workspace-clone.sh            # clone anything missing
./hc-scripts/workspace-clone.sh --fetch    # fetch every repo
./hc-scripts/workspace-clone.sh --pull     # fast-forward every repo
./hc-scripts/workspace-clone.sh --checkout develop
```

## Building pieces of core

From `core/`:

```bash
cargo check -p hc-core                 # one crate
cargo build -p hc-hue                  # one plugin
cargo build --workspace --release      # optimized, everything
cargo run -p homecore -- --home <sandbox> --config <sandbox>/config/homecore.toml
```

A change to `crates/hc-types` recompiles everything, plugins included,
because it is the plugin ABI. A change to `crates/hc-api` recompiles only
`hc-api` and `homecore`.

A new Rust plugin goes in `core/plugins/<name>/` and is added to
`[workspace] members` in `core/Cargo.toml`. Start from
`core/plugins/hc-plugin-template/`.

## Non-Rust plugins and SDKs

A plugin in another language points at its SDK's checkout, so SDK edits
are live with no reinstall:

```bash
# from the plugin's directory, e.g. plugins/hc-mything/
pip install -e ../../sdks/hc-plugin-sdk-py
npm install ../../sdks/hc-plugin-sdk-js
dotnet add reference ../../sdks/hc-plugin-sdk-dotnet/HomeCoreSdk.csproj
```

Outside the workspace, install from a git tag (no package registry has
them):

```bash
pip install git+https://github.com/homeCore-io/hc-plugin-sdk-py@v<version>
npm install github:homeCore-io/hc-plugin-sdk-js#v<version>
```

Non-Rust plugins run under a plugin runtime (`hc-runtime-host`, built from
`core/runtime-host`). See
[Plugin Runtimes](https://homecore.io/docs/plugins/runtimes) and
[Developing Plugins](https://homecore.io/docs/plugins/developing-plugins).

## Workspace `just` recipes

The root `Justfile` is a symlink to `hc-scripts/Justfile.workspace`.

| Recipe | Does |
|---|---|
| `just check` | core's `just check`, then fmt, clippy and test for the standalone Rust clients |
| `just check-core` | core's `just check` (the same flags CI uses) |
| `just check-plugin <name>` | fmt, clippy, test for one workspace member. Its clippy flags are looser than CI's. |
| `just build` / `just build-release` | build everything Rust |
| `just clean`, `just clean-release` | `cargo clean` everything Rust. Never touches `sandbox/`. |
| `just sandbox`, `sandbox-run`, `sandbox-build` | run `<workspace>/sandbox`; see [sandbox.md](sandbox.md) |

`just check-clients` also checks the retired `hc-web-leptos`; if you did
not clone it, run `just check-core` instead.

## `run-dev.sh` runs against real hardware

`./hc-scripts/run-dev.sh` does, in order:

1. `git pull --ff-only` in hc-scripts, `core/`, each SDK, each plugin
   repo under `plugins/`, and each client repo (skip with `--no-pull`).
2. `cargo update` on core, which rewrites `Cargo.lock` (skip with
   `--no-update`).
3. Builds `homecore`, then each plugin in core's workspace. A failed
   plugin build only warns, and the old binary is used (skip with
   `--no-build`).
4. Starts `core/target/<profile>/homecore --home core --config
   config/homecore.dev.toml`. `--webui` also starts the web app's dev
   server on :5180 pointed at it.

`homecore.dev.toml` launches the real plugins with the configs under
`core/plugins/<name>/config/config.dev.toml`. Those files are gitignored
and hold real hub addresses and cloud credentials. Running this script
means running against the real house. Use it only on purpose, never for
anything destructive, and never from an AI agent without the owner's
explicit go-ahead.

## `deploy.sh`

`./hc-scripts/deploy.sh` builds and installs a production-like layout to
`/var/tmp/homeCore` (or `--dest DIR`). Its plugin list still points at
`plugins/hc-<name>` paths and the retired Leptos UI, so it is out of date
with the monorepo layout. Prefer a sandbox from [sandbox.md](sandbox.md),
or a [binary release](https://homecore.io/docs/getting-started/binary-releases)
for an install test.
