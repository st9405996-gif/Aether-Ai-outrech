"""HTTP transport for the separately deployed Sellbird Cloud AI Worker."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("sellbird.cloud_ai")


class CloudAITransport:
    def __init__(self, base_url: str, shared_secret: str, *, client_factory=httpx.AsyncClient):
        self.base_url = (base_url or "").rstrip("/")
        self.shared_secret = shared_secret or ""
        self._client_factory = client_factory
        try:
            parsed = httpx.URL(self.base_url)
            secure_origin = (parsed.scheme == "https" and bool(parsed.host)
                             and not parsed.query and not parsed.fragment
                             and parsed.path in ("", "/"))
        except Exception:
            secure_origin = False
        self.paused_reason = "" if secure_origin and self.shared_secret else (
            "Sellbird Cloud AI is not configured: set an HTTPS Worker origin in SELLBIRD_AI_URL and SELLBIRD_AI_SECRET.")

    @classmethod
    def from_env(cls, env):
        return cls(getattr(env, "sellbird_ai_url", ""),
                   getattr(env, "sellbird_ai_secret", ""))

    @staticmethod
    def route(agent: str, task: str) -> str:
        if task in {"classify_intent", "classify_reply", "reply_classification"}:
            return "/v1/classify-reply"
        if agent == "scout" or task in {"score_contacts", "research_score", "suggest_offers", "trainer", "training"}:
            return "/v1/research-score"
        return "/v1/write-email"

    async def preflight(self) -> str:
        if self.paused_reason:
            return self.paused_reason
        try:
            async with self._client_factory(timeout=httpx.Timeout(5, connect=3)) as client:
                response = await client.get(
                    self.base_url + "/health",
                    headers={"Authorization": f"Bearer {self.shared_secret}",
                             "Accept": "application/json"},
                )
            if response.status_code in (401, 403):
                self.paused_reason = "Sellbird Cloud AI rejected SELLBIRD_AI_SECRET. Check the shared secret and restart Sellbird."
                return self.paused_reason
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("ok") is not True:
                return "Sellbird Cloud AI Worker health check returned an unexpected response."
            return ""
        except Exception as exc:
            return f"Sellbird Cloud AI Worker is unreachable ({type(exc).__name__})."

    async def __call__(self, prompt: str, *, agent: str, task: str,
                       timeout: float, expect_json: bool) -> str:
        if self.paused_reason:
            return ""
        route = self.route(agent, task)
        payload = {"prompt": str(prompt), "agent": str(agent or ""),
                   "task": str(task or ""), "expectJson": bool(expect_json)}
        try:
            async with self._client_factory(
                timeout=httpx.Timeout(connect=8, read=min(float(timeout), 90),
                                      write=20, pool=8),
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    self.base_url + route,
                    headers={"Authorization": f"Bearer {self.shared_secret}",
                             "Content-Type": "application/json", "Accept": "application/json"},
                    json=payload,
                )
            if response.status_code in (401, 403):
                self.paused_reason = "Sellbird Cloud AI rejected SELLBIRD_AI_SECRET. Check the shared secret and restart Sellbird."
                logger.error("Sellbird Cloud AI rejected the configured shared secret.")
                return ""
            if response.status_code == 429:
                logger.warning("Sellbird Cloud AI rate limit reached.")
                return ""
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return ""
            return str(data.get("output") or data.get("text") or "")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Sellbird Cloud AI request failed (%s).", type(exc).__name__)
            return ""
