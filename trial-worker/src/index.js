/**
 * screen-coach trial proxy — lets the app work out of the box with no API key.
 *
 * The app (anthropic SDK with base_url pointed here) POSTs /v1/messages with an
 * x-trial-device UUID header. This worker forwards to the Anthropic API with the
 * owner's key (a Workers secret), within three limits:
 *   - per-device daily request count
 *   - per-IP daily request count
 *   - a global daily spend cap in USD, estimated from response usage at list prices
 * Counters live in KV with a 2-day TTL. KV is eventually consistent, so parallel
 * abuse can overshoot a little — the caps bound the order of magnitude, which is
 * all a free trial needs.
 */

// USD per million tokens, matched by model-id prefix. Sonnet 5 uses the
// post-introductory list price so the budget never undercounts.
const PRICES = [
  { prefix: "claude-sonnet-5", input: 3.0, output: 15.0 },
  { prefix: "claude-haiku-4-5", input: 1.0, output: 5.0 },
];

const LIMITS = {
  perDeviceDaily: 20, // analyses per device per day
  perIpDaily: 40, // an IP can host a couple of devices (NAT), not a farm
  globalDailyUsd: 1.0, // hard stop for the owner's wallet
};

const MAX_TOKENS_CAP = 4096; // config.MAX_TOKENS in the app; nothing needs more
const MAX_BODY_BYTES = 8 * 1024 * 1024; // screenshot payloads are ~1-3MB
const COUNTER_TTL_S = 2 * 24 * 3600;

const QUOTA_MSG =
  "今日体验额度已用完。想继续使用：菜单 → Set API Key… 填入你自己的 Anthropic API key（走官方直连，不再经过体验服务器）。";

function err(status, type, message) {
  return Response.json({ type: "error", error: { type, message } }, { status });
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Aggregate spend readout for the owner; no secrets, no per-user data.
    if (request.method === "GET" && url.pathname === "/") {
      const date = today();
      const spent = parseFloat((await env.TRIAL_KV.get(`spend:${date}`)) || "0");
      return Response.json({
        service: "screen-coach-trial",
        date,
        spent_usd: Math.round(spent * 10000) / 10000,
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
    const contentLength = parseInt(request.headers.get("content-length") || "0", 10);
    if (contentLength > MAX_BODY_BYTES) {
      return err(413, "request_too_large", "request body too large for the trial service");
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const date = today();
    const deviceKey = `d:${device}:${date}`;
    const ipKey = `i:${ip}:${date}`;
    const spendKey = `spend:${date}`;

    const [deviceCount, ipCount, spentRaw] = await Promise.all([
      env.TRIAL_KV.get(deviceKey),
      env.TRIAL_KV.get(ipKey),
      env.TRIAL_KV.get(spendKey),
    ]);
    if (parseFloat(spentRaw || "0") >= LIMITS.globalDailyUsd) {
      return err(429, "rate_limit_error", QUOTA_MSG);
    }
    if (
      parseInt(deviceCount || "0", 10) >= LIMITS.perDeviceDaily ||
      parseInt(ipCount || "0", 10) >= LIMITS.perIpDaily
    ) {
      return err(429, "rate_limit_error", QUOTA_MSG);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return err(400, "invalid_request_error", "body must be JSON");
    }
    if (typeof body.model !== "string" || !PRICES.some((p) => body.model.startsWith(p.prefix))) {
      return err(400, "invalid_request_error", "model not available on the trial service");
    }
    if (body.stream) {
      return err(400, "invalid_request_error", "streaming is not available on the trial service");
    }
    body.max_tokens = Math.min(body.max_tokens ?? MAX_TOKENS_CAP, MAX_TOKENS_CAP);

    const upstream = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": request.headers.get("anthropic-version") || "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify(body),
    });
    // Bounded by max_tokens cap, so buffering the JSON is fine here.
    const data = await upstream.json();

    if (upstream.ok && data.usage) {
      ctx.waitUntil(
        recordUsage(env, { deviceKey, ipKey, spendKey, model: body.model, usage: data.usage }),
      );
    }
    return Response.json(data, { status: upstream.status });
  },
};

async function recordUsage(env, { deviceKey, ipKey, spendKey, model, usage }) {
  const price = PRICES.find((p) => model.startsWith(p.prefix));
  const cost =
    ((usage.input_tokens || 0) * price.input + (usage.output_tokens || 0) * price.output) / 1e6;
  const [deviceCount, ipCount, spentRaw] = await Promise.all([
    env.TRIAL_KV.get(deviceKey),
    env.TRIAL_KV.get(ipKey),
    env.TRIAL_KV.get(spendKey),
  ]);
  await Promise.all([
    env.TRIAL_KV.put(deviceKey, String(parseInt(deviceCount || "0", 10) + 1), {
      expirationTtl: COUNTER_TTL_S,
    }),
    env.TRIAL_KV.put(ipKey, String(parseInt(ipCount || "0", 10) + 1), {
      expirationTtl: COUNTER_TTL_S,
    }),
    env.TRIAL_KV.put(spendKey, String(parseFloat(spentRaw || "0") + cost), {
      expirationTtl: COUNTER_TTL_S,
    }),
  ]);
}
