import test from "node:test";
import assert from "node:assert/strict";
import gateway from "../src/index.mjs";

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("health reports configuration state without exposing the origin", async () => {
  const response = await gateway.fetch(
    new Request("https://gateway.example/__gateway/health"),
    { ZYRQUEN_API_ORIGIN: "https://api.example" },
  );
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.service, "zyrquen-api-gateway");
  assert.equal(body.upstream_configured, true);
  assert.equal(JSON.stringify(body).includes("api.example"), false);
});

test("fails closed when the API origin is missing", async () => {
  const response = await gateway.fetch(
    new Request("https://gateway.example/v1/status"),
    {},
  );

  assert.equal(response.status, 503);
  assert.equal((await response.json()).error, "gateway_not_configured");
});

test("rejects non-HTTPS upstream origins", async () => {
  const response = await gateway.fetch(
    new Request("https://gateway.example/v1/status"),
    { ZYRQUEN_API_ORIGIN: "http://api.example" },
  );

  assert.equal(response.status, 503);
});

test("rejects unsupported methods before contacting the upstream", async () => {
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    throw new Error("must not be called");
  };

  const response = await gateway.fetch(
    new Request("https://gateway.example/v1/status", { method: "TRACE" }),
    { ZYRQUEN_API_ORIGIN: "https://api.example" },
  );

  assert.equal(response.status, 405);
  assert.equal(called, false);
});

test("forwards API requests to the fixed HTTPS origin and preserves authorization", async () => {
  let capturedRequest;
  globalThis.fetch = async (request, options) => {
    capturedRequest = { request, options };
    return new Response(JSON.stringify({ ok: true }), {
      status: 202,
      headers: { "content-type": "application/json" },
    });
  };

  const response = await gateway.fetch(
    new Request("https://gateway.example/v1/inference?mode=test", {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
        "x-correlation-id": "request-123",
      },
      body: JSON.stringify({ input: "hello" }),
    }),
    { ZYRQUEN_API_ORIGIN: "https://api.example" },
  );

  assert.equal(capturedRequest.request.url, "https://api.example/v1/inference?mode=test");
  assert.equal(capturedRequest.request.method, "POST");
  assert.equal(capturedRequest.request.headers.get("authorization"), "Bearer test-token");
  assert.equal(capturedRequest.request.headers.get("x-correlation-id"), "request-123");
  assert.equal(capturedRequest.options.redirect, "manual");
  assert.equal(response.status, 202);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("x-correlation-id"), "request-123");
});

test("returns a generic 502 when the upstream is unavailable", async () => {
  globalThis.fetch = async () => {
    throw new Error("private upstream detail");
  };

  const response = await gateway.fetch(
    new Request("https://gateway.example/v1/status"),
    { ZYRQUEN_API_ORIGIN: "https://api.example" },
  );

  assert.equal(response.status, 502);
  const body = await response.text();
  assert.equal(body.includes("private upstream detail"), false);
  assert.match(body, /upstream_unavailable/);
});
