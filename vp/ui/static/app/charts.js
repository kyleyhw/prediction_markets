// Charts drawn in the page as inline SVG, in the theme's colours. Every
// chart has a one-sentence summary for screen readers and a "show the
// numbers" table beside it, so nothing is carried by the picture alone; the
// hover crosshair is a convenience on top.
import { after, esc, t } from './ui.js';

// A fixed colour per sample strategy, so one keeps its colour everywhere.
const SLOTS = { market: 1, constant: 2, elo: 3, climatology: 4, llm: 5 };
export const colorOf = (name) => `var(--s${SLOTS[name] ?? 6})`;
export const BASELINE = 'var(--axis)';

function niceTicks(a, b, n) {
  const raw = (b - a) / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p, out = [];
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

let tip;
function showTip(e, html) {
  tip = tip || document.getElementById('tip');
  tip.innerHTML = html; tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 12) + 'px';
  tip.style.top = Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 12) + 'px';
}
const hideTip = () => { if (tip) tip.style.display = 'none'; };

// series: [{name, color, dash, points: [[x, y], ...]}]
// opts: {title, summary, xLabel, yLabel, xDomain, yDomain, diagonal, zeroLine,
//        dots, width, height, fmtX, fmtY}
export function lineChart(series, opts = {}) {
  series = series.filter((s) => s.points.length);
  if (!series.length) return '';
  const W = opts.width || 640, H = opts.height || 260, m = { l: 60, r: 14, t: 10, b: opts.xLabel ? 44 : 28 };
  const xs = series.flatMap((s) => s.points.map((p) => p[0])), ys = series.flatMap((s) => s.points.map((p) => p[1]));
  let [x0, x1] = opts.xDomain || [Math.min(...xs), Math.max(...xs)];
  let [y0, y1] = opts.yDomain || [Math.min(...ys), Math.max(...ys)];
  if (opts.zeroLine) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
  if (x1 === x0) x1 = x0 + 1;
  if (y1 === y0) { y1 = y0 + Math.max(1, Math.abs(y0) * 0.01); y0 -= Math.max(1, Math.abs(y0) * 0.01); }
  if (!opts.yDomain) { const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad; }
  const sx = (x) => m.l + ((x - x0) / (x1 - x0)) * (W - m.l - m.r);
  const sy = (y) => m.t + (1 - (y - y0) / (y1 - y0)) * (H - m.t - m.b);
  const minus = (s) => String(s).replace(/^-/, '−');
  const fx = (v) => minus((opts.fmtX || ((x) => (Number.isInteger(x) ? x : x.toFixed(2))))(v));
  const fy = (v) => minus((opts.fmtY || ((y) => (Math.abs(y) >= 100 ? Math.round(y) : y.toFixed(2))))(v));
  let g = '<g class="axis" fill="var(--muted)" font-size="11">';
  for (const v of niceTicks(y0, y1, 4)) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${sy(v)}" y2="${sy(v)}" stroke="var(--rule)"/><text x="${m.l - 8}" y="${sy(v) + 4}" text-anchor="end">${esc(fy(v))}</text>`;
  const xt = opts.xTicks ? opts.xTicks(x0, x1) : niceTicks(x0, x1, 5);
  for (const v of xt) g += `<text x="${sx(v)}" y="${H - m.b + 16}" text-anchor="middle">${esc(fx(v))}</text>`;
  g += `<line x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}" stroke="var(--axis)"/>`;
  if (opts.zeroLine && y0 < 0 && y1 > 0) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${sy(0)}" y2="${sy(0)}" stroke="var(--axis)"/>`;
  if (opts.diagonal) g += `<line x1="${sx(0)}" y1="${sy(0)}" x2="${sx(1)}" y2="${sy(1)}" stroke="var(--axis)"/>`;
  if (opts.xLabel) g += `<text x="${(m.l + W - m.r) / 2}" y="${H - 6}" text-anchor="middle">${esc(opts.xLabel)}</text>`;
  if (opts.yLabel) g += `<text transform="translate(12 ${(m.t + H - m.b) / 2}) rotate(-90)" text-anchor="middle">${esc(opts.yLabel)}</text>`;
  g += '</g>';
  for (const s of series) {
    const d = s.points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`).join(' ');
    g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"${s.dash ? ' stroke-dasharray="6 5"' : ''}/>`;
    if (opts.dots || s.points.length === 1) g += s.points.map((p) => `<circle cx="${sx(p[0])}" cy="${sy(p[1])}" r="4" fill="${s.color}" stroke="var(--surface)" stroke-width="2"/>`).join('');
  }
  const id = 'c' + Math.random().toString(36).slice(2, 9);
  const svg = `<svg viewBox="0 0 ${W} ${H}" id="${id}" role="img" aria-label="${esc(opts.summary || opts.title || '')}">${g}<line id="${id}x" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)" style="display:none"/><rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/></svg>`;
  const legend = series.length > 1 ? `<div class="legend">${series.map((s) => `<span><i class="${s.dash ? 'dash' : ''}" style="border-color:${s.color}"></i>${esc(s.name)}</span>`).join('')}</div>` : '';
  after(() => {
    const el = document.getElementById(id);
    if (!el) return;
    const cross = document.getElementById(id + 'x');
    el.addEventListener('mousemove', (e) => {
      const r = el.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * W;
      const xv = x0 + ((px - m.l) / (W - m.l - m.r)) * (x1 - x0);
      const near = series.map((s) => [s, s.points.reduce((b, p) => (!b || Math.abs(p[0] - xv) < Math.abs(b[0] - xv) ? p : b), null)]);
      cross.style.display = ''; cross.setAttribute('x1', sx(near[0][1][0])); cross.setAttribute('x2', sx(near[0][1][0]));
      showTip(e, `<b>${esc(fx(near[0][1][0]))}</b>` + near.map(([s, p]) => `<div class="r"><span>${esc(s.name)}</span><b>${esc(fy(p[1]))}</b></div>`).join(''));
    });
    el.addEventListener('mouseleave', () => { cross.style.display = 'none'; hideTip(); });
  });
  return `<figure class="chart" style="margin:0">${opts.title ? `<div class="title">${esc(opts.title)}</div>` : ''}${svg}${legend}${dataTable(series, fx, fy, opts)}</figure>`;
}

// The numbers behind a chart, one row per x, one column per series.
function dataTable(series, fx, fy, opts) {
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => a - b).slice(0, 500);
  const at = series.map((s) => new Map(s.points.map((p) => [p[0], p[1]])));
  const rows = xs.map((x) => `<tr><td class="num">${esc(fx(x))}</td>${at.map((m) => `<td class="num">${m.has(x) ? esc(fy(m.get(x))) : ''}</td>`).join('')}</tr>`).join('');
  return `<details class="data"><summary>${t('chart.numbers')}</summary><div class="wrap"><table><thead><tr><th scope="col" class="num">${esc(opts.xLabel || '')}</th>${
    series.map((s) => `<th scope="col" class="num">${esc(s.name)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></details>`;
}

// Time on the x axis: ticks at whole days, labelled by the locale.
export function dayTicks(x0, x1) {
  const day = 86400000, span = x1 - x0, step = Math.max(1, Math.ceil(span / day / 5)) * day, out = [];
  for (let v = Math.ceil(x0 / day) * day; v <= x1; v += step) out.push(v);
  return out.length ? out : [x0];
}

export function spark(points, color, label, w = 140, h = 34) {
  if (points.length < 2) return '';
  const y0 = Math.min(...points), y1 = Math.max(...points);
  const sx = (i) => (i / (points.length - 1)) * (w - 6) + 3;
  const sy = (v) => (y1 === y0 ? h / 2 : 3 + (1 - (v - y0) / (y1 - y0)) * (h - 6));
  const d = points.map((v, i) => `${i ? 'L' : 'M'}${sx(i).toFixed(1)} ${sy(v).toFixed(1)}`).join(' ');
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}"><path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/></svg>`;
}
