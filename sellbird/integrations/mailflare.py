"""Mailflare REST send + JMAP inbox provider.

Requires a Mailflare personal API key with the ``send`` scope and a JMAP
app-password/key with the ``jmap`` scope. The two credentials are deliberately
separate because Mailflare exposes these capabilities under different scopes.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from sellbird.integrations.mail_provider import (
    InboundMessage, MailIdentity, MailProvider, SendResult, identity_from_config,
    looks_like_bounce,
)

_TIMEOUT = httpx.Timeout(connect=8.0, read=25.0, write=20.0, pool=8.0)
_JMAP_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"]


class MailflareProvider(MailProvider):
    """Mailflare API provider; sends via REST and reads Inbox via JMAP."""

    name = "mailflare"
    carries_headers = False

    def __init__(self, config, env, *, identity: MailIdentity | None = None,
                 client_factory=httpx.AsyncClient):
        self.config = config
        self.env = env
        self.identity = identity or identity_from_config(config)
        self.base_url = (getattr(env, "mailflare_base_url", "") or "https://mailflare.st9405996.workers.dev").rstrip("/")
        self.api_key = getattr(env, "mailflare_api_key", "") or ""
        self.jmap_api_key = getattr(env, "mailflare_jmap_api_key", "") or ""
        self._client_factory = client_factory
        self._jmap_session: dict | None = None

    def is_configured(self) -> bool:
        try:
            parsed = httpx.URL(self.base_url)
            secure_origin = (parsed.scheme == "https" and bool(parsed.host)
                             and not parsed.username and not parsed.password
                             and not parsed.query and not parsed.fragment
                             and parsed.path in ("", "/"))
        except Exception:
            secure_origin = False
        return bool(secure_origin and self.api_key.strip() and self.jmap_api_key.strip()
                    and self.identity.address.strip())

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "Accept": "application/json",
                "Content-Type": "application/json"}

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            value = response.json()
        except ValueError:
            value = {}
        return value if isinstance(value, dict) else {}

    async def send_email(self, to_email: str, subject: str, body: str,
                         thread_ref: str = "", in_reply_to: str = "",
                         headers: Sequence[tuple[str, str]] = ()) -> SendResult:
        if not self.is_configured():
            return SendResult(False, error="Mailflare is not configured. Add send and JMAP keys, base URL and sender address.")
        payload: dict[str, Any] = {
            "from": self.identity.address,
            "to": [to_email],
            "subject": subject,
            "text": body,
        }
        if in_reply_to:
            payload["inReplyTo"] = in_reply_to
            # The provider's thread id is not a References header; only send
            # the known parent Message-ID rather than inventing a chain.
            payload["references"] = [in_reply_to]
        try:
            async with self._client_factory(timeout=_TIMEOUT, follow_redirects=False) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/send", headers=self._headers(self.api_key),
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            # The request may have reached Mailflare. Do not retry this send.
            return SendResult(False, error=f"Mailflare send outcome is unknown ({type(exc).__name__}).",
                              uncertain=True)
        except httpx.HTTPError as exc:
            return SendResult(False, error=f"Mailflare connection failed ({type(exc).__name__}).")

        data = self._json(response)
        if response.status_code == 429:
            return SendResult(False, error="Mailflare rate limit reached (HTTP 429).")
        if response.status_code in (401, 403):
            return SendResult(False, error="Mailflare rejected the API key or sender permission.")
        if response.status_code >= 500:
            return SendResult(False, error=f"Mailflare returned HTTP {response.status_code}; delivery may be uncertain.",
                              uncertain=True)
        if not response.is_success or data.get("ok") is False or data.get("error"):
            message = str(data.get("error") or data.get("message") or f"HTTP {response.status_code}")[:300]
            return SendResult(False, error=f"Mailflare send failed: {message}")
        message_id = str(data.get("messageId") or data.get("message_id") or data.get("id") or "")
        thread_id = str(data.get("threadId") or data.get("thread_id") or "")
        return SendResult(True, message_id=message_id, thread_ref=thread_id)

    async def _jmap_call(self, client: httpx.AsyncClient, session: dict,
                         method: str, args: dict, tag: str = "c1") -> dict:
        api_url = session.get("apiUrl")
        account_id = (session.get("primaryAccounts") or {}).get("urn:ietf:params:jmap:mail")
        if not isinstance(api_url, str) or not account_id:
            raise RuntimeError("Mailflare JMAP session is missing a secure apiUrl or mail account.")
        try:
            api_origin = httpx.URL(api_url)
            base_origin = httpx.URL(self.base_url)
            api_port = api_origin.port or 443
            base_port = base_origin.port or 443
            same_origin = (api_origin.scheme == "https" and api_origin.host == base_origin.host
                           and api_port == base_port and not api_origin.username
                           and not api_origin.password)
        except Exception:
            same_origin = False
        if not same_origin:
            raise RuntimeError("Mailflare JMAP apiUrl must use the configured Mailflare HTTPS origin.")
        body = {"using": _JMAP_USING,
                "methodCalls": [[method, {"accountId": account_id, **args}, tag]]}
        response = await client.post(api_url, headers=self._headers(self.jmap_api_key), json=body)
        if response.status_code in (401, 403):
            raise RuntimeError("Mailflare JMAP key was rejected; it needs the jmap scope.")
        response.raise_for_status()
        result = self._json(response).get("methodResponses") or []
        if not result or result[0][0] != method:
            raise RuntimeError("Mailflare returned an unexpected JMAP response.")
        return result[0][1] if isinstance(result[0][1], dict) else {}

    async def _session(self, client: httpx.AsyncClient) -> dict:
        if self._jmap_session:
            return self._jmap_session
        response = await client.get(f"{self.base_url}/.well-known/jmap",
                                    headers=self._headers(self.jmap_api_key))
        if response.status_code in (401, 403):
            raise RuntimeError("Mailflare JMAP key was rejected; it needs the jmap scope.")
        response.raise_for_status()
        data = self._json(response)
        if not data.get("apiUrl"):
            # Some deployments redirect the discovery URL to /jmap/session.
            response = await client.get(f"{self.base_url}/jmap/session",
                                        headers=self._headers(self.jmap_api_key))
            response.raise_for_status()
            data = self._json(response)
        if not data.get("apiUrl"):
            raise RuntimeError("Mailflare did not return a valid JMAP session.")
        self._jmap_session = data
        return data

    @staticmethod
    def _address(items) -> str:
        if not isinstance(items, list):
            return ""
        for item in items:
            if isinstance(item, dict) and item.get("email"):
                return str(item["email"]).strip().lower()
        return ""

    @staticmethod
    def _addresses(items) -> set[str]:
        if not isinstance(items, list):
            return set()
        return {str(item["email"]).strip().lower() for item in items
                if isinstance(item, dict) and item.get("email")}

    @staticmethod
    def _body_values(message: dict) -> str:
        values = message.get("bodyValues") or {}
        if isinstance(values, dict):
            for part in message.get("textBody") or []:
                if isinstance(part, dict):
                    value = values.get(part.get("partId"), {})
                    if isinstance(value, dict) and value.get("value"):
                        return str(value["value"])
        return str(message.get("preview") or "")

    async def get_replies(self, limit: int = 500) -> list[InboundMessage]:
        if not self.is_configured():
            raise RuntimeError("Mailflare is not configured for inbox reading.")
        async with self._client_factory(timeout=_TIMEOUT, follow_redirects=False) as client:
            session = await self._session(client)
            mailboxes = await self._jmap_call(client, session, "Mailbox/get",
                {"ids": None, "properties": ["id", "name", "role"]}, "mb")
            inbox = next((m for m in mailboxes.get("list", [])
                          if isinstance(m, dict) and (m.get("role") == "inbox"
                          or str(m.get("name", "")).lower() == "inbox")), None)
            if not inbox:
                return []
            wanted = max(1, min(int(limit), 500))
            ids = []
            position = 0
            while len(ids) < wanted:
                page_size = min(100, wanted - len(ids))
                page = await self._jmap_call(client, session, "Email/query", {
                    "filter": {"inMailbox": inbox["id"],
                               "after": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()},
                    "sort": [{"property": "receivedAt", "isAscending": False}],
                    "position": position,
                    "limit": page_size,
                    "calculateTotal": True,
                }, f"q{position}")
                page_ids = page.get("ids") or []
                if not isinstance(page_ids, list):
                    raise RuntimeError("Mailflare returned a malformed JMAP inbox page.")
                if not page_ids:
                    break
                ids.extend(str(item) for item in page_ids if item)
                position += len(page_ids)
                total = page.get("total")
                if isinstance(total, int) and total > wanted and len(ids) >= wanted:
                    raise RuntimeError("Mailflare inbox has more than 500 recent messages; refusing a partial reply read.")
                if len(page_ids) < page_size:
                    break
            if not ids:
                return []
            got = await self._jmap_call(client, session, "Email/get", {
                "ids": ids,
                "properties": ["id", "from", "to", "cc", "subject", "receivedAt", "messageId",
                               "inReplyTo", "references", "threadId", "preview",
                               "textBody", "htmlBody", "bodyValues", "keywords"],
                "bodyProperties": ["partId", "type", "charset", "disposition", "cid", "language", "location"],
                "fetchTextBodyValues": True,
                "fetchHTMLBodyValues": True,
            }, "g")
            message_rows = got.get("list") or []
            if not isinstance(message_rows, list) or len(message_rows) != len(ids):
                raise RuntimeError("Mailflare returned an incomplete JMAP message page; refusing a partial inbox read.")
            out = []
            for item in message_rows:
                if not isinstance(item, dict):
                    continue
                sender = self._address(item.get("from"))
                if not sender:
                    continue
                # Every sender identity on this Mailflare account reads the
                # same JMAP Inbox. Route a reply only to the alias it was sent
                # to, rather than letting the first reader claim every reply.
                recipients = self._addresses(item.get("to")) | self._addresses(item.get("cc"))
                if not self.identity.address or self.identity.address.strip().lower() not in recipients:
                    continue
                out.append(InboundMessage(
                    provider_id=str(item.get("id") or ""),
                    from_email=sender,
                    subject=str(item.get("subject") or ""),
                    body=self._body_values(item)[:5000],
                    message_id=str(item.get("messageId") or ""),
                    in_reply_to=str(item.get("inReplyTo") or ""),
                    thread_ref=str(item.get("threadId") or ""),
                    date=str(item.get("receivedAt") or ""),
                    is_bounce=looks_like_bounce(sender, str(item.get("subject") or "")),
                    headers={"references": item.get("references") or []},
                ))
            return out

    async def test_connection(self) -> tuple[bool, str]:
        if not self.is_configured():
            return False, "Add MAILFLARE_API_KEY (send scope), MAILFLARE_JMAP_API_KEY (jmap scope), and a sender address."
        try:
            async with self._client_factory(timeout=_TIMEOUT, follow_redirects=False) as client:
                session = await self._session(client)
                mailboxes = await self._jmap_call(client, session, "Mailbox/get",
                                      {"ids": None, "properties": ["id", "name", "role"]}, "test")
                if not any(isinstance(m, dict) and (m.get("role") == "inbox"
                       or str(m.get("name", "")).lower() == "inbox")
                       for m in mailboxes.get("list", [])):
                    return False, "Mailflare JMAP access works, but no Inbox mailbox was returned."
            return True, (f"Mailflare JMAP inbox access verified for {self.identity.address}. "
                          "The send key is checked by Mailflare on the first approved send; testing it would require sending a real email.")
        except Exception as exc:
            return False, f"Mailflare connection check failed: {str(exc)[:240]}"
