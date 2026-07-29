# Smoke-test placeholder. Project-specific parser tests should be added after bootstrap.

def test_status_contract():
    allowed = {"todo", "draft", "reviewed", "playable", "approved", "lqa"}
    assert "approved" in allowed
    assert "ai_done" not in allowed
