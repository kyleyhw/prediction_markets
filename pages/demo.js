// The demo page (docs/demo.md): a strategy described to the visitor's own
// model, or built from a form, then backtested in the page on real resolved
// markets. Nothing is stored: the conversation, the key and the results live
// in this tab only, and the visitor downloads what they want to keep.
import { backtest, render, validate } from './engine.js';
import { compileSpec, ModelError } from './llm.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const money = (v) => `${v < 0 ? '−' : ''}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pctText = (v) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`);

// Defaults a visitor can change: models that answer well enough and, for
// Google, a free key in a minute.
const MODELS = { gemini: 'gemini-3.1-flash-lite', anthropic: 'claude-sonnet-5-5' };
const NOTES = {
  gemini: 'Get a free key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>. Google may use what you send on its free tier to improve its products, and allows only its paid tier for people in the European Economic Area, Switzerland and the United Kingdom.',
  anthropic: 'Keys at <a href="https://console.anthropic.com/" target="_blank" rel="noopener">console.anthropic.com</a>; use is billed to your account.',
  ollama: 'Runs on your computer. Start Ollama with OLLAMA_ORIGINS set to this page\'s address so the page may call it.',
  custom: 'Any server that answers like OpenAI\'s chat completions.',
};

// `spec` is the strategy last run; `refining` the conversation's own, which
// a new message changes.
const state = { ctx: null, data: {}, model: null, history: [], transcript: [], spec: null, refining: null, run: null, pending: null };

function say(text, bad = false) {
  const s = $('status');
  s.textContent = text;
  s.classList.toggle('bad', bad);
}

async function json(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function domainData(name) {
  if (!state.data[name]) state.data[name] = await json(`data/${name}.json`);
  return state.data[name];
}

// ------------------------------------------------------------- the model

function setupModel() {
  const providers = state.ctx.providers;
  $('provider').innerHTML = providers.map((p) => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
  $('provider').value = 'gemini';
  const sync = () => {
    const p = providers.find((x) => x.id === $('provider').value);
    const typed = p.kind === 'openai' && p.base_url === null; // only a custom address is typed
    $('url-row').hidden = !typed;
    $('base-url').required = typed;
    $('key-row').hidden = !p.needs_key;
    $('key').required = p.needs_key;
    $('model-name').value = MODELS[p.id] || '';
    $('model-name').placeholder = MODELS[p.id] ? '' : 'the model\'s name, as the provider writes it';
    $('provider-note').innerHTML = NOTES[p.id] || '';
  };
  $('provider').addEventListener('change', sync);
  sync();
  $('model-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const p = providers.find((x) => x.id === $('provider').value);
    state.model = {
      id: p.id, kind: p.kind, model: $('model-name').value.trim(),
      base_url: p.base_url || $('base-url').value.trim(), key: $('key').value.trim(),
    };
    $('model-state').textContent = `: ${p.title}, ${state.model.model}`;
    $('model').open = false;
    say('Model set. Describe your strategy below.');
    $('words').focus();
  });
}

// ------------------------------------------------------- the conversation

function turnHtml(t) {
  if (t.role === 'you') return `<li class="turn you"><h3>You</h3><p>${esc(t.text)}</p></li>`;
  let h = `<li class="turn"><h3>Assistant</h3><p>${esc(t.text)}</p>`;
  if (t.rendering) h += `<ul>${t.rendering.map((l) => `<li>${esc(l)}</li>`).join('')}</ul><div class="row"><button class="btn primary" type="button" data-run="${t.n}">Run it on past markets</button></div>`;
  if (t.choices?.length) h += `<div class="row">${t.choices.map((c) => `<button class="btn" type="button" data-say="${esc(c)}">${esc(c)}</button>`).join('')}</div>`;
  return h + '</li>';
}

function drawTurns() {
  $('turns').innerHTML = state.transcript.map(turnHtml).join('');
}

async function send(words) {
  if (!words.trim() || state.pending) return;
  if (!state.model) {
    $('model').open = true;
    say('First choose your AI model and paste its key, or build a strategy from the form.', true);
    $('provider').focus();
    return;
  }
  state.transcript.push({ role: 'you', text: words });
  drawTurns();
  $('words').value = '';
  const button = $('say').querySelector('button[type=submit]');
  button.disabled = true;
  state.pending = true;
  say('Waiting for your model…');
  try {
    const answer = await compileSpec(words, { model: state.model, ctx: state.ctx, history: state.history, current: state.refining });
    state.history.push({ role: 'user', content: words }, { role: 'assistant', content: answer.message || '' });
    const turn = { role: 'assistant', text: answer.message || (answer.kind === 'spec' ? 'Here is the strategy as it will run:' : ''), choices: answer.choices, n: state.transcript.length };
    if (answer.kind === 'spec') {
      turn.rendering = answer.rendering;
      turn.spec = answer.spec;
    }
    state.transcript.push(turn);
    drawTurns();
    say(answer.kind === 'spec' ? 'The strategy is ready. Check the words, then run it.' : 'Your model replied.');
  } catch (e) {
    state.transcript.pop();
    drawTurns();
    $('words').value = words;
    say(e instanceof ModelError ? e.message : `Something went wrong: ${e.message}`, true);
  } finally {
    button.disabled = false;
    state.pending = null;
    $('words').focus();
  }
}

// ---------------------------------------------------------------- the form

function setupForm() {
  const ctx = state.ctx;
  const domains = Object.keys(ctx.markets).filter((d) => ctx.markets[d] > 0).sort((a, b) => ctx.markets[b] - ctx.markets[a]);
  $('f-domain').innerHTML = domains.map((d) => `<option value="${esc(d)}">${esc(ctx.domains[d].title)} (${ctx.markets[d]} past markets)</option>`).join('');
  $('f-when').innerHTML = ctx.cutoffs.map((h) => `<option value="${h}"${h === 24 ? ' selected' : ''}>${h < 24 ? `${h} hour${h === 1 ? '' : 's'}` : `${h / 24} day${h === 24 ? '' : 's'}`}</option>`).join('');
  const beliefs = async () => {
    const data = await domainData($('f-domain').value);
    const counts = {};
    for (const m of data.markets) for (const name of Object.keys(m.f)) counts[name] = (counts[name] || 0) + 1;
    const names = Object.keys(counts).filter((n) => n in ctx.beliefs).sort((a, b) => counts[b] - counts[a]);
    $('f-belief').innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(ctx.beliefs[n])} (${counts[n]} markets)</option>`).join('')
      || '<option value="">No forecast covers these markets yet</option>';
  };
  const way = () => {
    const edge = document.querySelector('input[name=f-way]:checked').value === 'edge';
    $('f-belief-row').hidden = !edge;
    $('f-edge-row').hidden = !edge;
  };
  $('f-domain').addEventListener('change', () => beliefs().catch(() => {}));
  document.querySelectorAll('input[name=f-way]').forEach((r) => r.addEventListener('change', way));
  way();
  beliefs().catch(() => {});
  $('build').addEventListener('submit', (e) => {
    e.preventDefault();
    const domain = $('f-domain').value;
    const w = document.querySelector('input[name=f-way]:checked').value;
    const stake = Math.min(Math.max(Number($('f-stake').value) || 1, 0.5), 5) / 100;
    const title = ctx.domains[domain].title;
    const spec = {
      version: 1,
      name: w === 'edge' ? `${title}: bet when ${ctx.beliefs[$('f-belief').value] || 'a forecast'} beats the price` : `${title}: back the ${w}`,
      idea: '',
      selector: { domains: [domain], kinds: [], where: [], words: [], exclude_words: [], min_volume_usd: null, min_liquidity_usd: null, max_spread: null },
      belief: { forecaster: w === 'edge' ? $('f-belief').value : 'market', instructions: '', tier: 'standard', samples: 1, sees_price: false },
      rule: { kind: w === 'edge' ? 'edge' : 'follow', min_edge: w === 'edge' ? Math.max(Number($('f-edge').value) || 3, 3) / 100 : 0.03, sides: 'both', follow: w === 'edge' ? null : w, price_min: 0, price_max: 1 },
      sizing: { kelly_fraction: 0.25, max_fraction: w === 'edge' ? stake : 0.05, flat_fraction: w === 'edge' ? 0.01 : Math.min(stake, 0.01), max_stake_usd: null, max_open: null, max_per_event: null, initial_cash: 1000 },
      schedule: { hours_before_close: Number($('f-when').value), cadence_hours: 1 },
    };
    const problems = validate(spec, ctx);
    if (problems.length) { say(problems.join(' '), true); return; }
    run(spec);
  });
}

// ------------------------------------------------------------ the backtest

function chart(bets, start) {
  if (!bets.length) return '';
  const values = [start, ...bets.map((b) => b.bankroll)];
  const w = 640, h = 220, pad = 44;
  const lo = Math.min(...values, start), hi = Math.max(...values, start);
  const span = hi - lo || 1;
  const x = (i) => pad + (i / (values.length - 1 || 1)) * (w - pad - 8);
  const y = (v) => 10 + (1 - (v - lo) / span) * (h - 34);
  const path = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Balance after each bet, from ${money(start)} to ${money(values[values.length - 1])}; the table below has every bet.">
    <line class="grid" x1="${pad}" x2="${w - 8}" y1="${y(hi)}" y2="${y(hi)}"/><line class="grid" x1="${pad}" x2="${w - 8}" y1="${y(lo)}" y2="${y(lo)}"/>
    <line class="base" x1="${pad}" x2="${w - 8}" y1="${y(start)}" y2="${y(start)}"/>
    <text x="4" y="${y(hi) + 4}">${Math.round(hi)}</text><text x="4" y="${y(lo) + 4}">${Math.round(lo)}</text>
    <path class="line" d="${path}"/><text x="${pad}" y="${h - 4}">first bet</text><text x="${w - 8}" y="${h - 4}" text-anchor="end">last bet</text></svg>`;
}

function resultHtml(spec, runs) {
  let h = '';
  for (const r of runs) {
    const title = state.ctx.domains[r.domain].title;
    const asked = spec.schedule.hours_before_close;
    h += `<h3>${esc(title)}</h3>`;
    if (r.cutoff !== asked) h += `<p class="small muted">This demo has prices at ${state.ctx.cutoffs.join(', ')} hours before a market ended, so it ran at ${r.cutoff} hours, the nearest to the ${asked} asked for.</p>`;
    if (!r.scored) { h += `<p>None of the ${r.candidates} past markets it would look at had a price and a forecast at that time, so there is nothing to show. Try other markets or another time.</p>`; continue; }
    const stat = (k, v, cls = '') => `<div class="stat"><span class="k">${k}</span><span class="v num ${cls}">${v}</span></div>`;
    h += `<div class="stats">${stat('Past markets it would look at', r.scored)}${stat('Bets placed', r.bets.length)}
      ${stat('Balance at the end', money(r.final), r.pnl > 0 ? 'pos' : r.pnl < 0 ? 'neg' : '')}${stat('Profit per dollar staked', pctText(r.roi), r.pnl > 0 ? 'pos' : r.pnl < 0 ? 'neg' : '')}
      ${stat('Bets won', r.bets.length ? `${r.wins} of ${r.bets.length}` : '—')}${stat('Worst fall from a high', pctText(r.max_drawdown))}
      ${stat('Fees paid', money(r.fees))}
      ${r.skill === null ? '' : stat('Forecast skill against the market', `${r.skill >= 0 ? '+' : ''}${(r.skill * 100).toFixed(1)}%`, r.skill > 0 ? 'pos' : 'neg')}</div>`;
    if (r.skill !== null) h += `<p class="small muted">Skill compares the forecast's Brier score with the market price's on the same ${r.scored} markets: above zero means it forecast better than the market did; most forecasts score below.</p>`;
    if (r.fees_assumed) h += `<p class="small muted">${r.fees_assumed} of these markets did not state their fee, so the venue's 5% rate was charged, which is the cautious choice.</p>`;
    h += chart(r.bets, spec.sizing.initial_cash);
    if (r.bets.length) {
      const rows = r.bets.slice(-200).reverse().map((b) => `<tr><td>${esc(b.settled.slice(0, 10))}</td><td>${esc(b.market.q)}</td><td>${b.side === 'yes' ? 'For' : 'Against'}</td>
        <td class="num">${(b.price * 100).toFixed(1)}¢</td><td class="num">${money(b.stake)}</td><td class="num ${b.pnl > 0 ? 'pos' : 'neg'}">${money(b.pnl)}</td></tr>`).join('');
      h += `<div class="table-wrap"><table><caption>Bets, newest first${r.bets.length > 200 ? ' (the last 200)' : ''}</caption>
        <thead><tr><th scope="col">Ended</th><th scope="col">Market</th><th scope="col">Bet</th><th scope="col" class="num">Price paid</th><th scope="col" class="num">Stake</th><th scope="col" class="num">Result</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    }
  }
  return h;
}

async function run(spec) {
  state.spec = spec;
  say('Running it on past markets…');
  try {
    const runs = [];
    for (const d of spec.selector.domains) {
      if (!state.ctx.markets[d]) continue;
      runs.push(backtest(spec, await domainData(d), state.ctx));
    }
    state.run = runs;
    $('words-out').innerHTML = `<p><strong>${esc(spec.name)}</strong></p>${render(spec, state.ctx).map((l) => `<p>${esc(l)}</p>`).join('')}`;
    $('numbers').innerHTML = runs.length ? resultHtml(spec, runs) : '<p>This demo has no past markets for these domains yet.</p>';
    $('result').hidden = false;
    $('result-h').focus();
    const bets = runs.reduce((s, r) => s + r.bets.length, 0);
    say(`Done: ${bets} bet${bets === 1 ? '' : 's'} on past markets.`);
  } catch (e) {
    say(`The backtest could not run: ${e.message}`, true);
  }
}

// --------------------------------------------------------------- downloads

function download(name, type, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}

const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50) || 'strategy';

function markdown() {
  const spec = state.spec;
  const lines = [`# ${spec.name}`, '', `Made in the vibe-predict demo on ${new Date().toISOString().slice(0, 10)}.`, ''];
  const talk = state.transcript;
  if (talk.length) {
    lines.push('## Conversation', '');
    if (state.model) lines.push(`Model: ${state.model.id}, ${state.model.model}.`, '');
    for (const t of talk) {
      lines.push(`**${t.role === 'you' ? 'You' : 'Assistant'}:** ${t.text}`, '');
      if (t.rendering) lines.push(...t.rendering.map((l) => `- ${l}`), '');
    }
  }
  lines.push('## The strategy', '', ...render(spec, state.ctx).map((l) => `- ${l}`), '', '```json', JSON.stringify(spec, null, 1), '```', '');
  for (const r of state.run || []) {
    lines.push(`## Backtest: ${state.ctx.domains[r.domain].title}`, '',
      `Data built ${state.ctx.built}; prices ${r.cutoff} hours before each market ended.`, '',
      '| Measure | Value |', '| :--- | ---: |',
      `| Past markets scored | ${r.scored} |`, `| Bets | ${r.bets.length} |`, `| Balance at the end | ${money(r.final)} |`,
      `| Profit per dollar staked | ${pctText(r.roi)} |`, `| Worst fall from a high | ${pctText(r.max_drawdown)} |`, `| Fees paid | ${money(r.fees)} |`,
      `| Forecast skill against the market | ${r.skill === null ? '—' : `${(r.skill * 100).toFixed(1)}%`} |`, '');
  }
  lines.push('Run it on your own copy: `uv run vp strategy backtest strategy.json`. See docs/tutorials/your_own_strategy.md.', '');
  return lines.join('\n');
}

// ------------------------------------------------------------------- start

async function start() {
  try {
    state.ctx = await json('data/demo.json');
  } catch {
    say('The demo\'s data could not be loaded. Try again in a minute.', true);
    return;
  }
  $('built').textContent = `Market data updated ${new Date(state.ctx.built).toLocaleString()}.`;
  setupModel();
  setupForm();
  $('say').addEventListener('submit', (e) => { e.preventDefault(); send($('words').value); });
  $('words').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send($('words').value); } });
  $('turns').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.say) send(b.dataset.say);
    if (b.dataset.run) { state.refining = state.transcript[Number(b.dataset.run)].spec; run(state.refining); }
  });
  $('new-chat').addEventListener('click', () => {
    state.history = []; state.transcript = []; state.refining = null; drawTurns();
    say('Started again. Your model and key are kept until you close the tab.');
    $('words').focus();
  });
  $('dl-spec').addEventListener('click', () => download(`${slug(state.spec.name)}.json`, 'application/json', JSON.stringify(state.spec, null, 1) + '\n'));
  $('dl-talk').addEventListener('click', () => download(`${slug(state.spec.name)}.md`, 'text/markdown', markdown()));
}

start();
