// Messages and formatting. Every word the app shows comes from a catalogue
// (locales/<language>.json), looked up by key; numbers, money, percentages and
// dates are formatted by Intl for the chosen locale. English is the only
// catalogue shipped; a locale names a catalogue and a formatting region, so
// en-GB and en-US share the words and differ in dates and separators.
import en from './locales/en.json' with { type: 'json' };

const CATALOGUES = { en };
export const LOCALES = [['en-GB', 'English (United Kingdom)'], ['en-US', 'English (United States)']];

let locale = 'en-GB';
let messages = en;

function fromBrowser() {
  for (const tag of navigator.languages || [navigator.language || '']) {
    const exact = LOCALES.find(([t]) => t.toLowerCase() === tag.toLowerCase());
    if (exact) return exact[0];
    const lang = LOCALES.find(([t]) => t.split('-')[0] === tag.split('-')[0].toLowerCase());
    if (lang) return lang[0];
  }
  return 'en-GB';
}

export function setLocale(tag) {
  locale = LOCALES.some(([t]) => t === tag) ? tag : fromBrowser();
  messages = CATALOGUES[locale.split('-')[0]] || en;
  document.documentElement.lang = locale;
}
export const getLocale = () => locale;

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// A value that is already HTML (a glossary term, a formatted number) and is
// inserted into a message as it is; everything else is escaped.
export const raw = (html) => ({ html: String(html) });

const lookup = (catalogue, key) => key.split('.').reduce((o, k) => (o == null ? undefined : o[k]), catalogue);

function translate(key, vars, escape) {
  let m = lookup(messages, key);
  if (m === undefined) m = lookup(en, key);
  if (m && typeof m === 'object' && 'other' in m) m = m[new Intl.PluralRules(locale).select(vars.n ?? 0)] ?? m.other;
  if (typeof m !== 'string') return escape ? esc(key) : key;
  return m.replace(/\{(\w+)\}/g, (_, k) => {
    const v = vars[k];
    if (v && typeof v === 'object' && 'html' in v) return escape ? v.html : v.html.replace(/<[^>]*>/g, '');
    return escape ? esc(v ?? '') : String(v ?? '');
  });
}
// The message for `key` as HTML, with {placeholders} filled. Messages are
// trusted text; values are escaped unless wrapped in raw(). A message given
// as {one, other, ...} is chosen by the locale's plural rules for vars.n.
export const t = (key, vars = {}) => translate(key, vars, true);
// The same as plain text, for attributes and chart labels (escape on use).
export const tp = (key, vars = {}) => translate(key, vars, false);
// The catalogue entry itself, for lists of paragraphs and similar.
export const entry = (key) => lookup(messages, key) ?? lookup(en, key);

const nf = (opts) => new Intl.NumberFormat(locale, opts);
const missing = (v) => v === null || v === undefined || Number.isNaN(v);
const DASH = '–';

export const fmt = {
  num: (v, d = 3) => (missing(v) ? DASH : nf({ minimumFractionDigits: d, maximumFractionDigits: d }).format(v)),
  int: (v) => (missing(v) ? DASH : nf({ maximumFractionDigits: 0 }).format(v)),
  money: (v, d = 2) => (missing(v) ? DASH : nf({ style: 'currency', currency: 'USD', minimumFractionDigits: d, maximumFractionDigits: d }).format(v)),
  signedMoney: (v, d = 2) => (missing(v) ? DASH : nf({ style: 'currency', currency: 'USD', minimumFractionDigits: d, maximumFractionDigits: d, signDisplay: 'exceptZero' }).format(v)),
  pct: (v, d = 0) => (missing(v) ? DASH : nf({ style: 'percent', minimumFractionDigits: d, maximumFractionDigits: d }).format(v)),
  signedPct: (v, d = 1) => (missing(v) ? DASH : nf({ style: 'percent', minimumFractionDigits: d, maximumFractionDigits: d, signDisplay: 'exceptZero' }).format(v)),
  signed: (v, d = 3) => (missing(v) ? DASH : nf({ minimumFractionDigits: d, maximumFractionDigits: d, signDisplay: 'exceptZero' }).format(v)),
  cents: (v, d = 1) => (missing(v) ? DASH : t('fmt.cents', { n: nf({ minimumFractionDigits: d, maximumFractionDigits: d }).format(100 * v) })),
  date: (iso) => (iso ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(iso)) : DASH),
  dateTime: (iso) => (iso ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso)) : DASH),
  shortDate: (ms) => new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short' }).format(new Date(ms)),
  // "in 2 days", "3 hours ago"
  relative(iso, now = Date.now()) {
    if (!iso) return DASH;
    const secs = (new Date(iso).getTime() - now) / 1000;
    const units = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    for (const [unit, size] of units) if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit);
    return rtf.format(Math.round(secs / 60), 'minute');
  },
};
