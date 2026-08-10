import { Navigate, Outlet } from 'react-router-dom'
import { useSessionProbe } from '../hooks/useAuth'

// Single route-guard for every authenticated route, replacing the 15
// independent per-page requireSession() calls from the old static
// dashboard. Renders nothing while the probe is pending so there's
// never a frame of visible protected content before the redirect.
export default function RequireAuth() {
  const { data } = useSessionProbe()

  if (!data) return null
  if (!data.authenticated) return <Navigate to="/login" replace />

  return <Outlet />
}
