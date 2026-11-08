# Deploying bonneaffaire on the Synology

bonneaffaire runs permanently on the DS920+ (x86-64, 4 GB RAM) as a Container Manager project of two containers:

- `bonneaffaire`: the MCP server (`bonneaffaire serve`). It serves the MCP endpoint at `/mcp` and a health check at `/health`.
- `cloudflared`: a Cloudflare Tunnel connector. It is the only route in from the internet.

The app has no authentication of its own. Outside the LAN it is reachable only through the tunnel, and Cloudflare Access sits in front of the tunnel and lets through only requests that carry a valid service token. LAN access stays open by decision (port 8000 on the NAS).

The files used here, all at the repo root:

| File | Purpose |
| --- | --- |
| `Dockerfile` | Builds the image from `uv.lock` with uv. A Provider that adds a dependency only has to update the lockfile. |
| `compose.yaml` | The project: both services, the restart policy, the health check dependency, memory limits. |
| `.env.example` | Every setting, commented. Copy it to `.env`. |

## 1. Settings

All settings are environment variables read when the server starts. They live in `.env` next to `compose.yaml`. To change one, edit `.env` and restart the project (Container Manager > Project > Action > Restart, or `docker compose up -d`). The image doesn't need a rebuild.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CLOUDFLARE_TUNNEL_TOKEN` | required | Token of the Cloudflare Tunnel (step 3). Used only by the `cloudflared` container. |
| `BONNEAFFAIRE_DISABLED_PROVIDERS` | empty | Comma-separated Provider names to switch off, e.g. `vinted,ebay`. Disabled Providers still appear in `list_providers` with `enabled: false`. |
| `BONNEAFFAIRE_TIMEOUT_SECONDS` | `20` | Seconds each Provider gets to answer one Search or Get Listing. Time spent waiting on the throttle is not counted. |
| `BONNEAFFAIRE_DEFAULT_LIMIT` | `50` | Listings per Provider when a Search doesn't give a `limit`. |
| `BONNEAFFAIRE_RATE_PER_MINUTE` | `20` | Requests per minute to each Provider. |
| `BONNEAFFAIRE_PROVIDER_RATES` | empty | Per-Provider rate overrides, e.g. `ldlc=30,leboncoin=5`. |
| `BONNEAFFAIRE_CACHE_SECONDS` | `120` | How long an identical Search is answered from cache. `0` turns the cache off. |
| `BONNEAFFAIRE_BACKOFF_SECONDS` | `600` | How long a blocked Provider is left alone before it is asked again. |
| `BONNEAFFAIRE_EBAY_CLIENT_ID` | empty | eBay Browse API client ID (App ID). eBay is disabled unless both are set. |
| `BONNEAFFAIRE_EBAY_CLIENT_SECRET` | empty | eBay Browse API client secret (Cert ID). See the client ID. |
| `BONNEAFFAIRE_HOST` / `BONNEAFFAIRE_PORT` | `0.0.0.0` / `8000` | Listen address inside the container. `compose.yaml` sets these, so leave them alone. |

A malformed value (e.g. `BONNEAFFAIRE_DEFAULT_LIMIT=lots`) stops the server at startup with an error naming the variable. You can read it in the container log.

Cache, throttle and backoff state is held in memory, so a restart clears it.

## 2. Container Manager project

1. In File Station, create a folder for the project, e.g. `/volume1/docker/bonneaffaire`.
2. Copy into it: `Dockerfile`, `.dockerignore`, `compose.yaml`, `pyproject.toml`, `uv.lock`, and the `src/` folder. A `git clone` over SSH works too: `git clone <repo> /volume1/docker/bonneaffaire`.
3. Copy `.env.example` to `.env` in that folder and fill it in. You get `CLOUDFLARE_TUNNEL_TOKEN` in step 3. This file is the persistent configuration and survives image rebuilds and container re-creation.
4. Open **Container Manager > Project > Create**:
   - Project name: `bonneaffaire`
   - Path: the folder from step 1
   - Source: *Use existing docker-compose.yml*. If your Container Manager version doesn't pick up `compose.yaml`, rename it `docker-compose.yml`.
   - Skip the Web Station portal settings.
5. Click **Done**. Container Manager builds the image on the NAS (a few minutes the first time) and starts both containers. `cloudflared` waits until `bonneaffaire` is healthy.

To update after a `git pull`: **Project > Action > Build**, then start the project again. From SSH, run `sudo docker compose up -d --build` in the folder instead.

If you'd rather not build on the NAS, build the image on another x86-64 machine and copy it across. Then run **Project > Action > Start**: compose uses the existing `bonneaffaire:latest` image.

```sh
docker build --platform linux/amd64 -t bonneaffaire:latest .
docker save bonneaffaire:latest | ssh admin@nas sudo docker load
```

Resource use: the image is about 230 MB and the server idles at about 60 MB of RAM. `compose.yaml` caps it at 512 MB and `cloudflared` at 128 MB.

### Checking it runs

- Container Manager > Container: `bonneaffaire` should show **Healthy**. The image's `HEALTHCHECK` calls `/health` every 30 s. It shows whether the process answers HTTP and never contacts Providers, so a blocked Provider can't mark the container unhealthy.
- From the LAN: `curl http://<nas-ip>:8000/health` returns `{"status":"ok","enabled_providers":["ldlc", ...]}`.
- MCP endpoint on the LAN: `http://<nas-ip>:8000/mcp`.

## 3. Cloudflare Tunnel

You need a domain on Cloudflare, here `example.com`, with the MCP server published as `bonneaffaire.example.com`.

1. Cloudflare dashboard > **Zero Trust > Networks > Tunnels > Create a tunnel**, type **Cloudflared**, name it `synology`.
2. On the "Install and run a connector" page choose **Docker**. Copy the token from the command shown (the long string after `--token`) into `CLOUDFLARE_TUNNEL_TOKEN` in `.env`. Don't run the command: the `cloudflared` service in `compose.yaml` is the connector. Restart the project; the tunnel should then show **Healthy** in the dashboard.
3. Add a **Public hostname**:
   - Subdomain `bonneaffaire`, domain `example.com`, path empty
   - Service type **HTTP**, URL `bonneaffaire:8000` (the compose service name, reachable on the project's network)
4. Save. Don't test from outside until the Access application in step 4 exists. Until then the hostname is open to anyone.

If you already run `cloudflared` elsewhere on the NAS, delete the `cloudflared` service from `compose.yaml`. Then point a public hostname of the existing tunnel at `http://<nas-ip>:8000`.

## 4. Cloudflare Access application and service token

### Create the service token

1. **Zero Trust > Access > Service credentials > Service Tokens > Create Service Token**.
2. Name it after the agent, e.g. `claude-code-laptop`, and pick a duration (non-expiring, or a year with a reminder to rotate).
3. Copy the **Client ID** and **Client Secret**. The secret is shown only once. Create one token per agent or machine so each can be revoked alone.

### Create the Access application

1. **Zero Trust > Access > Applications > Add an application > Self-hosted**.
2. Application name `bonneaffaire`. Add the public hostname `bonneaffaire.example.com` with an empty path, so the whole host, `/mcp` and `/health` included, is protected.
3. Add a policy:
   - Name `agents`, action **Service Auth**
   - Include: **Service Token**, and pick the token(s) from above
4. No identity provider or login page is needed: agents never see one. Save.

Check it from any machine. Without the headers Cloudflare returns `403` or redirects to a login page; with them you get the health JSON:

```sh
curl -i https://bonneaffaire.example.com/health
curl -s https://bonneaffaire.example.com/health \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET"
```

To revoke an agent, delete or rotate its service token. Nothing changes on the NAS.

## 5. Agent configuration (Claude Code)

The agent sends the two Access headers on every request to `https://bonneaffaire.example.com/mcp` (Streamable HTTP transport).

Add it from the command line:

```sh
claude mcp add --transport http bonneaffaire https://bonneaffaire.example.com/mcp \
  --header "CF-Access-Client-Id: <client-id>" \
  --header "CF-Access-Client-Secret: <client-secret>"
```

Or share it through a project `.mcp.json` that reads the secrets from the environment, so they stay out of git:

```json
{
  "mcpServers": {
    "bonneaffaire": {
      "type": "http",
      "url": "https://bonneaffaire.example.com/mcp",
      "headers": {
        "CF-Access-Client-Id": "${CF_ACCESS_CLIENT_ID}",
        "CF-Access-Client-Secret": "${CF_ACCESS_CLIENT_SECRET}"
      }
    }
  }
}
```

Then `export CF_ACCESS_CLIENT_ID=... CF_ACCESS_CLIENT_SECRET=...` before starting `claude`. Run `/mcp` in Claude Code: `bonneaffaire` should be connected, with the tools `search`, `get_listing` and `list_providers`.

Other MCP clients work the same way. Point them at the `/mcp` URL with the Streamable HTTP transport and set the two headers.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Container restarts at once; the log shows `BONNEAFFAIRE_...: expected ...` | Malformed value in `.env`. |
| `cloudflared` never starts | `bonneaffaire` isn't healthy yet, or `CLOUDFLARE_TUNNEL_TOKEN` is empty (compose refuses to start). |
| Agent gets `403` or an HTML login page | Missing or wrong service token headers, or the token isn't in the Access policy. |
| Tunnel hostname returns `502` | The public hostname's service URL is wrong; it must be `http://bonneaffaire:8000` when `cloudflared` runs in this project. |
| A Provider is always `blocked` | It's backing off (`BONNEAFFAIRE_BACKOFF_SECONDS`). Lower its rate in `BONNEAFFAIRE_PROVIDER_RATES`, or disable it. |
