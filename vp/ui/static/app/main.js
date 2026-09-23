// The shell: settings, the sidebar, the reading-level switch, and a router
// over the location hash. Each view is an async function returning HTML;
// the router puts it in <main>, runs the view's hooks, names the page in
// the title and, after a navigation, moves focus to the page heading so a
// screen reader announces where the person has arrived.
import { api, send, session, whoAmI } from './api.js';
import { esc, setLocale, t, tp } from './i18n.js';
import { loadLocal, loadRemote, prefs, save } from './prefs.js';
import { after, installGlossary, runHooks } from './ui.js';
import backtests from './views/backtests.js';
import describe from './views/describe.js';
import home from './views/home.js';
import learn from './views/learn.js';
import market from './views/market.js';
import markets from './views/markets.js';
import research from './views/research.js';
import settings from './views/settings.js';
import start from './views/start.js';
import strategies from './views/strategies.js';
import strategy from './views/strategy.js';

const ROUTES = { home, markets, market, strategies, strategy, describe, research, backtests, learn, settings, start };
const NAV = ['home', 'markets', 'strategies', 'backtests', 'learn', 'settings'];
const SECTION = { market: 'markets', start: 'home', strategy: 'strategies', describe: 'strategies', research: 'strategies' };

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
      <form method="post" action="/auth/sign-out"><button class="btn quiet" type="submit" style="padding:4px 0;min-height:24px">${t('account.sign_out')}</button></form>
      <span class="small"><a href="/terms">${t('account.terms')}</a> · <a href="/privacy">${t('account.privacy')}</a></span>`;
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
    // Nothing else shows until the current terms are accepted (task 48).
    main.innerHTML = session.hosted && !session.me.consent?.current ? consent() : await ROUTES[route](args);
  } catch (e) {
    main.innerHTML = `<h1 id="page-title" tabindex="-1">${t('error.title')}</h1><p class="lede">${t('error.text', { message: e.message })}</p>
      <a class="btn primary" href="#home">${t('error.home')}</a>`;
  }
  runHooks();
  const title = document.getElementById('page-title');
  document.title = `${title ? title.textContent : ''} · vibe-predict`;
  if (moveFocus && title) title.focus();
}

// The terms, the privacy notice and the age, when a person's acceptance is
// missing or older than the current version.
function consent() {
  after(() => document.getElementById('consent')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.currentTarget, status = document.getElementById('consent-status');
    if (!form.adult.checked) { status.textContent = tp('consent.needed'); return; }
    try {
      await send('POST', 'consent', { version: session.me.consent.required, adult: true });
      await whoAmI();
      await render(true);
    } catch (err) { status.textContent = err.message; }
  }));
  return `<h1 id="page-title" tabindex="-1">${t('consent.title')}</h1><p class="lede">${t('consent.text')}</p>
    <p><a href="/terms" target="_blank">${t('account.terms')}</a> · <a href="/privacy" target="_blank">${t('account.privacy')}</a></p>
    <form id="consent" class="measure"><label class="check"><input type="checkbox" name="adult"> <span>${t('consent.adult')}</span></label>
    <button class="btn primary" type="submit" style="margin-top:12px">${t('consent.button')}</button><p class="small" id="consent-status" role="status"></p></form>`;
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
