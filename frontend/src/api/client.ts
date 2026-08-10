import createClient from 'openapi-fetch'
import type { paths } from './schema'

// baseUrl "/" — same-origin in both dev (via vite.config.ts's proxy) and
// prod (FastAPI serves the built SPA itself). See plan §1.
export const api = createClient<paths>({ baseUrl: '/' })
