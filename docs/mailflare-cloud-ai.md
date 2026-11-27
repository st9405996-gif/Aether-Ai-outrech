# Mailflare and Sellbird Cloud AI

This integration adds two optional providers to the existing Sellbird project. It does not modify or deploy your Mailflare Worker or your AETHER-TRADE Worker.

## Mailflare email provider

The adapter uses Mailflare's `POST /api/v1/send` route for outbound messages and JMAP for inbox reading. The request/response contract must be verified against the deployed Mailflare Worker before the first live send. See the [Mailflare API documentation](https://mailflare.co/docs/api): sending uses the REST endpoint; JMAP discovery is `/.well-known/jmap` and requires a key with the `jmap` scope. The adapter expects a personal send key and a JMAP app password/key because those are separate permissions.

1. In Mailflare, create a personal API key with the `send` scope.
2. Create an app password/API key with the `jmap` scope for inbox reading.
3. In Sellbird → Sending and keys, enter the Mailflare origin, send key and JMAP key. The default origin in this fork is the user's configured `mailflare.st9405996.workers.dev` deployment; change it if your API is hosted elsewhere.
4. In `sellbird.yaml`, set:

   ```yaml
   channels:
     email:
       provider: "mailflare"
       require_approval: true
       max_daily_sends: 50
   ```

5. Keep the sender address in `persona.email` authorized in Mailflare. Test the provider from Sellbird's Inboxes screen or run `sellbird doctor`.
6. Mailflare currently works as the primary sending inbox. The secondary-inbox UI does not yet connect additional Mailflare addresses; use the existing Gmail, Microsoft 365 or SMTP paths for extra inboxes.

The send key is not tested by sending a real message: the connection check verifies JMAP access and explains that Mailflare checks send permission on the first approved send. A timeout or disconnect after a send request is treated as an uncertain outcome; Sellbird must not blindly retry it. Reply reads fail closed and propagate read errors so the heartbeat can hold sending when it cannot reliably inspect replies.

The adapter currently sends the expected payload fields (`from`, `to`, `subject`, `text`, `inReplyTo`, `references`) and accepts provider message/thread IDs when returned. Mailflare's public docs do not specify the exact send response shape, so the adapter tolerates the common `id` / `messageId` and `threadId` variants. Your deployed Worker must still be tested with your actual keys and deployment.

## Sellbird Cloud AI Worker

`cloudflare/sellbird-ai` is a separate Worker. It exposes:

- `GET /health` (authenticated with the shared bearer secret)
- `POST /v1/research-score` — Gemini
- `POST /v1/classify-reply` — Gemini
- `POST /v1/write-email` — Cloudflare Workers AI

All POST routes require a shared bearer secret, enforce a prompt size limit, validate task names, apply a Cloudflare rate-limit binding, and return generic provider errors. The Worker does not expose a general-purpose proxy. It does not log prompt content or credentials.

Deploy separately from `cloudflare/sellbird-ai`:

```bash
npm install -g wrangler
wrangler secret put SELLBIRD_AI_SECRET
wrangler secret put GEMINI_API_KEY
wrangler deploy
```

Set the same shared secret and deployed Worker URL in Sellbird → Sending and keys. Then set in `sellbird.yaml`:

```yaml
brain:
  provider: "cloudflare"
```

The Worker uses Workers AI model `@cf/meta/llama-3.3-70b-instruct-fp8-fast` by default and Gemini model `gemini-2.5-flash` by default. Model availability and free quotas can change; do not assume either provider remains free. If the model is unavailable in your account, change `CF_AI_MODEL` or `GEMINI_MODEL` in the Worker variables to a model enabled for your account.

## Local dashboard and remote access

The existing Sellbird dashboard deliberately binds to loopback only and refuses a public network bind. This patch preserves that security boundary. The project still runs locally on desktop; its existing Docker/remote-host workflow uses an SSH tunnel to reach the loopback dashboard. Mailflare is currently wired as the primary sending provider; connecting multiple separate Mailflare inboxes through the secondary-inbox UI is not implemented in this patch. A public multi-user hosted dashboard is not implemented by this integration: it needs a durable database volume, workspace-isolated secret storage, HTTPS, authentication/session management and a supported Python hosting target. A Cloudflare Worker cannot host the existing FastAPI/SQLite application by itself.

## Configuration variables

| Variable | Purpose |
|---|---|
| `MAILFLARE_BASE_URL` | Mailflare deployment origin, without a trailing slash |
| `MAILFLARE_API_KEY` | Mailflare personal API key with `send` scope |
| `MAILFLARE_JMAP_API_KEY` | Mailflare app password/key with `jmap` scope |
| `SELLBIRD_AI_URL` | Deployed Sellbird AI Worker origin |
| `SELLBIRD_AI_SECRET` | Shared bearer secret between Sellbird and the Worker |

Never commit real credentials or place them in `sellbird.yaml`.
