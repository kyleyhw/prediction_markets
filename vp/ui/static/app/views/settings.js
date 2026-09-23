// Settings: reading level, theme, language and formats, interests, the
// strategy Home follows, and the guided start; Detailed adds API tokens,
// an export of every record, and what is not here yet. Each control saves
// as it changes and says so in a status line a screen reader announces.
import { api, send, session } from '../api.js';
import { LOCALES, setLocale } from '../i18n.js';
import { applyTheme, render, shell } from '../main.js';
import { prefs, save } from '../prefs.js';
import { after, detailed, esc, fmt, head, strategyLabel, strategySentence, t, table, tp } from '../ui.js';

const radio = (name, value, current, title, text = '') => `<label class="choice"><input type="radio" name="${name}" value="${esc(value)}"${value === current ? ' checked' : ''}>
  <span><span class="t">${title}</span>${text ? `<br><span class="d">${text}</span>` : ''}</span></label>`;

function tokens(list) {
  const rows = list.filter((k) => !k.revoked_at).map((k) => [esc(k.name), esc(k.scope), esc(fmt.dateTime(k.created_at)),
    `<button class="btn quiet" type="button" data-revoke="${esc(k.id)}">${t('settings.revoke')}</button>`]);
  return (rows.length ? table([t('col.name'), t('col.scope'), t('col.created'), `<span class="sr-only">${t('settings.revoke')}</span>`], rows, { numFrom: 9 }) : `<p class="muted">${t('settings.no_tokens')}</p>`)
    + `<form id="new-token" class="row" style="margin-top:12px"><label for="token-name" class="sr-only">${t('col.name')}</label>
      <input type="text" id="token-name" required maxlength="100" placeholder="${tp('settings.token_placeholder')}">
      <label for="token-scope" class="sr-only">${t('col.scope')}</label><select id="token-scope"><option value="read">${t('settings.scope_read')}</option><option value="write">${t('settings.scope_write')}</option></select>
      <button class="btn" type="submit">${t('settings.create_token')}</button></form><div id="token-secret" role="status"></div>`;
}

async function download() {
  const parts = await Promise.all([
    session.hosted ? fetch('/auth/me').then((r) => r.json()) : null,
    Promise.resolve(prefs()),
    session.hosted ? api('tokens') : [],
    api('paper?limit=1000'),
    api('forecasts?limit=1000'),
  ]);
  const [account, settings, apiTokens, paper, forecasts] = parts;
  const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), account, settings, api_tokens: apiTokens, paper, forecasts }, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'vibe-predict-export.json';
  a.click();
  URL.revokeObjectURL(a.href);
}

// This month's model spending: a sentence in both levels, the breakdown in
// Detailed. It is a fact that changes decisions, so Simple keeps it.
async function spending() {
  const s = await api('spend');
  if (!s) return '';
  let h = `<h2>${t('settings.spend')}</h2><p>${t('settings.spend_line', { used: fmt.money(s.charged_usd), limit: fmt.money(s.limit_usd), left: fmt.money(s.remaining_usd) })}</p>`;
  if (detailed() && s.breakdown.length) {
    h += table([t('col.strategy'), t('col.domain'), t('col.model'), t('col.tokens_in'), t('col.tokens_out'), t('col.cache_read'), t('col.cost'), t('col.paid_by')],
      s.breakdown.map((r) => [esc(r.forecaster ?? '–'), esc(r.domain ?? '–'), esc(r.model ?? '–'), esc(fmt.int(r.input_tokens)), esc(fmt.int(r.output_tokens)),
        esc(fmt.int(r.cache_read_tokens)), esc(fmt.money(r.usd, 4)), t(r.paid_by === 'own_key' ? 'settings.paid_own' : 'settings.paid_platform')]),
      { caption: t('settings.spend_caption'), numFrom: 3 });
  }
  return h;
}

async function ownKey() {
  const k = await api('keys');
  if (!k?.enabled) return '';
  after(() => {
    const f = document.getElementById('key-form'), status = document.getElementById('key-status');
    f?.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const r = await send('PUT', 'keys', { key: f.key.value });
        f.key.value = '';
        status.textContent = tp('settings.key_saved', { hint: r.hint });
      } catch (err) { status.textContent = err.message; }
    });
    document.getElementById('key-remove')?.addEventListener('click', async () => {
      await send('DELETE', 'keys');
      status.textContent = tp('settings.key_removed');
    });
  });
  return `<h2>${t('settings.key')}</h2><p class="muted measure">${t('settings.key_note')}</p>
    ${k.hint ? `<p>${t('settings.key_current', { hint: k.hint })}</p>` : ''}
    <form id="key-form" class="row"><label for="key-input" class="sr-only">${t('settings.key')}</label>
      <input type="password" id="key-input" name="key" autocomplete="off" required minlength="20" placeholder="sk-ant-…" style="min-width:18em">
      <button class="btn" type="submit">${t('settings.key_save')}</button>
      ${k.hint ? `<button class="btn quiet" type="button" id="key-remove">${t('settings.key_remove')}</button>` : ''}</form>
    <p class="small" id="key-status" role="status"></p>`;
}

function refreshData(domains) {
  after(() => document.querySelectorAll('[data-refresh]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true;
    const r = await send('POST', 'refresh/' + b.dataset.refresh);
    document.getElementById('refresh-status').textContent = tp(r.queued ? 'settings.refresh_queued' : 'settings.refresh_recent');
  })));
  return `<h2>${t('settings.refresh')}</h2><p class="muted measure">${t('settings.refresh_note')}</p>
    <div class="row">${Object.entries(domains).map(([name, d]) => `<button class="btn" type="button" data-refresh="${esc(name)}">${t('settings.refresh_button', { title: d.title })}</button>`).join('')}</div>
    <p class="small" id="refresh-status" role="status"></p>`;
}

export default async function settings() {
  const o = await api('overview');
  const p = prefs();
  let h = head(t('settings.title'), t('settings.lede'));
  h += `<p class="small muted" id="saved" role="status"></p><form id="prefs" class="measure">`;
  h += `<fieldset><legend>${t('settings.level')}</legend><div class="choices">
    ${radio('level', 'simple', p.level, t('level.simple'), t('settings.level_simple'))}${radio('level', 'detailed', p.level, t('level.detailed'), t('settings.level_detailed'))}</div></fieldset>`;
  h += `<fieldset><legend>${t('settings.theme')}</legend><div class="choices">
    ${['system', 'light', 'dark'].map((v) => radio('theme', v, p.theme, t('settings.theme_' + v))).join('')}</div></fieldset>`;
  h += `<fieldset><legend>${t('settings.language')}</legend><label for="locale" class="sr-only">${t('settings.language')}</label>
    <select id="locale" name="locale"><option value="">${t('settings.language_browser')}</option>${LOCALES.map(([tag, name]) => `<option value="${tag}"${p.locale === tag ? ' selected' : ''}>${esc(name)}</option>`).join('')}</select>
    <p class="small muted" style="margin-top:6px">${t('settings.language_note', { example: fmt.dateTime(new Date().toISOString()) })}</p></fieldset>`;
  h += `<fieldset><legend>${t('settings.interests')}</legend><p class="small muted">${t('settings.interests_note')}</p><div class="choices">
    ${Object.entries(o.domains).map(([name, d]) => `<label class="choice"><input type="checkbox" name="interests" value="${esc(name)}"${p.interests.includes(name) ? ' checked' : ''}>
      <span><span class="t">${esc(d.title)}</span><br><span class="d">${esc(d.summary)}</span></span></label>`).join('')}</div></fieldset>`;
  const accounts = o.paper.accounts;
  if (accounts.length) {
    h += `<fieldset><legend>${t('settings.follow')}</legend><div class="choices">
      ${accounts.map((a) => radio('follow', a.forecaster, p.follow, esc(strategyLabel(a.forecaster)), esc(strategySentence(a.forecaster)))).join('')}</div></fieldset>`;
  }
  h += '</form>';
  if (session.hosted) h += await spending();
  h += `<h2>${t('settings.start')}</h2><p class="muted">${t('settings.start_note')}</p><button class="btn" type="button" id="restart">${t('settings.start_again')}</button>`;
  if (detailed()) {
    if (session.hosted) h += `<h2>${t('settings.tokens')}</h2><p class="muted measure">${t('settings.tokens_note')}</p><div id="tokens">${tokens(await api('tokens'))}</div>`;
    if (session.hosted) h += await ownKey();
    if (session.hosted) h += refreshData(o.domains);
    h += `<h2>${t('settings.export')}</h2><p class="muted measure">${t('settings.export_note')}</p><button class="btn" type="button" id="export">${t('settings.export_button')}</button>`;
    h += `<h2>${t('settings.later')}</h2><ul class="notes measure">${['play_money', 'notifications', 'model'].map((k) => `<li>${t('settings.later_' + k)}</li>`).join('')}</ul>`;
  }
  if (session.hosted) {
    h += `<h2>${t('settings.account')}</h2><dl class="kv"><dt>${t('settings.email')}</dt><dd>${esc(session.me.email)}</dd>
      <dt>${t('settings.workspace')}</dt><dd>${esc(session.me.workspace?.name ?? '')}</dd></dl>
      <form method="post" action="/auth/sign-out" style="margin-top:12px"><button class="btn" type="submit">${t('account.sign_out')}</button></form>`;
  }
  after(() => {
    const form = document.getElementById('prefs'), status = document.getElementById('saved');
    form.addEventListener('change', async (e) => {
      const el = e.target, patch = {};
      if (el.name === 'interests') patch.interests = [...form.querySelectorAll('input[name=interests]:checked')].map((x) => x.value);
      else patch[el.name] = el.value || null;
      try {
        await save(patch);
        status.textContent = tp('settings.saved');
      } catch { status.textContent = tp('settings.not_saved'); return; }
      if (el.name === 'theme') applyTheme();
      if (el.name === 'level' || el.name === 'locale') {
        if (el.name === 'locale') setLocale(prefs().locale);
        shell();
        await render(false);
        document.querySelector(`#prefs [name="${el.name}"]${el.type === 'radio' ? `[value="${el.value}"]` : ''}`)?.focus();
        document.getElementById('saved').textContent = tp('settings.saved');
      }
    });
    document.getElementById('restart').addEventListener('click', async () => { await save({ start: { step: 0, done: false } }); location.hash = '#start'; });
    document.getElementById('export')?.addEventListener('click', download);
    const box = document.getElementById('tokens');
    if (!box) return;
    box.addEventListener('click', async (e) => {
      const id = e.target.closest('[data-revoke]')?.dataset.revoke;
      if (!id) return;
      await send('DELETE', 'tokens/' + id);
      box.innerHTML = tokens(await api('tokens'));
    });
    box.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = document.getElementById('token-name').value, scope = document.getElementById('token-scope').value;
      const made = await send('POST', 'tokens', { name, scope });
      box.innerHTML = tokens(await api('tokens'));
      document.getElementById('token-secret').innerHTML = `<div class="aside"><p>${t('settings.token_once')}</p><p><code>${esc(made.token)}</code></p></div>`;
    });
  });
  return h;
}
