from fastbot.agent import audit_safe


def test_sensitive_tool_fields_are_redacted_from_audit():
    value=audit_safe({"selector":"#password","text":"top-secret","content":"private file","nested":{"api_key":"xai-secret"}})
    assert value["selector"] == "#password"
    assert value["text"] == {"redacted":True,"length":10}
    assert value["content"]["redacted"] is True
    assert value["nested"]["api_key"]["redacted"] is True
