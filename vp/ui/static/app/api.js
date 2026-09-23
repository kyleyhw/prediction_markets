// Talking to the server. The same page runs under `vp serve` (hosted, with
// accounts) and `vp ui` (a developer's local, read-only view with no
// accounts); `hosted` says which, and a few things differ: sign-in, saved
// settings, and whether empty states may show the command that fills them.
export const session = { hosted: false, me: null };

const isJson = (r) => (r.headers.get('content-type') || '').includes('json');

export async function api(path) {
  const r = await fetch('/api/' + path);
  // Under `vp serve` the data needs a session; `vp ui` never answers 401.
  if (r.status === 401) { location.href = '/sign-in'; return new Promise(() => {}); }
  if (r.status === 404) return null;
  if (!r.ok || !isJson(r)) throw new Error('HTTP ' + r.status);
  return r.json();
}

export async function send(method, path, body) {
  const r = await fetch('/api/' + path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) { location.href = '/sign-in'; return new Promise(() => {}); }
  if (!r.ok) {
    // The service explains a refusal in `detail`; show that, not a status.
    let detail = 'HTTP ' + r.status;
    try {
      const body = await r.json();
      if (typeof body.detail === 'string') detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg).join('; ');
    } catch { /* not JSON */ }
    const error = new Error(detail);
    error.status = r.status;
    throw error;
  }
  return r.status === 204 ? null : r.json();
}

// Who is signed in. `vp ui` answers every unknown path with the page, so
// only a JSON answer counts as an account.
export async function whoAmI() {
  try {
    const r = await fetch('/auth/me');
    if (r.ok && isJson(r)) { session.me = await r.json(); session.hosted = true; }
  } catch { /* local */ }
  return session;
}
