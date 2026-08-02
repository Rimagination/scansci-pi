const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff"
};

const MAX_MESSAGES = 32;
const DEFAULT_MANAGED_MODEL_ID = "glm-4.7-flash";
const DEFAULT_UPSTREAM_TIMEOUT_MS = 75_000;

// This catalog is intentionally closed: a desktop client may select one of
// these model IDs, but it can never turn the public gateway into a proxy for
// an arbitrary provider, endpoint, or account credential.
const MANAGED_MODELS = Object.freeze({
  "glm-4.7-flash": Object.freeze({
    upstreamUrl: "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    secretName: "ZHIPU_API_KEY",
    supportsThinking: true,
  }),
  "Qwen/Qwen2.5-7B-Instruct": Object.freeze({
    upstreamUrl: "https://api.siliconflow.cn/v1/chat/completions",
    secretName: "SILICONFLOW_API_KEY",
    supportsThinking: false,
  }),
});

export class RateLimiter {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    const body = await request.json();
    const dailyLimit = positiveInteger(body.daily_limit, 60);
    const minuteLimit = positiveInteger(body.minute_limit, 6);
    const now = Date.now();
    const minute = Math.floor(now / 60_000);
    const stored = (await this.state.storage.get("quota")) || { minute, minute_count: 0, day_count: 0 };
    const quota = {
      minute,
      minute_count: stored.minute === minute ? Number(stored.minute_count || 0) : 0,
      day_count: Number(stored.day_count || 0)
    };
    const allowed = quota.minute_count < minuteLimit && quota.day_count < dailyLimit;
    if (allowed) {
      quota.minute_count += 1;
      quota.day_count += 1;
      await this.state.storage.put("quota", quota);
    }
    return json({
      allowed,
      retry_after_seconds: allowed ? 0 : quota.minute_count >= minuteLimit ? 60 - Math.floor((now % 60_000) / 1000) : 86_400,
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/healthz") {
      return json({ status: "ok", models: Object.keys(MANAGED_MODELS) });
    }
    if (request.method !== "POST" || url.pathname !== "/v1/chat/completions") {
      return error(404, "not_found", "This gateway only exposes POST /v1/chat/completions.");
    }
    const requestId = crypto.randomUUID();
    try {
      const payload = await parseChatPayload(request, env);
      const managedModel = MANAGED_MODELS[payload.model];
      if (!managedModel) {
        throw requestError("The requested managed model is not available.");
      }
      const upstreamKey = env[managedModel.secretName];
      if (!upstreamKey) {
        return error(
          503,
          "managed_model_not_configured",
          "The requested managed model service is not configured.",
          diagnosticHeaders(requestId, { "x-scansci-error-class": "managed_model_not_configured" }),
        );
      }
      const admission = await checkLimit(request, env);
      if (!admission.allowed) {
        return error(429, "rate_limit_exceeded", "The managed model service has reached its temporary request limit.", {
          "retry-after": String(admission.retry_after_seconds),
          ...diagnosticHeaders(requestId, { "x-scansci-error-class": "gateway_rate_limit" }),
        });
      }

      const upstreamFetch = env.UPSTREAM_FETCH || fetch;
      const upstreamPayload = { ...payload };
      if (!managedModel.supportsThinking) {
        delete upstreamPayload.thinking;
      }
      const upstreamTimeoutMs = clampInteger(
        env.UPSTREAM_TIMEOUT_MS,
        5_000,
        85_000,
        DEFAULT_UPSTREAM_TIMEOUT_MS,
      );
      const upstreamAbort = new AbortController();
      const timeoutHandle = setTimeout(() => upstreamAbort.abort(), upstreamTimeoutMs);
      let upstream;
      try {
        upstream = await upstreamFetch(managedModel.upstreamUrl, {
          method: "POST",
          headers: {
            "authorization": `Bearer ${upstreamKey}`,
            "content-type": "application/json"
          },
          body: JSON.stringify(upstreamPayload),
          signal: upstreamAbort.signal,
        });
      } catch (reason) {
        const code = upstreamAbort.signal.aborted ? "upstream_timeout" : "upstream_connection_failed";
        const status = upstreamAbort.signal.aborted ? 504 : 502;
        const message = upstreamAbort.signal.aborted
          ? "The managed model provider did not respond before the gateway timeout."
          : "The managed model provider could not be reached.";
        return error(
          status,
          code,
          message,
          diagnosticHeaders(requestId, {
            "x-scansci-error-class": code,
            ...(upstreamAbort.signal.aborted ? { "retry-after": "10" } : {}),
          }),
        );
      } finally {
        clearTimeout(timeoutHandle);
      }
      if (!upstream.ok) {
        const retryAfter = upstream.headers.get("retry-after");
        const code = upstream.status === 429 ? "upstream_rate_limited" : "upstream_error";
        return error(
          upstream.status === 429 ? 429 : 502,
          code,
          "The managed model provider could not complete this request.",
          diagnosticHeaders(requestId, {
            "x-scansci-error-class": code,
            ...(retryAfter ? { "retry-after": retryAfter } : {}),
          }),
        );
      }
      return new Response(upstream.body, {
        status: 200,
        headers: {
          ...JSON_HEADERS,
          "content-type": upstream.headers.get("content-type") || JSON_HEADERS["content-type"],
          "x-scansci-model": payload.model,
          ...diagnosticHeaders(requestId),
        }
      });
    } catch (reason) {
      return error(
        reason.status || 400,
        reason.code || "invalid_request",
        reason.message || "Invalid request.",
        diagnosticHeaders(requestId),
      );
    }
  }
};

async function parseChatPayload(request, env) {
  const raw = await request.text();
  const maxInputChars = positiveInteger(env.MAX_INPUT_CHARS, 48_000);
  if (!raw || raw.length > maxInputChars) {
    throw requestError("The request body is empty or exceeds the managed service input limit.");
  }
  let source;
  try {
    source = JSON.parse(raw);
  } catch {
    throw requestError("Request body must be valid JSON.");
  }
  const messages = Array.isArray(source.messages) ? source.messages : [];
  if (!messages.length || messages.length > MAX_MESSAGES) {
    throw requestError(`messages must contain between 1 and ${MAX_MESSAGES} entries.`);
  }
  const normalizedMessages = messages.map((message) => {
    if (!message || typeof message !== "object" || typeof message.role !== "string" || typeof message.content !== "string") {
      throw requestError("Each message must contain string role and content fields.");
    }
    return { role: message.role, content: message.content };
  });
  const maxTokens = clampInteger(source.max_tokens ?? source.max_completion_tokens, 1, positiveInteger(env.MAX_OUTPUT_TOKENS, 4096), 2048);
  const thinking = normalizeThinking(source.thinking);
  const stream = source.stream === true;
  return {
    model: normalizeManagedModelId(source.model),
    messages: normalizedMessages,
    temperature: clampNumber(source.temperature, 0, 1, 0.4),
    top_p: clampNumber(source.top_p, 0.01, 1, 0.95),
    max_tokens: maxTokens,
    stream,
    ...(thinking ? { thinking } : {})
  };
}

function normalizeManagedModelId(value) {
  if (typeof value !== "string" || !value.trim()) {
    return DEFAULT_MANAGED_MODEL_ID;
  }
  return value.trim();
}

function normalizeThinking(value) {
  const type = value && typeof value === "object" ? value.type : "";
  return type === "enabled" || type === "disabled" ? { type } : null;
}

async function checkLimit(request, env) {
  const clientIp = request.headers.get("cf-connecting-ip") || "unknown";
  const day = new Date().toISOString().slice(0, 10);
  const identity = await sha256(`${day}:${clientIp}`);
  const id = env.RATE_LIMITER.idFromName(`ip:${identity}`);
  const limiter = env.RATE_LIMITER.get(id);
  const response = await limiter.fetch("https://rate-limiter/check", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      daily_limit: positiveInteger(env.DAILY_REQUEST_LIMIT, 60),
      minute_limit: positiveInteger(env.MINUTE_REQUEST_LIMIT, 6)
    })
  });
  return response.json();
}

function requestError(message) {
  return Object.assign(new Error(message), { status: 400, code: "invalid_request" });
}

function positiveInteger(value, fallback) {
  const number = Number.parseInt(String(value ?? ""), 10);
  return Number.isSafeInteger(number) && number > 0 ? number : fallback;
}

function clampInteger(value, minimum, maximum, fallback) {
  const number = Number.parseInt(String(value ?? ""), 10);
  return Number.isSafeInteger(number) ? Math.min(maximum, Math.max(minimum, number)) : fallback;
}

function clampNumber(value, minimum, maximum, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.min(maximum, Math.max(minimum, number)) : fallback;
}

async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (part) => part.toString(16).padStart(2, "0")).join("");
}

function json(value, init = {}) {
  return new Response(JSON.stringify(value), { ...init, headers: { ...JSON_HEADERS, ...(init.headers || {}) } });
}

function diagnosticHeaders(requestId, headers = {}) {
  return { "x-scansci-request-id": requestId, ...headers };
}

function error(status, code, message, headers = {}) {
  return json({ error: { code, message } }, { status, headers });
}
