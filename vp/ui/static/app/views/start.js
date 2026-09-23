// The guided start: what this is, pick interests, see your markets, choose
// a sample strategy to watch, choose a reading level. Five screens, one
// button each, skippable at every step and resumable: the step reached is
// saved, and Home offers to pick up where the person left off.
import { api } from '../api.js';
import { applyTheme, shell } from '../main.js';
import { prefs, save } from '../prefs.js';
import { after, esc, fmt, strategyLabel, strategySentence, t } from '../ui.js';
import { followed } from './home.js';
import { marketCard, orderedDomains } from './markets.js';

const STEPS = 5;

const choice = (type, name, value, checked, title, text) => `<label class="choice"><input type="${type}" name="${name}" value="${esc(value)}"${checked ? ' checked' : ''}>
  <span><span class="t">${title}</span><br><span class="d">${text}</span></span></label>`;

async function body(step, o) {
  const p = prefs();
  switch (step) {
    case 0:
      return `<p>${t('start.what_1')}</p><p>${t('start.what_2')}</p><div class="aside"><p>${t('start.what_3')}</p></div>`;
    case 1:
      return `<fieldset><legend>${t('start.interests_q')}</legend><div class="choices">${Object.entries(o.domains).map(([name, d]) =>
        choice('checkbox', 'interests', name, p.interests.includes(name), esc(d.title), esc(d.summary))).join('')}</div></fieldset>
        <p class="small muted">${t('start.interests_note')}</p>`;
    case 2: {
      for (const [name, d] of orderedDomains(o.domains)) {
        if (p.interests.length && !p.interests.includes(name)) continue;
        const snap = await api('snapshots/' + encodeURIComponent(name));
        const cards = (snap?.markets || []).filter((m) => m.has_book && m.p_yes != null).slice(0, 3);
        if (cards.length) {
          return `<p>${t('start.markets_intro', { title: d.title })}</p><div class="grid">${cards.map((m) => marketCard(m, name)).join('')}</div>
            <p class="small muted" style="margin-top:12px">${t('start.markets_note')}</p>`;
        }
      }
      return `<p>${t('start.markets_none')}</p>`;
    }
    case 3: {
      const accounts = o.paper.accounts;
      if (!accounts.length) return `<p>${t('start.sample_none')}</p>`;
      const current = followed(accounts);
      return `<fieldset><legend>${t('start.sample_q')}</legend><div class="choices">${accounts.map((a) =>
        choice('radio', 'follow', a.forecaster, a === current, esc(strategyLabel(a.forecaster)),
          `${esc(strategySentence(a.forecaster))} ${t('start.sample_balance', { balance: fmt.money(a.bankroll) })}`)).join('')}</div></fieldset>`;
    }
    default:
      return `<fieldset><legend>${t('start.level_q')}</legend><div class="choices">
        ${choice('radio', 'level', 'simple', p.level === 'simple', t('level.simple'), t('settings.level_simple'))}
        ${choice('radio', 'level', 'detailed', p.level === 'detailed', t('level.detailed'), t('settings.level_detailed'))}</div></fieldset>
        <p class="small muted">${t('start.level_note')}</p>`;
  }
}

// What the current step's controls say, as a settings patch.
function collect(step) {
  const form = document.getElementById('step');
  if (step === 1) return { interests: [...form.querySelectorAll('input[name=interests]:checked')].map((x) => x.value) };
  const picked = form.querySelector('input[type=radio]:checked');
  return picked ? { [picked.name]: picked.value } : {};
}

export default async function start([n] = []) {
  const step = Math.min(Math.max(parseInt(n, 10) || 0, 0), STEPS - 1);
  const o = await api('overview');
  const last = step === STEPS - 1;
  let h = `<div class="start"><p class="steps">${t('start.step', { n: step + 1, total: STEPS })}</p>
    <div class="progress" aria-hidden="true">${Array.from({ length: STEPS }, (_, i) => `<i class="${i <= step ? 'on' : ''}"></i>`).join('')}</div>
    <h1 id="page-title" tabindex="-1">${t(`start.titles.${step}`)}</h1><form id="step">${await body(step, o)}
    <div class="nav-row">${step ? `<button class="btn" type="button" id="back">${t('start.back')}</button>` : ''}
    <button class="btn quiet" type="button" id="skip-tour">${t('start.skip')}</button><span class="spacer"></span>
    <button class="btn primary" type="submit">${last ? t('start.finish') : step ? t('start.next') : t('start.begin')}</button></div></form></div>`;
  after(() => {
    const go = async (to, done = false) => {
      await save({ ...collect(step), start: { step: done ? prefs().start.step : to, done } });
      if (done) { applyTheme(); shell(); location.hash = '#home'; return; }
      location.hash = '#start/' + to;
    };
    document.getElementById('step').addEventListener('submit', (e) => { e.preventDefault(); go(step + 1, last); });
    document.getElementById('back')?.addEventListener('click', () => go(step - 1));
    document.getElementById('skip-tour').addEventListener('click', () => go(step, true));
  });
  return h;
}
