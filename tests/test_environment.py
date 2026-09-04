"""Secret avoidance: values are never captured, secret-looking names dropped."""

import json

from bugpacket.environment import capture_environment, safe_env_var_names

FAKE_ENV = {
    "AUTH0_DOMAIN": "value-auth0-example",
    "AWS_SECRET_ACCESS_KEY": "value-aws-hunter2",
    "DB_PASSWORD": "value-db-hunter2",
    "GITHUB_TOKEN": "value-ghp-abc123",
    "HOME": "value-home-dir",
    "LANG": "value-en-US",
    "MY_API_TOKEN": "value-api-xyz",
    "OPENAI_KEY": "value-sk-999",
    "PATH": "value-usr-bin",
    "STRIPE_CREDENTIALS": "value-stripe-live",
}


def test_secret_looking_names_are_dropped():
    names = safe_env_var_names(FAKE_ENV)
    assert names == ["HOME", "LANG", "PATH"]


def test_denylist_covers_key_token_secret_password():
    for name in ("A_KEY", "A_TOKEN", "A_SECRET", "A_PASSWORD", "A_AUTH", "a_key_b"):
        assert safe_env_var_names({name: "v"}) == []


def test_values_never_appear_anywhere():
    info = capture_environment(FAKE_ENV)
    dumped = json.dumps(info)
    for value in FAKE_ENV.values():
        assert value not in dumped


def test_capture_reports_names_only():
    info = capture_environment(FAKE_ENV)
    assert info["env_var_names"] == ["HOME", "LANG", "PATH"]
    assert "values are never captured" in info["env_note"]
    assert "python" in info
    assert "platform" in info
