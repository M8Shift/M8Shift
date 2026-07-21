# Deploy `protocol.m8shift.ai`

This directory is a standalone, dependency-free Cloudflare Worker. The deployed
Worker is the generated single file `worker.mjs`; it embeds both the canonical
Markdown and the pre-rendered HTML. It performs no runtime fetch.

## Verify the generated files

From the repository root:

```bash
python3 protocol-worker/generate.py --check
node protocol-worker/test-worker.mjs
cd protocol-worker
npx wrangler@4 deploy --dry-run
```

Regenerate after the canonical source changes:

```bash
python3 protocol-worker/generate.py
```

`protocol.md` must remain byte-for-byte identical to
`docs/en/AGENT-EXCHANGE-PROTOCOL.md`.

## Bind DNS and the Worker route

In the target Cloudflare account, select the `m8shift.ai` zone. Ensure DNS has
a proxied record for `protocol.m8shift.ai`. If it does not exist, create:

- Type: `CNAME`
- Name: `protocol`
- Target: `m8shift.ai`
- Proxy status: **Proxied**

The checked-in `wrangler.jsonc` binds the Worker route
`protocol.m8shift.ai/*` to the `m8shift.ai` zone. Do not add a second Worker to
the same route.

## Deploy

From `protocol-worker/`:

```bash
npx wrangler@4 whoami
npx wrangler@4 deploy
```

`whoami` must show the intended account before deployment. If it does not, run
`npx wrangler@4 login`, then repeat `whoami`. No secret or runtime binding is
required.

## Production smoke test

```bash
curl -i -H 'Accept: text/markdown' https://protocol.m8shift.ai/
curl -i -H 'Accept: text/html' -A 'Mozilla/5.0' https://protocol.m8shift.ai/
curl -i https://protocol.m8shift.ai/llms.txt
```

The first response must be raw Markdown, the second must contain
`<title>Agent Exchange Protocol</title>` in the response bytes, and the third
must point agents to the canonical URL.
