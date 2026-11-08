# 11: Deployment to the Synology

**What to build:** bonneaffaire runs permanently on the owner's DS920+ (x86-64) via Synology Container Manager. This covers:
- a Docker image and a compose file
- configuration through environment variables or a config file: enabled Providers, rates, timeouts, cache window, default limit, eBay credentials
- documentation for exposing the MCP server only through a Cloudflare Tunnel protected by Cloudflare Access, including creating a service token for agents and configuring an agent such as Claude Code to send it

No app-level auth. LAN access is open by decision.

**Blocked by:** 06, 10

**Status:** ready-for-agent

- [x] The image builds for x86-64, and the compose file starts the MCP server with a persistent config
- [x] All settings listed in the spec can be set without rebuilding the image
- [x] Documentation covers Container Manager setup, the cloudflared tunnel, the Cloudflare Access application and service token, and an example agent configuration sending the Access headers
- [x] A health check shows the service is up
