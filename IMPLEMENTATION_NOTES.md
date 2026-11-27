# Sellbird Mailflare + Cloud AI patch notes

## Implemented in this ZIP

- Wired `mailflare` into the native primary email provider selection.
- Added Mailflare origin, send key and JMAP key settings to the dashboard. Secret values are never returned by the settings API; blank password fields keep the saved value.
- Added Mailflare REST send handling, JMAP inbox/reply reads, message/thread ID capture, explicit auth/rate-limit handling, and uncertain-send outcomes that must not be blindly retried.
- Added same-origin HTTPS validation for the discovered JMAP API endpoint before sending the JMAP credential to it.
- Added `cloudflare` as a Brain provider, connected through the existing Brain transport seam.
- Added dashboard fields for the Sellbird AI Worker URL and shared secret.
- Included the separate Cloudflare Worker under `cloudflare/sellbird-ai` with authenticated endpoints, provider routing, request validation, prompt-size limits, rate limiting and generic provider errors.
- Preserved approval-first sending and existing daily send limits. No AETHER-TRADE Worker or Mailflare Worker source is modified by this project patch.

## Configure after extracting

1. In Sellbird → Sending and keys, enter the Mailflare deployment origin, send-scoped API key and JMAP-scoped key.
2. In `sellbird.yaml`, set `channels.email.provider: "mailflare"`. Keep `require_approval: true` while testing. Ensure `persona.email` is an authorized Mailflare sender.
3. Deploy the separate Worker from `cloudflare/sellbird-ai` using the instructions in that folder. Set the Worker secrets in Wrangler, then enter its URL and shared secret in Sending and keys.
4. To use the Cloud AI Worker as Sellbird's Brain, add this top-level section to `sellbird.yaml`:

   ```yaml
   brain:
     provider: cloudflare
   ```

5. Restart Sellbird after changing `sellbird.yaml`.

## Not implemented / requires your account

- The Mailflare API key and JMAP key were intentionally not supplied, so live account authentication and delivery were not tested. The deployed Mailflare Worker must be verified with your own credentials before relying on it.
- Mailflare is connected as the primary sending inbox only. Additional Mailflare inboxes are not yet supported in Sellbird's secondary-inbox screen; existing Gmail, Microsoft 365 and SMTP secondary inbox paths remain available.
- The existing FastAPI dashboard remains local/loopback-only. This patch does not create a public hosted dashboard. A Cloudflare Worker is not a host for the existing FastAPI + SQLite application; remote use remains via the project's SSH-tunnel workflow.
- The Cloudflare Worker was not deployed. Wrangler and the Cloudflare Workers type package were not installed in this environment.

## Validation performed

- Python compile check: passed.
- Mailflare send adapter mock smoke test: passed.
- Cloud AI transport mock smoke test: passed.
- `BrainConfig(provider="cloudflare")` and new environment config fields: passed.
- Dashboard settings element/function wiring check: passed.
- Dashboard JavaScript syntax check (`node --check`): passed.
- YAML parse check: passed.
- Full pytest collection could not run because this environment lacks project dependencies including `aiosqlite`, `mcp` and `aiosmtplib`; network access was unavailable to install them.
- Cloudflare Worker typecheck could not run because `@cloudflare/workers-types` is not installed.


## Product branding

The README heading and dashboard browser title use **Aether Trade Outreach System**. The underlying Python distribution, import package, CLI command, and some original UI copy still use `sellbird` to preserve compatibility with the upstream codebase. This is a modified AGPL-3.0-only fork; retain the LICENSE and upstream notices.
