// One strategy of the person's own: what runs (the engine's rendering of
// the confirmed version), what it would touch and cost (the preview), what
// it would have done (backtest run cards), how it is doing in paper, and
// its versions. Every figure comes from the service's data; none is
// written by a model.
import { api, send } from '../api.js';
import { render } from '../main.js';
import { jobsPanel } from '../work.js';
import { after, detailed, empty, esc, fmt, head, signed, t, table, term, tp } from '../ui.js';
import { simple as paperSimple } from './strategies.js';

function previewHtml(p) {
  let h = `<h2>${t('strategy.preview_title')}</h2><ul class="notes">`;
  h += `<li>${t('strategy.open_now', { n: p.open_now })}</li>`;
  const months = Object.keys(p.per_month);
  h += months.length
    ? `<li>${t('strategy.history', { n: p.resolved, since: months[0], per_month: fmt.num(p.settled_a_month, 0), priced: p.with_history })}</li>`
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

function card(run) {
  const c = run.results?.card;
  if (!c) return '';
  const bets = c.bets ? t('strategy.card_bets', { n: c.bets, ret: fmt.signedPct(c.return), fees: fmt.money(c.fees_usd) }) : t('strategy.card_no_bets');
  let h = `<div class="card" style="margin-bottom:12px"><h3 style="margin-top:0">${t('strategy.card_title', { domain: run.domain, version: run.version, when: fmt.dateTime(run.created_at) })}</h3>
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
  h += s.runs.length ? s.runs.map(card).join('') : `<p class="muted">${t('strategy.no_runs')}</p>`;
  h += `<h2>${t('strategy.paper_title')}</h2>`;
  const paper = s.accounts.length ? await api(`strategies/${id}/paper`) : null;
  h += paper?.paper.accounts.length ? paperSimple(paper.paper) : `<p class="muted">${t(s.accounts.length ? 'strategy.paper_waiting' : 'strategy.no_paper')}</p>`;
  if (detailed() && s.versions.length > 1) {
    h += `<h2>${t('strategy.versions')}</h2>` + table([t('strategy.col_version'), t('col.created'), t('strategy.col_changes')],
      s.versions.slice().reverse().map((x) => [esc(x.version), esc(fmt.dateTime(x.created_at)),
        x.changes.length ? esc(x.changes.map(([p, a, b]) => `${p}: ${JSON.stringify(a)} → ${JSON.stringify(b)}`).join('; ')) : '–']), { numFrom: 9 });
  }
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
