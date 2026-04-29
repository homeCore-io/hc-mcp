"""`hc-mcp setup` — create an API key against a homeCore instance and
write it to ~/.config/hc-mcp/config.toml at 0600.

Two auth paths into homeCore depending on what the operator has handy:
  - `--admin-token <jwt>`  : use a pre-existing admin JWT (e.g. from
                              the admin UI's "API tokens" view, or the
                              login response from a script).
  - `--username` / `--password` : log in via /auth/login and use the
                              returned JWT for the api-key creation
                              call. Password is prompted if not given.

The setup tool only needs the admin token long enough to POST
`/auth/api-keys`; it doesn't store the JWT anywhere.

Idempotent re-run with `--rotate` issues a fresh key. The previous key
isn't revoked automatically — operators can do that via the admin UI
or `DELETE /api/v1/auth/api-keys/{id}`.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import httpx

from .config import Config


# Phase 1 + plugin-action scope set. Read-only across the surfaces
# hc-mcp's current tools touch, plus plugins:write so
# invoke_plugin_action can dispatch commands.
DEFAULT_SCOPES = [
    "areas:read",
    "automations:read",
    "audit:read",
    "devices:read",
    "plugins:read",
    "plugins:write",
    "scenes:read",
]


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Wire the `setup` subcommand into the existing argparse tree.

    Called from server.main() so `hc-mcp setup` and `hc-mcp` share one
    entry-point binary.
    """
    p = subparsers.add_parser(
        "setup",
        help="Create an API key against a homeCore instance and save config",
        description=__doc__,
    )
    p.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="homeCore API base URL (default: %(default)s)",
    )
    p.add_argument(
        "--admin-token",
        default=os.environ.get("HC_ADMIN_TOKEN"),
        help="Admin JWT (or set HC_ADMIN_TOKEN). Skips username/password.",
    )
    p.add_argument(
        "--username",
        help="Admin username for /auth/login flow (alternative to --admin-token)",
    )
    p.add_argument(
        "--password",
        help="Admin password (prompted on stdin if --username given without this)",
    )
    p.add_argument(
        "--label",
        default="hc-mcp",
        help="Human-readable label for the new key (default: %(default)s)",
    )
    p.add_argument(
        "--scopes",
        default=",".join(DEFAULT_SCOPES),
        help=(
            "Comma-separated scope list. Default is the Phase 1 + plugin-action "
            "set; pass --scopes='' to issue an unscoped key (NOT recommended)."
        ),
    )
    p.add_argument(
        "--expires-days",
        type=int,
        default=None,
        help="Expiry in days. Omit for no expiry.",
    )
    p.add_argument(
        "--config-path",
        type=Path,
        default=None,
        help=f"Where to write config.toml (default: {Config.default_path()})",
    )
    p.add_argument(
        "--rotate",
        action="store_true",
        help="Create a new key even if a config already exists (does NOT revoke the old one).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config without prompting.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Execute the setup flow. Returns process exit code."""
    config_path = args.config_path or Config.default_path()

    if config_path.exists() and not args.rotate and not args.force:
        print(
            f"hc-mcp: config already exists at {config_path}.\n"
            f"  - Pass --rotate to issue a new key + overwrite.\n"
            f"  - Pass --force to overwrite without rotating (manual key paste).",
            file=sys.stderr,
        )
        return 2

    base_url = args.base_url.rstrip("/")

    # ── Resolve admin JWT ────────────────────────────────────────────
    admin_token = args.admin_token
    if admin_token is None:
        if not args.username:
            print(
                "hc-mcp setup: need either --admin-token, HC_ADMIN_TOKEN env, "
                "or --username/--password to log in.",
                file=sys.stderr,
            )
            return 2
        password = args.password or getpass.getpass(
            f"Password for {args.username}: "
        )
        try:
            admin_token = _login(base_url, args.username, password)
        except RuntimeError as e:
            print(f"hc-mcp setup: login failed — {e}", file=sys.stderr)
            return 3

    # ── Issue the API key ────────────────────────────────────────────
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    try:
        resp = _create_api_key(
            base_url=base_url,
            admin_token=admin_token,
            label=args.label,
            scopes=scopes,
            expires_in_days=args.expires_days,
        )
    except RuntimeError as e:
        print(f"hc-mcp setup: api-key creation failed — {e}", file=sys.stderr)
        return 4

    # ── Write config.toml at 0600 ────────────────────────────────────
    _write_config(
        path=config_path,
        base_url=base_url,
        api_key=resp["token"],
    )

    # ── Confirm to operator ──────────────────────────────────────────
    print(
        f"hc-mcp setup: success.\n"
        f"  Key id   : {resp['id']}\n"
        f"  Label    : {resp['label']}\n"
        f"  Scopes   : {', '.join(resp.get('scopes') or [])}\n"
        f"  Expires  : {resp.get('expires_at') or 'never'}\n"
        f"  Saved to : {config_path}",
        file=sys.stderr,
    )
    return 0


# ── HTTP helpers ────────────────────────────────────────────────────────────


def _login(base_url: str, username: str, password: str) -> str:
    """POST /auth/login → return JWT, or raise RuntimeError."""
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=10.0,
        )
    except httpx.RequestError as e:
        raise RuntimeError(f"network: {e}") from e

    if resp.status_code == 401:
        raise RuntimeError("invalid credentials")
    if resp.status_code != 200:
        raise RuntimeError(f"unexpected status {resp.status_code}: {resp.text[:200]}")

    body = resp.json()
    token = body.get("token") or body.get("access_token") or body.get("jwt")
    if not token:
        raise RuntimeError(f"login response missing token field: {body}")
    return token


def _create_api_key(
    base_url: str,
    admin_token: str,
    label: str,
    scopes: list[str],
    expires_in_days: int | None,
) -> dict:
    """POST /auth/api-keys → return the parsed CreateApiKeyResponse dict."""
    body: dict = {"label": label, "scopes": scopes}
    if expires_in_days is not None:
        body["expires_in_days"] = expires_in_days

    try:
        resp = httpx.post(
            f"{base_url}/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=body,
            timeout=10.0,
        )
    except httpx.RequestError as e:
        raise RuntimeError(f"network: {e}") from e

    if resp.status_code == 401:
        raise RuntimeError("admin token rejected (401)")
    if resp.status_code == 403:
        raise RuntimeError(
            "admin token forbidden (403) — does this user hold the requested scopes?"
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"unexpected status {resp.status_code}: {resp.text[:200]}")

    return resp.json()


# ── Config writing ──────────────────────────────────────────────────────────


def _write_config(path: Path, base_url: str, api_key: str) -> None:
    """Write config.toml at 0600. Creates parent directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # Open with mode 0600 directly so the secret is never on-disk
    # world-readable for any window between create and chmod.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(_render_config(base_url=base_url, api_key=api_key))
    except Exception:
        # Make sure we don't leave a half-written file with a real secret.
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _render_config(base_url: str, api_key: str) -> str:
    return (
        "# hc-mcp configuration. Generated by `hc-mcp setup`.\n"
        "# Permissions: 0600 (operator-only). Treat the api_key like\n"
        "# a password — anyone who reads this file can act on homeCore\n"
        "# at the scope set the key was issued with.\n"
        "\n"
        "[homecore]\n"
        f'base_url = "{base_url}"\n'
        f'api_key  = "{api_key}"\n'
        "# timeout_secs = 30.0    # uncomment to override the default\n"
    )
