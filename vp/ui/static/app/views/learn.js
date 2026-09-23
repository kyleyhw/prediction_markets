// Learn: short pages from "what is a prediction market" up. Simple shows
// the plain-language page and its picture; Detailed adds the formulas, the
// documentation page that carries the derivation, and the references.
import { lineChart } from '../charts.js';
import { entry } from '../i18n.js';
import { detailed, esc, fmt, head, t, tp } from '../ui.js';

const TOPICS = ['markets', 'price', 'backtest', 'paper', 'fees', 'hard'];

// The pictures, drawn in the page like every other chart.
const FIGURES = {
  price: () => `<figure class="figure card"><div class="chance"><b class="num" style="font-size:30px">${t('markets.chance', { pct: fmt.pct(0.62) })}</b></div>
    <div class="meter" aria-hidden="true" style="margin:8px 0"><i style="width:62%"></i></div>
    <div class="facts"><span>${t('learn.figure_price_yes', { price: fmt.cents(0.62, 0) })}</span><span>${t('learn.figure_price_no', { price: fmt.cents(0.38, 0) })}</span></div>
    <figcaption>${t('learn.figure_price_caption')}</figcaption></figure>`,
  backtest: () => {
    const x = (f) => 40 + f * 560;
    return `<figure class="figure card"><svg viewBox="0 0 640 110" role="img" aria-label="${esc(tp('learn.figure_backtest_summary'))}" style="width:100%;height:auto">
      <line x1="${x(0)}" x2="${x(1)}" y1="60" y2="60" stroke="var(--axis)" stroke-width="2"/>
      <rect x="${x(0)}" y="52" width="${x(0.62) - x(0)}" height="16" fill="var(--accent)" opacity=".22"/>
      <line x1="${x(0.62)}" x2="${x(0.62)}" y1="30" y2="90" stroke="var(--accent)" stroke-width="2"/>
      <circle cx="${x(0.9)}" cy="60" r="6" fill="var(--ink)"/>
      <g font-size="13" fill="var(--ink)"><text x="${x(0.31)}" y="44" text-anchor="middle">${esc(tp('learn.figure_backtest_known'))}</text>
      <text x="${x(0.62)}" y="22" text-anchor="middle">${esc(tp('learn.figure_backtest_cutoff'))}</text>
      <text x="${x(0.9)}" y="92" text-anchor="middle">${esc(tp('learn.figure_backtest_settled'))}</text></g></svg>
      <figcaption>${t('learn.figure_backtest_caption')}</figcaption></figure>`;
  },
  fees: () => {
    const points = Array.from({ length: 21 }, (_, i) => [i / 20, 0.05 * (i / 20) * (1 - i / 20) * 100]);
    return `<figure class="figure card">${lineChart([{ name: tp('learn.figure_fees_series'), color: 'var(--accent)', points }], {
      summary: tp('learn.figure_fees_summary'), xLabel: tp('learn.figure_fees_x'), yLabel: tp('learn.figure_fees_y'),
      xDomain: [0, 1], fmtX: (v) => fmt.pct(v), fmtY: (v) => v.toFixed(2), height: 220 })}<figcaption>${t('learn.figure_fees_caption')}</figcaption></figure>`;
  },
};

export default async function learn([topic] = []) {
  if (!TOPICS.includes(topic)) {
    return head(t('learn.title'), t('learn.lede')) + `<div class="grid cols-2">${TOPICS.map((id) =>
      `<article class="card"><h2 style="margin-top:0;font-size:17px"><a href="#learn/${id}">${t(`learn.topics.${id}.title`)}</a></h2><p class="muted">${t(`learn.topics.${id}.blurb`)}</p></article>`).join('')}</div>`;
  }
  const page = entry('learn.topics.' + topic);
  const paras = (list) => (list || []).map((p) => `<p>${esc(p)}</p>`).join('');
  let h = `<p><a href="#learn">${t('learn.back')}</a></p>` + head(t(`learn.topics.${topic}.title`));
  h += `<div class="learn"><article>${paras(page.simple)}${FIGURES[topic] ? FIGURES[topic]() : ''}`;
  if (detailed()) {
    h += `<h2>${t('learn.in_detail')}</h2>${paras(page.detailed)}`;
    if (page.doc) h += `<p class="muted small">${t('glossary_doc', { doc: page.doc })}</p>`;
    if (page.refs?.length) h += `<h2>${t('learn.references')}</h2><ul class="notes small">${page.refs.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>`;
  } else if (page.detailed?.length) {
    h += `<p class="small muted">${t('learn.more_in_detailed')}</p>`;
  }
  const next = TOPICS[TOPICS.indexOf(topic) + 1];
  h += `</article></div>${next ? `<p style="margin-top:24px"><a class="btn" href="#learn/${next}">${t('learn.next', { title: tp(`learn.topics.${next}.title`) })}</a></p>` : ''}`;
  return h;
}
