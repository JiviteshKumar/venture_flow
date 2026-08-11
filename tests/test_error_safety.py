from agents import claim_verifier
import ventureflow_agent


def test_fallback_memo_does_not_expose_provider_error():
    memo = ventureflow_agent._fallback_ai_analysis(
        "Test Co", {"quality": "LOW", "score": 40}, [], {}, 0, 0, 0,
        RuntimeError("secret provider endpoint"),
    )
    assert "secret provider endpoint" not in memo
    assert "temporarily unavailable" in memo


def test_claim_judge_does_not_expose_provider_error(monkeypatch):
    class BrokenCompletions:
        def create(self, **_):
            raise RuntimeError("private provider details")

    monkeypatch.setattr(
        claim_verifier,
        "client",
        type("Client", (), {"chat": type("Chat", (), {"completions": BrokenCompletions()})()})(),
    )
    result = claim_verifier.groq_judge("test claim", {"snippets": [], "full_texts": []})
    assert "private provider details" not in result["reasoning"]
    assert result["verdict"] == "NOT_ENOUGH_INFO"
