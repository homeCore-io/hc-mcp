---
name: dev-environment
description: Sets up and checks a homeCore development environment from scratch. Covers the toolchain (Rust pinned to CI, Node 24, Python, .NET), cloning the multi-repo workspace, building and running core, the SvelteKit web app and the plugin SDKs, running a safe sandbox with stand-in devices, running the same checks CI runs, and how releases are cut. Use when someone asks to "set up a homeCore dev environment", "build homeCore from source", "run a sandbox", "run homeCore locally", "run the web app against a dev core", "run the tests", "why does CI fail when it passes locally", or is new to contributing to homeCore. Not for installing homeCore to run a house; use the install guide for that.
license: MIT OR Apache-2.0
---

# homeCore dev environment

Follow the stages in order. Each one ends with a check. Do not move on
until the check passes.

Public docs for depth: [Dev Workflow](https://homecore.io/docs/development/dev-workflow)
and [Workspace Layout](https://homecore.io/docs/development/workspace).

## Safety rules (read first)

- Never point a dev build, a test, or the web app's dev server at a real
  house. Use a sandbox: its own `--home`, its own config, its own ports,
  and stand-in devices.
- `hc-scripts/run-dev.sh` is NOT sandboxed. It starts core with
  `core/config/homecore.dev.toml`, which launches the real plugins with
  their real configs, so it talks to real hubs, real devices and real
  cloud accounts. Do not use it unless that is exactly what you want, and
  never for anything destructive.
- `cargo run -p homecore` from inside `core/` with no `--home` uses
  `core/` as its home and loads the tracked `core/config/homecore.toml`,
  which declares plugins. Always pass `--home` and `--config`.
- No discovery from a sandbox (it would find real devices on your LAN).
- Nothing is published to npm, crates.io, PyPI or NuGet. Install SDKs
  from the workspace checkout or a git tag. Do not publish anything.

## Decisions to make up front

| Question | Choose |
|---|---|
| OS | Linux or macOS work natively. On Windows, use WSL2: every workspace script is bash. |
| Docker or native | Native for development. Docker images (`hc-core`, `hc-web-svelte`) are for running released or `:dev` builds; see [Docker](https://homecore.io/docs/getting-started/docker). |
| Nix | If you use Nix, a devenv config pins the whole toolchain. See [references/toolchain.md](references/toolchain.md). |
| Which repos | `core` and `hc-scripts` always. Add `hc-web-svelte` for UI work, an SDK repo for non-Rust plugins, `homeCore-io.github.io` for docs. `workspace-clone.sh` clones all of them. |

## Stage 1: Install the toolchain

Required for core: Rust 1.99 (the version CI and the release images use),
a C compiler, `cmake`, `pkg-config`, `git`. Node.js 24 for the web app and
plugin screens. `just`, `jq` and `curl` for recipes and API calls. `gh` if
you will cut releases. Python 3.11+ and .NET 8 only for those SDKs.

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup toolchain install 1.99 --component clippy --component rustfmt
cargo install just
```

Per-OS package lists, the Nix route, and why the pin matters:
[references/toolchain.md](references/toolchain.md).

**Check it works:**

```bash
rustc +1.99 --version     # rustc 1.99.x
node --version            # v24.x
just --version && jq --version
```

## Stage 2: Clone the workspace

The workspace root is a plain directory, not a git repo. Each
subdirectory is its own repo, listed in `hc-scripts/workspace.toml`.

```bash
mkdir homeCore && cd homeCore
git clone -b develop https://github.com/homeCore-io/hc-scripts.git hc-scripts
ln -s hc-scripts/workspace.toml workspace.toml
ln -s hc-scripts/Justfile.workspace Justfile
./hc-scripts/workspace-clone.sh
```

`workspace-clone.sh` clones every missing repo on `develop` using SSH
remotes (`git@github.com:...`). Without a GitHub SSH key, rewrite them to
HTTPS first:

```bash
git config --global url."https://github.com/".insteadOf "git@github.com:"
```

Then pin Rust inside core so plain `cargo` uses the CI version there:

```bash
cd core && rustup override set 1.99 && cd ..
```

Layout, what each repo is, and which ones are retired:
[references/workspace.md](references/workspace.md).

**Check it works:**

```bash
git -C core branch --show-current       # develop
ls core/homecore core/sdk/rust core/plugins
(cd core && rustc --version)            # 1.99.x
```

## Stage 3: Build core

`core/` is one cargo workspace: the server (`homecore/`), its crates, the
Rust SDK (`sdk/rust`), the runtime host and every Rust plugin. Build from
`core/`.

```bash
cd core
cargo check --workspace          # fastest feedback
cargo build -p homecore          # the server only
cargo build --workspace          # server and every plugin
```

Binaries land in `core/target/debug/`. A first build takes several minutes
and several GB of disk.

**Check it works:**

```bash
ls -l target/debug/homecore target/debug/hc-plugin-template
```

## Stage 4: Run a sandbox

A sandbox is a homeCore with its own home directory, loopback-only ports
that do not collide with any other core on the machine, and only stand-in
plugins. Create one outside the repos:

```bash
SBX=$HOME/hc-sandbox
mkdir -p "$SBX/config"
cat > "$SBX/config/homecore.toml" <<'EOF'
[server]
host = "127.0.0.1"
port = 18080

[broker]
host = "127.0.0.1"
port = 11883
v5_port = 11884
EOF

core/target/debug/homecore --home "$SBX" --config "$SBX/config/homecore.toml"
```

The `[broker]` section is required. With no config at all, core binds the
broker to `0.0.0.0` with no credentials and refuses to start, on purpose.

On first start core creates `data/`, `logs/`, `rules/` and an admin
account, and writes the password to `$SBX/INITIAL_ADMIN_PASSWORD`.

**Check it works** (second terminal):

```bash
curl -s http://127.0.0.1:18080/api/v1/health
# {"status":"ok","version":"0.1.x"}

PASS=$(sed -n 's/^Password: //p' "$SBX/INITIAL_ADMIN_PASSWORD")
TOKEN=$(curl -s -X POST http://127.0.0.1:18080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$PASS\"}" | jq -r .token)
curl -s http://127.0.0.1:18080/api/v1/devices -H "Authorization: Bearer $TOKEN" | jq -r '.[].device_id'
# mode_day, mode_night
```

Add a stand-in device (the template plugin simulates a light with no
hardware), reset the sandbox, and use the workspace `just sandbox`
recipes: [references/sandbox.md](references/sandbox.md).

## Stage 5: Run the web app against the sandbox

The web app is `clients/hc-web-svelte` (SvelteKit plus a small Node UI
server). Its dev server passes `/api/v1` and the event stream through to
core on the same origin, because core sends no CORS headers.

```bash
cd clients/hc-web-svelte
npm install
HC_CORE_URL=http://127.0.0.1:18080 npm run dev     # http://localhost:5180
```

Set `HC_CORE_URL` in the shell. The proxy reads `process.env`, and the
`.env` file is not loaded into it.

**Check it works:**

```bash
curl -s http://localhost:5180/api/v1/health    # same JSON as stage 4
```

Then open http://localhost:5180 and sign in as `admin`.

## Stage 6: SDKs and other repos (only if you need them)

| Repo | Set up | Test |
|---|---|---|
| `sdks/hc-plugin-sdk-py` | `pip install -e '.[dev]'` (in a venv) | `pytest -q tests/` |
| `sdks/hc-plugin-sdk-js` | `npm ci` | `npm test` |
| `sdks/hc-plugin-sdk-dotnet` | `dotnet build --configuration Release -warnaserror` | `dotnet test tests/HomeCore.PluginSdk.Tests.csproj` |
| `clients/hc-mcp` | `python3 -m venv .venv && .venv/bin/pip install -e .` | see its README |

A plugin uses an SDK straight from the checkout, so SDK edits are live:

```bash
pip install -e ../../sdks/hc-plugin-sdk-py
npm install ../../sdks/hc-plugin-sdk-js
dotnet add reference ../../sdks/hc-plugin-sdk-dotnet/HomeCoreSdk.csproj
```

The Rust SDK needs nothing: it is a member of core's workspace. Details
and how plugins in other languages run: [references/workspace.md](references/workspace.md).
For writing a plugin, see [Developing Plugins](https://homecore.io/docs/plugins/developing-plugins).

**Check it works:** each repo's test command passes.

## Stage 7: Run the checks CI runs

Before every push, run exactly what CI runs. From `core/`, with Rust 1.99:

```bash
cargo fmt --all --check
cargo clippy --all-targets --all-features -- -D warnings -A clippy::type_complexity
cargo test --all-features
```

`just check` in `core/` runs the same three steps. For the web app:

```bash
npm run typecheck && npm run lint && npm run format:check && npm test
npm run build && npm run budget
```

If you changed a plugin's `ui/`, also run `npm ci && npm run build` in
that `ui/` and confirm `dist/manifest.json` exists.

What CI runs where, and the rules for workflows:
[references/testing-and-ci.md](references/testing-and-ci.md).

**Check it works:** all commands exit 0.

## Stage 8: Branches and releases (high level)

- Work lands on `develop`. Pushes there need no ceremony. CI runs on every
  push and on pull requests into `develop` or `main`.
- Releases are cut from `main`, by tag, and only after CI on that exact
  commit is green. Tag last.
- `v<version>` releases core (tarball and `hc-core` image).
  `hc-<name>-v<version>` releases one plugin as a signed registry
  artifact. The web app and SDKs release from their own repos with `v*`
  tags.
- Every release gets an entry in
  [Release Notes](https://homecore.io/docs/release-notes),
  written for people running a house, as part of cutting it.

Full sequence and the version files to bump:
[references/testing-and-ci.md](references/testing-and-ci.md#releases).

## Common mistakes

| Symptom | Cause and fix |
|---|---|
| `[broker] is bound to 0.0.0.0 (non-loopback) with no [[broker.clients]]` | No config, or no `[broker]` section. Add `host = "127.0.0.1"` under `[broker]`. |
| `the MQTT broker can't listen on 127.0.0.1:1883: Address already in use` | Another core is running. Give the sandbox its own `port` and `v5_port` (v5 defaults to 1884). |
| Core starts real plugins or talks to real devices | You ran without `--home`, ran `run-dev.sh`, or `HOMECORE_HOME`/`HOMECORE_CONFIG` in your shell point at a real config. Stop it, then pass `--home` and `--config` explicitly. |
| Clippy passes locally, fails in CI | Local Rust is newer than 1.99. Run `rustup override set 1.99` in `core/`. |
| Web app shows a sign-in error or talks to the wrong core | `HC_CORE_URL` not exported. Pass it on the `npm run dev` command line. |
| `workspace-clone.sh` reports `[fail]` | No SSH key for GitHub. Use the `insteadOf` rewrite in stage 2. |
| `Cargo.lock` changed after `run-dev.sh` | It runs `cargo update` by default. Pass `--no-update`, and revert the lockfile if you did not mean to change it. |

More, with fixes: [references/troubleshooting.md](references/troubleshooting.md).

## Reference files

- [references/toolchain.md](references/toolchain.md): read when installing
  tools on a specific OS, using Nix/devenv, or when local and CI results differ.
- [references/workspace.md](references/workspace.md): read to understand
  the repo layout, which repos are retired, and the workspace scripts
  (`run-dev.sh`, `deploy.sh`, `just` recipes).
- [references/sandbox.md](references/sandbox.md): read before running
  anything that sends commands, adds plugins, or needs stand-in devices.
- [references/testing-and-ci.md](references/testing-and-ci.md): read
  before pushing, when CI fails, or before cutting a release.
- [references/troubleshooting.md](references/troubleshooting.md): read
  when a stage's check fails.
