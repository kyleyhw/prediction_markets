// Your record (hosted only, Phase 19; docs/shadow.md): paste a public
// address, agree to link it, and read what the trades say about the person
// as a forecaster, the rule that describes them if one holds on held-out
// data, and where the gap between them and that rule comes from. Every
// figure comes from the card the import job computed; none is written by a
// model.
import { api, send, session } from '../api.js';
import { render } from '../main.js';
import { jobsPanel } from '../work.js';
import { after, detailed, empty, esc, fmt, head, signed, t, table, tp } from '../ui.js';

const short = (a) => `${a.slice(0, 6)}…${a.slice(-4)}`;
const pts = (v) => fmt.num(100 * v, 1);
const iv = (x, f = pts) => (x ? `${f(x.mean)} [${f(x.low)}, ${f(x.high)}]` : '–');

function importForm(consent) {
  after(() => document.getElementById('shadow-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = document.getElementById('shadow-status');
    const address = document.getElementById('shadow-address').value.trim();
    if (!document.getElementById('shadow-consent').checked) { status.textContent = tp('shadow.consent_needed'); return; }
    try {
      const made = await send('POST', 'shadow', { address, consent: true });
      location.hash = `#shadow/${made.id}`;
    } catch (err) { status.textContent = err.message; }
  }));
  return `<form id="shadow-form" class="measure"><div class="row"><label for="shadow-address">${t('shadow.address')}</label>
    <input type="text" id="shadow-address" required minlength="42" maxlength="42" placeholder="0x…" autocomplete="off" spellcheck="false" style="min-width:24em" class="mono"></div>
    <label class="check"><input type="checkbox" id="shadow-consent"> <span>${esc(consent)}</span></label>
    <div class="row" style="margin-top:12px"><button class="btn primary" type="submit">${t('shadow.import')}</button></div>
    <p id="shadow-status" class="small" role="status"></p></form>`;
}

// The one habit that cost the most, in words, or none.
function habit(hb, o) {
  if (hb.longshot.stake_share > 0.1 && hb.longshot.win_rate != null && hb.longshot.win_rate < hb.longshot.mean_price) {
    return t('shadow.habit_longshot', { share: fmt.pct(hb.longshot.stake_share), won: fmt.pct(hb.longshot.win_rate), price: fmt.pct(hb.longshot.mean_price) });
  }
  if (hb.chased_share > 0.2 && hb.clv_chased != null && hb.clv_calm != null && hb.clv_chased < hb.clv_calm) {
    return t('shadow.habit_chasing', { share: fmt.pct(hb.chased_share), chased: pts(hb.clv_chased), calm: pts(hb.clv_calm) });
  }
  if (hb.return_sold_early != null && hb.return_held != null && hb.return_sold_early < hb.return_held) {
    return t('shadow.habit_selling', { early: fmt.signedPct(hb.return_sold_early), held: fmt.signedPct(hb.return_held) });
  }
  if (hb.fee_drag != null && hb.fee_drag > 0.3) return t('shadow.habit_fees', { share: fmt.pct(hb.fee_drag) });
  return o.scored ? t('shadow.habit_none') : '';
}

function ruleBlock(c, iid) {
  const found = Object.entries(c.rules).flatMap(([domain, r]) => r.rules.map((x, i) => ({ ...x, domain, index: i })));
  const good = found.filter((x) => x.validated);
  let h = `<h2>${t('shadow.rule_title')}</h2>`;
  if (!good.length) h += `<p class="muted measure">${t(found.length ? 'shadow.rule_none' : 'shadow.rule_no_domain')}</p>`;
  for (const r of good) {
    h += `<div class="card" style="margin-bottom:12px"><p style="margin-top:0"><b>${esc(r.words)}</b></p>
      <p class="small muted">${t('shadow.rule_held', { coverage: fmt.pct(r.held_out.coverage), agreement: fmt.pct(r.held_out.agreement), lift: fmt.num(r.held_out.lift, 1) })}</p>
      <button class="btn primary" type="button" data-try="${esc(r.domain)}:${r.index}">${t('shadow.try')}</button></div>`;
  }
  if (detailed() && found.length) {
    h += table([t('shadow.col_rule'), t('shadow.col_origin'), t('shadow.col_fit'), t('shadow.col_held'), t('shadow.col_valid')],
      found.map((r) => [esc(r.words), t('shadow.origin.' + r.origin), esc(`${fmt.pct(r.formation.coverage)} · ${fmt.num(r.formation.lift, 1)}×`),
        esc(`${fmt.pct(r.held_out.coverage)} · ${fmt.pct(r.held_out.agreement)} · ${fmt.num(r.held_out.lift, 1)}× · ${r.held_out.agreed}`),
        t(r.validated ? 'shadow.yes' : 'shadow.no')]), { caption: t('shadow.rules_caption'), numFrom: 2 });
  }
  after(() => document.querySelectorAll('[data-try]').forEach((b) => b.addEventListener('click', async () => {
    const [domain, index] = b.dataset.try.split(':');
    b.disabled = true;
    try {
      const made = await send('POST', `shadow/${iid}/try`, { domain, index: Number(index) });
      location.hash = `#describe/new/${made.conversation_id}`;
    } catch (err) { document.getElementById('card-status').textContent = err.message; b.disabled = false; }
  })));
  return h;
}

function counterfactualBlock(c) {
  const rows = Object.entries(c.counterfactual).filter(([, v]) => v);
  if (!rows.length) return '';
  let h = `<h2>${t('shadow.cf_title')}</h2>`;
  for (const [domain, v] of rows) {
    h += `<p class="measure">${t('shadow.cf_line', { you: fmt.signedPct(v.you), rule: fmt.signedPct(v.rule), n: v.bets, m: v.rule_markets })}</p>`;
    if (detailed()) {
      h += table([t('shadow.part'), t('shadow.part_value')], ['sizing', 'timing', 'selection'].map((k) => [t('shadow.parts.' + k), esc(iv(v[k], (x) => fmt.signedPct(x)))]),
        { caption: t('shadow.cf_caption', { domain }), numFrom: 1 });
    }
  }
  return h + `<p class="small muted measure">${t('shadow.cf_note')}</p>`;
}

function detailedTables(c) {
  const o = c.diagnostics.overall, hb = c.diagnostics.habits;
  let h = `<h2>${t('shadow.measures')}</h2>`;
  h += table([t('shadow.measure'), t('shadow.value')], [
    [t('shadow.m.bets'), esc(`${fmt.int(o.scored)} / ${fmt.int(o.bets)}`)],
    [t('shadow.m.staked'), esc(fmt.money(o.staked, 0))],
    [t('shadow.m.return'), signed(o.return, esc(fmt.signedPct(o.return)))],
    [t('shadow.m.edge'), esc(iv(o.edge))],
    [t('shadow.m.brier'), esc(o.brier ? `${fmt.num(o.brier.entry, 4)} / ${fmt.num(o.brier.close, 4)}` : '–')],
    [t('shadow.m.log'), esc(o.log_loss ? `${fmt.num(o.log_loss.entry, 4)} / ${fmt.num(o.log_loss.close, 4)}` : '–')],
    [t('shadow.m.skill'), esc(o.skill_vs_close == null ? '–' : fmt.signed(o.skill_vs_close))],
    [t('shadow.m.clv'), esc(iv(o.clv))],
    [t('shadow.m.clv_pos'), esc(o.clv_positive == null ? '–' : fmt.pct(o.clv_positive))],
  ], { caption: t('shadow.measures_caption'), numFrom: 1 });
  h += table([t('shadow.band'), t('shadow.m.bets'), t('shadow.mean_price'), t('shadow.win_rate'), t('shadow.stake_share')],
    c.diagnostics.calibration.map((r) => [esc(`${fmt.pct(r.band[0])}–${fmt.pct(r.band[1])}`), esc(r.bets), esc(fmt.pct(r.mean_price)), esc(fmt.pct(r.win_rate)), esc(fmt.pct(r.stake_share))]),
    { caption: t('shadow.calibration_caption'), numFrom: 1 });
  const hv = (v, f) => (v == null ? '–' : f(v));
  h += `<h3>${t('shadow.habits')}</h3><dl class="kv">
    <dt>${t('shadow.h.longshot')}</dt><dd>${esc(`${fmt.pct(hb.longshot.stake_share)} · ${hv(hb.longshot.win_rate, fmt.pct)} / ${hv(hb.longshot.mean_price, fmt.pct)}`)}</dd>
    <dt>${t('shadow.h.favourite')}</dt><dd>${esc(`${fmt.pct(hb.favourite.stake_share)} · ${hv(hb.favourite.win_rate, fmt.pct)} / ${hv(hb.favourite.mean_price, fmt.pct)}`)}</dd>
    <dt>${t('shadow.h.holding')}</dt><dd>${esc(hv(hb.holding_hours_median, (v) => fmt.num(v, 1)))}</dd>
    <dt>${t('shadow.h.fills')}</dt><dd>${esc(hv(hb.fills_per_bet, (v) => fmt.num(v, 1)))}</dd>
    <dt>${t('shadow.h.early')}</dt><dd>${esc(`${hv(hb.sold_early_share, fmt.pct)} · ${hv(hb.return_sold_early, fmt.signedPct)} / ${hv(hb.return_held, fmt.signedPct)}`)}</dd>
    <dt>${t('shadow.h.chased')}</dt><dd>${esc(`${hv(hb.chased_share, fmt.pct)} · ${hv(hb.clv_chased, pts)} / ${hv(hb.clv_calm, pts)}`)}</dd>
    <dt>${t('shadow.h.sizing')}</dt><dd>${esc(`${hv(hb.stake_cv, (v) => fmt.num(v, 2))} · ${hv(hb.stake_clv_corr, (v) => fmt.signed(v, 2))} · ${fmt.pct(hb.top_tenth_stake_share)}`)}</dd>
    <dt>${t('shadow.h.fees')}</dt><dd>${esc(`${fmt.money(hb.fees_upper_bound, 0)} · ${hv(hb.fee_drag, fmt.pct)}`)}</dd></dl>`;
  const group = (g, caption) => (Object.keys(g).length ? table([t('shadow.group'), t('shadow.m.bets'), t('shadow.m.return'), t('shadow.m.edge'), t('shadow.m.clv')],
    Object.entries(g).map(([k, v]) => [esc(k), esc(v.scored), esc(fmt.signedPct(v.return)), esc(iv(v.edge)), esc(iv(v.clv))]), { caption, numFrom: 1 }) : '');
  h += group(c.diagnostics.by_domain, t('shadow.by_domain')) + group(c.diagnostics.by_month, t('shadow.by_month'));
  if (c.peer) {
    h += `<h3>${t('shadow.peer')}</h3><p class="measure">${t('shadow.peer_line', { pct: fmt.pct(c.peer.percentile), n: c.peer.listed, category: c.peer.category.toLowerCase(), median: fmt.signedPct(c.peer.median_listed) })}</p>
      <ul class="notes small">${c.peer.caveats.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`;
  }
  if (c.venue_pnl?.length) {
    const last = c.venue_pnl.at(-1);
    h += `<p class="small muted measure">${t('shadow.venue_pnl', { pnl: fmt.signedMoney(last.p, 0), when: fmt.date(new Date(last.t * 1000).toISOString()) })}</p>`;
  }
  return h;
}

function proofBlock(item) {
  after(() => document.getElementById('proof-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = document.getElementById('proof-status');
    try {
      const r = await send('POST', `shadow/${item.id}/verify`, { signature: document.getElementById('proof-sig').value.trim() });
      if (r.verified) await render(false); else status.textContent = tp('shadow.proof_failed');
    } catch (err) { status.textContent = err.message; }
  }));
  if (item.verified) return `<p><span class="pill ok">${t('shadow.verified')}</span></p>`;
  return `<details class="card"><summary>${t('shadow.proof_title')}</summary><p class="small muted measure">${t('shadow.proof_note')}</p>
    <pre class="mono small" style="white-space:pre-wrap">${esc(item.message)}</pre>
    <form id="proof-form"><label for="proof-sig">${t('shadow.proof_sig')}</label>
    <input type="text" id="proof-sig" required minlength="130" maxlength="132" class="mono" style="width:100%" autocomplete="off" spellcheck="false">
    <div class="row" style="margin-top:8px"><button class="btn" type="submit">${t('shadow.proof_check')}</button></div><p id="proof-status" class="small" role="status"></p></form></details>`;
}

function download(c) {
  const blob = new Blob([JSON.stringify(c, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `report-card-${c.address.slice(0, 8)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function one(iid) {
  const item = await api(`shadow/${iid}`);
  if (!item) return head(t('shadow.missing')) + empty(t('shadow.missing'), t('shadow.missing_text'), [['#shadow', t('shadow.back')]]);
  let h = `<p><a href="#shadow">${t('shadow.back')}</a></p>` + head(t('shadow.card_title', { address: short(item.address) }), '');
  h += `<p id="card-status" class="small" role="status"></p>`;
  if (item.state === 'queued' || item.state === 'running') {
    return h + `<p class="measure">${t('shadow.working')}</p>` + jobsPanel(['shadow_import'], { limit: 1, onDone: () => render(false) });
  }
  if (item.state === 'failed') return h + `<p class="neg">${t('shadow.failed', { error: item.error || '' })}</p>`;
  const c = item.card, o = c.diagnostics.overall, hb = c.diagnostics.habits;
  h += `<section class="card"><ul class="notes">`;
  h += o.scored
    ? `<li>${t('shadow.s_return', { n: o.scored, ret: fmt.signedPct(o.return), won: fmt.pct(o.win_rate), price: fmt.pct(o.mean_entry) })}</li>`
    : `<li>${t('shadow.s_none')}</li>`;
  if (o.clv) {
    const key = o.clv.low > 0 ? 'shadow.s_clv_up' : o.clv.high < 0 ? 'shadow.s_clv_down' : 'shadow.s_clv_level';
    h += `<li>${t(key, { share: fmt.pct(o.clv_positive), pts: pts(Math.abs(o.clv.mean)) })}</li>`;
  }
  const hab = habit(hb, o);
  if (hab) h += `<li>${hab}</li>`;
  h += `</ul></section>`;
  h += ruleBlock(c, iid);
  h += counterfactualBlock(c);
  if (detailed()) h += detailedTables(c);
  h += `<h2>${t('shadow.caveats')}</h2><ul class="notes small measure">${c.caveats.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`;
  h += `<div class="row"><button class="btn" type="button" id="card-json">${t('shadow.export_json')}</button>
    <a class="btn" href="/api/shadow/${esc(iid)}/card.csv" download>${t('shadow.export_csv')}</a>
    <button class="btn quiet" type="button" id="card-refresh">${t('shadow.refresh')}</button>
    <button class="btn quiet" type="button" id="card-delete">${t('shadow.delete')}</button></div>`;
  h += proofBlock(item);
  after(() => {
    document.getElementById('card-json').addEventListener('click', () => download(c));
    document.getElementById('card-refresh').addEventListener('click', async () => {
      await send('POST', 'shadow', { address: item.address, consent: true });
      await render(false);
    });
    document.getElementById('card-delete').addEventListener('click', async () => {
      if (!confirm(tp('shadow.delete_confirm'))) return;
      await send('DELETE', `shadow/${iid}`);
      location.hash = '#shadow';
    });
  });
  return h;
}

export default async function shadow([iid] = []) {
  if (!session.hosted) return head(t('shadow.title')) + empty(t('team.local'), t('team.local_text'), [['#home', t('error.home')]]);
  if (iid) return one(iid);
  const data = await api('shadow');
  let h = head(t('shadow.title'), t('shadow.lede'));
  h += importForm(data.consent);
  if (data.imports.length) {
    h += `<h2>${t('shadow.yours')}</h2>` + table([t('shadow.address'), t('shadow.state'), t('shadow.m.return'), t('col.created')],
      data.imports.map((x) => [`<a href="#shadow/${esc(x.id)}" class="mono">${esc(short(x.address))}</a>${x.verified ? ` <span class="pill ok">${t('shadow.verified')}</span>` : ''}`,
        t('shadow.states.' + x.state), esc(x.summary ? fmt.signedPct(x.summary.return) : '–'), esc(fmt.dateTime(x.updated_at))]), { numFrom: 2, caption: t('shadow.yours_caption') });
  }
  h += `<p class="small muted measure">${t('shadow.how')}</p>`;
  return h;
}
