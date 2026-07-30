// static/js/auth.js
//
// Shared client-side session gate for dashboard pages served under the
// generic /static mount — these can't get a server-side per-route
// redirect the way GET / can (main.py's serve_frontend), since
// StaticFiles just serves bytes regardless of session state. Call
// requireSession() first thing on page load; it does one cheap
// session-or-token-gated GET and bounces to /static/login.html on 401.
//
// Never imported by static/checkin.html or static/login.html — those
// pages are meant to work with no session at all (see their own
// comments for why).

export async function requireSession() {
  const response = await fetch('/settings');
  if (response.status === 401) {
    location.replace('/static/login.html');
    return false;
  }
  return true;
}

export async function logout() {
  await fetch('/logout', { method: 'POST' });
  location.replace('/static/login.html');
}
