// The demo's engine: a spec checked, put in words and backtested in the page.
//
// Each function is a port of the Python it names, kept line for line so the
// two can be compared; tests/test_demo.py runs both on the same inputs and
// fails on any difference. The data comes from `vp demo` (vp/demo.py): each
// resolved market's price and every statistical forecaster's probability at
// a few cutoffs, computed ahead of time through the engine's cutoff-bounded
// evidence. Nothing here forecasts.

// ---------------------------------------------------------------- the shape

// Pydantic's checks, as far as the spec's JSON schema states them: closed
// objects, types, bounds and defaults. Returns [value with defaults, errors].
export function conform(value, schema, path = '') {
  const errors = [];
  const at = (msg) => errors.push(`${path || 'spec'}: ${msg}`);
  if (schema.anyOf) {
    for (const option of schema.anyOf) {
      const [v, e] = conform(value, option, path);
      if (!e.length) return [v, []];
    }
    at('not one of the allowed forms');
    return [value, errors];
  }
  if ('const' in schema && value !== schema.const) at(`must be ${JSON.stringify(schema.const)}`);
  if (schema.enum && !schema.enum.includes(value)) at(`must be one of ${schema.enum.join(', ')}`);
  switch (schema.type) {
    case 'null':
      if (value !== null) at('must be empty');
      return [value, errors];
    case 'object': {
      if (value === null || typeof value !== 'object' || Array.isArray(value)) { at('must be an object'); return [value, errors]; }
      const out = {};
      const props = schema.properties || {};
      for (const key of Object.keys(value)) if (!(key in props)) errors.push(`${path ? path + '.' : ''}${key}: not a setting a spec has`);
      for (const [key, sub] of Object.entries(props)) {
        const where = path ? `${path}.${key}` : key;
        if (key in value) {
          const [v, e] = conform(value[key], sub, where);
          out[key] = v; errors.push(...e);
        } else if ('default' in sub) {
          out[key] = structuredClone(sub.default);
          if (out[key] && typeof out[key] === 'object' && !Array.isArray(out[key])) out[key] = conform(out[key], sub, where)[0];
        } else if ((schema.required || []).includes(key)) errors.push(`${where}: missing`);
        else if (sub.type === 'array') out[key] = []; // a default_factory, which the schema omits
        else if (sub.type === 'object' || sub.properties) out[key] = conform({}, sub, where)[0];
      }
      return [out, errors];
    }
    case 'array': {
      if (!Array.isArray(value)) { at('must be a list'); return [value, errors]; }
      if (schema.minItems != null && value.length < schema.minItems) at(`needs at least ${schema.minItems}`);
      const out = value.map((item, i) => { const [v, e] = conform(item, schema.items || {}, `${path}.${i}`); errors.push(...e); return v; });
      return [out, errors];
    }
    case 'string':
      if (typeof value !== 'string') { at('must be text'); break; }
      if (schema.minLength != null && value.length < schema.minLength) at(`needs at least ${schema.minLength} characters`);
      if (schema.maxLength != null && value.length > schema.maxLength) at(`at most ${schema.maxLength} characters`);
      break;
    case 'integer':
    case 'number':
      if (typeof value !== 'number' || !Number.isFinite(value) || (schema.type === 'integer' && !Number.isInteger(value))) { at(`must be a ${schema.type}`); break; }
      if (schema.minimum != null && value < schema.minimum) at(`must be at least ${schema.minimum}`);
      if (schema.maximum != null && value > schema.maximum) at(`must be at most ${schema.maximum}`);
      if (schema.exclusiveMinimum != null && value <= schema.exclusiveMinimum) at(`must be more than ${schema.exclusiveMinimum}`);
      if (schema.exclusiveMaximum != null && value >= schema.exclusiveMaximum) at(`must be less than ${schema.exclusiveMaximum}`);
      break;
    case 'boolean':
      if (typeof value !== 'boolean') at('must be true or false');
      break;
    default:
  }
  return [value, errors];
}

// ------------------------------------------------- vp/strategy/spec.py: words

// Python's format(v, 'g'): six significant digits, no trailing zeros.
export function g(v) {
  if (v === 0) return '0';
  const exp = Math.floor(Math.log10(Math.abs(v)));
  if (exp < -4 || exp >= 6) {
    const [m, e] = Number(v).toExponential(5).split('e');
    const mant = m.includes('.') ? m.replace(/0+$/, '').replace(/\.$/, '') : m;
    const n = parseInt(e, 10);
    return `${mant}e${n < 0 ? '-' : '+'}${String(Math.abs(n)).padStart(2, '0')}`;
  }
  return String(parseFloat(Number(v).toPrecision(6)));
}

const commas = (s) => s.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
// Python rounds half to even when formatting; toFixed rounds the binary value,
// which agrees for every amount a spec can hold.
const usd = (v) => (Number.isInteger(v) ? `$${commas(v.toFixed(0))}` : `$${commas(v.toFixed(2).split('.')[0])}.${v.toFixed(2).split('.')[1]}`);
const pct = (v) => `${g(v * 100)}%`;
const points = (v) => { const n = v * 100; return `${g(n)} point` + (n === 1 ? '' : 's'); };
const cents = (v) => `${g(v * 100)}¢`;
const either = (values) => {
  const q = values.map((v) => `“${v}”`);
  return q.length === 1 ? q[0] : q.slice(0, -1).join(', ') + ' or ' + q[q.length - 1];
};
const OPS = { is: 'is', is_not: 'is not', contains: 'contains', at_least: 'is at least', at_most: 'is at most' };
const LIMIT_SHOW = {
  kelly_fraction: (v) => g(v),
  max_fraction: (v) => pct(v) + ' of the balance',
  flat_fraction: (v) => pct(v) + ' of the balance',
  min_edge: (v) => points(v),
};
const number = (text) => { const t = String(text).trim(); return t !== '' && Number.isFinite(Number(t)) ? Number(t) : null; };

export function render(spec, ctx) {
  return [renderMarkets(spec.selector, ctx), renderBelief(spec, ctx), renderTrade(spec.rule), renderSize(spec.rule, spec.sizing), renderWhen(spec.schedule, spec.sizing)];
}

function renderMarkets(sel, ctx) {
  const titles = sel.domains.map((d) => ctx.domains[d]?.title || d);
  const kinds = sel.kinds.length ? sel.kinds.map((k) => ctx.kind_names[k] || k.replaceAll('_', ' ')).join(', ') : 'their main markets';
  let text = `Markets: ${titles.join(' and ')}, ${kinds}`;
  for (const c of sel.where) text += `; where ${c.field.replaceAll('_', ' ')} ${OPS[c.op]} ${either(c.values)}`;
  if (sel.words.length) text += `; only questions mentioning ${either(sel.words)}`;
  if (sel.exclude_words.length) text += `; never questions mentioning ${either(sel.exclude_words)}`;
  text += '.';
  const floors = [];
  if (sel.min_volume_usd != null) floors.push(`at least ${usd(sel.min_volume_usd)} traded`);
  if (sel.min_liquidity_usd != null) floors.push(`at least ${usd(sel.min_liquidity_usd)} of liquidity`);
  if (sel.max_spread != null) floors.push(`a spread of at most ${cents(sel.max_spread)}`);
  if (floors.length) text += ' In paper only, a market also needs ' + floors.join(', ') + ' (a backtest cannot know these as they were).';
  return text;
}

function renderBelief(spec, ctx) {
  const b = spec.belief;
  if (spec.rule.kind === 'follow') return "Belief: none. It follows the market's own prices and makes no forecast.";
  const text = 'Belief: ' + (ctx.beliefs[b.forecaster] || b.forecaster);
  if (b.forecaster !== 'llm') return text + '.';
  return text + '. (An AI model as the forecaster runs on your own copy, not in this demo.)';
}

function renderTrade(rule) {
  let band = '';
  if (rule.price_min > 0 || rule.price_max < 1) band = ` only when the price is between ${cents(rule.price_min)} and ${cents(rule.price_max)}`;
  if (rule.kind === 'follow') {
    const side = rule.follow === 'favourite' ? 'favourite' : 'underdog';
    return `Trade: buys the ${side} of every market` + (band || ' at any price') + '.';
  }
  const sides = { both: 'on either side', yes: 'only on the first outcome (usually “Yes”)', no: 'only against the first outcome' }[rule.sides];
  const text = `Trade: when its chance beats the price after fees by at least ${points(rule.min_edge)}, ${sides}`;
  return text + (band ? `,${band}` : '') + '.';
}

function renderSize(rule, s) {
  let text = rule.kind === 'follow'
    ? `Size: ${pct(Math.min(s.flat_fraction, s.max_fraction))} of the balance on each`
    : `Size: ${g(s.kelly_fraction)} of the Kelly stake, at most ${pct(s.max_fraction)} of the balance on one market`;
  if (s.max_stake_usd != null) text += ` and never more than ${usd(s.max_stake_usd)}`;
  if (s.max_open != null) text += `; at most ${s.max_open} open at once`;
  if (s.max_per_event != null) text += `; at most ${s.max_per_event} in one event`;
  if (s.max_open != null || s.max_per_event != null) text += ' (in paper; a backtest settles each bet before the next)';
  return text + '.';
}

function renderWhen(sch, s) {
  const every = sch.cadence_hours === 1 ? 'every hour' : `every ${sch.cadence_hours} hours`;
  return `When: from ${g(sch.hours_before_close)} hours before a market's scheduled end, checked ${every}; a backtest forecasts each market ${g(sch.hours_before_close)} hours before it settled. Starts with ${usd(s.initial_cash)} of paper money.`;
}

// ------------------------------------------- vp/strategy/spec.py: validate

export function validate(spec, ctx) {
  const problems = [];
  const { selector: sel, belief, rule, sizing } = spec;
  const chosen = sel.domains.filter((d) => d in ctx.domains).map((d) => ctx.domains[d]);
  for (const name of sel.domains) if (!(name in ctx.domains)) problems.push(`There is no domain called ${repr(name)}.`);
  const kinds = {};
  for (const d of chosen) Object.assign(kinds, d.all_kinds);
  for (const kind of sel.kinds) if (!(kind in kinds)) problems.push(`The chosen domains have no markets of kind ${repr(kind)}.`);
  const fields = new Set();
  for (const [kind, names] of Object.entries(kinds)) {
    const used = sel.kinds.length ? sel.kinds.includes(kind) : chosen.some((d) => kind in d.kinds);
    if (used) names.forEach((f) => fields.add(f));
  }
  for (const c of sel.where) {
    if (chosen.length && !fields.has(c.field)) problems.push(`The chosen markets have no field ${repr(c.field)} to filter on.`);
    if ((c.op === 'at_least' || c.op === 'at_most') && (c.values.length !== 1 || number(c.values[0]) === null)) problems.push(`${c.op} on ${c.field} needs one number.`);
  }
  if (!(belief.forecaster in ctx.beliefs)) problems.push(`There is no forecaster called ${repr(belief.forecaster)}.`);
  if (belief.forecaster !== 'llm' && (belief.instructions || belief.sees_price)) problems.push('Instructions and showing the price apply only to the AI model.');
  if (rule.kind === 'follow') {
    if (rule.follow === null) problems.push('A follow rule must say whether it backs the favourite or the underdog.');
    if (belief.forecaster !== 'market') problems.push('A follow rule makes no forecast; its belief must be the market.');
  } else if (belief.forecaster === 'market') {
    problems.push("An edge rule needs a belief other than the market's own price, which never beats itself.");
  }
  if (rule.kind === 'edge' && rule.follow !== null) problems.push('Only a follow rule backs the favourite or the underdog.');
  if (rule.price_min >= rule.price_max) problems.push('The lowest price must be below the highest.');
  const limits = [
    ['kelly_fraction', sizing.kelly_fraction, 'at most'],
    ['max_fraction', sizing.max_fraction, 'at most'],
    ['flat_fraction', sizing.flat_fraction, 'at most'],
    ['min_edge', rule.min_edge, 'at least'],
  ];
  for (const [name, value, way] of limits) {
    const cap = ctx.caps[name];
    if (way === 'at most' ? value > cap : value < cap) problems.push(`${ctx.limit_names[name]} must be ${way} ${LIMIT_SHOW[name](cap)}.`);
  }
  return problems;
}

// Python's repr of a short string, as the messages quote names.
const repr = (s) => (s.includes("'") && !s.includes('"') ? `"${s}"` : `'${s.replaceAll('\\', '\\\\').replaceAll("'", "\\'")}'`);

// -------------------------------------------- vp/strategy/run.py: selects

function holds(c, value) {
  if (value === undefined || value === null || value === '') return false;
  const text = String(value).toLowerCase();
  const wanted = c.values.map((v) => v.toLowerCase());
  if (c.op === 'is') return wanted.includes(text);
  if (c.op === 'is_not') return !wanted.includes(text);
  if (c.op === 'contains') return wanted.some((w) => text.includes(w));
  const n = number(value);
  const bound = number(c.values[0]);
  if (n === null || bound === null) return false;
  return c.op === 'at_least' ? n >= bound : n <= bound;
}

export function selects(sel, market, domain, ctx) {
  if (!sel.domains.includes(domain)) return false;
  const kind = market.kind;
  if (sel.kinds.length) {
    if (!sel.kinds.includes(kind)) return false;
  } else if (kind == null || !ctx.domains[domain] || !(kind in ctx.domains[domain].kinds)) return false;
  if (!sel.where.every((c) => holds(c, market.fields[c.field]))) return false;
  const question = market.q.toLowerCase();
  if (sel.words.length && !sel.words.some((w) => question.includes(w.toLowerCase()))) return false;
  if (sel.exclude_words.some((w) => question.includes(w.toLowerCase()))) return false;
  return true;
}

// ------------------------------------------- vp/backtest/sizing.py: Policy

const perShare = (fees, p) => fees.rate * (p * (1 - p)) ** fees.exponent;
const kellyFraction = (p, price) => (price <= 0 || price >= 1 ? 0 : Math.max((p - price) / (1 - price), 0));

function size(p, ask, bid, fees, kelly, maxFraction, minEdge) {
  const yesPrice = ask + perShare(fees, ask);
  const noPrice = (1 - bid) + perShare(fees, 1 - bid);
  const yesEdge = p - yesPrice;
  const noEdge = (1 - p) - noPrice;
  if (Math.max(yesEdge, noEdge) <= Math.max(minEdge, 0)) return null;
  const [side, price, q] = yesEdge >= noEdge ? ['yes', yesPrice, p] : ['no', noPrice, 1 - p];
  const fraction = Math.min(kelly * kellyFraction(q, price), maxFraction);
  if (fraction <= 0) return null;
  return { side, price, fraction, edge: (q - price) / price };
}

export function policy(spec) {
  const { rule, sizing: s } = spec;
  return {
    kelly: s.kelly_fraction, maxFraction: s.max_fraction, minEdge: rule.min_edge, sides: rule.sides,
    follow: rule.kind === 'follow' ? rule.follow : null, flatFraction: s.flat_fraction,
    priceMin: rule.price_min, priceMax: rule.price_max, maxStake: s.max_stake_usd ?? null,
  };
}

export function position(pol, p, ask, bid, fees) {
  let pos;
  if (pol.follow !== null) {
    const favourite = ask + bid >= 1 ? 'yes' : 'no';
    const side = pol.follow === 'signal' ? (p >= 0.5 ? 'yes' : 'no') : pol.follow === 'favourite' ? favourite : favourite === 'yes' ? 'no' : 'yes';
    pos = { side, price: 0, fraction: Math.min(pol.flatFraction, pol.maxFraction), edge: 0 };
  } else {
    const found = size(p, ask, bid, fees, pol.kelly, pol.maxFraction, pol.minEdge);
    if (found === null || (pol.sides !== 'both' && pol.sides !== found.side)) return null;
    pos = found;
  }
  const quote = pos.side === 'yes' ? ask : 1 - bid;
  if (!(pol.priceMin <= quote && quote <= pol.priceMax) || !(quote > 0 && quote < 1)) return null;
  if (pol.follow !== null) return { side: pos.side, price: quote + perShare(fees, quote), fraction: pos.fraction, edge: 0 };
  return pos;
}

// ---------------------------------------- vp/backtest/simulate.py: simulate

export function simulate(opps, pol, { initialCash, halfSpread }) {
  let bankroll = initialCash;
  const bets = [];
  const sorted = [...opps].sort((a, b) => (a.settled < b.settled ? -1 : a.settled > b.settled ? 1 : 0));
  for (const o of sorted) {
    if (bankroll <= 0) break;
    const bid = Math.max(o.q - halfSpread, 0);
    const ask = Math.min(o.q + halfSpread, 1);
    const pos = position(pol, o.p, ask, bid, o.fees);
    if (pos === null) continue;
    let stake = Math.min(pos.fraction * bankroll, bankroll);
    if (pol.maxStake !== null) stake = Math.min(stake, pol.maxStake);
    const shares = stake / pos.price;
    const won = o.y === (pos.side === 'yes' ? 1 : 0);
    const pnl = won ? shares - stake : -stake;
    bankroll += pnl;
    const quote = pos.side === 'yes' ? ask : 1 - bid;
    bets.push({ market: o.market, settled: o.settled, side: pos.side, price: pos.price, stake, shares, pnl, bankroll, fee: shares * (pos.price - quote), y: o.y, q: o.q, p: o.p });
  }
  return bets;
}

// ------------------------------------------- vp/strategy/run.py: backtest

const clip = (p) => Math.min(Math.max(p, 0.01), 0.99);

// The cutoff the data has nearest the spec's (the page says which ran).
export function cutoffFor(hours, cutoffs) {
  return cutoffs.reduce((best, c) => (Math.abs(c - hours) < Math.abs(best - hours) ? c : best), cutoffs[0]);
}

export function backtest(spec, data, ctx) {
  const domain = data.domain;
  const cutoff = String(cutoffFor(spec.schedule.hours_before_close, data.cutoffs));
  const follow = spec.rule.kind === 'follow';
  const name = spec.belief.forecaster;
  const props = new Set(ctx.props);
  let candidates = 0;
  let assumed = 0;
  const opps = [];
  for (const m of data.markets) {
    if (spec.selector.kinds.length ? !spec.selector.kinds.includes(m.kind) : props.has(m.kind)) continue;
    if (!selects(spec.selector, m, domain, ctx)) continue;
    candidates += 1;
    if (m.fee === null) assumed += 1;
    const q = m.price[cutoff];
    if (q === undefined) continue;
    const p = follow ? clip(q) : m.f[name]?.[cutoff];
    if (p === undefined) continue;
    const fees = m.fee === null ? { rate: ctx.fee_rate_assumed, exponent: 1 } : { rate: m.fee[0], exponent: m.fee[1] };
    opps.push({ market: m, settled: m.settled, p, q, y: m.y, fees });
  }
  const bets = simulate(opps, policy(spec), { initialCash: spec.sizing.initial_cash, halfSpread: ctx.half_spread });
  return summarise(domain, Number(cutoff), candidates, opps, bets, assumed, follow, spec.sizing.initial_cash);
}

function summarise(domain, cutoff, candidates, opps, bets, assumed, noForecast, initialCash) {
  const n = opps.length;
  const brier = (f) => (n ? opps.reduce((s, o) => s + (f(o) - o.y) ** 2, 0) / n : 0);
  const reference = brier((o) => clip(o.q));
  const belief = brier((o) => o.p);
  let peak = initialCash;
  let drawdown = 0;
  for (const b of bets) { peak = Math.max(peak, b.bankroll); drawdown = Math.min(drawdown, (b.bankroll - peak) / (peak > 0 ? peak : 1)); }
  const pnl = bets.reduce((s, b) => s + b.pnl, 0);
  const staked = bets.reduce((s, b) => s + b.stake, 0);
  return {
    domain, cutoff, candidates, scored: n, fees_assumed: assumed, bets,
    brier: noForecast ? null : belief, brier_market: reference, skill: noForecast || !(reference > 0) ? null : 1 - belief / reference,
    pnl, staked, roi: staked > 0 ? pnl / staked : null, final: initialCash + pnl,
    wins: bets.filter((b) => b.pnl > 0).length, fees: bets.reduce((s, b) => s + b.fee, 0), max_drawdown: drawdown,
  };
}

// ------------------------------------------- a code strategy's answers

// The answers of a "Write your own code" strategy (pages/strategy_api.py):
// signals buy the side named at a flat stake, as a follow rule does; chances
// are an edge rule's belief. The same simulation as every other strategy.
export function backtestAnswers(data, run, settings, ctx) {
  const cutoff = String(settings.cutoff);
  const signals = run.sort === 'signal';
  const opps = [];
  let assumed = 0;
  for (const m of data.markets) {
    const a = run.answers[m.id];
    const q = m.price[cutoff];
    if (a === undefined || q === undefined) continue;
    if (m.fee === null) assumed += 1;
    const fees = m.fee === null ? { rate: ctx.fee_rate_assumed, exponent: 1 } : { rate: m.fee[0], exponent: m.fee[1] };
    opps.push({ market: m, settled: m.settled, p: signals ? (a === 'yes' ? 1 : 0) : a, q, y: m.y, fees });
  }
  const pol = {
    kelly: 0.25, maxFraction: settings.max_fraction, minEdge: settings.min_edge, sides: 'both',
    follow: signals ? 'signal' : null, flatFraction: settings.max_fraction, priceMin: 0, priceMax: 1, maxStake: null,
  };
  const bets = simulate(opps, pol, { initialCash: settings.initial_cash, halfSpread: ctx.half_spread });
  return summarise(data.domain, Number(cutoff), opps.length, opps, bets, assumed, signals, settings.initial_cash);
}
