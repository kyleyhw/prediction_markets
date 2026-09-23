// The shell: settings, the sidebar, the reading-level switch, and a router
// over the location hash. Each view is an async function returning HTML;
// the router puts it in <main>, runs the view's hooks, names the page in
// the title and, after a navigation, moves focus to the page heading so a
// screen reader announces where the person has arrived.
import { api, session, whoAmI } from './api.js';
import { esc, setLocale, t, tp } from './i18n.js';
import { loadLocal, loadRemote, prefs, save } from './prefs.js';
import { installGlossary, runHooks } from './ui.js';
import backtests from './views/backtests.js';
import home from './views/home.js';
import learn from './views/learn.js';
import market from './views/market.js';
import markets from './views/markets.js';
import settings from './views/settings.js';
import start from './views/start.js';
import strategies from './views/strategies.js';

const ROUTES = { home, markets, market, strategies, backtests, learn, settings, start };
const NAV = ['home', 'markets', 'strategies', 'backtests', 'learn', 'settings'];
const SECTION = { market: 'markets', start: 'home' };

export function applyTheme() {
  const theme = prefs().theme;
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
}

export function shell() {
  document.getElementById('tagline').textContent = tp('app.tagline');
  document.getElementById('skip').textContent = tp('app.skip');
  document.getElementById('nav').innerHTML = `<ul>${NAV.map((n) => `<li><a href="#${n}">${t('nav.' + n)}</a></li>`).join('')}</ul>`;
  const level = prefs().level;
  document.getElementById('level').innerHTML = `<span class="label" id="level-label">${t('level.label')}</span>
    <div class="seg" role="group" aria-labelledby="level-label">${['simple', 'detailed'].map((l) =>
      `<button type="button" data-level="${l}" aria-pressed="${l === level}">${t('level.' + l)}</button>`).join('')}</div>`;
  const foot = document.getElementById('foot');
  if (session.hosted) {
    foot.innerHTML = `<span class="who" title="${esc(session.me.email)}">${esc(session.me.email)}</span>
      <form method="post" action="/auth/sign-out"><button class="btn quiet" type="submit" style="padding:4px 0;min-height:24px">${t('account.sign_out')}</button></form>`;
  } else {
    foot.innerHTML = `<span>${t('account.local')}</span><code id="root"></code>`;
    api('overview').then((o) => { if (o?.root) document.getElementById('root').textContent = o.root; }).catch(() => {});
  }
  document.querySelectorAll('#level button').forEach((b) => b.addEventListener('click', async () => {
    await save({ level: b.dataset.level });
    shell();
    await render(false);
    document.querySelector(`#level button[data-level="${b.dataset.level}"]`)?.focus();
  }));
}

export async function render(moveFocus = true) {
  const [name, ...args] = location.hash.slice(1).split('/').map(decodeURIComponent);
  const route = ROUTES[name] ? name : 'home';
  const progress = prefs().start;
  // A person's first visit starts the guided tour; after that it is offered.
  if (route === 'home' && !progress.done && progress.step === 0 && !sessionStorage.getItem('vp-toured')) {
    sessionStorage.setItem('vp-toured', '1');
    location.replace('#start');
    return;
  }
  const section = SECTION[route] || route;
  document.querySelectorAll('#nav a').forEach((a) => {
    if (a.getAttribute('href') === '#' + section) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  const main = document.getElementById('main');
  try {
    main.innerHTML = await ROUTES[route](args);
  } catch (e) {
    main.innerHTML = `<h1 id="page-title" tabindex="-1">${t('error.title')}</h1><p class="lede">${t('error.text', { message: e.message })}</p>
      <a class="btn primary" href="#home">${t('error.home')}</a>`;
  }
  runHooks();
  const title = document.getElementById('page-title');
  document.title = `${title ? title.textContent : ''} · vibe-predict`;
  if (moveFocus && title) title.focus();
}

async function boot() {
  loadLocal();
  applyTheme();
  await whoAmI();
  await loadRemote();
  setLocale(prefs().locale);
  applyTheme();
  installGlossary();
  shell();
  document.getElementById('skip').addEventListener('click', (e) => { e.preventDefault(); document.getElementById('main').focus(); });
  addEventListener('hashchange', () => render(true));
  await render(false);
}

boot();
