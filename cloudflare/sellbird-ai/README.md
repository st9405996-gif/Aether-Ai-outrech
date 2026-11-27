# Sellbird Cloud AI Worker

A separate, authenticated Cloudflare Worker. It does not modify the AETHER-TRADE or Mailflare Workers.

## Routes

- `GET /health` — authenticated health check; no secrets or provider state returned.
- `POST /v1/research-score` — Gemini.
- `POST /v1/classify-reply` — Gemini.
- `POST /v1/write-email` — Cloudflare Workers AI binding.

All POST routes require `Authorization: Bearer <SELLBIRD_AI_SECRET>`. Requests are limited to 28,000 prompt characters and 30 requests/minute per route limiter key. Only known Sellbird tasks are accepted. Provider failures return a generic error; prompt bodies and credentials are not logged.

## Deploy

From this directory:

```bash
npm install -g wrangler
wrangler secret put SELLBIRD_AI_SECRET
wrangler secret put GEMINI_API_KEY
wrangler deploy
```

Create a long random shared secret and use the same value for Sellbird's `SELLBIRD_AI_SECRET`. Never commit either secret. `wrangler.toml` includes a rate-limit binding; if Cloudflare requires a newly provisioned rate-limit namespace in your account, replace namespace ID `10012026` with the namespace ID created for this Worker before deploying.

Workers AI requires the account's Workers AI entitlement/binding. Gemini API availability and quotas depend on the Google account and may not be free indefinitely. No automatic provider fallback is performed.
