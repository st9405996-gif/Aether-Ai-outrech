# Remote access to a self-hosted Sellbird dashboard

Sellbird intentionally refuses to bind its FastAPI dashboard to a public network interface. Keep that boundary. If you need to open the same dashboard from another device, use a private tunnel rather than changing the app to listen on `0.0.0.0`.

This is remote access to the dashboard running on your own computer/server, not a separately hosted multi-tenant Sellbird service. The database and `.env` remain on that host.

## Cloudflare Tunnel (optional)

1. Run Sellbird on a Linux host using the existing Docker Compose setup. It keeps the dashboard on `127.0.0.1:5555` and persists the project directory.
2. In Cloudflare Zero Trust, create a remotely managed Tunnel for this host.
3. Add a public hostname and set its service to `http://localhost:5555` (the tunnel container uses host networking).
4. Add a Cloudflare Access application and an allow policy for only the account(s) that should use the dashboard. Do not publish the hostname without an Access policy.
5. Copy the tunnel token into `.env` as `CLOUDFLARE_TUNNEL_TOKEN`. Do not commit it.
6. Start both services:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d
   ```

7. Open the Access-protected hostname. Sellbird's own dashboard unlock token remains required as a second layer.

To stop remote access while leaving Sellbird running:

```bash
docker compose -f docker-compose.yml -f docker-compose.tunnel.yml stop cloudflared
```

The tunnel is a separate Cloudflare resource. This repository change does not create the tunnel, configure Access, publish DNS, or touch the AETHER-TRADE or Mailflare Workers. Cloudflare account terms and feature availability may change.

## Important limitation

This does not create a public hosted dashboard with separate user accounts/workspaces. That would require a persistent Python host, durable database storage, workspace-isolated credentials, HTTPS and session management. Cloudflare Workers AI is only the model gateway; it cannot host the existing FastAPI/SQLite dashboard application by itself.
