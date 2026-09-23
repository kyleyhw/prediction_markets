// Home: the followed sample strategy's play-money balance and its chart
// against doing nothing, what changed in the last day, and one next step.
// Detailed adds every strategy's figures, their curves together, and the
// ledger's integrity.
import { api, session } from '../api.js';
import { render } from '../main.js';
import { BASELINE, colorOf, dayTicks, lineChart } from '../charts.js';
import { prefs } from '../prefs.js';
import { jobsPanel } from '../work.js';
import { detailed, empty, esc, fmt, head, raw, signed, strategyLabel, strategyName, strategySentence, t, table, term, tp } from '../ui.js';

// The strategy Home follows: the person's choice, else the first that trades.
export function followed(accounts) {
  const trading = accounts.filter((a) => a.forecaster !== 'market');
  return accounts.find((a) => a.forecaster === prefs().follow)
    || trading.find((a) => a.settled || a.open_count) || trading[0] || null;
}

// Balance over time from the first order, with doing nothing (keeping the
// starting amount) drawn alongside.
export function balanceChart(accounts, start, { title = '', height = 240 } = {}) {
  const series = accounts.filter((a) => a.curve_at[0]).map((a) => ({
    name: strategyLabel(a.forecaster),
    color: colorOf(a.forecaster),
    points: a.curve.map((v, i) => [new Date(a.curve_at[i]).getTime(), v]),
  }));
  if (!series.length) return '';
  const xs = series.flatMap((s) => s.points.map((p) => p[0]));
  series.push({ name: tp('chart.doing_nothing'), color: BASELINE, dash: true, points: [[Math.min(...xs), start], [Math.max(...xs, Date.now()), start]] });
  const one = accounts.length === 1 ? accounts[0] : null;
  return lineChart(series, {
    title,
    height,
    summary: one ? tp('chart.balance_summary', { name: strategyLabel(one.forecaster), start: fmt.money(start), now: fmt.money(one.bankroll), n: one.settled }) : tp('chart.balances_summary', { n: accounts.length }),
    fmtX: (x) => fmt.shortDate(x),
    xTicks: dayTicks,
    fmtY: (y) => fmt.money(y, 0),
  });
}

function comparison(a, start) {
  if (!a.settled) return t('home.nothing_settled');
  const diff = a.bankroll - start;
  if (Math.abs(diff) < 0.005) return t('home.level_with_nothing');
  return t(diff > 0 ? 'home.ahead_of_nothing' : 'home.behind_nothing', { amount: fmt.money(Math.abs(diff)) });
}

function today(paper) {
  const d = paper.today, items = [];
  if (d.settlement) items.push(t('home.today_settled', { n: d.settlement, pnl: raw(signed(d.pnl, esc(fmt.signedMoney(d.pnl)))) }));
  if (d.order) items.push(t('home.today_orders', { n: d.order }));
  if (d.forecast) items.push(t('home.today_forecasts', { n: d.forecast }));
  if (d.cycle) items.push(t('home.today_cycles', { n: d.cycle }));
  return items.length ? `<ul class="notes">${items.map((i) => `<li>${i}</li>`).join('')}</ul>` : `<p class="muted">${t('home.today_none')}</p>`;
}

function nextStep(accounts) {
  const [href, label] = !prefs().interests.length ? ['#start/1', t('next.interests')]
    : !accounts.length ? ['#learn/paper', t('next.learn_paper')]
      : accounts.some((a) => a.open_count) ? ['#strategies', t('next.positions')]
        : ['#markets', t('next.markets')];
  return `<a class="btn primary" href="${href}">${label}</a>`;
}

export default async function home() {
  const o = await api('overview');
  const paper = o.paper, start = paper.start_cash, accounts = paper.accounts;
  const progress = prefs().start;
  let h = head(t('home.title'), t('home.lede'));
  if (!progress.done && progress.step > 0) {
    h += `<div class="aside"><p>${t('home.resume_start')}</p><a class="btn" href="#start/${progress.step}">${t('home.resume_button')}</a></div>`;
  }
  if (paper.verified === false) h += `<div class="aside caution" role="alert"><p>${t('home.chain_broken')}</p></div>`;
  if (!accounts.length) {
    if (session.hosted) {
      return h + `<div class="card"><h3>${t('home.empty_title')}</h3><p class="muted">${t('work.sample_waiting')}</p></div>`;
    }
    return h + empty(t('home.empty_title'), t('home.empty_text'), [['#markets', t('next.markets')], ['#learn/paper', t('next.learn_paper')]],
      'vp paper run --domain ' + Object.keys(o.domains).join(' '));
  }
  const a = followed(accounts);
  const change = a.bankroll - start;
  h += `<div class="card hero"><div class="k">${t('home.play_money_of', { name: raw(strategyName(a.forecaster)) })}</div>
    <div class="v num">${esc(fmt.money(a.bankroll))}</div>
    <p>${t('home.since_start', { change: raw(signed(change, esc(fmt.signedMoney(change)))), pct: fmt.signedPct(change / start), start: fmt.money(start) })} ${comparison(a, start)}</p>
    <p class="muted small">${esc(strategySentence(a.forecaster))} ${a.open_count ? t('home.open', { n: a.open_count, stake: fmt.money(a.exposure) }) : ''} ${a.fees ? t('home.fees_paid', { fees: fmt.money(a.fees) }) : ''}</p>
    ${a.settled ? balanceChart([a], start) : `<p class="muted small">${t('home.chart_later')}</p>`}
    ${o.sample ? `<p class="muted small">${t('work.sample_shared')}</p>` : ''}
    <p class="small" style="margin:6px 0 0"><a class="target" href="#settings">${t('home.follow_other')}</a></p></div>`;
  h += `<div class="grid cols-2" style="margin-top:14px">
    <section class="card"><h2 style="margin-top:0">${t('home.today_title')}</h2>${today(paper)}</section>
    <section class="card"><h2 style="margin-top:0">${t('home.next_title')}</h2><p class="muted">${t('home.next_text')}</p>${nextStep(accounts)}</section></div>`;
  h += jobsPanel(['paper_cycle', 'settle', 'backtest'], { limit: 3, onDone: () => render(false) });
  if (detailed()) {
    h += `<h2>${t('home.all_title')}</h2>`;
    h += table(
      [t('col.strategy'), term('bankroll', tp('col.balance')), term('realised', tp('col.realised')), term('exposure', tp('col.open_stake')), term('fee', tp('col.fees')), t('col.settled'), term('skill', tp('col.forward_skill'))],
      accounts.map((x) => [strategyName(x.forecaster), esc(fmt.money(x.bankroll)), signed(x.realised, esc(fmt.signedMoney(x.realised))), esc(fmt.money(x.exposure)),
        esc(fmt.money(x.fees)), esc(fmt.int(x.settled)), x.skill == null ? '–' : signed(x.skill, esc(fmt.signed(x.skill)))]),
      { caption: t('home.all_caption', { start: fmt.money(start) }) },
    );
    const chart = balanceChart(accounts.filter((x) => x.settled), start, { title: tp('home.all_chart') });
    if (chart) h += `<div class="card" style="margin-top:14px">${chart}</div>`;
    h += `<p class="cap">${term('ledger', tp('glossary.ledger.name'))}: ${t('home.ledger_line', { n: paper.entries })} ${paper.verified ? `<span class="pill ok">${term('verified', tp('glossary.verified.name'))}</span>` : ''}</p>`;
  }
  return h;
}
