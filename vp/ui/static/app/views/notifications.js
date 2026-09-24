// Notifications (hosted only, task 87): what has happened that concerns
// the person, newest first, and where each kind goes besides this page:
// email, a connected chat channel, or nowhere else; and quiet hours, during
// which messages wait and the page still shows everything at once.
import { api, send, session } from '../api.js';
import { render, shell } from '../main.js';
import { after, empty, esc, fmt, head, raw, t, tp } from '../ui.js';

const KINDS = ['mention', 'reply', 'invitation', 'fill', 'settlement', 'budget', 'halt', 'brief', 'health', 'delivery'];

function item(n) {
  const title = esc(n.title);
  const link = n.link && n.link.startsWith('#') ? `<a href="${esc(n.link)}">${title}</a>` : title;
  return `<li class="${n.read ? '' : 'unread'}"><span class="pill">${KINDS.includes(n.kind) ? t('notifications.kinds.' + n.kind) : esc(n.kind)}</span>
    <b>${link}</b>${n.read ? '' : ` <span class="sr-only">${t('notifications.unread_sr')}</span>`}<br>
    ${n.body ? `<span>${esc(n.body)}</span><br>` : ''}<span class="small muted">${esc(fmt.relative(n.created_at))}</span></li>`;
}

function preferences(prefs, channels) {
  const live = channels.filter((c) => !c.disabled);
  const routes = [['email', tp('notifications.email')], ...live.map((c) => ['channel:' + c.id, c.name])];
  const rows = KINDS.map((k) => `<tr><th scope="row">${t('notifications.kinds.' + k)}</th>${routes.map(([r, label]) =>
    `<td class="num"><input type="checkbox" data-kind="${k}" value="${esc(r)}" aria-label="${esc(tp('notifications.route_label', { kind: tp('notifications.kinds.' + k), route: label }))}"${(prefs.kinds[k] || []).includes(r) ? ' checked' : ''}></td>`).join('')}</tr>`).join('');
  const q = prefs.quiet || {};
  return `<h2>${t('notifications.where')}</h2><p class="muted measure">${t('notifications.where_note')}</p>
    <form id="notify-prefs"><div class="wrap"><table><caption>${t('notifications.where_caption')}</caption><thead><tr><th scope="col">${t('notifications.kind')}</th>
    ${routes.map(([, label]) => `<th scope="col" class="num">${esc(label)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>
    <fieldset><legend>${t('notifications.quiet')}</legend><p class="small muted">${t('notifications.quiet_note')}</p>
      <label class="check"><input type="checkbox" id="quiet-on"${q.start ? ' checked' : ''}> <span>${t('notifications.quiet_on')}</span></label>
      <div class="row"><label for="quiet-start">${t('notifications.quiet_from')}</label><input type="time" id="quiet-start" value="${esc(q.start || '22:00')}">
      <label for="quiet-end">${t('notifications.quiet_to')}</label><input type="time" id="quiet-end" value="${esc(q.end || '07:00')}">
      <label for="quiet-tz">${t('notifications.quiet_tz')}</label><input type="text" id="quiet-tz" maxlength="64" value="${esc(q.tz || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')}"></div></fieldset>
    <button class="btn primary" type="submit">${t('notifications.save')}</button></form>`;
}

export default async function notifications() {
  if (!session.hosted) return head(t('notifications.title')) + empty(t('team.local'), t('team.local_text'), [['#home', t('error.home')]]);
  const [list, prefs, channels] = await Promise.all([api('notifications'), api('notifications/prefs'), api('channels')]);
  let h = head(t('notifications.title'), t('notifications.lede', { n: list.unread }));
  h += `<p id="notify-status" class="small" role="status"></p>`;
  if (list.items.length) {
    if (list.unread) h += `<button class="btn" type="button" id="read-all">${t('notifications.read_all')}</button>`;
    h += `<ul class="notes notices">${list.items.map(item).join('')}</ul>`;
  } else h += `<p class="muted">${t('notifications.none')}</p>`;
  h += preferences(prefs, channels || []);
  h += `<p class="small muted measure">${t('notifications.channels_note', { link: raw(`<a href="#delivery">${t('nav.delivery')}</a>`) })}</p>`;
  after(() => {
    const status = document.getElementById('notify-status');
    document.getElementById('read-all')?.addEventListener('click', async () => {
      await send('POST', 'notifications/read', { ids: list.items.filter((n) => !n.read).map((n) => n.id) });
      shell();
      await render(false);
    });
    document.getElementById('notify-prefs').addEventListener('submit', async (e) => {
      e.preventDefault();
      const kinds = Object.fromEntries(KINDS.map((k) => [k, [...document.querySelectorAll(`input[data-kind="${k}"]:checked`)].map((x) => x.value)]));
      const quiet = document.getElementById('quiet-on').checked
        ? { start: document.getElementById('quiet-start').value, end: document.getElementById('quiet-end').value, tz: document.getElementById('quiet-tz').value.trim() || 'UTC' }
        : null;
      try { await send('PUT', 'notifications/prefs', { kinds, quiet }); status.textContent = tp('settings.saved'); } catch (err) { status.textContent = err.message; }
    });
  });
  return h;
}
