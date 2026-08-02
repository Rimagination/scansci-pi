# ScanSciAI managed-model gateway

This Worker provides the zero-configuration public model service used by the
ScanSci desktop application. It accepts OpenAI-compatible chat requests,
allows only the declared ScanSciAI models, applies small per-IP quotas, and
forwards each request to its provider without exposing upstream credentials.

| ScanSciAI model ID | Upstream | Cloudflare Worker secret |
| --- | --- | --- |
| `glm-4.7-flash` | Zhipu | `ZHIPU_API_KEY` |
| `Qwen/Qwen2.5-7B-Instruct` | SiliconFlow | `SILICONFLOW_API_KEY` |

## Operator setup

From this directory, authenticate the service operator and deploy:

```powershell
npx wrangler login
npm install
npx wrangler deploy
npx wrangler secret put ZHIPU_API_KEY
npx wrangler secret put SILICONFLOW_API_KEY
```

Set only the provider secrets for models that should be enabled. Never put a
secret in `wrangler.jsonc`, an `.env` file committed to source control, or the
ScanSci executable.

After deployment, copy the Worker URL into the ScanSci release configuration.
The public endpoint is intentionally limited to `POST /v1/chat/completions`
and only routes to the closed model catalog in `src/index.js`.

## Local checks

```powershell
npm install
npm test
npm run check
```
