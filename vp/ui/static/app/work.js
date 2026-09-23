// Work started from the page (hosted only): the jobs panel that shows what
// is queued and running with its progress, polling while anything is
// active, and the actions that start work. Under `vp ui` there are no jobs;
// the commands run from the terminal.
import { api, send, session } from './api.js';
import { after, esc, fmt, t, tp } from './ui.js';

let timer = null;
addEventListener('hashchange', () => { clearInterval(timer); timer = null; });

const ACTIVE = new Set(['queued', 'running']);

function jobLine(j) {
  const fraction = j.progress?.fraction ?? (j.state === 'succeeded' ? 1 : 0);
  const pct = Math.round(100 * fraction);
  const message = j.progress?.message ? ` · ${esc(j.progress.message)}` : '';
  const cancel = ACTIVE.has(j.state) ? `<button class="btn quiet" type="button" data-cancel="${esc(j.id)}">${t('jobs.cancel')}</button>` : '';
  const error = j.state === 'dead' || j.state === 'failed' ? `<p class="small neg" style="margin:4px 0 0">${esc((j.error || '').split('\n')[0])}</p>` : '';
  return `<li class="job"><div class="row" style="margin:0;justify-content:space-between">
      <span><b>${t('jobs.kind.' + j.kind)}</b> <span class="pill">${t('jobs.state.' + j.state)}</span>
      <span class="small muted">${esc(fmt.relative(j.created_at))}${message}</span></span>${cancel}</div>
    ${ACTIVE.has(j.state) ? `<div class="meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="${esc(tp('jobs.progress'))}"><i style="width:${pct}%"></i></div>` : ''}${error}</li>`;
}

// A panel of the workspace's recent jobs of some kinds. `onDone` runs once
// when a job that was active when the panel appeared has finished.
export function jobsPanel(kinds, { limit = 5, title = true, onDone = null } = {}) {
  if (!session.hosted) return '';
  const id = 'jobs-' + Math.random().toString(36).slice(2, 8);
  after(() => watch(id, kinds, limit, onDone));
  return `<section aria-live="polite" id="${id}">${title ? `<h2>${t('jobs.title')}</h2>` : ''}<ul class="jobs"></ul></section>`;
}

async function watch(id, kinds, limit, onDone) {
  const seenActive = new Set();
  const draw = async () => {
    const box = document.getElementById(id);
    if (!box) { clearInterval(timer); timer = null; return; }
    const all = (await api('jobs?limit=30')) || [];
    const mine = all.filter((j) => kinds.includes(j.kind)).slice(0, limit);
    const list = box.querySelector('ul');
    list.innerHTML = mine.length ? mine.map(jobLine).join('') : `<li class="muted small">${t('jobs.none')}</li>`;
    list.querySelectorAll('[data-cancel]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      await send('POST', `jobs/${b.dataset.cancel}/cancel`);
      draw();
    }));
    let finished = false;
    for (const j of mine) {
      if (ACTIVE.has(j.state)) seenActive.add(j.id);
      else if (seenActive.delete(j.id)) finished = true;
    }
    if (finished && onDone) onDone();
    const busy = mine.some((j) => ACTIVE.has(j.state));
    if (busy && !timer) timer = setInterval(draw, 2000);
    if (!busy && timer) { clearInterval(timer); timer = null; }
  };
  await draw();
}

export async function startPaper(domains) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  return send('POST', 'paper/start', { domains, timezone });
}
