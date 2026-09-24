// Leaderboards (task 84): strategies their owners entered, ranked by how
// much better their forecasts were than the market's own price on the same
// questions, with the interval around that, and only once a strategy has
// enough settled forecasts to say so. Never by money won alone: a lucky run
// of large bets is not skill.
import { api, session } from '../api.js';
import { after, detailed, empty, esc, fmt, head, level, signed, t, table, term, tp } from '../ui.js';

const WINDOWS = ['30d', '90d', 'all'];

function board(b, domain, window) {
  if (!b || !b.entries.length) return empty(t('leaderboards.empty'), t('leaderboards.empty_text'), [['#strategies', t('leaderboards.enter')]]);
  const ranked = b.entries.filter((e) => e.rank);
  const waiting = b.entries.filter((e) => !e.rank);
  let h = '';
  if (ranked.length) {
    const cols = [t('leaderboards.rank'), t('col.strategy'), t('col.settled')];
    if (detailed()) cols.push(term('skill', tp('col.forward_skill')), t('leaderboards.advantage'), t('leaderboards.pnl'));
    else cols.push(t('leaderboards.verdict'));
    h += table(cols, ranked.map((e) => {
      const row = [esc(e.rank), esc(e.name), esc(fmt.int(e.settled))];
      const a = e.advantage;
      if (detailed()) row.push(signed(e.skill, esc(fmt.signed(e.skill))), esc(`${fmt.signed(a.mean, 4)} [${fmt.num(a.low, 4)}, ${fmt.num(a.high, 4)}]`), esc(fmt.signedMoney(e.pnl)));
      else row.push(t(a.low > 0 ? 'leaderboards.better' : a.high < 0 ? 'leaderboards.worse' : 'leaderboards.level'));
      return row;
    }), { caption: t('leaderboards.caption', { domain, window: tp('leaderboards.windows.' + window) }), numFrom: detailed() ? 2 : 9 });
  } else h += `<p class="muted">${t('leaderboards.none_ranked', { n: b.min_ranked })}</p>`;
  if (waiting.length) {
    h += `<h3>${t('leaderboards.waiting', { n: b.min_ranked })}</h3><ul class="notes">${waiting.map((e) => `<li>${esc(e.name)}: ${t('leaderboards.settled_n', { n: e.settled })}</li>`).join('')}</ul>`;
  }
  return h + `<p class="small muted">${t('leaderboards.computed', { when: fmt.dateTime(b.computed_at) })}</p>`;
}

export default async function leaderboards([domain = 'all', window = '90d'] = []) {
  if (!session.hosted) return head(t('leaderboards.title')) + empty(t('team.local'), t('team.local_text'), [['#home', t('error.home')]]);
  const [boards, overview] = await Promise.all([api('leaderboards'), api('overview')]);
  const titles = { all: tp('leaderboards.all'), ...Object.fromEntries(Object.entries(overview?.domains || {}).map(([n, d]) => [n, d.title])) };
  if (!titles[domain]) domain = 'all';
  if (!WINDOWS.includes(window)) window = '90d';
  let h = head(t('leaderboards.title'), level(t('leaderboards.lede_simple', { n: 50 }), t('leaderboards.lede_detailed', { n: 50 })));
  h += `<form id="board-pick" class="row"><label for="board-domain">${t('col.domain')}</label><select id="board-domain">${Object.entries(titles).map(([n, title]) => `<option value="${esc(n)}"${n === domain ? ' selected' : ''}>${esc(title)}</option>`).join('')}</select>
    <label for="board-window">${t('leaderboards.window')}</label><select id="board-window">${WINDOWS.map((w) => `<option value="${w}"${w === window ? ' selected' : ''}>${t('leaderboards.windows.' + w)}</option>`).join('')}</select></form>`;
  h += board(boards?.[`${domain}:${window}`], titles[domain], window);
  h += `<p class="small muted measure">${t('leaderboards.how')}</p>`;
  after(() => document.getElementById('board-pick').addEventListener('change', () => {
    location.hash = `#leaderboards/${document.getElementById('board-domain').value}/${document.getElementById('board-window').value}`;
  }));
  return h;
}
