# ui — debug interface for the pseudonymization proxy

Vite + React + shadcn/ui. Talks only to the `/debug/*` endpoints of `../proxy.py`.
Reachable for the IPs in `PSEUDO_DEBUG_ALLOW` (default: localhost only; `../start.sh`
sets `*` because the host is only reachable over VPN): `http://<proxy-host>:9112/ui/`.

Views: **Audit** (search the log, detail, per-request leak check),
**Detection** (test a text, all candidates with their decision),
**Request preview** (messages array → what the upstream would see), **Status**.

## Use (built, served by the proxy)

```bash
npm --prefix ui run build
rsync -a --delete ui/dist/ <gpu-host>:pseudo-ui/
scp proxy.py <gpu-host>:pseudo-proxy.py && ssh <gpu-host> '~/pseudo-start.sh'
```

## Develop

```bash
PSEUDO_PROXY=http://<proxy-host>:9112 npm --prefix ui run dev
```

Without `PSEUDO_PROXY`, Vite proxies to `localhost:9112` (e.g. a local test proxy).
