import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Backend routes this SPA talks to — proxied to FastAPI in dev so the
// browser sees everything as same-origin (matches prod, where FastAPI
// serves the built SPA itself). See CLAUDE.md / plan §1 for why no
// CORS middleware is needed either way.
const API_PATHS = [
  'login', 'logout', 'health', 'text', 'agent-activity', 'voice', 'transcribe',
  'synthesize', 'threads', 'vault', 'projects', 'settings', 'debug', 'device',
  'alert-sounds', 'checkins', 'checkin', 'reminders', 'activity-log', 'calendar',
]

// A few of these paths (settings, reminders, projects, activity-log) are
// *also* top-level SPA routes — GET /settings serves JSON to a fetch()
// call, but a real browser navigation/refresh at /settings needs Vite's
// own SPA shell instead, or the proxy would forward the page load to the
// backend and get JSON back. Browsers mark real navigations with `Accept:
// text/html` (fetch() doesn't send that unless told to), so bypass the
// proxy for those and let Vite's own index.html fallback handle them —
// same distinguishing signal main.py's prefer_spa_for_html_navigation
// middleware uses for the equivalent collision in production.
function bypassHtmlNavigation(req: { headers: { accept?: string } }) {
  if (req.headers.accept?.includes('text/html')) return '/index.html'
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(
      API_PATHS.map((p) => [
        `/${p}`,
        { target: 'http://localhost:8000', bypass: bypassHtmlNavigation },
      ]),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
