from app.work_orders.service import canonical_payload_hash, redact_sensitive_values


def test_sensitive_nested_fields_are_redacted_before_persistence() -> None:
    payload = {
        "authorization": "Bearer must-not-be-stored",
        "root_cause": {"summary": "safe", "api_key": "must-not-be-stored"},
        "evidence": [{"token": "must-not-be-stored"}],
    }

    assert redact_sensitive_values(payload) == {
        "authorization": "[REDACTED]",
        "root_cause": {"summary": "safe", "api_key": "[REDACTED]"},
        "evidence": [{"token": "[REDACTED]"}],
    }


def test_payload_hash_is_stable_across_mapping_order() -> None:
    assert canonical_payload_hash({"a": 1, "b": 2}) == canonical_payload_hash({"b": 2, "a": 1})
