// The site's one script: the theme switch, copy buttons, and search over
// search.json, loaded on first use. The pages read fully without it.
(() => {
  const root = document.documentElement.dataset.root || './';
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const saved = store.get('vp-site-theme');
  if (saved) document.documentElement.dataset.theme = saved;

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('theme')?.addEventListener('click', () => {
      const dark = matchMedia('(prefers-color-scheme: dark)').matches;
      const now = document.documentElement.dataset.theme || (dark ? 'dark' : 'light');
      const next = now === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      store.set('vp-site-theme', next);
    });

    for (const pre of document.querySelectorAll('article pre')) {
      const b = document.createElement('button');
      b.className = 'copy'; b.type = 'button'; b.textContent = 'Copy';
      b.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(pre.innerText.replace(/Copy$/, '').trim()); b.textContent = 'Copied'; }
        catch { b.textContent = 'Select and copy'; }
        setTimeout(() => { b.textContent = 'Copy'; }, 1500);
      });
      pre.appendChild(b);
    }

    let index = null;
    const load = async () => {
      if (!index) index = await (await fetch(root + 'search.json')).json();
      return index;
    };
    const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const search = (q) => {
      // A light stem, so "strategy" finds "strategies" and "fees" "fee".
      const stem = (w) => (w.length > 5 ? w.replace(/(ies|es|s|y)$/, '') : w.replace(/s$/, ''));
      const words = q.toLowerCase().split(/\s+/).filter((w) => w.length > 1).map(stem);
      if (!words.length) return [];
      // Each entry is one section of a page: its title counts most, then
      // the section's heading, then how often the words occur in its text.
      const scored = [];
      for (const p of index) {
        const t = p.t.toLowerCase(), h = p.h.toLowerCase(), x = p.x.toLowerCase();
        let score = 0;
        for (const w of words) {
          const inText = x.includes(w);
          if (!t.includes(w) && !h.includes(w) && !inText) { score = 0; break; }
          score += (t.includes(w) ? 6 : 0) + (h.includes(w) ? 5 : 0) + (inText ? 1 + Math.min(x.split(w).length - 1, 20) / 10 : 0);
        }
        if (q.length > 3 && (h.includes(q.toLowerCase()) || t.includes(q.toLowerCase()))) score += 6;
        if (score) scored.push([score, p]);
      }
      scored.sort((a, b) => b[0] - a[0]);
      const seen = new Set(), best = [];
      for (const [, p] of scored) {  // the best section of each page
        if (seen.has(p.t)) continue;
        seen.add(p.t); best.push(p);
        if (best.length === 12) break;
      }
      return best;
    };
    const item = (p, q) => {
      const x = p.x.toLowerCase(), i = x.indexOf(q.toLowerCase().split(/\s+/)[0]);
      const snip = i < 0 ? p.x.slice(0, 110) : p.x.slice(Math.max(0, i - 40), i + 90);
      const where = p.h ? `${p.s} › ${p.h}` : p.s;
      return `<li><a href="${root}${p.u}">${esc(p.t)}<small>${esc(where)} · ${esc(snip)}…</small></a></li>`;
    };

    const input = document.getElementById('q');
    const list = document.getElementById('results');
    input?.addEventListener('input', async () => {
      const q = input.value.trim();
      if (q.length < 2) { list.hidden = true; return; }
      await load();
      const found = search(q);
      list.innerHTML = found.length ? found.map((p) => item(p, q)).join('') : '<li><small style="padding:6px 12px">Nothing found.</small></li>';
      list.hidden = false;
    });
    input?.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { list.hidden = true; input.blur(); }
      if (e.key === 'ArrowDown') { e.preventDefault(); list.querySelector('a')?.focus(); }
    });
    list?.addEventListener('keydown', (e) => {
      const links = [...list.querySelectorAll('a')], i = links.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); links[Math.min(i + 1, links.length - 1)]?.focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); (i > 0 ? links[i - 1] : input).focus(); }
      if (e.key === 'Escape') { list.hidden = true; input.focus(); }
    });
    document.addEventListener('click', (e) => { if (list && !e.target.closest('.search')) list.hidden = true; });

    const page = document.getElementById('page-results');
    const q = new URLSearchParams(location.search).get('q');
    if (page && q) {
      input.value = q;
      load().then(() => {
        const found = search(q);
        page.innerHTML = found.length ? found.map((p) => item(p, q)).join('') : '<li>Nothing found.</li>';
      });
    }
  });
})();
