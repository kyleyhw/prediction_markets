// Describe a strategy: a conversation with the compiler (docs/strategies.md).
// The person writes; the assistant answers with a proposal, a question or a
// refusal. A proposal is shown as the engine renders it (never the model's
// prose), and "Run this" freezes exactly that as a version. The hash is
// #describe/<strategy id or new>/<conversation id>.
import { api, send, session } from '../api.js';
import { render } from '../main.js';
import { announceReply, follow, markReplied, waitingHtml } from '../talk.js';
import { after, detailed, empty, esc, explain, fmt, head, modelNotice, t, tp } from '../ui.js';

function proposal(turn, convo) {
  const c = turn.content;
  const lines = `<ul class="notes spec">${c.rendering.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`;
  const changes = c.changes?.length
    ? `<h4>${t('describe.changes')}</h4><ul class="notes">${c.changes.map(([path, a, b]) => `<li><code>${esc(path)}</code>: ${esc(JSON.stringify(a))} → ${esc(JSON.stringify(b))}</li>`).join('')}</ul>`
    : '';
  const json = detailed() ? `<details><summary>${t('describe.spec_json')}</summary><pre>${esc(JSON.stringify(c.spec, null, 1))}</pre></details>` : '';
  return `${c.message ? `<p>${esc(c.message)}</p>` : ''}<h3>${t('describe.what_runs')}</h3>${lines}${changes}${json}
    <div class="row"><button class="btn primary" type="button" data-confirm="${esc(turn.id)}">${t(convo.strategy_id ? 'describe.confirm_version' : 'describe.confirm')}</button></div>`;
}

function turnHtml(turn, convo) {
  const c = turn.content;
  if (turn.role === 'user') return `<li class="turn you"><h2 class="k">${t('describe.you')}</h2><p>${esc(c.words)}</p></li>`;
  let body;
  if (c.kind === 'spec') body = proposal(turn, convo);
  else if (c.kind === 'question') {
    body = `<p>${esc(c.message)}</p>${c.choices?.length ? `<div class="row">${c.choices.map((x) => `<button class="btn" type="button" data-say="${esc(x)}">${esc(x)}</button>`).join('')}</div>` : ''}`;
  } else body = `<div class="aside caution"><p>${esc(c.message)}</p></div>`;
  const remember = (c.remember || []).map((note) => `<button class="btn quiet" type="button" data-remember="${esc(note)}">${t('describe.remember', { note })}</button>`).join('');
  const problems = detailed() && c.problems?.length
    ? `<details><summary>${t('describe.problems')}</summary><ul class="notes small">${c.problems.map((x) => `<li><code>${esc(x)}</code></li>`).join('')}</ul></details>`
    : '';
  body += problems;
  const cost = detailed() && c.cost_usd ? `<p class="small muted">${t('describe.cost', { usd: fmt.money(c.cost_usd, 3), model: c.model })}</p>` : '';
  return `<li class="turn card"><h2 class="k">${t('describe.assistant')}</h2>${body}${remember ? `<div class="row">${remember}</div>` : ''}${cost}</li>`;
}

export default async function describe([target = 'new', conversationId] = []) {
  const strategyId = target === 'new' ? null : target;
  let h = head(strategyId ? t('describe.refine_title') : t('describe.title'), strategyId ? t('describe.refine_lede') : t('describe.lede'));
  if (!session.hosted) return h + empty(t('describe.local_title'), t('describe.local_text'), [['#strategies', t('describe.back')]]);
  h += await modelNotice();
  const convo = conversationId ? await api(`conversations/${conversationId}`) : null;
  if (convo?.turns.length || convo?.waiting?.length) h += `<ol class="turns" aria-label="${tp('describe.conversation')}">${convo.turns.map((x) => turnHtml(x, convo)).join('')}${waitingHtml(convo)}</ol>`;
  else if (!strategyId) h += `<p class="muted">${t('describe.examples_intro')}</p><ul class="notes">${['one', 'two', 'three'].map((k) => `<li><button class="btn quiet" type="button" data-say="${tp('describe.example_' + k)}">${t('describe.example_' + k)}</button></li>`).join('')}</ul>`;
  h += `<form id="say" class="stack"><label for="words">${t(convo?.turns.length ? 'describe.reply_label' : 'describe.label')}</label>
    <textarea id="words" rows="3" maxlength="2000" required></textarea>
    <div class="row"><button class="btn primary" type="submit">${t('describe.send')}</button></div></form>
    <p id="say-status" class="small" role="status"></p>`;
  after(() => {
    const status = document.getElementById('say-status');
    const wait = async (jobId, next) => {
      const j = await follow(jobId, status);
      markReplied(j?.state === 'succeeded');
      if (location.hash !== next) location.hash = next;
      else await render(false);
    };
    const say = async (words) => {
      // Buttons wait; the text box keeps the focus (it used to fall off).
      document.querySelectorAll('#say button, [data-say]').forEach((b) => { b.disabled = true; });
      document.getElementById('words').focus();
      status.textContent = tp('describe.sending');
      try {
        const r = await send('POST', 'strategies/compile', { words, conversation_id: conversationId || null, strategy_id: strategyId });
        document.getElementById('words').value = '';
        await wait(r.job_id, `#describe/${target}/${r.conversation_id}`);
      } catch (e) {
        explain(status, e);
        document.querySelectorAll('#say button, [data-say]').forEach((b) => { b.disabled = false; });
      }
    };
    announceReply(status);
    // A message still being answered when the page opens: keep waiting.
    const pending = (convo?.waiting || []).find((w) => w.state === 'waiting');
    if (pending) {
      document.querySelectorAll('#say button').forEach((b) => { b.disabled = true; });
      status.textContent = tp('describe.waiting');
      wait(pending.job_id, location.hash);
    }
    document.getElementById('say').addEventListener('submit', (e) => {
      e.preventDefault();
      const words = document.getElementById('words').value.trim();
      if (words) say(words);
    });
    document.querySelectorAll('[data-say]').forEach((b) => b.addEventListener('click', () => say(b.dataset.say)));
    document.querySelectorAll('[data-confirm]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      try {
        const made = await send('POST', 'strategies/confirm', { conversation_id: conversationId, turn_id: Number(b.dataset.confirm) });
        location.hash = `#strategy/${made.strategy_id}`;
      } catch (e) { status.textContent = e.message; b.disabled = false; }
    }));
    document.querySelectorAll('[data-remember]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      try { await send('POST', 'memory', { note: b.dataset.remember }); status.textContent = tp('describe.remembered'); } catch (e) { status.textContent = e.message; }
    }));
  });
  return h;
}
