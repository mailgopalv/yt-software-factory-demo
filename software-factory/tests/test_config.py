import os

import pytest

from factory import config as config_module
from factory.config import load_config

YAML = """
store: {{path: ../store}}
auth: {auth}
model: claude-opus-5-5
agents:
  db_agent: {{max_turns: 7}}
"""


@pytest.fixture
def factory_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "FACTORY_DIR", tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-from-dotenv\n")
    return tmp_path


def write_yaml(factory_dir, auth):
    path = factory_dir / "factory.yaml"
    path.write_text(YAML.format(auth=auth))
    return path


def test_subscription_mode_removes_api_keys_so_the_login_is_used(factory_dir, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-set-on-this-machine")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")

    config = load_config(write_yaml(factory_dir, "subscription"))

    assert config.auth == "subscription"
    assert config.api_key == ""
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ


def test_api_key_mode_reads_the_key_from_dotenv(factory_dir, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    config = load_config(write_yaml(factory_dir, "api_key"))

    assert config.auth == "api_key"
    assert config.api_key == "sk-ant-from-dotenv"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_unknown_auth_mode_is_rejected(factory_dir):
    with pytest.raises(ValueError, match="auth"):
        load_config(write_yaml(factory_dir, "magic"))


def test_per_agent_limits_override_the_defaults(factory_dir):
    config = load_config(write_yaml(factory_dir, "subscription"))

    assert config.limits_for("db_agent").max_turns == 7
    assert config.limits_for("reviewer_agent").max_turns == 40
