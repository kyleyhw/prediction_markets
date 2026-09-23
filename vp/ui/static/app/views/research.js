// The research assistant (docs/strategies.md): ask about markets, evidence
// and your strategies; the answer is built from tool results and checked
// by the number gate before it is shown. Detailed shows what it looked at.
// The hash is #research/<conversation id>.
import { api, send, session } from '../api.js';
import { render } from '../main.js';
import { after, detailed, empty, esc, fmt, head, t, tp } from '../ui.js';

const DONE = new Set(['succeeded', 'failed', 'dead', 'cancelled']);

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
  const convo = conversationId ? await api(`conversations/${conversationId}`) : null;
  if (convo?.turns.length) {
    h += `<ol class="turns" aria-label="${tp('describe.conversation')}">${convo.turns.map((x) => x.role === 'user'
      ? `<li class="turn you"><h3 class="k">${t('describe.you')}</h3><p>${esc(x.content.words)}</p></li>`
      : `<li class="turn card"><h3 class="k">${t('describe.assistant')}</h3>${answer(x.content)}</li>`).join('')}</ol>`;
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
    const say = async (words) => {
      document.querySelectorAll('#say button, [data-say]').forEach((b) => { b.disabled = true; });
      status.textContent = tp('research.working');
      try {
        const r = await send('POST', 'research', { words, conversation_id: conversationId || null });
        for (;;) {
          const j = await api(`jobs/${r.job_id}`);
          if (!j || DONE.has(j.state)) {
            if (j && j.state !== 'succeeded') status.textContent = tp('describe.failed', { error: (j.error || '').split('\n')[0] });
            break;
          }
          if (j.progress?.message) status.textContent = j.progress.message;
          await new Promise((res) => setTimeout(res, 1500));
        }
        const next = `#research/${r.conversation_id}`;
        if (location.hash !== next) location.hash = next;
        else await render(false);
      } catch (e) {
        status.textContent = e.message;
        document.querySelectorAll('#say button, [data-say]').forEach((b) => { b.disabled = false; });
      }
    };
    document.getElementById('say').addEventListener('submit', (e) => {
      e.preventDefault();
      const words = document.getElementById('words').value.trim();
      if (words) say(words);
    });
    document.querySelectorAll('[data-say]').forEach((b) => b.addEventListener('click', () => say(b.dataset.say)));
  });
  return h;
}
