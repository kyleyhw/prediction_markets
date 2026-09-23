// Shared pieces of every view: the reading level, glossary terms and their
// popover, tables, empty states, and the hooks a view registers to wire up
// its controls once its HTML is in the document.
import { session } from './api.js';
import { entry, esc, fmt, raw, t, tp } from './i18n.js';
import { prefs } from './prefs.js';

export { esc, fmt, raw, t, tp };

export const detailed = () => prefs().level === 'detailed';
// Pick the rendering for the current reading level.
export const level = (simple, full) => (detailed() ? full : simple);

let hooks = [];
export const after = (fn) => hooks.push(fn);
export function runHooks() { const run = hooks; hooks = []; for (const fn of run) fn(); }

// ---------- glossary ----------
// In Detailed mode a term is a dotted button that opens its definition; in
// Simple mode the words stand alone, because the sentence around them
// already says what they mean.
export function term(key, label) {
  const g = entry('glossary.' + key);
  const text = esc(label ?? (g ? g.name : key));
  if (!g || !detailed()) return text;
  return `<button type="button" class="term" data-term="${esc(key)}" aria-haspopup="dialog" aria-expanded="false" aria-controls="pop">${text}</button>`;
}

const pop = () => document.getElementById('pop');
let opener = null;
function closePop(restore) {
  const p = pop();
  if (p.hidden) return;
  p.hidden = true;
  if (opener) { opener.setAttribute('aria-expanded', 'false'); if (restore) opener.focus(); }
  opener = null;
}
function openPop(button) {
  const g = entry('glossary.' + button.dataset.term);
  if (!g) return;
  const p = pop();
  closePop(false);
  p.innerHTML = `<b id="pop-title">${esc(g.name)}</b>${esc(g.text)}${g.doc ? `<span class="doc">${t('glossary_doc', { doc: g.doc })}</span>` : ''}`;
  p.hidden = false;
  const r = button.getBoundingClientRect();
  let x = r.left, y = r.bottom + 8;
  if (x + p.offsetWidth > innerWidth - 12) x = Math.max(12, innerWidth - p.offsetWidth - 12);
  if (y + p.offsetHeight > innerHeight - 12) y = Math.max(12, r.top - p.offsetHeight - 8);
  p.style.left = x + 'px'; p.style.top = y + 'px';
  button.setAttribute('aria-expanded', 'true');
  opener = button;
}
export function installGlossary() {
  document.addEventListener('click', (e) => {
    const b = e.target.closest('.term');
    if (b) { e.stopPropagation(); if (opener === b) closePop(true); else openPop(b); return; }
    if (!e.target.closest('#pop')) closePop(false);
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePop(true); });
  addEventListener('hashchange', () => closePop(false));
}

// ---------- building blocks ----------
export const head = (title, lede) => `<h1 id="page-title" tabindex="-1">${title}</h1>${lede ? `<p class="lede">${lede}</p>` : ''}`;

export function table(columns, rows, { caption = '', numFrom = 1 } = {}) {
  const cls = (i) => (i >= numFrom ? ' class="num"' : '');
  return `<div class="wrap"><table>${caption ? `<caption>${caption}</caption>` : ''}<thead><tr>${
    columns.map((c, i) => `<th scope="col"${cls(i)}>${c}</th>`).join('')}</tr></thead><tbody>${
    rows.map((r) => `<tr>${r.map((c, i) => `<td${cls(i)}>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

// Nothing dead-ends: an empty state says what fills it and offers a way on.
// On a developer's machine (`vp ui`) it also names the command.
export function empty(title, text, actions = [], command = '') {
  const buttons = actions.map(([href, label], i) => `<a class="btn${i ? '' : ' primary'}" href="${esc(href)}">${label}</a>`).join('');
  const dev = command && !session.hosted ? `<p class="small muted">${t('empty.command', { command: raw(`<code>${esc(command)}</code>`) })}</p>` : '';
  return `<div class="card"><h3>${title}</h3><p class="muted">${text}</p>${dev}${buttons ? `<div class="row" style="margin:0">${buttons}</div>` : ''}</div>`;
}

export const signedClass = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '');
export const signed = (v, text) => `<span class="${signedClass(v)}">${text}</span>`;

// Friendly and technical names of a sample strategy (a forecaster running
// in paper) and of a market kind.
export function strategyName(name) {
  const s = entry('forecasters.' + name);
  return detailed() || !s ? term(name, name) : esc(s.name);
}
export const strategyLabel = (name) => (detailed() ? name : entry('forecasters.' + name)?.name ?? name);
export const strategySentence = (name) => entry('forecasters.' + name)?.simple ?? t('forecasters_unknown');
export const kindName = (kind) => entry('kinds.' + (kind || 'unparsed'))?.name ?? esc(kind);

// Fee on one share bought at price p: rate * (p(1 - p))^exponent.
export const feePerShare = (p, rate, exponent = 1) => (rate == null || p == null ? null : rate * Math.pow(p * (1 - p), exponent || 1));

export function feeSentence(m) {
  if (m.fee_rate == null) return t('fees.unknown');
  if (m.fee_rate === 0) return t('fees.none');
  const fee = feePerShare(m.ask ?? m.p_yes, m.fee_rate, m.fee_exponent);
  return fee < 0.0005 ? t('fees.tiny') : t('fees.simple', { cents: fmt.cents(fee) });
}

// "62% chance" for Yes/No, "62% chance: Spirit" when the outcomes are named.
export function chance(m) {
  if (m.p_yes == null) return t('markets.no_price');
  const yesNo = (m.outcomes || []).join('/').toLowerCase() === 'yes/no';
  return yesNo ? t('markets.chance', { pct: fmt.pct(m.p_yes) }) : t('markets.chance_of', { pct: fmt.pct(m.p_yes), outcome: m.outcomes[0] });
}
