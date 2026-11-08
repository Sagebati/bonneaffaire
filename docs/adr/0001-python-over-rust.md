# Python, not Rust

Rust was the preferred language, but bonneaffaire is written in Python. The only maintained clients for Vinted and Leboncoin (`lbc`, `vinted_scraper`, `vinted-api-kit`) are Python, and so are the best anti-bot tools (curl_cffi for browser TLS impersonation; camoufox and nodriver for stealth browsers). Rust's HTTP impersonation (`wreq`) is on par, but it has no maintained marketplace clients and no stealth browser. The internal endpoints change often (Vinted replaced its search endpoint in October 2026), so staying close to the libraries that track those changes outweighs the language preference.

## Considered Options

- Rust core using `wreq`, with Vinted/Leboncoin endpoint code ported from Python and a Python sidecar for browser challenges: rejected, because we would maintain the ports ourselves against endpoint churn.
- Rust core shelling out to the Python libraries: rejected, because it is two runtimes and a subprocess boundary for no gain.
