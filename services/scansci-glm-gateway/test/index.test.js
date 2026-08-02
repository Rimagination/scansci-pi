import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.js";

function makeEnv({ zhipuSecret = "zhipu-secret", siliconflowSecret = "siliconflow-secret", upstreamStatus = 200 } = {}) {
  const state = { quota: null };
  return {
    ZHIPU_API_KEY: zhipuSecret,
    SILICONFLOW_API_KEY: siliconflowSecret,
    DAILY_REQUEST_LIMIT: "2",
    MINUTE_REQUEST_LIMIT: "2",
    MAX_INPUT_CHARS: "48000",
    MAX_OUTPUT_TOKENS: "4096",
    RATE_LIMITER: {
      idFromName: (name) => name,
      get: () => ({
        fetch: async (_url, request) => {
          const limits = JSON.parse(request.body);
          const minute = Math.floor(Date.now() / 60_000);
          const quota = state.quota && state.quota.minute === minute ? state.quota : { minute, minute_count: 0, day_count: 0 };
          const allowed = quota.minute_count < limits.minute_limit && quota.day_count < limits.daily_limit;
          if (allowed) {
            quota.minute_count += 1;
            quota.day_count += 1;
            state.quota = quota;
          }
          return new Response(JSON.stringify({ allowed, retry_after_seconds: allowed ? 0 : 60 }), { headers: { "content-type": "application/json" } });
        }
      })
    },
    upstreamStatus
  };
}

test("health endpoint exposes no secret", async () => {
  const response = await worker.fetch(new Request("https://gateway.example/healthz"), makeEnv());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    status: "ok",
    models: ["glm-4.7-flash", "Qwen/Qwen2.5-7B-Instruct"],
  });
});

test("gateway routes GLM through Zhipu and removes caller credentials", async () => {
  let upstreamRequest;
  let upstreamUrl;
  const env = makeEnv();
  env.UPSTREAM_FETCH = async (url, init) => {
    upstreamUrl = url;
    upstreamRequest = init;
    return new Response(JSON.stringify({ id: "chatcmpl-test", choices: [{ message: { role: "assistant", content: "ok" } }] }), { headers: { "content-type": "application/json" } });
  };
  const response = await worker.fetch(new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", "authorization": "Bearer client-token", "cf-connecting-ip": "203.0.113.10" },
    body: JSON.stringify({ model: "glm-4.7-flash", messages: [{ role: "user", content: "hello" }], max_tokens: 99999, stream: true, thinking: { type: "disabled" } })
  }), env);
  assert.equal(response.status, 200);
  assert.equal(upstreamUrl, "https://open.bigmodel.cn/api/paas/v4/chat/completions");
  assert.equal(upstreamRequest.headers.authorization, "Bearer zhipu-secret");
  assert.match(response.headers.get("x-scansci-request-id") || "", /^[0-9a-f-]{36}$/i);
  const forwarded = JSON.parse(upstreamRequest.body);
  assert.equal(forwarded.model, "glm-4.7-flash");
  assert.equal(forwarded.max_tokens, 4096);
  assert.equal(forwarded.stream, true);
  assert.deepEqual(forwarded.thinking, { type: "disabled" });
});

test("gateway routes the managed Qwen model through SiliconFlow", async () => {
  let upstreamRequest;
  let upstreamUrl;
  const env = makeEnv();
  env.UPSTREAM_FETCH = async (url, init) => {
    upstreamUrl = url;
    upstreamRequest = init;
    return new Response(JSON.stringify({ choices: [{ message: { role: "assistant", content: "ok" } }] }), { headers: { "content-type": "application/json" } });
  };
  const response = await worker.fetch(new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": "203.0.113.12" },
    body: JSON.stringify({ model: "Qwen/Qwen2.5-7B-Instruct", messages: [{ role: "user", content: "hello" }], stream: true, thinking: { type: "enabled" } })
  }), env);
  assert.equal(response.status, 200);
  assert.equal(upstreamUrl, "https://api.siliconflow.cn/v1/chat/completions");
  assert.equal(upstreamRequest.headers.authorization, "Bearer siliconflow-secret");
  const forwarded = JSON.parse(upstreamRequest.body);
  assert.equal(forwarded.model, "Qwen/Qwen2.5-7B-Instruct");
  assert.equal(forwarded.stream, true);
  assert.equal("thinking" in forwarded, false);
});

test("gateway rejects undeclared model IDs without calling an upstream", async () => {
  let called = false;
  const env = makeEnv();
  env.UPSTREAM_FETCH = async () => { called = true; throw new Error("must not call upstream"); };
  const response = await worker.fetch(new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model: "somebody-elses-model", messages: [{ role: "user", content: "hello" }] })
  }), env);
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error.code, "invalid_request");
  assert.equal(called, false);
});

test("gateway reports a missing SiliconFlow secret without calling an upstream", async () => {
  let called = false;
  const env = makeEnv({ siliconflowSecret: "" });
  env.UPSTREAM_FETCH = async () => { called = true; throw new Error("must not call upstream"); };
  const response = await worker.fetch(new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model: "Qwen/Qwen2.5-7B-Instruct", messages: [{ role: "user", content: "hello" }] })
  }), env);
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error.code, "managed_model_not_configured");
  assert.equal(called, false);
});

test("gateway rejects oversized input before sending it upstream", async () => {
  let called = false;
  const env = makeEnv();
  env.UPSTREAM_FETCH = async () => { called = true; throw new Error("must not call upstream"); };
  env.MAX_INPUT_CHARS = "10";
  const response = await worker.fetch(new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "hello" }] })
  }), env);
  assert.equal(response.status, 400);
  assert.equal(called, false);
});

test("gateway returns 429 when the public limit is exhausted", async () => {
  const env = makeEnv();
  env.UPSTREAM_FETCH = async () => new Response(JSON.stringify({ choices: [] }), { headers: { "content-type": "application/json" } });
  const makeRequest = () => new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": "203.0.113.11" },
    body: JSON.stringify({ messages: [{ role: "user", content: "hello" }] })
  });
  assert.equal((await worker.fetch(makeRequest(), env)).status, 200);
  assert.equal((await worker.fetch(makeRequest(), env)).status, 200);
  const limited = await worker.fetch(makeRequest(), env);
  assert.equal(limited.status, 429);
  assert.equal((await limited.json()).error.code, "rate_limit_exceeded");
  assert.equal(limited.headers.get("x-scansci-error-class"), "gateway_rate_limit");
  assert.match(limited.headers.get("x-scansci-request-id") || "", /^[0-9a-f-]{36}$/i);
});

test("gateway reports an unreachable managed provider as a retryable upstream failure", async () => {
  const env = makeEnv();
  env.UPSTREAM_FETCH = async () => { throw new TypeError("network unavailable"); };
  const response = await worker.fetch(new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "hello" }] })
  }), env);

  assert.equal(response.status, 502);
  assert.equal((await response.json()).error.code, "upstream_connection_failed");
  assert.equal(response.headers.get("x-scansci-error-class"), "upstream_connection_failed");
});

test("gateway preserves upstream 429 separately from its own rate limiter", async () => {
  const env = makeEnv();
  env.UPSTREAM_FETCH = async () => new Response("busy", { status: 429, headers: { "retry-after": "12" } });
  const response = await worker.fetch(new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "hello" }] })
  }), env);

  assert.equal(response.status, 429);
  assert.equal((await response.json()).error.code, "upstream_rate_limited");
  assert.equal(response.headers.get("x-scansci-error-class"), "upstream_rate_limited");
  assert.equal(response.headers.get("retry-after"), "12");
});
