/**
 * screen-coach trial proxy — lets the app work out of the box with no API key.
 *
 * The app (anthropic SDK with base_url pointed here) POSTs /v1/messages with an
 * x-trial-device UUID header. This worker forwards to the Anthropic API with the
 * owner's key (a Workers secret), within three limits:
 *   - per-device daily request count
 *   - per-IP daily request count
 *   - a global daily spend cap in USD, estimated from response usage at list prices
 *
 * Concurrency model: limits are enforced by a SYNCHRONOUS check-and-reserve
 * against per-isolate in-memory state (`pending`, below), layered on KV as the
 * durable floor. A burst of concurrent requests inside one isolate serializes
 * on the synchronous reservation, so it cannot blow past the caps the way a
 * naive read-KV → call-upstream → write-KV flow does (that exact bypass was
 * reproduced in review: 30 concurrent requests, $2 spent against a $1 cap).
 * Residual exposure — KV write races across isolates/colos (ms-to-60s windows)
 * — can overshoot by a bounded amount; a $1/day trial tier accepts that, and
 * the deployer's real backstop should be a spend-limited API key.
 */

// USD per million tokens, matched by model-id prefix. Sonnet 5 uses the
// post-introductory list price so the budget never undercounts. cache_write is
// priced at the worst-case 2x premium (1h TTL) even though the proxy rejects
// cache_control bodies — belt and suspenders for the accounting.
const PRICES = [
  { prefix: "claude-sonnet-5", input: 3.0, output: 15.0 },
  { prefix: "claude-haiku-4-5", input: 1.0, output: 5.0 },
];

const LIMITS = {
  perDeviceDaily: 20, // analyses per device per day
  perIpDaily: 40, // an IP can host a couple of devices (NAT), not a farm
  globalDailyUsd: 1.0, // hard stop for the owner's wallet
};

// Pessimistic per-request cost reserved while a request is in flight, released
// against the actual figure when the response lands. A full analysis measures
// ~$0.01-0.015; anything reserving above this while under the cap is fine.
const RESERVE_USD = 0.02;

const MAX_TOKENS_CAP = 4096; // config.MAX_TOKENS in the app; nothing needs more
const MAX_BODY_BYTES = 8 * 1024 * 1024; // screenshot payloads are ~1-3MB
const COUNTER_TTL_S = 2 * 24 * 3600;

const QUOTA_MSG =
  "今日体验额度已用完。想继续使用：菜单 → Set API Key… 填入你自己的 Anthropic API key（走官方直连，不再经过体验服务器）。";

// Per-isolate in-flight reservations. NOT request state — a shared limiter,
// deliberately module-level so concurrent requests in this isolate see each
// other before any KV write lands. Keyed by day; reset when the day rolls.
const pending = { date: "", spend: 0, devices: new Map(), ips: new Map() };

function rollPending(date) {
  if (pending.date !== date) {
    pending.date = date;
    pending.spend = 0;
    pending.devices.clear();
    pending.ips.clear();
  }
}

function err(status, type, message) {
  return Response.json(
    { type: "error", error: { type, message } },
    // The anthropic SDK auto-retries 429/5xx unless told not to; a quota
    // rejection is final for the day, so save the user the backoff delay.
    { status, headers: { "x-should-retry": "false" } },
  );
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function requestCost(model, usage) {
  const price = PRICES.find((p) => model.startsWith(p.prefix));
  if (!price || !usage) return RESERVE_USD; // unknown shape: bill the reserve
  const cacheWrite = usage.cache_creation_input_tokens || 0;
  const cacheRead = usage.cache_read_input_tokens || 0;
  return (
    ((usage.input_tokens || 0) * price.input +
      (usage.output_tokens || 0) * price.output +
      cacheWrite * price.input * 2.0 + // worst-case cache-write premium
      cacheRead * price.input * 0.1) /
    1e6
  );
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Aggregate spend readout for the owner; no secrets, no per-user data.
    // Browsers get a small human-readable page (raw JSON reads as "broken"
    // to a person); curl/scripts keep getting JSON.
    if (request.method === "GET" && url.pathname === "/") {
      const date = today();
      const spent = parseFloat((await env.TRIAL_KV.get(`spend:${date}`)) || "0");
      const spentUsd = Math.round(spent * 10000) / 10000;
      if ((request.headers.get("accept") || "").includes("text/html")) {
        const pct = Math.min(100, Math.round((spentUsd / LIMITS.globalDailyUsd) * 100));
        return new Response(
          `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>screen-coach 体验服务</title>
<body style="font-family:system-ui;max-width:34em;margin:8vh auto;padding:0 1em;line-height:1.7">
<h1 style="font-size:1.3em">📖 screen-coach 体验服务</h1>
<p>状态：<b style="color:#2a7">运行中</b>（这个地址是给 app 用的接口，不是网页应用）。</p>
<p>今日（${date}，UTC）已用额度：<b>$${spentUsd}</b> / $${LIMITS.globalDailyUsd}</p>
<div style="background:#eee;border-radius:6px;height:10px"><div style="background:#2a7;border-radius:6px;height:10px;width:${pct}%"></div></div>
<p style="color:#777;font-size:0.9em">下载 app：<a href="https://github.com/Defiabell/screen-coach">github.com/Defiabell/screen-coach</a></p>
</body>`,
          { headers: { "content-type": "text/html; charset=utf-8" } },
        );
      }
      return Response.json({
        service: "screen-coach-trial",
        date,
        spent_usd: spentUsd,
        budget_usd: LIMITS.globalDailyUsd,
      });
    }

    if (request.method !== "POST" || url.pathname !== "/v1/messages") {
      return err(404, "not_found_error", "only POST /v1/messages is proxied");
    }

    const device = request.headers.get("x-trial-device") || "";
    if (!/^[0-9a-fA-F-]{36}$/.test(device)) {
      return err(400, "invalid_request_error", "missing or malformed x-trial-device header");
    }

    // Measure actual bytes — content-length is client-asserted and omittable.
    const rawBody = await request.arrayBuffer();
    if (rawBody.byteLength > MAX_BODY_BYTES) {
      return err(413, "request_too_large", "request body too large for the trial service");
    }
    let body;
    try {
      body = JSON.parse(new TextDecoder().decode(rawBody));
    } catch {
      return err(400, "invalid_request_error", "body must be JSON");
    }
    if (typeof body.model !== "string" || !PRICES.some((p) => body.model.startsWith(p.prefix))) {
      return err(400, "invalid_request_error", "model not available on the trial service");
    }
    if (body.stream) {
      return err(400, "invalid_request_error", "streaming is not available on the trial service");
    }
    // The app never uses prompt caching; a hand-crafted caching request would
    // bill at premium rates the accounting shouldn't have to model.
    if (JSON.stringify(body).includes('"cache_control"')) {
      return err(400, "invalid_request_error", "cache_control is not available on the trial service");
    }
    body.max_tokens = Math.min(body.max_tokens ?? MAX_TOKENS_CAP, MAX_TOKENS_CAP);

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const date = today();
    const deviceKey = `d:${device}:${date}`;
    const ipKey = `i:${ip}:${date}`;
    const spendKey = `spend:${date}`;

    const [kvDevice, kvIp, kvSpend] = await Promise.all([
      env.TRIAL_KV.get(deviceKey),
      env.TRIAL_KV.get(ipKey),
      env.TRIAL_KV.get(spendKey),
    ]);

    // Check-and-reserve. Everything from here to the `pending` mutations is
    // synchronous — no await — so concurrent requests in this isolate observe
    // each other's reservations regardless of interleaving.
    rollPending(date);
    const effDevice = parseInt(kvDevice || "0", 10) + (pending.devices.get(device) || 0);
    const effIp = parseInt(kvIp || "0", 10) + (pending.ips.get(ip) || 0);
    const effSpend = parseFloat(kvSpend || "0") + pending.spend;
    if (
      effSpend + RESERVE_USD > LIMITS.globalDailyUsd ||
      effDevice >= LIMITS.perDeviceDaily ||
      effIp >= LIMITS.perIpDaily
    ) {
      return err(429, "rate_limit_error", QUOTA_MSG);
    }
    pending.devices.set(device, (pending.devices.get(device) || 0) + 1);
    pending.ips.set(ip, (pending.ips.get(ip) || 0) + 1);
    pending.spend += RESERVE_USD;

    let upstream, data;
    try {
      upstream = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": env.ANTHROPIC_API_KEY,
          "anthropic-version": request.headers.get("anthropic-version") || "2023-06-01",
          "content-type": "application/json",
        },
        body: JSON.stringify(body),
      });
      // Bounded by max_tokens cap, so buffering the JSON is fine here.
      data = await upstream.json();
    } catch (e) {
      // Upstream unreachable/garbled: release the reservation, charge nothing.
      pending.devices.set(device, (pending.devices.get(device) || 0) - 1);
      pending.ips.set(ip, (pending.ips.get(ip) || 0) - 1);
      pending.spend -= RESERVE_USD;
      console.log(JSON.stringify({ event: "upstream_error", message: String(e) }));
      return err(502, "api_error", "upstream request failed; try again");
    }

    const cost = upstream.ok ? requestCost(body.model, data.usage) : 0;
    ctx.waitUntil(settle(env, { date, deviceKey, ipKey, spendKey, device, ip, cost }));
    console.log(
      JSON.stringify({ event: "proxied", status: upstream.status, model: body.model, cost }),
    );
    return Response.json(data, { status: upstream.status });
  },
};

/** Persist the outcome to KV and release the in-memory reservation.

Request COUNTS persist regardless of upstream outcome — otherwise a request
shaped to 400 upstream would never consume quota and could spam the owner's
key for free. SPEND persists only for successful calls (cost is 0 otherwise).
Fresh read-modify-write per key: a small cross-isolate race window remains,
but the in-memory reservation covers the in-flight window that actually
mattered (seconds of upstream latency). */
async function settle(env, { date, deviceKey, ipKey, spendKey, device, ip, cost }) {
  try {
    const [kvDevice, kvIp, kvSpend] = await Promise.all([
      env.TRIAL_KV.get(deviceKey),
      env.TRIAL_KV.get(ipKey),
      env.TRIAL_KV.get(spendKey),
    ]);
    await Promise.all([
      env.TRIAL_KV.put(deviceKey, String(parseInt(kvDevice || "0", 10) + 1), {
        expirationTtl: COUNTER_TTL_S,
      }),
      env.TRIAL_KV.put(ipKey, String(parseInt(kvIp || "0", 10) + 1), {
        expirationTtl: COUNTER_TTL_S,
      }),
      env.TRIAL_KV.put(spendKey, String(parseFloat(kvSpend || "0") + cost), {
        expirationTtl: COUNTER_TTL_S,
      }),
    ]);
  } finally {
    // Release the reservation only after KV reflects the outcome (or the day
    // rolled, in which case rollPending already wiped it).
    if (pending.date === date) {
      pending.devices.set(device, Math.max(0, (pending.devices.get(device) || 0) - 1));
      pending.ips.set(ip, Math.max(0, (pending.ips.get(ip) || 0) - 1));
      pending.spend = Math.max(0, pending.spend - RESERVE_USD);
    }
  }
}
