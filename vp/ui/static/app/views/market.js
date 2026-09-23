// One market: the question, its chance and how that has moved across the
// snapshots, when it closes, what buying costs, and what the sample
// strategies forecast for it. Detailed adds the order book, the fee
// formula, the fields the parser read and the identifiers.
import { api } from '../api.js';
import { dayTicks, lineChart } from '../charts.js';
import { chance, detailed, esc, feePerShare, feeSentence, fmt, head, kindName, strategyLabel, strategyName, t, table, term, tp } from '../ui.js';

export default async function market([domain, id] = []) {
  const m = domain && id ? await api(`markets/${encodeURIComponent(domain)}/${encodeURIComponent(id)}`) : null;
  const back = `<p><a href="#markets/${encodeURIComponent(domain || '')}">${t('market.back')}</a></p>`;
  if (!m) return back + head(t('market.missing_title'), t('market.missing_text'));
  let h = back + head(esc(m.question), m.event && m.event !== m.question ? esc(m.event) : '');
  const width = m.p_yes == null ? 0 : Math.round(100 * m.p_yes);
  h += `<div class="card hero"><div class="chance"><b style="font-size:34px">${chance(m)}</b></div>
    <div class="meter" aria-hidden="true" style="margin:8px 0 12px"><i style="width:${width}%"></i></div>
    <p>${t('market.explain', { outcome: m.outcomes[0], pct: fmt.pct(m.p_yes) })}</p>
    <div class="facts"><span>${m.end_date ? t(new Date(m.end_date).getTime() < Date.now() ? 'market.overdue' : 'market.closes', { when: fmt.relative(m.end_date), date: fmt.dateTime(m.end_date) }) : t('markets.no_close')}</span>
    <span>${feeSentence(m)}</span>${m.has_book ? '' : `<span>${t('markets.no_book')}</span>`}</div></div>`;

  const points = m.series.map((s) => [new Date(s.at).getTime(), s.p_yes]);
  h += `<h2>${t('market.history_title')}</h2>`;
  h += points.length > 1
    ? `<div class="card">${lineChart([{ name: tp('market.series', { outcome: m.outcomes[0] }), color: 'var(--accent)', points }], {
      summary: tp('market.history_summary', { n: points.length, first: fmt.pct(points[0][1]), last: fmt.pct(points[points.length - 1][1]) }),
      yDomain: [0, 1], fmtY: (y) => fmt.pct(y), fmtX: (x) => fmt.shortDate(x), xTicks: dayTicks, height: 220 })}</div>`
    : `<p class="muted">${t('market.history_later')}</p>`;

  h += `<h2>${t('market.forecasts_title')}</h2>`;
  if (!m.forecasts.length) h += `<p class="muted">${t('market.no_forecasts')}</p>`;
  else if (detailed()) {
    h += table([t('col.strategy'), term('phat', tp('glossary.phat.name')), term('cutoff', tp('glossary.cutoff.name'))],
      m.forecasts.map((f) => [strategyName(f.forecaster), esc(fmt.num(f.p_hat, 3)), esc(fmt.dateTime(f.cutoff))]));
  } else {
    h += `<ul class="notes">${m.forecasts.map((f) => `<li>${t('market.forecast_line', { name: strategyLabel(f.forecaster), pct: fmt.pct(f.p_hat), when: fmt.relative(f.cutoff) })}</li>`).join('')}</ul>`;
  }

  if (detailed()) {
    const depth = Math.max(m.book.bids.length, m.book.asks.length);
    h += `<h2>${t('market.book_title')}</h2>`;
    h += depth ? table([term('bid', tp('glossary.bid.name')), t('col.size'), term('ask', tp('glossary.ask.name')), t('col.size')],
      Array.from({ length: depth }, (_, i) => [m.book.bids[i], m.book.asks[i]].flatMap((l) => (l ? [esc(fmt.num(l.price, 3)), esc(fmt.num(l.size, 1))] : ['', '']))),
      { numFrom: 0, caption: t('market.book_caption', { outcome: m.outcomes[0] }) }) : `<p class="muted">${t('markets.no_book')}</p>`;
    h += `<h2>${term('fee', tp('glossary.fee.name'))}</h2>`;
    h += m.fee_rate == null ? `<p>${t('fees.unknown')}</p>`
      : `<p class="formula">fee = C · ${esc(fmt.num(m.fee_rate, 3))} · (p(1 − p))^${esc(fmt.num(m.fee_exponent, 0))}</p>
         <p>${t('fees.detailed', { rate: fmt.num(m.fee_rate, 3), ask: fmt.num(m.ask, 3), fee: fmt.num(feePerShare(m.ask, m.fee_rate, m.fee_exponent), 4) })}</p>`;
    h += `<h2>${t('market.fields_title')}</h2><dl class="kv">
      <dt>${term('kind', tp('glossary.kind.name'))}</dt><dd>${kindName(m.kind)}</dd>
      ${Object.entries(m.parsed).filter(([k]) => k !== 'kind').map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}
      <dt>${t('market.outcomes')}</dt><dd>${m.outcomes.map(esc).join(' / ')}</dd>
      <dt>${t('market.volume')}</dt><dd class="num">${esc(fmt.money(m.volume_usd, 0))}</dd>
      <dt>${t('market.liquidity')}</dt><dd class="num">${esc(fmt.money(m.liquidity_usd, 0))}</dd>
      <dt>${t('market.market_id')}</dt><dd class="mono">${esc(m.market_id)}</dd>
      <dt>${t('market.captured')}</dt><dd>${esc(fmt.dateTime(m.fetched_at))}</dd></dl>`;
  }
  return h;
}
