# Toolchain

What to install, per OS, and why the versions are pinned.

## Versions that matter

| Tool | Version | Why this one |
|---|---|---|
| Rust | 1.99 (with `clippy`, `rustfmt`) | CI (`hc-scripts/.github/workflows/rust-ci.yml`, `rust_version` default) and the release Dockerfiles (`rust:1.99-alpine`) use it. A newer local toolchain has a different clippy lint set. |
| Node.js | 24 | `node-ci.yml` pins `node_version: "24"` and the web app's image builds from `node:24-alpine`. `package.json` accepts `>=22`, but test on 24. Plugin screens build with 24 in core's CI. |
| Python | 3.11 or newer | The Python SDK and `hc-mcp` require 3.11+. |
| .NET SDK | 8 or newer | The .NET SDK targets `net8.0`. |
| `just` | any | Recipes in the workspace root, `core/`, and each plugin. |
| `jq`, `curl` | any | API calls in the shell. |
| `gh` | any | Watching CI runs and dispatching release workflows. |
| C compiler, `cmake`, `pkg-config` | any | Some Rust dependencies compile bundled C (SQLite, zstd, aws-lc). OpenSSL headers are not needed; homeCore uses rustls. |
| `websocat` | optional | Watching the event stream: `cargo install websocat`. |

There is no `rust-toolchain.toml` in core, so pin it yourself:

```bash
rustup toolchain install 1.99 --component clippy --component rustfmt
cd <workspace>/core && rustup override set 1.99
```

`rustup override` is stored in rustup's own settings for that directory and
changes nothing in the repo. When the pin moves (the `rust_version` default
in `rust-ci.yml` and the Dockerfiles' `rust:<ver>-alpine` move together),
repeat with the new version.

## Linux

Debian or Ubuntu:

```bash
sudo apt install build-essential cmake pkg-config git curl jq
```

Fedora:

```bash
sudo dnf install gcc gcc-c++ make cmake pkgconf-pkg-config git curl jq
```

Then Rust from https://rustup.rs (stage 1 of SKILL.md), Node 24 from your
distribution, NodeSource, or a version manager such as `nvm`
(`nvm install 24`), and `cargo install just`.

## macOS

```bash
xcode-select --install
brew install cmake pkg-config jq just gh node@24
```

Then Rust from https://rustup.rs.

## Windows

Use WSL2 with a Linux distribution and follow the Linux steps inside it.
The workspace scripts (`workspace-clone.sh`, `run-dev.sh`, the `just`
recipes) are bash. Core does build on Windows and ships a service
installer (`core/scripts/install-service.ps1`), but the dev workflow
assumes a Unix shell.

## Nix and devenv

If you use Nix, a [devenv](https://devenv.sh) config at the workspace root
gives every contributor the same tools. The workspace root is not a repo,
so create these files yourself.

`devenv.yaml`:

```yaml
inputs:
  nixpkgs:
    url: github:NixOS/nixpkgs/nixos-unstable
  rust-overlay:
    url: github:oxalica/rust-overlay
    inputs:
      nixpkgs:
        follows: nixpkgs
```

`devenv.nix`:

```nix
{ pkgs, config, ... }:
{
  packages = with pkgs; [ gh just jq curl unzip cmake pkg-config openssl ];

  # Keep equal to rust_version in hc-scripts' rust-ci.yml.
  languages.rust = { enable = true; channel = "stable"; version = "1.99.1"; };
  languages.python = { enable = true; package = pkgs.python312; uv.enable = true; };
  languages.javascript = { enable = true; package = pkgs.nodejs_24; };

  # Point a bare `homecore` at a sandbox, never at a real house.
  env = {
    HOMECORE_HOME = "${config.devenv.root}/sandbox";
    HOMECORE_CONFIG = "${config.devenv.root}/sandbox/homecore.toml";
  };

  enterShell = ''
    export PATH="$DEVENV_ROOT/core/target/debug:$PATH"
  '';
}
```

`.envrc` (for direnv, so the shell loads on `cd`):

```bash
eval "$(devenv direnvrc)"
use devenv
```

Run `devenv shell` (or `direnv allow`). The `env` block means a bare
`homecore` or `cargo run -p homecore` uses the sandbox at
`<workspace>/sandbox/`. Create that sandbox as described in
[sandbox.md](sandbox.md) before running it. .NET is not included; add
`dotnet-sdk_8` to `packages` if you work on the .NET SDK.

## Environment variables that change behavior

| Variable | Effect |
|---|---|
| `HOMECORE_HOME` | Base directory when `--home` is not given. Otherwise the current directory is used. |
| `HOMECORE_CONFIG` | Config path when `--config` is not given. Otherwise `<home>/config/homecore.toml`. A relative path resolves against the home. |
| `RUST_LOG` | Log filter, added to `[logging]` in the config and winning on conflict. Example: `RUST_LOG=info,hc_core::engine=debug`. |
| `HC_ALLOW_ANONYMOUS_REMOTE_BROKER` | Set to `1` to let the broker bind a non-loopback address with no credentials. Never set this in a sandbox. |
| `HC_CORE_URL` | Web app only: where its proxy finds core. Defaults to `http://127.0.0.1:8080`. |

Check your shell for stale `HOMECORE_HOME` or `HOMECORE_CONFIG` before
running core:

```bash
env | grep ^HOMECORE_
```
