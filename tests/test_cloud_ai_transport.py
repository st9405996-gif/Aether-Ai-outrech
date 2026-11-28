import httpx
import pytest

from sellbird.integrations.cloud_ai import CloudAITransport


def test_cloud_ai_routes_tasks_to_specialized_worker_endpoints():
    assert CloudAITransport.route("scout", "score_contacts") == "/v1/research-score"
    # Routing is by task, not by agent: the Handler also writes replies, and
    # those must go to Workers AI, not to the Gemini classifier.
    assert CloudAITransport.route("handler", "classify_intent") == "/v1/classify-reply"
    assert CloudAITransport.route("handler", "generate_response") == "/v1/write-email"
    assert CloudAITransport.route("handler", "fix_reply") == "/v1/write-email"
    assert CloudAITransport.route("writer", "personal_email") == "/v1/write-email"


@pytest.mark.asyncio
async def test_cloud_ai_transport_authenticates_and_returns_output():
    seen = {}
    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"output": '{"subject":"Hello","body":"Hi"}'})
    transport = httpx.MockTransport(handler)
    factory = lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs)
    client = CloudAITransport("https://sellbird-ai.example", "shared-secret", client_factory=factory)
    result = await client("write", agent="writer", task="personal_email", timeout=10, expect_json=True)
    assert result == '{"subject":"Hello","body":"Hi"}'
    assert seen["auth"] == "Bearer shared-secret"
    assert seen["url"] == "https://sellbird-ai.example/v1/write-email"


@pytest.mark.asyncio
async def test_cloud_ai_missing_config_pauses_without_network_call():
    client = CloudAITransport("", "")
    assert client.paused_reason
    assert await client("prompt", agent="writer", task="personal_email", timeout=1,
                        expect_json=True) == ""
