// A comment thread under a run, a market or a strategy (hosted only, task
// 83): replies one level deep, @name mentions that notify a teammate, edits
// within five minutes, deleting one's own and, for owners, hiding anyone's.
// The body is shown as plain text; nothing a person types becomes markup.
import { api, send, session } from './api.js';
import { after, esc, fmt, t, tp } from './ui.js';

const owner = () => session.me?.roles?.includes('owner');
const EDIT_MS = 5 * 60 * 1000;

function one(c, reply) {
  const text = c.removed ? `<p class="muted small">${t('comments.' + c.removed)}</p>` : `<p class="comment-body">${esc(c.body)}</p>`;
  const acts = [];
  if (!c.removed && !reply) acts.push(`<button class="btn quiet" type="button" data-reply="${esc(c.id)}">${t('comments.reply')}</button>`);
  if (!c.removed && c.mine && Date.now() - new Date(c.created_at).getTime() < EDIT_MS) acts.push(`<button class="btn quiet" type="button" data-edit="${esc(c.id)}">${t('comments.edit')}</button>`);
  if (!c.removed && c.mine) acts.push(`<button class="btn quiet" type="button" data-delete="${esc(c.id)}">${t('comments.delete')}</button>`);
  if (!c.removed && !c.mine && owner()) acts.push(`<button class="btn quiet" type="button" data-hide="${esc(c.id)}">${t('comments.hide')}</button>`);
  return `<li class="comment" data-id="${esc(c.id)}"><p class="small muted" style="margin:0"><b>${esc(c.who ?? tp('comments.someone'))}</b> · ${esc(fmt.relative(c.created_at))}${c.edited ? ' · ' + t('comments.edited') : ''}</p>
    ${text}${acts.length ? `<div class="row" style="margin:0">${acts.join('')}</div>` : ''}
    ${c.replies.length ? `<ul class="comments">${c.replies.map((r) => one(r, true)).join('')}</ul>` : ''}</li>`;
}

const form = (id, label, value = '') => `<form class="comment-form" data-form="${esc(id)}"><label for="cf-${esc(id)}" class="sr-only">${label}</label>
  <textarea id="cf-${esc(id)}" name="body" rows="3" maxlength="4000" required placeholder="${tp('comments.placeholder')}">${esc(value)}</textarea>
  <div class="row" style="margin:6px 0 0"><button class="btn" type="submit">${label}</button></div></form>`;

async function fill(box, kind, subject) {
  const list = (await api(`comments/${kind}/${encodeURIComponent(subject)}`)) || [];
  box.innerHTML = (list.length ? `<ul class="comments">${list.map((c) => one(c, false)).join('')}</ul>` : `<p class="muted">${t('comments.none')}</p>`)
    + form('new', tp('comments.post')) + `<p class="small" role="status" data-status></p>`;
}

export function commentsPanel(kind, subject) {
  if (!session.hosted) return '';
  const id = 'comments-' + Math.random().toString(36).slice(2, 8);
  after(async () => {
    const box = document.getElementById(id);
    if (!box) return;
    await fill(box, kind, subject);
    const status = () => box.querySelector('[data-status]');
    const refresh = () => fill(box, kind, subject);
    box.addEventListener('click', async (e) => {
      const b = e.target.closest('button[data-reply],button[data-edit],button[data-delete],button[data-hide]');
      if (!b) return;
      const li = b.closest('.comment');
      try {
        if (b.dataset.reply) {
          if (!li.querySelector('.comment-form')) { li.insertAdjacentHTML('beforeend', form('r' + b.dataset.reply, tp('comments.reply'))); li.querySelector('textarea').focus(); }
        } else if (b.dataset.edit) {
          const body = li.querySelector('.comment-body').textContent;
          li.querySelector('.comment-body').outerHTML = form('e' + b.dataset.edit, tp('comments.save'), body);
          li.querySelector('textarea').focus();
        } else if (b.dataset.delete) { await send('DELETE', `comments/${b.dataset.delete}`); await refresh(); }
        else if (b.dataset.hide) { await send('POST', `comments/${b.dataset.hide}/hide`); await refresh(); }
      } catch (err) { status().textContent = err.message; }
    });
    box.addEventListener('submit', async (e) => {
      e.preventDefault();
      const f = e.target, key = f.dataset.form, body = f.body.value.trim();
      if (!body) return;
      try {
        if (key.startsWith('e')) await send('PUT', `comments/${key.slice(1)}`, { body });
        else await send('POST', 'comments', { subject_kind: kind, subject_id: subject, body, parent: key.startsWith('r') ? key.slice(1) : null });
        await refresh();
        status().textContent = tp('comments.posted');
      } catch (err) { status().textContent = err.message; }
    });
  });
  return `<h2>${t('comments.title')}</h2><p class="small muted measure">${t('comments.note')}</p><div id="${id}"><p class="muted">${t('comments.loading')}</p></div>`;
}
