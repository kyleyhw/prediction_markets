// Risk (hosted only, Phase 20; docs/portfolio.md): every open paper
// position of the workspace as one portfolio. Simple says the most that
// could be lost this week and what 19 weeks in 20 would stay under;
// Detailed adds the whole book, the favourites-win scenario and where the
// stake is concentrated. Positions of one event are modelled together:
// of a day's buckets, at most one can win.
import { api, session } from '../api.js';
import { detailed, empty, esc, fmt, head, level, signed, t, table, tp } from '../ui.js';

const measures = (r) => [
  [t('risk.m.positions'), esc(fmt.int(r.positions))],
  [t('risk.m.stake'), esc(fmt.money(r.stake))],
  [t('risk.m.expected'), signed(r.expected, esc(fmt.signedMoney(r.expected)))],
  [t('risk.m.worst'), signed(r.worst_case, esc(fmt.signedMoney(r.worst_case)))],
  [t('risk.m.loss95'), esc(fmt.money(r.loss_95))],
  [t('risk.m.loss99'), esc(fmt.money(r.loss_99))],
  [t('risk.m.shortfall'), esc(fmt.money(r.shortfall_95))],
  [t('risk.m.favourites'), signed(r.favourites_win, esc(fmt.signedMoney(r.favourites_win)))],
];

const groups = (rows, caption) => table([t('risk.group'), t('risk.m.stake'), t('risk.share')],
  rows.map((g) => [esc(g.group), esc(fmt.money(g.stake)), esc(fmt.pct(g.share))]), { caption, numFrom: 1 });

export default async function risk() {
  if (!session.hosted) return head(t('risk.title')) + empty(t('team.local'), t('team.local_text'), [['#home', t('error.home')]]);
  const r = await api('risk');
  let h = head(t('risk.title'), level(t('risk.lede_simple'), t('risk.lede_detailed')));
  if (!r.all.positions) return h + empty(t('risk.none'), t('risk.none_text'), [['#strategies', t('nav.strategies')]]);
  const w = r.week;
  if (w.positions) {
    const share = r.bankroll ? Math.min(-w.worst_case / r.bankroll, 1) : 0;
    h += `<div class="card hero"><p style="margin-top:0">${t('risk.week', { worst: fmt.money(-w.worst_case), q: fmt.money(w.loss_95) })}</p>
      <div class="meter" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(100 * share)}" aria-label="${esc(tp('risk.meter', { pct: fmt.pct(share) }))}"><i style="width:${(100 * share).toFixed(1)}%"></i></div>
      <p class="small muted">${t('risk.meter', { pct: fmt.pct(share) })}</p></div>`;
  } else h += `<p class="measure">${t('risk.week_none')}</p>`;
  h += `<p class="measure">${t('risk.all', { n: r.all.positions, worst: fmt.money(-r.all.worst_case), fav: fmt.signedMoney(r.all.favourites_win) })}</p>`;
  if (detailed()) {
    h += `<h2>${t('risk.numbers')}</h2>` + table([t('risk.measure'), t('risk.all_col'), t('risk.week_col')],
      measures(r.all).map((row, i) => [row[0], row[1], w.positions ? measures(w)[i][1] : '–']), { caption: t('risk.numbers_caption'), numFrom: 1 });
    h += `<h2>${t('risk.where')}</h2>` + groups(r.all.by_domain, t('risk.by_domain')) + groups(r.all.by_event, t('risk.by_event'))
      + groups(r.all.by_date, t('risk.by_date')) + groups(r.all.by_strategy, t('risk.by_strategy'));
    h += `<p class="small muted measure">${t('risk.model', { rho: fmt.num(r.all.model.event_rho, 1), day: fmt.num(r.all.model.day_rho, 1), n: fmt.int(r.all.model.draws) })}</p>`;
  }
  return h + `<p class="small muted measure">${t('risk.play')}</p>`;
}
