from __future__ import annotations

from jubilant_recorder.redaction import redact_config_dict, redact_string


class TestRedactString:
    def test_password_query_param(self):
        result, changed = redact_string("login?password=hunter2&user=alice")
        assert changed
        assert "hunter2" not in result
        assert "<redacted:password>" in result
        assert "user=alice" in result

    def test_token_query_param(self):
        result, changed = redact_string("api?token=abc123xyz&action=read")
        assert changed
        assert "abc123xyz" not in result
        assert "<redacted:token>" in result
        assert "action=read" in result

    def test_bearer_header(self):
        result, changed = redact_string("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig")
        assert changed
        assert "eyJhbGciOiJSUzI1NiJ9" not in result
        assert "<redacted:bearer>" in result

    def test_bearer_header_case_insensitive(self):
        result, changed = redact_string("authorization: bearer mytoken123")
        assert changed
        assert "mytoken123" not in result
        assert "<redacted:bearer>" in result

    def test_url_with_credentials(self):
        result, changed = redact_string("curl https://admin:s3cr3t@example.com/api")
        assert changed
        assert "s3cr3t" not in result
        assert "<redacted:url-credentials>" in result
        assert "example.com" in result

    def test_clean_string_untouched(self):
        clean = "running install hook"
        result, changed = redact_string(clean)
        assert not changed
        assert result == clean

    def test_multiple_patterns_in_one_string(self):
        s = "password=abc token=xyz"
        result, changed = redact_string(s)
        assert changed
        assert "abc" not in result
        assert "xyz" not in result
        assert result.count("<redacted:") == 2

    def test_surrounding_context_preserved(self):
        s = "curl -fsSL -H 'Authorization: Bearer tok123' https://example.com/install.sh"
        result, changed = redact_string(s)
        assert changed
        assert "tok123" not in result
        assert "curl" in result
        assert "https://example.com/install.sh" in result


class TestRedactConfigDict:
    def test_password_key_redacted(self):
        result, changed = redact_config_dict({"password": "hunter2"})
        assert changed
        assert "hunter2" not in result["password"]
        assert result["password"].startswith("<redacted:")

    def test_token_key_redacted(self):
        result, changed = redact_config_dict({"api-token": "mytoken"})
        assert changed
        assert "mytoken" not in result["api-token"]
        assert result["api-token"].startswith("<redacted:")

    def test_secret_key_redacted(self):
        result, changed = redact_config_dict({"app-secret": "supersecret"})
        assert changed
        assert "supersecret" not in result["app-secret"]
        assert result["app-secret"].startswith("<redacted:")

    def test_non_matching_key_passed_through(self):
        result, changed = redact_config_dict({"log-level": "debug"})
        assert not changed
        assert result["log-level"] == "debug"

    def test_non_string_value_passed_through(self):
        result, changed = redact_config_dict({"num-retries": 3, "enabled": True})
        assert not changed
        assert result["num-retries"] == 3
        assert result["enabled"] is True

    def test_original_dict_not_mutated(self):
        original = {"password": "secret123", "log-level": "info"}
        result, changed = redact_config_dict(original)
        assert changed
        assert original["password"] == "secret123"
        assert result["password"] != original["password"]

    def test_key_not_matching_string_redaction_still_applied(self):
        result, changed = redact_config_dict({"extra-info": "password=abc"})
        assert changed
        assert "abc" not in result["extra-info"]
        assert "<redacted:password>" in result["extra-info"]
