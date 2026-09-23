// Signals (docs/signals.md): the library of tested signals, each scored
// against the market on the same markets (the bench), and the public
// benchmark's weeks. Every figure is the bench's or the benchmark's own.
import { api } from '../api.js';
import { detailed, empty, esc, fmt, head, t, table } from '../ui.js';

const VERDICTS = ['alive', 'par', 'anti', 'too few'];
const verdictKey = (v) => 'signals.verdict.' + v.replace(' ', '_');

function domainBench(domain, title, b) {
  const rows = Object.entries(b.signals);
  const counts = Object.fromEntries(VERDICTS.map((v) => [v, rows.filter(([, r]) => r.verdict === v).length]));
  let h = `<h3>${esc(title)}</h3><p>${t('signals.domain_line', { alive: counts.alive, par: counts.par, anti: counts.anti, few: counts['too few'], n: rows.length, markets: fmt.int(b.with_price) })}</p>`;
  if (!detailed()) {
    return h + `<ul class="notes">${rows.map(([, r]) => `<li>${esc(r.title)}: ${t(verdictKey(r.verdict))}</li>`).join('')}</ul>`;
  }
  h += table([t('signals.col_signal'), t('signals.col_verdict'), t('signals.col_n'), t('signals.col_advantage'), t('signals.col_needed'), t('signals.col_price')],
    rows.map(([id, r]) => [`${esc(r.title)} <code class="small">${esc(id)}</code>`, `<span class="pill${r.verdict === 'alive' ? ' ok' : r.verdict === 'anti' ? ' bad' : ''}">${t(verdictKey(r.verdict))}</span>`,
      esc(fmt.int(r.n)), r.advantage ? esc(`${fmt.signed(r.advantage.mean, 4)} [${fmt.num(r.advantage.low, 4)}, ${fmt.num(r.advantage.high, 4)}]`) : '–',
      r.needed_n == null ? '–' : esc(fmt.int(r.needed_n)), r.uses_price ? t('signals.yes') : t('signals.no')]),
    { numFrom: 2, caption: t('signals.bench_caption', { hours: b.hours }) });
  return h + `<p class="small muted">${t('signals.reproduce')} <code>${esc(b.command)}</code></p>`;
}

function week(w) {
  let h = `<div class="card" style="margin-bottom:12px"><h3 style="margin-top:0">${t('signals.week_title', { week: w.week })}</h3>
    <p>${t(w.scored_at ? 'signals.week_scored' : 'signals.week_sealed', { n: w.questions.length, configs: w.entries.length, when: fmt.dateTime(w.frozen_at) })}</p>`;
  if (detailed()) {
    const scored = w.entries.filter((e) => e.score);
    h += scored.length
      ? table([t('signals.col_config'), t('signals.col_n'), t('signals.col_brier'), t('signals.col_skill'), t('signals.col_ranked')],
        scored.map((e) => [esc(e.config), esc(fmt.int(e.score.n)), esc(fmt.num(e.score.brier, 4)), esc(fmt.signed(e.score.skill, 3)), e.score.ranked ? t('signals.yes') : t('signals.no')]),
        { numFrom: 1, caption: t('signals.scores_caption') })
      : `<ul class="notes small mono">${w.entries.map((e) => `<li>${esc(e.config)}: ${esc(e.commitment.slice(0, 16))}…</li>`).join('')}</ul>`;
    h += `<p class="small muted mono">${t('signals.week_hash', { hash: w.hash.slice(0, 16), seed: w.seed })}</p>`;
  }
  return h + '</div>';
}

export default async function signals() {
  const [s, weeks, overview] = await Promise.all([api('signals'), api('benchmark'), api('overview')]);
  const titles = Object.fromEntries(Object.entries(overview?.domains || {}).map(([name, d]) => [name, d.title]));
  let h = head(t('signals.title'), t('signals.lede'));
  // A domain where no signal applies has nothing to show.
  const benches = Object.entries(s?.bench || {}).filter(([, b]) => Object.keys(b.signals).length);
  h += `<h2>${t('signals.bench_title')}</h2>`;
  h += benches.length
    ? benches.map(([d, b]) => domainBench(d, titles[d] || d, b)).join('')
    : empty(t('signals.no_bench_title'), t('signals.no_bench_text'), [], 'vp signals bench --domain <domain>');
  h += `<h2>${t('signals.benchmark_title')}</h2><p class="muted measure">${t('signals.benchmark_text')}</p>`;
  h += weeks?.length ? weeks.map(week).join('') : `<p class="muted">${t('signals.no_weeks')}</p>`;
  if (detailed() && s?.signals) {
    h += `<h2>${t('signals.library_title')}</h2>` + s.signals.map((x) => `<details><summary><b>${esc(x.title)}</b> <code class="small">${esc(x.id)}</code></summary>
      <p class="small">${t('signals.cutoff', { text: x.cutoff })} ${t('signals.warmup', { text: x.warmup })}${x.uses_price ? ' ' + t('signals.reads_price') : ''}</p>
      <ul class="notes small">${x.references.map((r) => `<li>${esc(r)}</li>`).join('')}</ul></details>`).join('');
  }
  return h;
}
