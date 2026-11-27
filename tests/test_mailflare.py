from types import SimpleNamespace

import httpx
import pytest

from sellbird.integrations.mail_provider import MailIdentity
from sellbird.integrations.mailflare import MailflareProvider


def provider(handler):
    transport = httpx.MockTransport(handler)
    factory = lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs)
    config = SimpleNamespace(persona=SimpleNamespace(email="sales@example.test", name="Sellbird"))
    env = SimpleNamespace(mailflare_base_url="https://mailflare.test", mailflare_api_key="send-key",
                          mailflare_jmap_api_key="jmap-key")
    return MailflareProvider(config, env, client_factory=factory)


@pytest.mark.asyncio
async def test_mailflare_send_uses_documented_rest_shape_and_preserves_ids():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read()
        return httpx.Response(200, json={"ok": True, "id": "m-1", "threadId": "t-1"})
    p = provider(handler)
    result = await p.send_email("lead@example.test", "Hello", "Hi there")
    assert result.ok and result.message_id == "m-1" and result.thread_ref == "t-1"
    assert seen["url"] == "https://mailflare.test/api/v1/send"
    assert seen["auth"] == "Bearer send-key"
    import json
    payload = json.loads(seen["body"])
    assert payload == {"from": "sales@example.test", "to": ["lead@example.test"],
                       "subject": "Hello", "text": "Hi there"}


@pytest.mark.asyncio
async def test_mailflare_auth_failure_is_not_uncertain():
    p = provider(lambda request: httpx.Response(403, json={"error": "forbidden"}))
    result = await p.send_email("lead@example.test", "Hello", "Hi")
    assert not result.ok and not result.uncertain
    assert "rejected" in result.error.lower()


@pytest.mark.asyncio
async def test_mailflare_timeout_is_uncertain_and_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("read timed out")
    result = await provider(handler).send_email("lead@example.test", "Hello", "Hi")
    assert not result.ok and result.uncertain and len(calls) == 1


@pytest.mark.asyncio
async def test_mailflare_jmap_reads_inbox_messages():
    def handler(request):
        if request.method == "GET" and request.url.path == "/.well-known/jmap":
            return httpx.Response(200, json={
                "apiUrl": "https://mailflare.test/jmap/api",
                "primaryAccounts": {"urn:ietf:params:jmap:mail": "account-1"},
            })
        body = request.read().decode()
        if '"Mailbox/get"' in body:
            return httpx.Response(200, json={"methodResponses": [["Mailbox/get", {
                "list": [{"id": "inbox-1", "name": "Inbox", "role": "inbox"}]
            }, "mb"]]})
        if '"Email/query"' in body:
            return httpx.Response(200, json={"methodResponses": [["Email/query", {
                "ids": ["email-1"]
            }, "q"]]})
        if '"Email/get"' in body:
            return httpx.Response(200, json={"methodResponses": [["Email/get", {
                "list": [{
                    "id": "email-1", "from": [{"name": "Jane", "email": "jane@example.test"}],
                    "subject": "Re: Question", "receivedAt": "2026-11-27T10:00:00Z",
                    "messageId": "<reply@example.test>", "inReplyTo": "<sent@example.test>",
                    "threadId": "thread-1", "textBody": [{"partId": "p1"}],
                    "bodyValues": {"p1": {"value": "Thanks for the details."}},
                }]
            }, "g"]]})
        raise AssertionError(f"Unexpected JMAP request: {request.url} {body}")

    messages = await provider(handler).get_replies()
    assert len(messages) == 1
    msg = messages[0]
    assert msg.provider_id == "email-1"
    assert msg.from_email == "jane@example.test"
    assert msg.subject == "Re: Question"
    assert msg.body == "Thanks for the details."
    assert msg.message_id == "<reply@example.test>"
    assert msg.in_reply_to == "<sent@example.test>"
    assert msg.thread_ref == "thread-1"
