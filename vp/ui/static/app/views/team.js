// The team (hosted only, task 81): which workspace this is and the others
// the person belongs to, who is in it with which role, invitations, and
// the activity feed that attributes every change to a person. Owners
// invite, change roles and remove; anyone may leave.
import { api, send, session, whoAmI } from '../api.js';
import { render, shell } from '../main.js';
import { after, detailed, empty, esc, fmt, head, t, table, tp } from '../ui.js';

const ROLES = ['owner', 'editor', 'viewer'];
const ACTIONS = ['joined', 'left', 'removed', 'invited', 'invitation_revoked', 'role_changed', 'renamed', 'confirmed', 'paper_started', 'retired',
  'shared', 'share_updated', 'unshared', 'forked', 'commented', 'comment_hidden', 'leaderboard_joined', 'leaderboard_left',
  'channel_added', 'channel_removed', 'sender_paired', 'brief_proposed', 'brief_confirmed', 'brief_stopped', 'webhook_added', 'webhook_removed'];

const roleSelect = (m) => `<label for="role-${esc(m.user_id)}" class="sr-only">${t('team.role_of', { email: m.email })}</label>
  <select id="role-${esc(m.user_id)}" data-role="${esc(m.user_id)}">${ROLES.map((r) => `<option value="${r}"${r === m.role ? ' selected' : ''}>${t('team.roles.' + r)}</option>`).join('')}</select>`;

function action(a) {
  const known = ACTIONS.includes(a.action);
  const detail = a.detail?.role ? ` (${esc([].concat(a.detail.role).map((r) => tp('team.roles.' + r)).join(', '))})` : a.detail?.name ? ` (${esc(a.detail.name)})` : '';
  return `<li><span class="small muted">${esc(fmt.relative(a.at))}</span> · <b>${esc(a.who ?? tp('comments.someone'))}</b> ${known ? t('team.action.' + a.action) : esc(a.action)}${detail}</li>`;
}

export default async function team() {
  if (!session.hosted) return head(t('team.title')) + empty(t('team.local'), t('team.local_text'), [['#home', t('error.home')]]);
  const [info, feed] = await Promise.all([api('team'), api('team/activity?limit=50')]);
  const admin = info.you_may_administer;
  let h = head(t('team.title'), t('team.lede', { name: session.me.workspace?.name ?? '' }));
  h += `<p id="team-status" class="small" role="status"></p>`;

  if (info.workspaces.length > 1) {
    h += `<h2>${t('team.workspaces')}</h2><ul class="notes">${info.workspaces.map((w) => `<li>${esc(w.name)} · ${t('team.roles.' + w.role)} · ${t('team.members_n', { n: w.members })}
      ${w.id === session.me.workspace?.id ? ` <span class="pill">${t('team.current')}</span>` : ` <button class="btn quiet" type="button" data-switch="${esc(w.id)}">${t('team.switch')}</button>`}</li>`).join('')}</ul>`;
  }

  h += `<h2>${t('team.members')}</h2>`;
  h += table([t('col.email'), t('team.role'), t('team.joined'), `<span class="sr-only">${t('team.actions')}</span>`],
    info.members.map((m) => [esc(m.email) + (m.you ? ` <span class="pill">${t('team.you')}</span>` : ''),
      admin && !m.you ? roleSelect(m) : t('team.roles.' + m.role), esc(fmt.date(m.joined_at)),
      m.you ? `<button class="btn quiet" type="button" data-leave="${esc(m.user_id)}">${t('team.leave')}</button>`
        : admin ? `<button class="btn quiet" type="button" data-remove="${esc(m.user_id)}" aria-label="${tp('team.remove_label', { email: m.email })}">${t('team.remove')}</button>` : '']),
    { numFrom: 9, caption: t('team.members_caption') });
  h += `<p class="small muted measure">${t('team.roles_note')}</p>`;

  // Everyone's own workspace starts as Personal; a shared one needs a name
  // its members can tell from their own in the switcher.
  const shared = info.members.length > 1 || info.invitations.length;
  if (admin && shared && session.me.workspace?.name === 'Personal') h += `<div class="aside"><p>${t('team.name_it')}</p></div>`;
  if (admin) {
    h += `<h2>${t('team.invite')}</h2><form id="invite" class="row"><label for="invite-email" class="sr-only">${t('col.email')}</label>
      <input type="email" id="invite-email" name="email" required maxlength="254" placeholder="${tp('team.invite_placeholder')}" autocomplete="off">
      <label for="invite-role" class="sr-only">${t('team.role')}</label><select id="invite-role" name="role"><option value="viewer">${t('team.roles.viewer')}</option><option value="editor">${t('team.roles.editor')}</option></select>
      <button class="btn primary" type="submit">${t('team.invite_send')}</button></form>`;
    if (info.invitations.length) {
      h += table([t('col.email'), t('team.role'), t('team.expires'), `<span class="sr-only">${t('team.actions')}</span>`],
        info.invitations.map((i) => [esc(i.email), t('team.roles.' + i.role), esc(fmt.relative(i.expires_at)),
          `<button class="btn quiet" type="button" data-revoke="${esc(i.id)}">${t('team.revoke')}</button>`]), { numFrom: 9, caption: t('team.pending') });
    }
    h += `<h2>${t('team.name')}</h2><form id="rename" class="row"><label for="team-name" class="sr-only">${t('team.name')}</label>
      <input type="text" id="team-name" required maxlength="100" value="${esc(session.me.workspace?.name ?? '')}">
      <button class="btn" type="submit">${t('team.rename')}</button></form>`;
  }

  h += `<h2>${t('team.activity')}</h2>`;
  h += feed.length ? `<ul class="notes">${feed.slice(0, detailed() ? 50 : 15).map(action).join('')}</ul>` : `<p class="muted">${t('team.no_activity')}</p>`;

  after(() => {
    const status = document.getElementById('team-status');
    const act = async (fn, again = true) => { try { await fn(); if (again) await render(false); } catch (e) { status.textContent = e.message; } };
    document.querySelectorAll('select[data-role]').forEach((s) => s.addEventListener('change', () => act(() => send('PUT', `team/members/${s.dataset.role}`, { role: s.value }))));
    document.querySelectorAll('[data-remove]').forEach((b) => b.addEventListener('click', () => act(() => send('DELETE', `team/members/${b.dataset.remove}`))));
    document.querySelectorAll('[data-revoke]').forEach((b) => b.addEventListener('click', () => act(() => send('DELETE', `team/invitations/${b.dataset.revoke}`))));
    const leave = document.querySelector('[data-leave]');
    leave?.addEventListener('click', () => {
      if (!confirm(tp('team.leave_confirm'))) return;
      act(async () => { await send('DELETE', `team/members/${leave.dataset.leave}`); location.href = '/sign-in'; }, false);
    });
    document.querySelectorAll('[data-switch]').forEach((b) => b.addEventListener('click', () => act(async () => {
      await send('POST', 'team/switch', { workspace_id: b.dataset.switch });
      await whoAmI();
      shell();
    })));
    document.getElementById('invite')?.addEventListener('submit', (e) => {
      e.preventDefault();
      const email = document.getElementById('invite-email').value, role = document.getElementById('invite-role').value;
      act(() => send('POST', 'team/invitations', { email, role }));
    });
    document.getElementById('rename')?.addEventListener('submit', (e) => {
      e.preventDefault();
      const name = document.getElementById('team-name').value;
      act(async () => { await send('PUT', 'team', { name }); await whoAmI(); shell(); });
    });
  });
  return h;
}
