"""Config resolution: file, env overrides, and the precedence between them."""

from __future__ import annotations

import pytest

from hc_mcp.config import Config, load


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("HC_MCP_CONFIG", "HC_MCP_BASE_URL", "HC_MCP_API_KEY", "HC_MCP_TIMEOUT_SECS"):
        monkeypatch.delenv(k, raising=False)
    # Never read the developer's real ~/.config/hc-mcp/config.toml.
    monkeypatch.setattr(
        Config,
        "default_path",
        staticmethod(lambda: __import__("pathlib").Path("/nonexistent/hc-mcp.toml")),
    )


def write_config(tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def test_loads_from_an_explicit_path(tmp_path):
    p = write_config(
        tmp_path,
        '[homecore]\nbase_url = "http://box:9090"\napi_key = "hc_sk_file"\ntimeout_secs = 12\n',
    )
    cfg = load(str(p))
    assert cfg.base_url == "http://box:9090"
    assert cfg.api_key == "hc_sk_file"
    assert cfg.timeout_secs == 12.0


def test_env_overrides_the_file(tmp_path, monkeypatch):
    p = write_config(
        tmp_path, '[homecore]\nbase_url = "http://from-file:1"\napi_key = "from_file"\n'
    )
    monkeypatch.setenv("HC_MCP_BASE_URL", "http://from-env:2")
    monkeypatch.setenv("HC_MCP_API_KEY", "from_env")
    cfg = load(str(p))
    assert cfg.base_url == "http://from-env:2"
    assert cfg.api_key == "from_env"


def test_explicit_path_beats_the_env_path(tmp_path, monkeypatch):
    explicit = write_config(tmp_path, '[homecore]\napi_key = "explicit"\n')
    other = tmp_path / "other.toml"
    other.write_text('[homecore]\napi_key = "from_env_path"\n')
    monkeypatch.setenv("HC_MCP_CONFIG", str(other))
    assert load(str(explicit)).api_key == "explicit"


def test_env_path_is_used_when_no_explicit_path(tmp_path, monkeypatch):
    p = write_config(tmp_path, '[homecore]\napi_key = "from_env_path"\n')
    monkeypatch.setenv("HC_MCP_CONFIG", str(p))
    assert load().api_key == "from_env_path"


def test_missing_api_key_is_a_named_error(monkeypatch):
    monkeypatch.setenv("HC_MCP_BASE_URL", "http://box:8080")
    with pytest.raises(RuntimeError) as e:
        load()
    msg = str(e.value)
    assert "HC_MCP_API_KEY" in msg
    # The error should say how to mint one, not just that it is absent.
    assert "api-key issue" in msg


def test_defaults_when_only_a_key_is_supplied(monkeypatch):
    monkeypatch.setenv("HC_MCP_API_KEY", "k")
    cfg = load()
    assert cfg.base_url == "http://127.0.0.1:8080"
    assert cfg.timeout_secs == 5.0


def test_trailing_slash_is_stripped(monkeypatch):
    # HomeCoreClient appends "/api/v1", so a trailing slash here would produce
    # a double slash in every request path.
    monkeypatch.setenv("HC_MCP_API_KEY", "k")
    monkeypatch.setenv("HC_MCP_BASE_URL", "http://box:8080/")
    assert load().base_url == "http://box:8080"


def test_timeout_from_env_is_coerced(monkeypatch):
    monkeypatch.setenv("HC_MCP_API_KEY", "k")
    monkeypatch.setenv("HC_MCP_TIMEOUT_SECS", "2.5")
    assert load().timeout_secs == 2.5


def test_a_nonexistent_config_path_is_not_fatal(monkeypatch, tmp_path):
    # Env vars alone are a supported way to run, so pointing at a file that
    # is not there should fall through rather than raise.
    monkeypatch.setenv("HC_MCP_API_KEY", "k")
    cfg = load(str(tmp_path / "nope.toml"))
    assert cfg.api_key == "k"
