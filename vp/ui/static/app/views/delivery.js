// Delivery (hosted only, tasks 85, 86 and 89): the places research reaches
// people besides this page (email, chats and webhooks), the briefs sent to
// them on a schedule, with the watch list each brief's last run fills, and
// in Detailed the signed webhooks and the read-only tool server for other
// programs. A brief the assistant proposes stays off until a person
// switches it on here; a new chat sender is approved here, never in a chat.
import { api, send, session } from '../api.js';
import { render } from '../main.js';
import { after, detailed, empty, esc, fmt, head, level, raw, t, table, tp } from '../ui.js';

const KINDS = ['email', 'telegram', 'slack', 'discord', 'webhook'];
const TEMPLATES = ['disagreements', 'settlements', 'weekly'];
const zone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

function channelsHtml(list, admin) {
  const live = list.filter((c) => !c.disabled);
  let h = `<h2>${t('delivery.channels')}</h2><p class="muted measure">${t('delivery.channels_note')}</p>`;
  h += live.length ? table([t('col.name'), t('delivery.kind'), t('delivery.target'), t('delivery.sent'), t('delivery.failed'), `<span class="sr-only">${t('team.actions')}</span>`],
    live.map((c) => [esc(c.name), t('delivery.kinds.' + c.kind), esc(c.target), esc(fmt.int(c.sent)), esc(fmt.int(c.dead)),
      admin ? `<button class="btn quiet" type="button" data-channel-off="${esc(c.id)}" aria-label="${tp('delivery.remove_label', { name: c.name })}">${t('delivery.remove')}</button>` : '']),
    { numFrom: 3, caption: t('delivery.channels_caption') }) : `<p class="muted">${t('delivery.no_channels')}</p>`;
  const pending = live.flatMap((c) => c.pairing.map((p) => ({ ...p, channel: c.name })));
  if (pending.length && admin) {
    h += `<h3>${t('delivery.pairing')}</h3><p class="small muted measure">${t('delivery.pairing_note')}</p><ul class="notes">${pending.map((p) =>
      `<li>${t('delivery.pairing_line', { who: p.display || p.sender, channel: p.channel, when: fmt.relative(p.at) })} <code>${esc(p.code)}</code>
       <button class="btn" type="button" data-pair="${esc(p.code)}">${t('delivery.approve')}</button></li>`).join('')}</ul>`;
  }
  if (admin) {
    h += `<details class="card"><summary>${t('delivery.add_channel')}</summary><form id="channel-form" style="margin-top:12px">
      <div class="row"><label for="ch-kind">${t('delivery.kind')}</label><select id="ch-kind">${KINDS.map((k) => `<option value="${k}">${t('delivery.kinds.' + k)}</option>`).join('')}</select>
      <label for="ch-name">${t('col.name')}</label><input type="text" id="ch-name" required maxlength="100"></div>
      <div class="row"><label for="ch-target" id="ch-target-label">${t('delivery.targets.email')}</label><input type="text" id="ch-target" required maxlength="500" style="min-width:20em" autocomplete="off"></div>
      <div class="row" id="ch-secret-row" hidden><label for="ch-secret" id="ch-secret-label">${t('delivery.secrets.telegram')}</label><input type="password" id="ch-secret" maxlength="500" autocomplete="off" style="min-width:20em"></div>
      <p class="small muted" id="ch-help">${t('delivery.help.email')}</p>
      <button class="btn primary" type="submit">${t('delivery.add')}</button></form><div id="channel-made" role="status"></div></details>`;
  }
  return h;
}

// The watch list: the rows of a brief's machine-readable block.
function watch(b) {
  const rows = b.last?.rows || [];
  if (!b.last) return `<p class="small muted">${t('delivery.never_run')}</p>`;
  if (!rows.length) return `<p class="small muted">${t('delivery.nothing', { date: fmt.date(b.last.date) })}</p>`;
  const cap = t('delivery.watch_caption', { date: fmt.date(b.last.date) });
  if (b.template === 'disagreements') {
    return table([t('col.market'), t('col.strategy'), t('delivery.forecast'), t('delivery.price'), t('delivery.points')],
      rows.map((r) => [esc(r.question), esc(r.forecaster), esc(fmt.pct(r.forecast)), esc(fmt.pct(r.price)), esc(fmt.signed(r.points, 0))]), { caption: cap, numFrom: 2 });
  }
  if (b.template === 'settlements') {
    return table([t('col.market'), t('delivery.result'), t('delivery.pnl'), t('delivery.account')],
      rows.map((r) => [esc(r.question || r.market_id), t(r.won ? 'delivery.won' : 'delivery.lost'), esc(fmt.signedMoney(r.pnl)), esc(r.account)]), { caption: cap, numFrom: 2 });
  }
  return table([t('delivery.account'), t('col.settled'), t('delivery.pnl'), t('col.forward_skill')],
    rows.map((r) => [esc(r.account), esc(fmt.int(r.settled)), esc(fmt.signedMoney(r.pnl)), esc(fmt.signed(r.skill))]), { caption: cap, numFrom: 1 });
}

function briefsHtml(data, channels, domains, writer) {
  let h = `<h2>${t('delivery.briefs')}</h2><p class="muted measure">${t('delivery.briefs_note')}</p>`;
  h += data.briefs.length ? data.briefs.map((b) => `<section class="card" style="margin-bottom:12px"><h3 style="margin-top:0">${esc(b.title)}</h3>
    <p>${b.enabled ? t('delivery.on', { cron: b.cron, tz: b.timezone }) : b.proposed_by === 'assistant' ? t('delivery.proposed_assistant') : t('delivery.off')}
      ${b.channel ? t('delivery.to', { name: b.channel.name }) : t('delivery.to_page')}${b.last_run_at ? ' ' + t('delivery.last', { when: fmt.relative(b.last_run_at) }) : ''}</p>
    ${detailed() ? `<p class="small muted mono">${esc(b.cron)} · ${esc(b.timezone)} · ${esc(JSON.stringify(b.variables))}</p>` : ''}
    ${writer ? `<div class="row">${b.enabled ? `<button class="btn" type="button" data-brief-stop="${esc(b.id)}">${t('delivery.stop')}</button>`
      : `<button class="btn primary" type="button" data-brief-on="${esc(b.id)}">${t('delivery.switch_on')}</button>`}
      <button class="btn quiet" type="button" data-brief-run="${esc(b.id)}">${t('delivery.run_now')}</button></div>` : ''}
    ${watch(b)}</section>`).join('') : `<p class="muted">${t('delivery.no_briefs')}</p>`;
  if (!writer) return h;
  const live = channels.filter((c) => !c.disabled);
  h += `<details class="card"><summary>${t('delivery.new_brief')}</summary><form id="brief-form" style="margin-top:12px">
    <fieldset><legend>${t('delivery.which')}</legend><div class="choices">${TEMPLATES.map((k, i) => `<label class="choice"><input type="radio" name="template" value="${k}"${i ? '' : ' checked'}>
      <span><span class="t">${esc(data.templates[k].title)}</span></span></label>`).join('')}</div></fieldset>
    <div class="row" data-for="disagreements"><label for="b-threshold">${t('delivery.threshold')}</label><input type="number" id="b-threshold" min="1" max="50" value="10"></div>
    <fieldset data-for="disagreements"><legend>${t('delivery.domains')}</legend><div class="row">${Object.entries(domains).map(([n, d]) =>
      `<label class="check"><input type="checkbox" name="b-domain" value="${esc(n)}"> <span>${esc(d.title)}</span></label>`).join('')}</div><p class="small muted">${t('delivery.domains_note')}</p></fieldset>
    <div class="row" data-for="settlements" hidden><label for="b-days">${t('delivery.days')}</label><input type="number" id="b-days" min="1" max="14" value="1"></div>
    <div class="row"><label for="b-when">${t('delivery.when')}</label><select id="b-when"><option value="daily">${t('delivery.daily')}</option><option value="weekdays">${t('delivery.weekdays')}</option><option value="monday">${t('delivery.mondays')}</option></select>
      <label for="b-time">${t('delivery.at')}</label><input type="time" id="b-time" value="08:00" required>
      <label for="b-tz">${t('notifications.quiet_tz')}</label><input type="text" id="b-tz" value="${esc(zone())}" maxlength="64"></div>
    ${detailed() ? `<div class="row"><label for="b-cron">${t('delivery.cron')}</label><input type="text" id="b-cron" maxlength="100" placeholder="0 8 * * *" class="mono"></div>` : ''}
    <div class="row"><label for="b-channel">${t('delivery.send_to')}</label><select id="b-channel"><option value="">${t('delivery.page_only')}</option>${live.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select></div>
    <button class="btn primary" type="submit">${t('delivery.create_brief')}</button></form></details>`;
  return h;
}

function hooksHtml(data) {
  let h = `<h2>${t('delivery.webhooks')}</h2><p class="muted measure">${t('delivery.webhooks_note')}</p>`;
  h += data.hooks.length ? table([t('delivery.host'), t('delivery.events'), t('delivery.sent'), t('delivery.failed'), `<span class="sr-only">${t('team.actions')}</span>`],
    data.hooks.map((w) => [esc(w.host), esc(w.events.join(', ')), esc(fmt.int(w.sent)), esc(fmt.int(w.dead)),
      `<button class="btn quiet" type="button" data-hook-off="${esc(w.id)}">${t('delivery.remove')}</button>`]), { numFrom: 2, caption: t('delivery.webhooks_caption') })
    : `<p class="muted">${t('delivery.no_webhooks')}</p>`;
  h += `<form id="hook-form"><div class="row"><label for="h-url">${t('delivery.url')}</label><input type="url" id="h-url" required maxlength="500" placeholder="https://" style="min-width:20em"></div>
    <fieldset><legend>${t('delivery.events')}</legend><div class="row">${data.events.map((e) => `<label class="check"><input type="checkbox" name="h-event" value="${esc(e)}"> <span class="mono">${esc(e)}</span></label>`).join('')}</div></fieldset>
    <button class="btn" type="submit">${t('delivery.add_webhook')}</button></form><div id="hook-made" role="status"></div>`;
  return h;
}

const mcpHtml = () => `<h2>${t('delivery.mcp')}</h2><p class="muted measure">${t('delivery.mcp_note')}</p>
  <p><code>${esc(location.origin)}/mcp</code></p><p class="small muted measure">${t('delivery.mcp_tokens', { link: raw(`<a href="#settings">${t('nav.settings')}</a>`) })}</p>`;

function cronOf() {
  const typed = document.getElementById('b-cron')?.value.trim();
  if (typed) return typed;
  const [hh, mm] = document.getElementById('b-time').value.split(':').map(Number);
  const days = { daily: '*', weekdays: '1-5', monday: '1' }[document.getElementById('b-when').value];
  return `${mm} ${hh} * * ${days}`;
}

export default async function delivery() {
  if (!session.hosted) return head(t('delivery.title')) + empty(t('team.local'), t('team.local_text'), [['#home', t('error.home')]]);
  const roles = session.me.roles || [];
  const admin = roles.includes('owner'), writer = admin || roles.includes('editor');
  const [channels, briefs, overview, hooks] = await Promise.all([api('channels'), api('briefs'), api('overview'), detailed() && admin ? api('webhooks') : null]);
  let h = head(t('delivery.title'), level(t('delivery.lede_simple'), t('delivery.lede_detailed')));
  h += `<p id="delivery-status" class="small" role="status"></p>`;
  h += channelsHtml(channels, admin);
  h += briefsHtml(briefs, channels, overview?.domains || {}, writer);
  if (hooks) h += hooksHtml(hooks);
  if (detailed()) h += mcpHtml();
  after(() => {
    const status = document.getElementById('delivery-status');
    const act = async (fn, again = true) => { try { await fn(); if (again) await render(false); } catch (e) { status.textContent = e.message; } };
    const on = (sel, fn) => document.querySelectorAll(sel).forEach((b) => b.addEventListener('click', () => act(() => fn(b))));
    on('[data-channel-off]', (b) => send('DELETE', `channels/${b.dataset.channelOff}`));
    on('[data-pair]', (b) => send('POST', 'channels/pair', { code: b.dataset.pair }));
    on('[data-brief-on]', (b) => send('POST', `briefs/${b.dataset.briefOn}/confirm`));
    on('[data-brief-stop]', (b) => send('POST', `briefs/${b.dataset.briefStop}/stop`));
    on('[data-hook-off]', (b) => send('DELETE', `webhooks/${b.dataset.hookOff}`));
    document.querySelectorAll('[data-brief-run]').forEach((b) => b.addEventListener('click', () => act(async () => {
      await send('POST', `briefs/${b.dataset.briefRun}/run`);
      status.textContent = tp('delivery.queued');
    }, false)));

    const kind = document.getElementById('ch-kind');
    const relabel = () => {
      const k = kind.value;
      document.getElementById('ch-target-label').textContent = tp('delivery.targets.' + k);
      document.getElementById('ch-help').textContent = tp('delivery.help.' + k);
      const secret = k === 'telegram' || k === 'slack';
      document.getElementById('ch-secret-row').hidden = !secret;
      if (secret) document.getElementById('ch-secret-label').textContent = tp('delivery.secrets.' + k);
    };
    kind?.addEventListener('change', relabel);
    document.getElementById('channel-form')?.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = { kind: kind.value, name: document.getElementById('ch-name').value, target: document.getElementById('ch-target').value.trim(),
        secret: document.getElementById('ch-secret').value || null };
      act(async () => {
        const made = await send('POST', 'channels', body);
        await render(false);
        if (made.inbound_url) {
          document.getElementById('delivery-status').innerHTML = `<div class="aside"><p>${t('delivery.inbound', { url: made.inbound_url })}</p>
            ${made.telegram_secret_token ? `<p>${t('delivery.telegram_secret', { token: made.telegram_secret_token })}</p>` : ''}</div>`;
        }
      }, false);
    });

    const form = document.getElementById('brief-form');
    const shown = () => {
      const tpl = form.querySelector('input[name=template]:checked').value;
      form.querySelectorAll('[data-for]').forEach((el) => { el.hidden = el.dataset.for !== tpl; });
    };
    form?.addEventListener('change', (e) => { if (e.target.name === 'template') shown(); });
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      const template = form.querySelector('input[name=template]:checked').value;
      const variables = template === 'disagreements'
        ? { threshold: Number(document.getElementById('b-threshold').value), domains: [...form.querySelectorAll('input[name=b-domain]:checked')].map((x) => x.value) }
        : template === 'settlements' ? { days: Number(document.getElementById('b-days').value) } : {};
      const body = { template, variables, cron: cronOf(), timezone: document.getElementById('b-tz').value.trim() || 'UTC', channel_id: document.getElementById('b-channel').value || null };
      act(async () => {
        const made = await send('POST', 'briefs', body);
        await send('POST', `briefs/${made.id}/confirm`);
      });
    });

    document.getElementById('hook-form')?.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = { url: document.getElementById('h-url').value.trim(), events: [...document.querySelectorAll('input[name=h-event]:checked')].map((x) => x.value) };
      act(async () => {
        const made = await send('POST', 'webhooks', body);
        await render(false);
        document.getElementById('delivery-status').innerHTML = `<div class="aside"><p>${t('delivery.hook_secret')}</p><p><code>${esc(made.secret)}</code></p></div>`;
      }, false);
    });
  });
  return h;
}
