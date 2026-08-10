import { Route, Routes } from 'react-router-dom'
import RequireAuth from './components/RequireAuth'
import AppShell from './components/layout/AppShell'
import LoginPage from './routes/LoginPage'
import ChatPage from './routes/ChatPage'
import ProfilePage from './routes/ProfilePage'
import VaultPage from './routes/VaultPage'
import ProjectsPage from './routes/ProjectsPage'
import ProjectPage from './routes/ProjectPage'
import SettingsPage from './routes/SettingsPage'
import RemindersPage from './routes/RemindersPage'
import CheckinsAdminPage from './routes/CheckinsAdminPage'
import AlertSoundsPage from './routes/AlertSoundsPage'
import ErrorsPage from './routes/ErrorsPage'
import ActivityLogPage from './routes/ActivityLogPage'
import ThreadDebugPage from './routes/ThreadDebugPage'
import TestingPage from './routes/TestingPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<ChatPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/vault" element={<VaultPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:name" element={<ProjectPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/reminders" element={<RemindersPage />} />
          <Route path="/admin/checkins" element={<CheckinsAdminPage />} />
          <Route path="/admin/alert-sounds" element={<AlertSoundsPage />} />
          <Route path="/admin/errors" element={<ErrorsPage />} />
          <Route path="/activity-log" element={<ActivityLogPage />} />
          <Route path="/admin/thread-debug" element={<ThreadDebugPage />} />
          <Route path="/admin/testing" element={<TestingPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
