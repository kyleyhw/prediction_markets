// The demo's free AI (docs/demo.md). The page sends the conversation; this
// adds the platform's own strategy-compiler instructions and answer schema,
// read from the published demo, and asks Gemini on the owner's free-tier key.
// It answers nothing else, so the key cannot be used as a general chatbot:
// every answer is forced into the strategy schema. The owner pays nothing:
// on the free tier Google stops at its daily quota instead of billing.
import { FREE_TIER, PAID_ONLY } from './countries.js';

const LIMITS = { messages: 16, chars: 4000, total: 24000, current: 8000 };
let cached = null; // { at, ctx }

const json = (status, body, origin) => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json', ...cors(origin) },
});

function cors(origin) {
  return origin ? { 'access-control-allow-origin': origin, 'access-control-allow-methods': 'POST, OPTIONS', 'access-control-allow-headers': 'content-type', 'access-control-max-age': '86400', vary: 'origin' } : {};
}

// The page that may call: the demo's own site, plus any listed in ORIGINS.
function allowed(request, env) {
  const origin = request.headers.get('origin') || '';
  const own = new URL(env.SITE).origin;
  const extra = (env.ORIGINS || '').split(',').map((s) => s.trim()).filter(Boolean);
  return origin === own || extra.includes(origin) ? origin : null;
}

async function context(env, fetcher) {
  if (cached && Date.now() - cached.at < 3600_000) return cached.ctx;
  const res = await fetcher(`${env.SITE}/data/demo.json`);
  if (!res.ok) throw new Error(`demo.json: ${res.status}`);
  const ctx = await res.json();
  cached = { at: Date.now(), ctx };
  return ctx;
}

export function region(country) {
  if (!country || FREE_TIER.has(country)) return null;
  return PAID_ONLY.has(country)
    ? "Google's terms do not allow its free AI service to be used for people in the European Economic Area, Switzerland or the United Kingdom."
    : 'Google does not offer its free AI service where you are.';
}

function checked(body) {
  const { messages, current } = body || {};
  if (!Array.isArray(messages) || !messages.length || messages.length > LIMITS.messages) return null;
  let total = 0;
  for (const m of messages) {
    if (!m || !['user', 'assistant'].includes(m.role) || typeof m.content !== 'string' || m.content.length > LIMITS.chars) return null;
    total += m.content.length;
  }
  if (total > LIMITS.total || messages[messages.length - 1].role !== 'user') return null;
  const refining = current == null ? '' : JSON.stringify(current);
  if (refining.length > LIMITS.current) return null;
  return { messages, refining };
}

export default {
  async fetch(request, env, _ctx, fetcher = fetch) {
    const origin = allowed(request, env);
    if (request.method === 'OPTIONS') return new Response(null, { status: origin ? 204 : 403, headers: cors(origin) });
    const url = new URL(request.url);
    if (request.method !== 'POST' || url.pathname !== '/compile') return json(404, { code: 'not_found', message: 'Not here.' }, origin);
    if (!origin) return json(403, { code: 'origin', message: 'This AI answers only the demo page.' }, null);
    const why = region(request.cf?.country);
    if (why) return json(451, { code: 'region_blocked', message: why }, origin);
    const ip = request.headers.get('cf-connecting-ip') || 'unknown';
    if (env.PER_IP && !(await env.PER_IP.limit({ key: ip })).success) {
      return json(429, { code: 'slow_down', message: 'That is a lot of messages at once; wait a minute and send again.' }, origin);
    }
    let body;
    try { body = checked(await request.json()); } catch { body = null; }
    if (!body) return json(400, { code: 'bad_request', message: 'The conversation is too long or not in the expected form. Start again.' }, origin);
    const ctx = await context(env, fetcher);
    let system = ctx.system;
    if (body.refining) system += `\nThe person is refining this confirmed spec. Answer with the whole new spec, changing only what they ask for:\n${body.refining}`;
    const res = await fetcher(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(env.MODEL)}:generateContent`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-goog-api-key': env.GEMINI_API_KEY },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents: body.messages.map((m) => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] })),
        generationConfig: { responseMimeType: 'application/json', responseJsonSchema: ctx.schema, maxOutputTokens: 8000 },
      }),
    });
    if (res.status === 429) return json(503, { code: 'used_up', message: 'The free AI has answered all it can for now; try again later, or use your own key.' }, origin);
    if (!res.ok) return json(502, { code: 'upstream', message: `The AI service answered ${res.status}; try again in a minute.` }, origin);
    const data = await res.json();
    const parts = data?.candidates?.[0]?.content?.parts || [];
    const text = parts.filter((p) => !p.thought && p.text).map((p) => p.text).join('');
    if (!text) return json(502, { code: 'empty', message: 'The AI gave no answer; say it another way.' }, origin);
    return json(200, { text }, origin);
  },
};
