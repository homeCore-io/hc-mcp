# Troubleshooting

Find the symptom, apply the fix, then rerun the failed stage's check.

## Cloning

**`workspace-clone.sh` prints `[fail]` for every repo.** The manifest uses
SSH remotes and you have no GitHub SSH key. Either add a key to GitHub or
rewrite to HTTPS:

```bash
git config --global url."https://github.com/".insteadOf "git@github.com:"
./hc-scripts/workspace-clone.sh
```

**`workspace.toml not found`.** The script reads
`hc-scripts/workspace.toml` next to itself. Run it from a full clone of
`hc-scripts`, not a copy of the script.

**`pull failed on <branch> (diverged or dirty?)`.** That repo has local
commits or uncommitted changes. Resolve it in that repo; the script only
fast-forwards.

## Building

**`linker cc not found`, or a `-sys` crate fails to build.** Install a C
compiler, `cmake` and `pkg-config` (see [toolchain.md](toolchain.md)).

**Out of disk.** `core/target/` grows to many GB. `cargo clean` in `core/`
(or `just clean-release` to drop only release artifacts).

**A plugin fails to compile after a change in `crates/hc-types`.** That
crate is the plugin ABI. Fix the plugin in the same change; CI builds the
whole workspace together.

## Running core

**`[broker] is bound to 0.0.0.0 (non-loopback) with no [[broker.clients]]
credentials configured`.** Core found no config, or a config with no
`[broker]` section, and refuses to run an anonymous broker on the LAN.
Check the config path in the first two lines of output (`homeCore config
file: ...`), then add:

```toml
[broker]
host = "127.0.0.1"
```

**`the MQTT broker can't listen on 127.0.0.1:<port>: Address already in
use`.** Another core (or a Mosquitto) holds the port. Find it with
`ss -ltnp | grep <port>` (Linux) or `lsof -i :<port>` (macOS), stop it, or
give the sandbox different `port` and `v5_port` values. The v5 listener
defaults to 1884, so set it too.

**API port in use.** Change `[server] port`.

**Core loaded the wrong config or started plugins you did not declare.**
Read the first two lines of output: `homeCore base directory` and
`homeCore config file`. Resolution order is `--home`, then
`HOMECORE_HOME`, then the current directory; and `--config`, then
`HOMECORE_CONFIG`, then `<home>/config/homecore.toml`. Run
`env | grep ^HOMECORE_` and pass both flags explicitly. Running from
`core/` with no flags loads the tracked `core/config/homecore.toml`.

**`Warning: config parse error ...; using defaults`.** A TOML syntax error.
Core falls back to defaults, which then trips the broker guard. Fix the
file.

**No `INITIAL_ADMIN_PASSWORD` file.** It is written only when no users
exist. If you reused a `data/` directory, the admin already exists. Reset
the sandbox (see [sandbox.md](sandbox.md)) or use the password you set.

**Login returns `{"error":"invalid credentials"}`.** You passed the whole
file as the password. Extract only the value:

```bash
sed -n 's/^Password: //p' <home>/INITIAL_ADMIN_PASSWORD
```

**A plugin keeps restarting.** Check `<home>/logs/` and the plugin's own
`logs/`. Common causes: its config names the wrong `broker_port`, its
`plugin_id` does not match the `[[plugins]] id`, or the `binary` path is
wrong (relative paths resolve against `--home`).

**Edits to a plugin's config have no effect.** After the first start core
uses its own copy at `<home>/config/plugins/<plugin_id>.toml`. Edit that.

## Web app

**The app loads but every API call fails, or it reaches the wrong core.**
The dev proxy reads `HC_CORE_URL` from the process environment and
defaults to `http://127.0.0.1:8080`. Values in `.env` do not reach it.
Start it as:

```bash
HC_CORE_URL=http://127.0.0.1:<sandbox-port> npm run dev
```

**`Port 5180 is already in use`.** The dev server uses a strict port. Stop the
other dev server.

**`npm run lint` fails but `typecheck` passes.** Lint is `svelte-check`
with `--fail-on-warnings`. Fix the warnings.

**`npm run budget` fails.** The home screen's JavaScript must stay within
its compressed size budget. Trim what you added to the initial bundle.

## CI

**Green locally, red in CI on clippy.** Toolchain mismatch. Run
`rustup override set 1.99` in `core/` and rerun `just check`.

**A run fails at startup with zero jobs and no annotation.** The calling
workflow is missing `permissions: {contents: read, issues: write}`.

**The plugin screens job fails with `built no dist/manifest.json`.** The
plugin's `ui` build did not write its manifest, or `ui/package-lock.json`
is not committed.

**The canary is red.** Latest stable Rust added lints. Nothing is broken;
it previews the next pin bump.

## `run-dev.sh` surprises

**It changed `Cargo.lock`.** It runs `cargo update` unless you pass
`--no-update` (or `--no-pull`). Revert with `git -C core checkout
Cargo.lock` if you did not want that.

**It pulled every repo.** Pass `--no-pull`.

**It connected to real devices.** That is what it does: it runs the real
plugin configs. Use a sandbox instead (see [sandbox.md](sandbox.md)).
