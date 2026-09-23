// Backtests: how each sample strategy would have done on markets that have
// already settled. Simple says it in sentences ("would have turned $1,000
// into $427 over 167 bets; worse than doing nothing") with the balance
// chart against doing nothing; Detailed has the scores, the bet statistics,
// the reliability diagram and the cumulative advantage, and can overlay a
// second run. Both say when a run assumed no fees or rests on too few
// markets to tell skill from luck.
import { api, send, session } from '../api.js';
import { render } from '../main.js';
import { jobsPanel } from '../work.js';
import { BASELINE, colorOf, lineChart } from '../charts.js';
import { after, detailed, empty, esc, fmt, head, raw, signed, strategyLabel, strategyName, strategySentence, t, table, term, tp } from '../ui.js';
import { orderedDomains, stampIso } from './markets.js';

// Settled markets needed to detect a two-point Brier edge at 5% with 80%
// power (PROJECT_PLAN.md, Mathematical core: n = 7.85 sd^2 / delta^2).
const ENOUGH = 350;

function cautions(res) {
  const c = [];
  if (res.common < ENOUGH) c.push(t('bt.small_sample', { n: res.common, enough: ENOUGH }));
  if (!res.config.fee_rate) c.push(t('bt.no_fees'));
  return c.length ? `<div class="aside caution">${c.map((x) => `<p>${x}</p>`).join('')}</div>` : '';
}

function equityChart(runs, opts = {}) {
  const series = [];
  for (const [res, suffix, dash] of runs) {
    for (const f of res.forecasters) {
      if (f.name === 'market' || !f.equity || f.equity.length < 2) continue;
      series.push({ name: strategyLabel(f.name) + suffix, color: colorOf(f.name), dash, points: f.equity.map((v, i) => [i, v]) });
    }
  }
  if (!series.length) return '';
  const start = runs[0][0].config.initial_cash, longest = Math.max(...series.map((s) => s.points.length - 1));
  series.push({ name: tp('chart.doing_nothing'), color: BASELINE, dash: true, points: [[0, start], [longest, start]] });
  return lineChart(series, { title: tp('bt.equity_title'), summary: tp('bt.equity_summary', { start: fmt.money(start) }), xLabel: tp('bt.equity_x'), fmtY: (y) => fmt.money(y, 0), ...opts });
}

function simple(res) {
  const start = res.config.initial_cash;
  let h = '';
  for (const f of res.forecasters.filter((x) => x.name !== 'market')) {
    const lines = [];
    if (f.stats && f.equity?.length) {
      const end = f.equity[f.equity.length - 1];
      lines.push(t('bt.turned', { start: fmt.money(start, 0), end: fmt.money(end, 0), n: f.stats.count }));
      lines.push(Math.abs(end - start) < 0.5 ? t('bt.same_as_nothing') : t(end > start ? 'bt.better_than_nothing' : 'bt.worse_than_nothing'));
    } else lines.push(t('bt.no_bets'));
    lines.push(t(f.skill > 0 ? 'bt.more_accurate' : f.skill < 0 ? 'bt.less_accurate' : 'bt.as_accurate', { n: f.n }));
    if (f.cost_usd) lines.push(t('bt.cost', { cost: fmt.money(f.cost_usd) }));
    h += `<section class="card" style="margin-bottom:12px"><h3>${strategyName(f.name)}</h3><p class="muted small">${esc(strategySentence(f.name))}</p><p>${lines.join(' ')}</p></section>`;
  }
  const chart = equityChart([[res, '', false]]);
  return h + (chart ? `<div class="card">${chart}</div>` : '');
}

function full(res, other) {
  const c = res.config;
  let h = `<p class="cap" style="margin:0 0 12px">${t('bt.config', {
    hours: raw(term('hours', tp('bt.hours', { n: c.hours_before_close }))), kinds: c.kinds.length ? c.kinds.join(', ') : tp('bt.all_kinds'),
    candidates: fmt.int(res.candidates), priced: fmt.int(res.with_price), scored: fmt.int(res.common), seconds: res.seconds })}<br>
    ${t('bt.sizing', { kelly: raw(term('kelly', String(c.kelly_multiplier))), cap: fmt.pct(c.max_fraction), edge: raw(term('minedge', String(c.min_edge))),
    spread: raw(term('spread', String(c.half_spread))), fee: raw(term('fee', String(c.fee_rate))), start: fmt.money(c.initial_cash, 0) })}</p>`;
  h += `<h2>${t('bt.scores_title')}</h2>` + table(
    [t('col.strategy'), term('n', 'n'), term('brier', 'Brier ↓'), term('log', 'Log ↓'), term('skill', 'Skill ↑'), term('reliability', 'Reliability ↓'), term('resolution', 'Resolution ↑'), term('ece', 'ECE ↓'), term('cost', tp('col.cost'))],
    res.forecasters.map((f) => [strategyName(f.name), esc(fmt.int(f.n)), esc(fmt.num(f.brier, 4)), esc(fmt.num(f.log, 4)), signed(f.skill, esc(fmt.signed(f.skill, 4))),
      esc(fmt.num(f.calibration.reliability, 4)), esc(fmt.num(f.calibration.resolution, 4)), esc(fmt.num(f.calibration.ece, 4)), esc(fmt.money(f.cost_usd))]),
    { caption: t('bt.scores_caption') });
  const bets = res.forecasters.filter((f) => f.stats);
  if (bets.length) {
    h += `<h2>${t('bt.bets_title')}</h2>` + table(
      [t('col.strategy'), term('bets', tp('glossary.bets.name')), term('return', tp('glossary.return.name')), term('drawdown', tp('glossary.drawdown.name')), term('winrate', tp('glossary.winrate.name')),
        term('pf', tp('glossary.pf.name')), term('sharpe', tp('glossary.sharpe.name')), term('sharpeci', tp('glossary.sharpeci.name')), term('psharpe', tp('glossary.psharpe.name'))],
      bets.map((f) => [strategyName(f.name), esc(fmt.int(f.stats.count)), signed(f.stats.total_return, esc(fmt.signedPct(f.stats.total_return, 2))), esc(fmt.pct(f.stats.max_drawdown, 2)),
        esc(fmt.pct(f.stats.win_rate, 1)), esc(fmt.num(f.stats.profit_factor, 2)), esc(fmt.num(f.stats.per_bet_sharpe, 3)),
        f.sharpe ? esc(`[${fmt.num(f.sharpe.lower, 3)}, ${fmt.num(f.sharpe.upper, 3)}]`) : '–', f.sharpe ? esc(fmt.num(f.sharpe.probability_positive, 2)) : '–']),
      { caption: t('bt.bets_caption') });
  }
  const runs = [[res, '', false]].concat(other ? [[other, ' (B)', true]] : []);
  const mix = (key, map) => runs.flatMap(([r, sfx, dash]) => r.forecasters.filter((f) => f[key]).map((f) => ({ name: f.name + sfx, color: colorOf(f.name), dash, points: map(f) })));
  const rel = mix('calibration', (f) => f.calibration.bins.map((b) => [b.mean_forecast, b.observed_frequency]));
  const adv = mix('advantage', (f) => f.advantage.map((v, i) => [i + 1, v])).filter((s) => !s.name.startsWith('market'));
  h += `<h2>${t('bt.charts_title')}</h2><div class="grid cols-2">
    <div class="card">${lineChart(rel, { title: tp('bt.reliability_title'), summary: tp('bt.reliability_summary'), xLabel: tp('bt.reliability_x'), yLabel: tp('bt.reliability_y'), xDomain: [0, 1], yDomain: [0, 1], diagonal: true, dots: true })}<p class="cap">${t('bt.reliability_caption')}</p></div>
    <div class="card">${lineChart(adv, { title: tp('bt.advantage_title'), summary: tp('bt.advantage_summary'), xLabel: tp('bt.advantage_x'), zeroLine: true, fmtY: (y) => y.toFixed(2) })}<p class="cap">${t('bt.advantage_caption')}</p></div>
    <div class="card" style="grid-column:1/-1">${equityChart(runs, { width: 1100, height: 300 })}<p class="cap">${t('bt.equity_caption')}</p></div></div>`;
  return h;
}

// Runs made before results.json existed: their tables and figures as written.
function legacy(run) {
  const [scores, betsT] = run.tables;
  let h = `<p class="muted">${run.lines.map(esc).join(' · ')}</p>`;
  if (scores) h += table(scores[0].map(esc), scores.slice(1).map((r) => r.map(esc)));
  if (betsT) h += '<br>' + table(betsT[0].map(esc), betsT.slice(1).map((r) => r.map(esc)));
  return h + `<div class="grid cols-3" style="margin-top:12px">${run.figures.map((f) => `<img style="width:100%;border-radius:8px;border:1px solid var(--rule)" src="/api/backtests/${encodeURIComponent(run.domain)}/${encodeURIComponent(run.stamp)}/${encodeURIComponent(f)}" alt="${esc(f)}">`).join('')}</div>`;
}

const OFFERED = ['market', 'constant', 'elo', 'climatology'];

// The form that starts a backtest (hosted): what it covers and costs is
// shown before it runs, and its progress below it.
async function form(o) {
  const caps = await api('capabilities');
  const names = OFFERED.concat(caps?.llm ? ['llm'] : []);
  const domains = orderedDomains(o.domains);
  after(() => {
    const f = document.getElementById('bt-form'), status = document.getElementById('bt-estimate');
    const body = () => {
      const data = {
        domain: f.domain.value,
        forecasters: [...f.querySelectorAll('input[name=forecasters]:checked')].map((x) => x.value),
      };
      if (f.hours) data.hours_before_close = Number(f.hours.value);
      if (f.max && f.max.value) data.max_markets = Number(f.max.value);
      if (f.batch) data.batch = f.batch.checked;
      return data;
    };
    const estimate = async () => {
      const data = body();
      if (!data.forecasters.length) { status.textContent = tp('bt.form.pick_one'); return; }
      try {
        const e = await send('POST', 'backtests/estimate', data);
        status.innerHTML = e.estimate_usd > 0
          ? t('bt.form.cost', { n: e.markets, cost: fmt.money(e.estimate_usd), left: fmt.money(e.remaining_usd), limit: fmt.money(e.limit_usd) })
          : t('bt.form.free', { n: e.markets });
      } catch (err) { status.textContent = err.message; }
    };
    f.addEventListener('change', estimate);
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const button = f.querySelector('button[type=submit]');
      button.disabled = true;
      try {
        await send('POST', 'backtests', body());
        status.textContent = tp('bt.form.queued');
        await render(false);
      } catch (err) { status.textContent = err.message; button.disabled = false; }
    });
    estimate();
  });
  const label = (n) => (detailed() ? n : strategyLabel(n));
  return `<section class="card" style="margin-bottom:18px"><h2 style="margin-top:0">${t('bt.form.title')}</h2>
    <form id="bt-form"><div class="row">
      <label for="bt-domain" class="small muted">${t('bt.form.domain')}</label>
      <select id="bt-domain" name="domain">${domains.map(([name, d]) => `<option value="${esc(name)}">${esc(d.title)}</option>`).join('')}</select></div>
      <fieldset><legend class="small">${t('bt.form.strategies')}</legend><div class="row" style="margin:0">${names.map((n) =>
        `<label class="check"><input type="checkbox" name="forecasters" value="${n}"${['market', 'constant'].includes(n) ? ' checked' : ''}> <span>${esc(label(n))}</span></label>`).join('')}</div></fieldset>
      ${detailed() ? `<div class="row"><label for="bt-hours" class="small muted">${t('bt.form.hours')}</label>
        <input type="text" inputmode="decimal" id="bt-hours" name="hours" value="24" style="width:6em">
        <label for="bt-max" class="small muted">${t('bt.form.max')}</label>
        <input type="text" inputmode="numeric" id="bt-max" name="max" placeholder="${tp('bt.form.all')}" style="width:8em"></div>` : ''}
      ${caps?.llm ? `<label class="check" style="margin-bottom:10px"><input type="checkbox" name="batch"> <span>${t('bt.form.batch')}</span></label>` : ''}
      <p class="small" id="bt-estimate" role="status"></p>
      <button class="btn primary" type="submit">${t('bt.form.run')}</button></form></section>`
    + jobsPanel(['backtest'], { onDone: () => { location.hash = '#backtests/0'; render(false); } });
}

export default async function backtests([sel, cmp] = []) {
  const [runs, o] = await Promise.all([api('backtests'), api('overview')]);
  let h = head(t('bt.title'), t('bt.lede'));
  if (session.hosted) h += await form(o);
  if (!runs.length) {
    return h + (session.hosted
      ? `<p class="muted">${t('bt.form.none_yet')}</p>`
      : empty(t('bt.empty_title'), t('bt.empty_text'), [['#learn/backtest', t('learn.topics.backtest.title')]], 'vp backtest --domain <domain> --forecasters market elo'));
  }
  const i = Math.min(Math.max(+sel || 0, 0), runs.length - 1), run = runs[i];
  const other = detailed() && cmp !== undefined && cmp !== '' && runs[+cmp]?.results ? runs[+cmp].results : null;
  const title = (r) => o.domains[r.domain]?.title ?? r.domain;
  h += `<label for="run" class="small muted">${t('bt.pick')}</label>
    <div class="row"><select id="run">${runs.map((r, j) => `<option value="${j}"${j === i ? ' selected' : ''}>${esc(title(r))} · ${esc(fmt.dateTime(stampIso(r.stamp)))}${r.results ? ` · ${esc(tp('bt.scored', { n: r.results.common }))}` : ''}</option>`).join('')}</select>
    ${detailed() ? `<label class="small muted" for="cmp">${t('bt.compare')}</label><select id="cmp"><option value="">${t('bt.compare_none')}</option>${runs.map((r, j) => (j !== i && r.results ? `<option value="${j}"${runs[+cmp] === r ? ' selected' : ''}>${esc(title(r))} · ${esc(fmt.dateTime(stampIso(r.stamp)))}</option>` : '')).join('')}</select>` : ''}</div>`;
  after(() => {
    document.getElementById('run').addEventListener('change', (e) => { location.hash = '#backtests/' + e.target.value; });
    document.getElementById('cmp')?.addEventListener('change', (e) => { location.hash = `#backtests/${i}/${e.target.value}`; });
  });
  const res = run.results;
  if (!res) return h + legacy(run);
  if (!res.common) return h + `<p>${t('bt.nothing_scored', { title: title(run), hours: res.config.hours_before_close })}</p>`;
  h += `<p>${t('bt.run_line', { title: title(run), n: res.common, hours: res.config.hours_before_close })}</p>` + cautions(res);
  return h + (detailed() ? full(res, other) : simple(res));
}
