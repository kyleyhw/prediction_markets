// A conversation with the assistant, as the Describe and Research pages
// share it. Found with a simulated screen-reader user (2026-10-13): after
// Send, focus fell off the page; the wait said "up to a minute" and never
// changed; the reply arrived unannounced; and a message whose reply had
// not come was gone on return. So focus stays in the text box, the status
// counts the minutes, the reply is announced and focused, and a message
// still waiting (or whose reply failed) is shown from its job.
import { api } from './api.js';
import { esc, t, tp } from './ui.js';

const DONE = new Set(['succeeded', 'failed', 'dead', 'cancelled']);
const FLAG = 'vp-replied';

export function waitingHtml(convo) {
  return (convo?.waiting || []).map((w) => `<li class="turn you"><h2 class="k">${t('describe.you')}</h2><p>${esc(w.words)}</p>
    ${w.state === 'waiting'
      ? `<p class="small muted">${t('describe.waiting')}</p>`
      : `<p class="small">${t('describe.no_reply', { error: w.error || '' })} <button class="btn quiet" type="button" data-say="${esc(w.words)}">${t('describe.send_again')}</button></p>`}</li>`).join('');
}

// Follow a job to its end, telling the status how long it has been.
export async function follow(jobId, status) {
  const started = Date.now();
  let told = 0;
  for (;;) {
    const j = await api(`jobs/${jobId}`);
    if (!j || DONE.has(j.state)) return j;
    const minutes = Math.floor((Date.now() - started) / 60000);
    if (minutes > told) { told = minutes; status.textContent = tp('describe.still', { n: minutes }); }
    await new Promise((r) => setTimeout(r, 2000));
  }
}

// After the page re-renders with the reply: announce it and move to it.
export function markReplied(ok) { try { sessionStorage.setItem(FLAG, ok ? 'ok' : 'failed'); } catch { /* private mode */ } }

export function announceReply(status) {
  let flag = null;
  try { flag = sessionStorage.getItem(FLAG); sessionStorage.removeItem(FLAG); } catch { /* private mode */ }
  if (!flag) return;
  const turns = document.querySelectorAll('.turns > li');
  const last = turns[turns.length - 1];
  if (last) { last.setAttribute('tabindex', '-1'); last.focus(); }
  status.textContent = tp(flag === 'ok' ? 'describe.replied' : 'describe.reply_failed');
}
