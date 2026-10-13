// The research assistant (docs/strategies.md): ask about markets, evidence
// and your strategies; the answer is built from tool results and checked
// by the number gate before it is shown. Detailed shows what it looked at.
// The hash is #research/<conversation id>.
import { api, send, session } from '../api.js';
import { render } from '../main.js';
import { announceReply, follow, markReplied, waitingHtml } from '../talk.js';
import { after, detailed, dropDraft, empty, esc, explain, fmt, head, keepDraft, modelNotice, t, tp } from '../ui.js';


function answer(c) {
  let h = `<div class="prose">${esc(c.text).split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('')}</div>`;
  if (c.stopped) h = `<div class="aside caution">${h}</div>`;
  const g = c.gate || {};
  if (g.replaced?.length) h += `<p class="small muted">${t('research.replaced', { n: g.replaced.length })}</p>`;
  else if (g.figures) h += `<p class="small muted">${t('research.checked', { n: g.figures })}</p>`;
  if (c.tools?.length) {
    h += detailed()
      ? `<details><summary>${t('research.looked', { n: c.tools.length })}</summary><ol class="notes">${c.tools.map((x) =>
        `<li><code>${esc(x.name)}</code> <code class="small">${esc(JSON.stringify(x.input))}</code><pre>${esc(x.result)}</pre></li>`).join('')}</ol></details>`
      : `<p class="small muted">${t('research.looked', { n: c.tools.length })}</p>`;
  }
  if (detailed() && c.cost_usd) h += `<p class="small muted">${t('describe.cost', { usd: fmt.money(c.cost_usd, 3), model: c.model })}</p>`;
  return h;
}

export default async function research([conversationId] = []) {
  let h = head(t('research.title'), t('research.lede'));
  if (!session.hosted) return h + empty(t('describe.local_title'), t('research.local_text'), [['#strategies', t('describe.back')]]);
  h += await modelNotice();
  const convo = conversationId ? await api(`conversations/${conversationId}`) : null;
  if (convo?.turns.length || convo?.waiting?.length) {
    h += `<ol class="turns" aria-label="${tp('describe.conversation')}">${convo.turns.map((x) => x.role === 'user'
      ? `<li class="turn you"><h2 class="k">${t('describe.you')}</h2><p>${esc(x.content.words)}</p></li>`
      : `<li class="turn card"><h2 class="k">${t('describe.assistant')}</h2>${answer(x.content)}</li>`).join('')}${waitingHtml(convo)}</ol>`;
  } else {
    h += `<p class="muted">${t('describe.examples_intro')}</p><ul class="notes">${['one', 'two', 'three'].map((k) =>
      `<li><button class="btn quiet" type="button" data-say="${tp('research.example_' + k)}">${t('research.example_' + k)}</button></li>`).join('')}</ul>`;
  }
  h += `<form id="say" class="stack"><label for="words">${t('research.label')}</label>
    <textarea id="words" rows="3" maxlength="2000" required></textarea>
    <div class="row"><button class="btn primary" type="submit">${t('describe.send')}</button></div></form>
    <p id="say-status" class="small" role="status"></p>`;
  after(() => {
    const status = document.getElementById('say-status');
    const wait = async (jobId, next, since) => {
      const j = await follow(jobId, status, since);
      markReplied(j?.state === 'succeeded');
      if (location.hash !== next) location.hash = next;
      else await render(false);
    };
    const say = async (words) => {
      document.querySelectorAll('#say button, [data-say]').forEach((b) => { b.disabled = true; });
      document.getElementById('words').focus();
      status.textContent = tp('research.working');
      try {
        const r = await send('POST', 'research', { words, conversation_id: conversationId || null });
        document.getElementById('words').value = '';
        dropDraft();
        const next = `#research/${r.conversation_id}`;
        // A new conversation moves to its own address now: the message shows
        // while it waits, and the reply's focus is not taken back by a route
        // change when it arrives (keyboard-only run, 2026-10-13).
        if (location.hash !== next) { location.hash = next; return; }
        await wait(r.job_id, next);
      } catch (e) {
        explain(status, e);
        document.querySelectorAll('#say button, [data-say]').forEach((b) => { b.disabled = false; });
      }
    };
    document.getElementById('say').addEventListener('submit', (e) => {
      e.preventDefault();
      const words = document.getElementById('words').value.trim();
      if (words) say(words);
    });
    document.querySelectorAll('[data-say]').forEach((b) => b.addEventListener('click', () => say(b.dataset.say)));
    keepDraft(document.getElementById('words'));
    announceReply(status);
    const pending = (convo?.waiting || []).find((w) => w.state === 'waiting');
    if (pending) {
      document.querySelectorAll('#say button').forEach((b) => { b.disabled = true; });
      status.textContent = tp('describe.waiting');
      // Focus back in the text box after the move to this address.
      setTimeout(() => document.getElementById('words')?.focus(), 0);
      wait(pending.job_id, location.hash, pending.at);
    }
  });
  return h;
}
