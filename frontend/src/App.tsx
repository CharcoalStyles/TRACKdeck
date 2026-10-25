import { Route, Routes } from 'react-router-dom'
import RequireAuth from './components/RequireAuth'
import AppShell from './components/layout/AppShell'
import LoginPage from './routes/LoginPage'
import HomePage from './routes/HomePage'
import CapturesPage from './routes/CapturesPage'
import ChatPage from './routes/ChatPage'
import SettingsPage from './routes/SettingsPage'
import RemindersPage from './routes/RemindersPage'
import CheckinsAdminPage from './routes/CheckinsAdminPage'
import AlertSoundsPage from './routes/AlertSoundsPage'
import ErrorsPage from './routes/ErrorsPage'
import ThreadDebugPage from './routes/ThreadDebugPage'
import TestingPage from './routes/TestingPage'
import ReflectionPage from './routes/ReflectionPage'
import DayPlanningPage from './routes/DayPlanningPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/captures" element={<CapturesPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/reminders" element={<RemindersPage />} />
          <Route path="/admin/checkins" element={<CheckinsAdminPage />} />
          <Route path="/admin/alert-sounds" element={<AlertSoundsPage />} />
          <Route path="/admin/errors" element={<ErrorsPage />} />
          <Route path="/admin/thread-debug" element={<ThreadDebugPage />} />
          <Route path="/admin/testing" element={<TestingPage />} />
          <Route path="/reflection" element={<ReflectionPage />} />
          <Route path="/day-planning" element={<DayPlanningPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
