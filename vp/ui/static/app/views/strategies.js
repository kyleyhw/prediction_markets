// Strategies: the person's own strategies (hosted), described in a
// conversation and each with its own page; then the sample strategies
// running on play money, each with its
// balance against doing nothing and its open positions in words. Detailed
// is the paper-trading record in full: accounts, open positions with the
// fee each paid, settlements, and the hash-chained ledger itself.
import { api, send, session } from '../api.js';
import { render } from '../main.js';
import { jobsPanel } from '../work.js';
import { after, detailed, empty, esc, fmt, head, raw, signed, strategyName, strategySentence, t, table, term, tp } from '../ui.js';
import { balanceChart } from './home.js';

const SHOWN = 5;
const OPEN_SHOWN = 50;

function position(o) {
  const side = o.side === 'yes' ? t('strategies.side_yes') : t('strategies.side_no');
  return t('strategies.position', { side: raw(side), question: o.question, price: fmt.cents(o.price, 0), stake: fmt.money(o.stake), fee: fmt.money(o.fee ?? 0) });
}

export function simple(p) {
  let h = '';
  for (const a of p.accounts) {
    const change = a.bankroll - p.start_cash;
    h += `<section class="card" style="margin-bottom:14px"><h2 style="margin-top:0">${strategyName(a.forecaster)}</h2>
      <p class="muted">${esc(strategySentence(a.forecaster))}</p>
      <div class="v num">${esc(fmt.money(a.bankroll))}</div>
      <p>${t('home.since_start', { change: raw(signed(change, esc(fmt.signedMoney(change)))), pct: fmt.signedPct(change / p.start_cash), start: fmt.money(p.start_cash) })}
      ${a.forecaster === 'market' ? t('strategies.never_bets') : t('strategies.counts', { n: a.settled, open: a.open.length })}</p>
      ${a.settled ? balanceChart([a], p.start_cash, { height: 180 }) : ''}
      ${a.open.length ? `<h3 style="margin-top:12px">${t('strategies.waiting')}</h3><ul class="notes">${a.open.slice(0, SHOWN).map((o) => `<li>${position(o)}</li>`).join('')}</ul>
        ${a.open.length > SHOWN ? `<p class="small muted">${t('strategies.and_more', { n: a.open.length - SHOWN })}</p>` : ''}` : ''}</section>`;
  }
  return h;
}

function full(p) {
  let h = table(
    [t('col.strategy'), term('bankroll', tp('col.balance')), term('realised', tp('col.realised')), term('exposure', tp('col.open_stake')), term('fee', tp('col.fees')), t('col.open'), t('col.settled'), term('skill', tp('col.forward_skill'))],
    p.accounts.map((a) => [strategyName(a.forecaster), esc(fmt.money(a.bankroll)), signed(a.realised, esc(fmt.signedMoney(a.realised))), esc(fmt.money(a.exposure)),
      esc(fmt.money(a.fees)), esc(fmt.int(a.open.length)), esc(fmt.int(a.settled)), a.skill == null ? '–' : signed(a.skill, esc(fmt.signed(a.skill)))]),
    { caption: t('home.all_caption', { start: fmt.money(p.start_cash) }) });
  const chart = balanceChart(p.accounts.filter((a) => a.settled), p.start_cash, { title: tp('home.all_chart') });
  if (chart) h += `<div class="card" style="margin-top:14px">${chart}</div>`;
  // The largest stakes first, and no more than a table can be read through
  // (a screen reader heard 1,236 rows here); the ledger holds them all.
  const all = p.accounts.flatMap((a) => a.open.map((o) => [a, o])).sort((x, y) => y[1].stake - x[1].stake);
  const open = all.slice(0, OPEN_SHOWN).map(([a, o]) => [strategyName(a.forecaster), `<span class="wrapc">${esc(o.question)}</span>`, esc(o.side),
    esc(fmt.num(o.q, 3)), esc(fmt.num(o.p_hat, 3)), esc(fmt.num(o.price, 4)), esc(fmt.num(o.shares, 1)), esc(fmt.money(o.stake)),
    o.fee == null ? `<span class="muted">${t('strategies.fee_unrecorded')}</span>` : `${esc(fmt.money(o.fee, 4))}${o.fee_source === 'assumed' ? ` <span class="muted">(${t('strategies.assumed')})</span>` : ''}`]);
  h += `<h2>${t('strategies.open_title')}</h2>`;
  if (all.length > OPEN_SHOWN) h += `<p class="cap">${t('strategies.open_shown', { shown: fmt.int(OPEN_SHOWN), n: fmt.int(all.length) })}</p>`;
  h += open.length ? table([t('col.strategy'), t('col.market'), term('side', tp('glossary.side.name')), term('q', 'q'), term('phat', 'p̂'), term('price', tp('glossary.price.name')),
    term('shares', tp('glossary.shares.name')), term('stake', tp('glossary.stake.name')), term('fee', tp('glossary.fee.name'))], open, { numFrom: 3, caption: t('strategies.open_caption') }) : `<p class="muted">${t('strategies.none_open')}</p>`;
  h += `<h2>${t('strategies.settled_title')}</h2>`;
  h += p.settlements.length ? table([t('col.at'), t('col.strategy'), t('col.market'), term('label', tp('glossary.label.name')), term('pnl', tp('glossary.pnl.name')), term('brier', tp('glossary.brier.name')), t('col.market_brier')],
    p.settlements.slice().reverse().map((s) => [esc(fmt.dateTime(s.at)), strategyName(s.forecaster), esc(s.market_id), esc(s.label), signed(s.pnl, esc(fmt.signedMoney(s.pnl))), esc(fmt.num(s.brier, 4)), esc(fmt.num(s.brier_market, 4))]),
    { numFrom: 3, caption: t('strategies.settled_caption') }) : `<p class="muted">${t('strategies.none_settled')}</p>`;
  h += `<h2>${term('ledger', tp('glossary.ledger.name'))}</h2><p class="cap" style="margin:0 0 8px">${t('strategies.ledger_caption', { n: p.entries })}
    ${p.verified ? `<span class="pill ok">${term('verified', tp('glossary.verified.name'))}</span>` : `<span class="pill bad">${t('strategies.chain_broken_pill')}</span>`}</p>`;
  h += `<div class="card timeline">${p.recent.slice().reverse().map((e) => `<details><summary><span class="mono small">${esc(fmt.dateTime(e.at))}</span>
    <span><span class="pill">${esc(e.kind)}</span> <span class="muted mono small">#${esc(e.seq)}</span></span><span class="small">${esc(summarise(e))}</span></summary>
    <pre>${esc(JSON.stringify(e, null, 1))}</pre></details>`).join('')}</div>`;
  return h;
}

function summarise(e) {
  const d = e.data;
  switch (e.kind) {
    case 'order': return `${d.forecaster} ${d.side} ${fmt.num(d.shares, 1)} @ ${fmt.num(d.price, 3)} (${fmt.money(d.stake)}): ${d.question}`;
    case 'forecast': return `${d.forecaster} p̂ ${fmt.num(d.p_hat, 3)}, q ${fmt.num(d.q, 3)}, market ${d.market_id}`;
    case 'settlement': return `${d.forecaster} market ${d.market_id}: label ${d.label}, ${fmt.signedMoney(d.pnl)}`;
    case 'cycle': return `${d.domain}: ${d.markets}`;
    default: return JSON.stringify(d);
  }
}

export default async function strategies() {
  const p = await api('paper?limit=60');
  let h = head(t('strategies.title'), t('strategies.lede'));
  if (p.verified === false) h += `<div class="aside caution" role="alert"><p>${t('home.chain_broken')}</p></div>`;
  if (!session.hosted) h += `<div class="aside"><p>${t('strategies.own_hosted')}</p></div>`;
  if (session.hosted) {
    const mine = (await api('strategies')) || [];
    h += `<h2>${t('strategies.mine_title')}</h2>`;
    h += mine.length
      ? `<div class="grid">${mine.map((s) => `<a class="card link" href="#strategy/${esc(s.id)}"><h3 style="margin-top:0">${esc(s.name)}</h3>
          <p><span class="pill">${t('strategy.status.' + s.status)}</span> <span class="small muted">${t('strategies.mine_version', { n: s.version })}</span></p>
          <p class="small muted">${esc(s.rendering[0])}</p></a>`).join('')}</div>`
      : `<p class="muted">${t('strategies.mine_none')}</p>`;
    h += `<div class="row"><a class="btn primary" href="#describe/new">${t('strategies.describe')}</a>
      <a class="btn" href="#research">${t('strategies.research')}</a></div>`;
    h += `<h2>${t('strategies.samples_title')}</h2>`;
    const o = await api('overview');
    const exportLink = detailed() ? `<a class="btn quiet" href="/api/paper/export" download>${t('work.export_ledger')}</a>` : '';
    if (o.sample) {
      h += `<p class="muted">${t('work.sample_shared')} ${t('work.sample_hourly')}</p>${exportLink ? `<div class="row">${exportLink}</div>` : ''}`;
      if (!p.accounts.length) return h;
      return h + (detailed() ? full(p) : simple(p));
    }
    h += `<div class="row">
      <button class="btn" type="button" data-run="cycle">${t('work.run_cycle')}</button>
      <button class="btn" type="button" data-run="settle">${t('work.run_settle')}</button>
      ${exportLink}</div>
      <p class="small" id="run-status" role="status"></p>`;
    h += jobsPanel(['paper_cycle', 'settle'], { onDone: () => render(false) });
    after(() => document.querySelectorAll('[data-run]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      try { await send('POST', 'paper/run?what=' + b.dataset.run); await render(false); } catch (err) {
        document.getElementById('run-status').textContent = err.message;
        b.disabled = false;
      }
    })));
  }
  if (!p.accounts.length) return h + (session.hosted ? '' : empty(t('home.empty_title'), t('home.empty_text'), [['#learn/paper', t('next.learn_paper')]], 'vp paper run --domain <domain>'));
  return h + (detailed() ? full(p) : simple(p));
}
