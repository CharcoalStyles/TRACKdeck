// static/js/nav.js
//
// Shared header/nav markup, injected into a page's #appHeader element —
// avoids hand-duplicating the same <nav> block across every dashboard
// page. Same vanilla-ES-module pattern as chat.js/api.js/auth.js, no
// framework, no build step.
//
// Usage (call unconditionally, before the requireSession() gate, so the
// logout link still works even if the session check is about to
// redirect):
//   import { renderNav } from '/static/js/nav.js';
//   renderNav('chat');  // 'chat' | 'profile' | 'settings' | 'testing' |
//                        // 'checkins' | 'alert-sounds' | 'errors'

import { logout } from './auth.js';

const ADMIN_PAGES = ['settings', 'testing', 'checkins', 'alert-sounds', 'errors'];

export function renderNav(activePage) {
  const header = document.getElementById('appHeader');
  const isAdminActive = ADMIN_PAGES.includes(activePage);

  header.innerHTML = `
    <h1>Assistant Dashboard</h1>
    <nav>
      <a href="/static/index.html" class="${activePage === 'chat' ? 'active' : ''}">Chat</a>
      <a href="/static/profile.html" class="${activePage === 'profile' ? 'active' : ''}">Profile</a>
      <details class="nav-admin${isAdminActive ? ' active' : ''}">
        <summary>Admin</summary>
        <div class="nav-admin-menu">
          <a href="/static/settings.html" class="${activePage === 'settings' ? 'active' : ''}">Settings</a>
          <a href="/static/testing.html" class="${activePage === 'testing' ? 'active' : ''}">Testing</a>
          <a href="/static/checkins.html" class="${activePage === 'checkins' ? 'active' : ''}">Check-Ins</a>
          <a href="/static/alert-sounds.html" class="${activePage === 'alert-sounds' ? 'active' : ''}">Alert Sounds</a>
          <a href="/static/errors.html" class="${activePage === 'errors' ? 'active' : ''}">Errors</a>
          <a href="/calendar/" target="_blank" rel="noopener" title="Manage calendars (create/rename/delete) — to view or edit events, use a CalDAV app like Thunderbird or your phone's calendar">Calendar</a>
        </div>
      </details>
      <a href="#" id="logoutBtn">Log out</a>
    </nav>
  `;

  document.getElementById('logoutBtn').addEventListener('click', async (e) => {
    e.preventDefault();
    await logout();
  });
}
