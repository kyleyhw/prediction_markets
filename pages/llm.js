// The visitor's own model, called from the page (docs/demo.md).
//
// The demo has no server, so the key a visitor types goes from this page
// straight to the provider they chose and nowhere else; it is held in memory
// and gone when the tab closes. The question asked is the platform's own
// compiler prompt and answer schema (vp/strategy/compiler.py), exported by
// `vp demo`; the answer is checked by engine.js as the platform checks it.
import { conform, render, validate } from './engine.js';

export class ModelError extends Error {
  constructor(message, code) { super(message); this.code = code; }
}

async function post(url, headers, body) {
  let res;
  try {
    res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) });
  } catch {
    throw new ModelError('The page could not reach the provider. Check the address and your connection; a model on your own computer must allow this page\'s address (for Ollama, set OLLAMA_ORIGINS).', 'network');
  }
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch { /* not JSON */ }
  if (!res.ok) {
    const detail = (data?.error?.message || data?.error || text || '').toString().slice(0, 300);
    if (res.status === 401 || res.status === 403) throw new ModelError(`The provider refused the key (${res.status}). ${detail}`, 'key');
    if (res.status === 429) throw new ModelError(`The provider says the limit for this key is used up for now (429). Wait and try again, or use another key. ${detail}`, 'limit');
    if (/location|region|country/i.test(detail)) throw new ModelError(`The provider does not serve your region: ${detail} Pick another provider, or run your own copy with any model.`, 'region');
    throw new ModelError(`The provider answered ${res.status}: ${detail}`, res.status === 400 ? 'request' : 'server');
  }
  return data;
}

// One call: the system prompt, the turns so far, and the answer's schema.
// Returns the answer's text (JSON).
async function ask(model, system, messages, schema) {
  if (model.kind === 'gemini') {
    const data = await post(
      `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model.model)}:generateContent`,
      { 'x-goog-api-key': model.key },
      {
        systemInstruction: { parts: [{ text: system }] },
        contents: messages.map((m) => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] })),
        generationConfig: { responseMimeType: 'application/json', responseJsonSchema: schema, maxOutputTokens: 8000 },
      },
    );
    const c = data?.candidates?.[0];
    if (!c?.content?.parts) throw new ModelError(`The model gave no answer (${c?.finishReason || data?.promptFeedback?.blockReason || 'empty'}).`, 'empty');
    return c.content.parts.filter((p) => !p.thought && p.text).map((p) => p.text).join('');
  }
  if (model.kind === 'anthropic') {
    const data = await post(
      'https://api.anthropic.com/v1/messages',
      { 'x-api-key': model.key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
      { model: model.model, max_tokens: 8000, system, messages, output_config: { format: { type: 'json_schema', schema } } },
    );
    if (data.stop_reason === 'refusal') throw new ModelError('The model declined to translate this request.', 'refusal');
    return (data.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('');
  }
  // OpenAI-compatible: a schema-checked answer where the server takes one,
  // otherwise JSON with the schema in the prompt (as vp/llm/openai_compat.py).
  const url = `${model.base_url.replace(/\/$/, '')}/chat/completions`;
  const headers = model.key ? { authorization: `Bearer ${model.key}` } : {};
  const turns = (sys) => [{ role: 'system', content: sys }, ...messages];
  const read = (data) => data?.choices?.[0]?.message?.content || '';
  if (model.jsonMode !== 'object') {
    try {
      return read(await post(url, headers, { model: model.model, messages: turns(system), response_format: { type: 'json_schema', json_schema: { name: 'answer', schema, strict: true } } }));
    } catch (e) {
      if (!(e instanceof ModelError) || !['request', 'server'].includes(e.code)) throw e;
      model.jsonMode = 'object'; // remembered for this tab
    }
  }
  const withSchema = `${system}\n\nAnswer with one JSON object that follows this JSON schema exactly:\n${JSON.stringify(schema)}`;
  return read(await post(url, headers, { model: model.model, messages: turns(withSchema), response_format: { type: 'json_object' } }));
}

// The compiler's loop (vp/strategy/compiler.py: compile_spec): one answer,
// checked; if the engine refuses the spec, the model is told why once.
export async function compileSpec(words, { model, ctx, history, current }) {
  let system = ctx.system;
  if (current) system += `\nThe person is refining this confirmed spec. Answer with the whole new spec, changing only what they ask for:\n${JSON.stringify(current)}`;
  const messages = [...history, { role: 'user', content: words }];
  let problems = [];
  let garbled = false;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const text = await ask(model, system, messages, ctx.schema);
    let answer = null;
    try {
      answer = JSON.parse(text.replace(/^```(?:json)?\s*|\s*```$/g, ''));
    } catch {
      answer = null;
    }
    if (answer === null || typeof answer !== 'object' || !['spec', 'question', 'refusal'].includes(answer.answer)) {
      garbled = true;
      problems = ['the answer was not the JSON asked for'];
    } else if (answer.answer !== 'spec') {
      return { kind: answer.answer, message: String(answer.message || ''), choices: Array.isArray(answer.choices) ? answer.choices : [] };
    } else {
      garbled = false;
      if (answer.spec && typeof answer.spec === 'object') {
        const [spec, errors] = conform({ ...answer.spec, idea: current ? current.idea : (history.find((m) => m.role === 'user')?.content ?? words) }, ctx.spec_schema);
        if (errors.length) { garbled = true; problems = errors; } else {
          problems = validate(spec, ctx);
          if (!problems.length) return { kind: 'spec', message: String(answer.message || ''), spec, rendering: render(spec, ctx) };
        }
      } else problems = ['the answer was a spec but carried none'];
    }
    if (attempt === 0) {
      messages.push({ role: 'assistant', content: text });
      messages.push({ role: 'user', content: `The engine refused that spec:\n- ${problems.join('\n- ')}\nFix it if the person's words allow; otherwise ask them.` });
    }
  }
  return {
    kind: 'question',
    message: garbled
      ? 'I could not turn that into something that runs. Could you say it another way: which markets to look at, which side to back, and the most you would pay for a share?'
      : `This can't run as described: ${problems.join(' ')} What would you like to change?`,
    choices: [],
    problems,
  };
}
