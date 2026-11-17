# Tests, CI and releases

Public page: https://homecore.io/docs/development/dev-workflow

## Tests

From `core/`:

```bash
cargo test --all-features                          # the whole workspace, as CI runs it
cargo test -p hc-core                              # one crate
cargo test -p homecore --test integration_test     # one integration binary
cargo test -p hc-core repeat_until                 # tests whose names contain this
cargo test --workspace -- --nocapture              # show println! output
```

| Where | What its tests cover |
|---|---|
| `crates/hc-auth` | password hashing, JWT issue and validation, roles, refresh rotation |
| `crates/hc-types` | rule vocabulary, snapshotted in `docs/rule-vocabulary.json` (regenerate with `UPDATE_VOCABULARY=1 cargo test -p hc-types --features schema`) |
| `crates/hc-core` | triggers, conditions, the action executor, the scheduler |
| `crates/hc-state` | device registry and history |
| `homecore/tests/` | the full stack in-process: MQTT to state to rules, scopes, API keys, sessions, plugin runtimes, streaming, and `openapi_covers_router_test` (fails if `docs/openapi.yaml` and the router disagree) |
| `core/plugins/hc-*` | each plugin's own unit tests; `ui/` tests run with `vitest` |

Integration tests start an embedded broker on a free port and use temp
files. They never need hardware. Tests marked `#[ignore]` that need a
stand-in say so in their plugin's README (for example hc-reolink's).

Write tests against shapes copied from real devices, with secrets
scrubbed. Never write a test that sends a command to a real device.

Other repos:

```bash
# clients/hc-web-svelte
npm test
# sdks/hc-plugin-sdk-py (in a venv)
pip install -e '.[dev]' && pytest -q tests/
# sdks/hc-plugin-sdk-js
npm ci && npm test
# sdks/hc-plugin-sdk-dotnet
dotnet build HomeCoreSdk.csproj --configuration Release -warnaserror
dotnet test tests/HomeCore.PluginSdk.Tests.csproj --configuration Release
```

## What CI runs

| Repo | Workflow | Steps |
|---|---|---|
| core | `.github/workflows/ci.yml` calling `hc-scripts` `rust-ci.yml@main` | `cargo fmt --all --check`; `cargo clippy --all-targets --all-features -- -D warnings -A clippy::type_complexity`; `cargo test --all-features`. Plus a job that builds every `plugins/*/ui` (`npm ci && npm run build`, must produce `dist/manifest.json`). |
| core | `canary.yml` (weekly) | the same Rust checks on latest stable. Gates nothing. Red means "stable moved", a preview of the next pin bump. |
| hc-web-svelte | `ci.yml` calling `node-ci.yml@main` | `npm ci`, `typecheck`, `lint` (fails on warnings), `format:check`, `test`, `build`, then the size budget |
| SDKs | their own `ci.yml` | the test commands above |

CI runs on pushes to `develop` and `main` and on pull requests into
either. When `develop` goes red, the shared workflow opens a tracking
issue and closes it on recovery.

### Reproduce CI before pushing

From `core/`, with the pinned toolchain (`rustc --version` shows 1.99.x):

```bash
just check
```

That runs the same three commands as CI. `just check-plugin <name>` at
the workspace root uses looser clippy flags than CI, so do not treat it
as a CI check. If you changed a plugin's `ui/`:

```bash
cd core/plugins/<name>/ui && npm ci && npm run build && ls dist/manifest.json
```

Commit `ui/package-lock.json` (core ignores lockfiles elsewhere, so the UI
needs `!package-lock.json` in its `.gitignore`).

For the web app:

```bash
npm run typecheck && npm run lint && npm run format:check && npm test
npm run build && npm run budget
```

### Why local green can be CI red

- **Toolchain.** CI compiles with the pinned Rust (1.99). A newer local
  Rust has a different clippy lint set. Fix: `rustup override set 1.99` in
  `core/`.
- **Features.** CI runs with `--all-features` across the whole workspace,
  so a plugin that only compiled because a sibling enabled a feature fails
  there.
- **Warnings.** CI denies all warnings (`-D warnings`).

### Rules for workflow files

- Every caller's `ci.yml` (and any `release.yml` that runs CI as a gate)
  declares `permissions: {contents: read, issues: write}`. Without it the
  run dies at startup with zero jobs and no error message.
- Callers do not override `rust_version` or `node_version`. The pinned
  defaults match what the Dockerfiles ship. Bump them in `hc-scripts`
  together with the Dockerfiles.
- The reusable workflows are referenced as `@main`, so a change merged to
  `hc-scripts` `main` is live for every repo at once. Work on `develop`
  there and PR to `main`.

## Releases

Pushes to `develop` need no ceremony. A release does. The full history
behind these rules is in `hc-scripts/README.md`.

### Tags

| Tag | Releases |
|---|---|
| `v<version>` in core | the server: tarball, checksum, `ghcr.io/homecore-io/hc-core` image |
| `hc-<name>-v<version>` in core | one plugin: a signed `.tar.zst` registry artifact (with its `ui/` if it has one) |
| `v<version>` in hc-web-svelte | the `ghcr.io/homecore-io/hc-web-svelte` image |
| `v<version>` in an SDK repo | a GitHub Release only |

There is no cross-repo tag ordering. Nothing goes to npm, crates.io, PyPI
or NuGet.

### Sequence

1. On `develop`, bump the version:
   - server: `version` in `core/homecore/Cargo.toml` and `info.version`
     in `core/docs/openapi.yaml`, then refresh `Cargo.lock`
     (`cargo check`). A test fails if the two disagree, so run checks
     after the bump.
   - plugin: `version` in `core/plugins/<name>/Cargo.toml`.
   - web app: `version` in `package.json`.
2. Write the entry in `homeCore-io.github.io/docs/release-notes.md`, for
   people running a house: what they can now do, what they must change on
   upgrade, what is deliberately unchanged. A release with nothing an
   operator would notice still gets an entry saying so.
3. Push `develop`, merge to `main`, push `main`.
4. Watch CI on that commit (`gh run watch`). Continue only when green.
5. Tag last: `git tag v<version> && git push origin v<version>`. A core
   release that changes plugins tags each of them on the same commit.
6. Watch the release run.

To prove the release pipeline without making a release:

```bash
gh workflow run release.yml --ref develop                   # the server
gh workflow run release.yml --ref develop -f plugin=hc-<name>   # a plugin
```

This builds and archives with no GitHub Release and no registry update.
It is also how a `:dev` image gets built; `:dev` is not built on every
push.

If a tag's artifacts are already published and something is wrong, fix
forward with a new version. Never move a published tag.

Release one thing at a time and read each CI result before the next.
