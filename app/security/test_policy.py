from app.security.policy import FailureType, PermissionPolicy, classify_failure, redact_mapping


def test_failure_taxonomy_and_redaction():
    assert classify_failure("timeout") is FailureType.TIMEOUT
    assert classify_failure("authorization_denied") is FailureType.PERMISSION_REJECTION
    assert redact_mapping({"api_key": "secret", "query": "hello"}) == {
        "api_key": "[REDACTED]", "query": "hello"
    }


def test_permission_policy_supports_server_and_tool_scopes():
    metadata = type("Metadata", (), {"server": "memory", "name": "memory__search"})()
    assert PermissionPolicy(allowed_servers={"memory"}).allows(metadata, {})
    assert not PermissionPolicy(allowed_servers={"browser"}).allows(metadata, {})
