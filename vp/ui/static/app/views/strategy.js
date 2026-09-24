// One strategy of the person's own: what runs (the engine's rendering of
// the confirmed version), what it would touch and cost (the preview), what
// it would have done (backtest run cards), how it is doing in paper, and
// its versions. Every figure comes from the service's data; none is
// written by a model.
import { api, send, session } from '../api.js';
import { commentsPanel } from '../comments.js';
import { render } from '../main.js';
import { jobsPanel } from '../work.js';
import { after, detailed, empty, esc, fmt, head, signed, t, table, term, tp } from '../ui.js';
import { full as paperFull, simple as paperSimple } from './strategies.js';

function previewHtml(p) {
  let h = `<h2>${t('strategy.preview_title')}</h2><ul class="notes">`;
  h += `<li>${t('strategy.open_now', { n: p.open_now })}</li>`;
  const months = Object.keys(p.per_month);
  h += months.length
    ? `<li>${t('strategy.history', { n: p.resolved, since: fmt.month(months[0]), per_month: fmt.num(p.settled_a_month, 0), priced: p.with_history })}</li>`
    : `<li>${t('strategy.no_history')}</li>`;
  h += p.backtest_usd || p.paper_month_usd
    ? `<li>${t('strategy.cost', { markets: p.backtest_markets, backtest: fmt.money(p.backtest_usd), month: fmt.money(p.paper_month_usd) })}</li>`
    : `<li>${t('strategy.free')}</li>`;
  if (p.bets_needed) {
    const months = p.settled_a_month ? Math.ceil(p.bets_needed / p.settled_a_month) : null;
    h += `<li>${t('strategy.power', { n: p.bets_needed, edge: fmt.num(100 * p.edge, 0), price: fmt.cents(p.price, 0) })}
      ${months ? t('strategy.power_months', { n: months }) : ''}</li>`;
  }
  h += p.notes.map((n) => `<li>${esc(n)}</li>`).join('') + '</ul>';
  if (p.examples.length) h += `<h3>${t('strategy.examples')}</h3><ul class="notes">${p.examples.map((q) => `<li>${esc(q)}</li>`).join('')}</ul>`;
  return h;
}

function card(run, titles) {
  const c = run.results?.card;
  if (!c) return '';
  const bets = c.bets ? t('strategy.card_bets', { n: c.bets, ret: fmt.signedPct(c.return), fees: fmt.money(c.fees_usd) }) : t('strategy.card_no_bets');
  let h = `<div class="card" style="margin-bottom:12px"><h3 style="margin-top:0">${t('strategy.card_title', { domain: titles[run.domain] || run.domain, version: run.version, when: fmt.dateTime(run.created_at) })}</h3>
    <p>${t('strategy.card_scored', { n: c.scored, of: c.candidates })} ${bets}</p>`;
  if (c.advantage) {
    h += `<p>${t(c.advantage.low > 0 ? 'strategy.card_better' : c.advantage.high < 0 ? 'strategy.card_worse' : 'strategy.card_level')}</p>`;
    if (detailed()) {
      h += table([term('skill', tp('col.forward_skill')), term('brier', tp('glossary.brier.name')), t('col.market_brier'), t('strategy.col_advantage'), t('strategy.col_needed')],
        [[signed(c.skill, esc(fmt.signed(c.skill))), esc(fmt.num(c.brier, 4)), esc(fmt.num(c.brier_market, 4)),
          esc(`${fmt.signed(c.advantage.mean, 4)} [${fmt.num(c.advantage.low, 4)}, ${fmt.num(c.advantage.high, 4)}]`), esc(c.needed_n == null ? '–' : fmt.int(c.needed_n))]],
        { numFrom: 0, caption: t('strategy.card_caption') });
    }
  }
  if (c.caveats.length) h += `<ul class="notes small">${c.caveats.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`;
  if (detailed()) h += `<p class="small muted mono">${t('strategy.manifest', { hash: (c.manifest_hash || '').slice(0, 12) })}</p>`;
  return h + '</div>';
}

// Sharing a public, read-only snapshot (task 82) and entering the
// leaderboard (task 84): each switch says what a stranger would see.
async function shareHtml(id, retired) {
  const info = await api(`strategies/${id}/share`);
  if (!info) return '';
  const s = info.share;
  const box = (name, on) => `<label class="check"><input type="checkbox" name="${name}"${on ? ' checked' : ''}> <span>${t('share.' + name)}</span></label>`;
  let h = `<h2>${t('share.title')}</h2><p class="muted measure">${t('share.note')}</p>`;
  if (s) {
    const url = `${info.public_url}/s/${s.slug}`;
    h += `<p>${t('share.live', { views: s.views, forks: s.forks })} <a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a></p>`;
  }
  h += `<form id="share-form" class="measure"><div class="choices">${box('show_pnl', s?.show_pnl)}${box('show_spec', s?.show_spec)}${box('show_author', s?.show_author)}</div>
    <div class="row"><button class="btn${s ? '' : ' primary'}" type="submit">${t(s ? 'share.update' : 'share.publish')}</button>
    ${s ? `<button class="btn quiet" type="button" id="unshare">${t('share.stop')}</button>` : ''}</div></form>`;
  h += `<h2>${t('share.board_title')}</h2><p class="muted measure">${t('share.board_note')}</p>`;
  h += info.leaderboard
    ? `<p>${t('share.entered', { name: info.leaderboard })} <a href="#leaderboards">${t('share.see_boards')}</a></p><button class="btn quiet" type="button" id="leave-board">${t('share.withdraw')}</button>`
    : retired ? '' : `<form id="board-form" class="row"><label for="board-name">${t('share.board_name')}</label><input type="text" id="board-name" required maxlength="60">
      <button class="btn" type="submit">${t('share.enter')}</button></form>`;
  h += `<p id="share-status" class="small" role="status"></p>`;
  after(() => {
    const status = document.getElementById('share-status');
    const act = async (fn) => { try { await fn(); await render(false); } catch (e) { status.textContent = e.message; } };
    const form = document.getElementById('share-form');
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = Object.fromEntries(['show_pnl', 'show_spec', 'show_author'].map((k) => [k, form.querySelector(`[name=${k}]`).checked]));
      act(() => send('PUT', `strategies/${id}/share`, body));
    });
    document.getElementById('unshare')?.addEventListener('click', () => act(() => send('DELETE', `strategies/${id}/share`)));
    document.getElementById('leave-board')?.addEventListener('click', () => act(() => send('DELETE', `strategies/${id}/leaderboard`)));
    document.getElementById('board-form')?.addEventListener('submit', (e) => {
      e.preventDefault();
      const display_name = document.getElementById('board-name').value;
      act(() => send('PUT', `strategies/${id}/leaderboard`, { display_name }));
    });
  });
  return h;
}

// Health (task 101) and promotion (task 102): whether the strategy still
// beats the market in paper, and the numbered criteria for moving on, which
// a person approves; paper is advisory, live is binding (Phase 22).
async function healthHtml(id) {
  const hh = (await api(`strategies/${id}/health`))?.health;
  let h = `<h2>${t('health.title')}</h2>`;
  if (!hh) return h + `<p class="muted">${t('health.none')}</p>`;
  h += `<p><span class="pill${hh.state === 'healthy' ? ' ok' : hh.state === 'decayed' ? ' bad' : ''}">${t('health.states.' + hh.state)}</span>
    ${t('health.line.' + hh.state, { n: hh.settled })}</p>`;
  if (hh.paused) {
    h += `<div class="aside caution"><p>${t('health.paused')}</p><button class="btn" type="button" id="resume">${t('health.resume')}</button></div>`;
    after(() => document.getElementById('resume').addEventListener('click', async () => { await send('POST', `strategies/${id}/health/resume`); await render(false); }));
  }
  if (detailed()) {
    h += `<p class="small muted">${t('health.cusum', { s: fmt.num(hh.cusum, 2), h: fmt.num(hh.threshold, 0) })}</p>`;
    if (hh.transitions.length) {
      h += table([t('health.col_settled'), t('health.col_from'), t('health.col_to'), t('health.col_cusum')],
        hh.transitions.map((x) => [esc(x.settled), t('health.states.' + x.from), t('health.states.' + x.to), esc(fmt.num(x.cusum, 2))]),
        { caption: t('health.transitions'), numFrom: 3 });
    }
  }
  return h;
}

async function promotionHtml(id) {
  const list = (await api(`strategies/${id}/promotion`))?.evaluations || [];
  let h = `<h2>${t('promotion.title')}</h2><p class="muted measure">${t('promotion.note')}</p>
    <div class="row"><button class="btn" type="button" data-promote="paper">${t('promotion.check_paper')}</button>
    <button class="btn" type="button" data-promote="live">${t('promotion.check_live')}</button></div><p id="promo-status" class="small" role="status"></p>`;
  const last = list[0];
  if (last) {
    h += `<div class="card"><h3 style="margin-top:0">${t('promotion.result', { target: tp('promotion.targets.' + last.target), when: fmt.dateTime(last.evaluated_at) })}</h3>
      <ul class="notes">${last.criteria.map((c) => `<li><span class="pill${c.passed ? ' ok' : ' bad'}">${t(c.passed ? 'promotion.met' : 'promotion.not_met')}</span>
        ${t('promotion.criteria.' + c.name)}${detailed() ? ` <span class="small muted">(${esc(c.detail)})</span>` : ''}</li>`).join('')}</ul>
      ${last.approved_at ? `<p><span class="pill ok">${t('promotion.approved', { when: fmt.dateTime(last.approved_at) })}</span></p>`
        : last.passed ? `<button class="btn primary" type="button" data-approve="${esc(last.id)}">${t('promotion.approve')}</button>` : `<p class="small muted">${t('promotion.not_yet')}</p>`}</div>`;
  }
  after(() => {
    const status = document.getElementById('promo-status');
    document.querySelectorAll('[data-promote]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      try { await send('POST', `strategies/${id}/promotion`, { target: b.dataset.promote }); await render(false); } catch (e) { status.textContent = e.message; b.disabled = false; }
    }));
    document.querySelector('[data-approve]')?.addEventListener('click', async (e) => {
      try { await send('POST', `promotions/${e.currentTarget.dataset.approve}/approve`); await render(false); } catch (err) { status.textContent = err.message; }
    });
  });
  return h;
}

export default async function strategy([id]) {
  const s = await api(`strategies/${id}`);
  if (!s) return head(t('strategy.missing')) + empty(t('strategy.missing'), t('strategy.missing_text'), [['#strategies', t('describe.back')]]);
  const v = s.versions.at(-1);
  let h = head(esc(s.name), t('strategy.status.' + s.status));
  h += `<section class="card"><h2 style="margin-top:0">${t('strategy.what_runs', { version: v.version })}</h2>
    <ul class="notes spec">${v.rendering.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>
    ${detailed() ? `<p class="small muted mono">${t('strategy.hash', { hash: v.spec_hash.slice(0, 12) })}</p>` : ''}</section>`;
  const retired = s.status === 'retired';
  h += `<div class="row">${retired ? '' : `<button class="btn primary" type="button" data-act="backtest">${t('strategy.backtest')}</button>
    ${s.status === 'paper' ? '' : `<button class="btn" type="button" data-act="paper">${t('strategy.paper')}</button>`}`}
    <a class="btn" href="#describe/${esc(s.id)}">${t('strategy.refine')}</a>
    ${retired ? '' : `<button class="btn quiet" type="button" data-act="retire">${t('strategy.retire')}</button>`}</div>
    <p id="act-status" class="small" role="status"></p>`;
  h += jobsPanel(['backtest'], { limit: 3, onDone: () => render(false) });
  const preview = await api(`strategies/${id}/preview`);
  if (preview) h += previewHtml(preview);
  h += `<h2>${t('strategy.runs_title')}</h2>`;
  const titles = Object.fromEntries(Object.entries((await api('overview'))?.domains || {}).map(([name, d]) => [name, d.title]));
  h += s.runs.length ? s.runs.map((r) => card(r, titles)).join('') : `<p class="muted">${t('strategy.no_runs')}</p>`;
  h += `<h2>${t('strategy.paper_title')}</h2>`;
  const paper = s.accounts.length ? await api(`strategies/${id}/paper`) : null;
  h += paper?.paper.accounts.length ? (detailed() ? paperFull(paper.paper) : paperSimple(paper.paper)) : `<p class="muted">${t(s.accounts.length ? 'strategy.paper_waiting' : 'strategy.no_paper')}</p>`;
  if (detailed() && s.versions.length > 1) {
    h += `<h2>${t('strategy.versions')}</h2>` + table([t('strategy.col_version'), t('col.created'), t('strategy.col_changes')],
      s.versions.slice().reverse().map((x) => [esc(x.version), esc(fmt.dateTime(x.created_at)),
        x.changes.length ? esc(x.changes.map(([p, a, b]) => `${p}: ${JSON.stringify(a)} → ${JSON.stringify(b)}`).join('; ')) : '–']), { numFrom: 9 });
  }
  if (session.hosted && s.accounts.length) h += await healthHtml(id);
  if (session.hosted) h += await promotionHtml(id);
  if (session.hosted) h += await shareHtml(id, retired);
  h += commentsPanel('strategy', id);
  after(() => document.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', async () => {
    const status = document.getElementById('act-status');
    b.disabled = true;
    try {
      if (b.dataset.act === 'backtest') await send('POST', `strategies/${id}/backtest`, {});
      else await send('POST', `strategies/${id}/${b.dataset.act}`);
      await render(false);
    } catch (e) { status.textContent = e.message; b.disabled = false; }
  })));
  return h;
}
