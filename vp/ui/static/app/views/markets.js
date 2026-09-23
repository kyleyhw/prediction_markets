// Markets: the open markets of one interest as cards, from the latest
// snapshot. Simple shows the question, the chance, when it closes and what
// buying costs in fees; Detailed adds the quotes, the market type and the
// fee rate. The search filters in place, without re-rendering the page.
import { api } from '../api.js';
import { prefs } from '../prefs.js';
import { after, chance, detailed, empty, esc, feeSentence, fmt, head, kindName, t, term, tp } from '../ui.js';

const PAGE = 36;

export const stampIso = (stamp) => {
  const m = String(stamp || '').match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
  return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z` : null;
};

// Interests first, then the rest, each as [name, {title, summary, ...}].
export function orderedDomains(domains) {
  const mine = prefs().interests;
  return Object.entries(domains).sort(([a], [b]) => (mine.includes(a) ? mine.indexOf(a) : 99) - (mine.includes(b) ? mine.indexOf(b) : 99));
}

export function marketCard(m, domain) {
  const closes = m.end_date ? t('markets.closes', { when: fmt.relative(m.end_date) }) : t('markets.no_close');
  const facts = [closes, feeSentence(m)];
  if (!m.has_book) facts.push(t('markets.no_book'));
  if (detailed()) {
    facts.push(`${term('bid', tp('glossary.bid.name'))} <span class="num">${esc(fmt.num(m.bid, 3))}</span> · ${term('ask', tp('glossary.ask.name'))} <span class="num">${esc(fmt.num(m.ask, 3))}</span>`);
    facts.push(`<span class="pill">${kindName(m.kind)}</span>`);
  }
  const width = m.p_yes == null ? 0 : Math.round(100 * m.p_yes);
  return `<article class="card mcard">
    <h3 class="q"><a href="#market/${encodeURIComponent(domain)}/${encodeURIComponent(m.market_id)}">${esc(m.question)}</a></h3>
    ${m.event && m.event !== m.question ? `<div class="ev">${esc(m.event)}</div>` : ''}
    <div class="chance"><b class="num">${chance(m)}</b></div>
    <div class="meter" aria-hidden="true"><i style="width:${width}%"></i></div>
    <div class="facts">${facts.map((f) => `<span>${f}</span>`).join('')}</div></article>`;
}

export default async function markets([wanted] = []) {
  const o = await api('overview');
  const domains = orderedDomains(o.domains);
  const domain = o.domains[wanted] ? wanted : domains[0][0];
  const info = o.domains[domain];
  const snap = await api('snapshots/' + encodeURIComponent(domain));
  let h = head(t('markets.title'), t('markets.lede'));
  h += `<nav aria-label="${tp('markets.interests_label')}" class="row">${domains.map(([name, d]) =>
    `<a class="btn${name === domain ? ' primary' : ''}" href="#markets/${encodeURIComponent(name)}"${name === domain ? ' aria-current="page"' : ''}>${esc(d.title)}</a>`).join('')}</nav>`;
  h += `<p class="muted">${esc(info.summary)}</p>`;
  if (!snap || !snap.stamp) {
    return h + empty(t('markets.empty_title', { title: info.title }), t('markets.empty_text'), [['#learn/markets', t('learn.topics.markets.title')]], 'vp snapshot --domain ' + domain);
  }
  const traded = snap.markets.filter((m) => m.has_book).length;
  h += `<div class="row"><label for="q" class="sr-only">${t('markets.search_label')}</label>
    <input type="search" id="q" placeholder="${tp('markets.search_placeholder')}" autocomplete="off">
    <label class="check"><input type="checkbox" id="dead"> <span>${t('markets.show_untraded', { n: snap.markets.length - traded })}</span></label></div>
    <p class="small muted" id="count" role="status"></p><div class="grid cols-3" id="results"></div>
    <div class="row" style="margin-top:14px"><button class="btn" type="button" id="more" hidden>${t('markets.more')}</button></div>
    <p class="cap">${t('markets.as_of', { when: fmt.relative(stampIso(snap.stamp)), date: fmt.dateTime(stampIso(snap.stamp)) })}</p>`;
  after(() => {
    let shown = PAGE;
    const q = document.getElementById('q'), dead = document.getElementById('dead');
    dead.checked = !traded;
    const draw = () => {
      const words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
      const rows = snap.markets.filter((m) => (dead.checked || m.has_book)
        && words.every((w) => `${m.question} ${m.event || ''}`.toLowerCase().includes(w)));
      document.getElementById('results').innerHTML = rows.slice(0, shown).map((m) => marketCard(m, domain)).join('');
      document.getElementById('count').innerHTML = t('markets.count', { n: rows.length, shown: Math.min(shown, rows.length) });
      document.getElementById('more').hidden = rows.length <= shown;
    };
    let timer;
    q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { shown = PAGE; draw(); }, 200); });
    dead.addEventListener('change', () => { shown = PAGE; draw(); });
    document.getElementById('more').addEventListener('click', () => { shown += PAGE; draw(); });
    draw();
  });
  return h;
}
