// A person's interface settings. Hosted, they are saved to the server
// (`/api/settings`), so they follow the person between devices; this
// browser keeps a copy so the first paint already has the right theme and
// reading level. Under `vp ui` there is no server copy and the browser's is
// the only one.
import { send, session } from './api.js';

const KEY = 'vp-settings';
export const DEFAULTS = { level: 'simple', theme: 'system', locale: null, interests: [], follow: null, start: { step: 0, done: false } };
let current = { ...DEFAULTS };

function readLocal() {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || '{}');
    const theme = localStorage.getItem('vp-theme'); // the dashboard's older key
    return theme && !stored.theme ? { ...stored, theme } : stored;
  } catch { return {}; }
}
function writeLocal() { try { localStorage.setItem(KEY, JSON.stringify(current)); } catch { /* private mode */ } }

export function loadLocal() { current = { ...DEFAULTS, ...readLocal() }; return current; }

export async function loadRemote() {
  if (!session.hosted) return current;
  try {
    const r = await fetch('/api/settings');
    if (r.ok) { current = { ...DEFAULTS, ...(await r.json()) }; writeLocal(); }
  } catch { /* keep the local copy */ }
  return current;
}

export const prefs = () => current;

export async function save(patch) {
  current = { ...current, ...patch };
  writeLocal();
  if (session.hosted) current = { ...DEFAULTS, ...(await send('PUT', 'settings', current)) };
  return current;
}
