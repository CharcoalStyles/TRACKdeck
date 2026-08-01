// static/js/api.js
//
// Thin fetch wrappers shared across every dashboard page. Nothing
// framework-specific here — just native ES module exports, imported
// directly by browsers that support <script type="module">.
//
// Auth rides along automatically: same-origin fetches send the signed
// session cookie set by POST /login (main.py's SessionMiddleware), no
// token needs to be attached client-side. A logged-out browser gets a
// 401 from any of these — see static/js/auth.js's requireSession() for
// the redirect-to-login handling.

/**
 * Send one turn to the agent.
 * @returns {Promise<{reply: string, thread_id: string, keyword: string}>}
 */
export async function sendText(text, { threadId = null, oneShot = false, mode = null } = {}) {
  const response = await fetch('/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      thread_id: threadId,
      one_shot: oneShot,
      mode,
    }),
  });
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/** @returns {Promise<{checkins: Array<{id: string, category: string, prompt_text: string, status: string, scheduled_at: number, fired_at: number|null, resolved_at: number, reply: string|null}>}>} */
export async function getTodaysCheckins() {
  const response = await fetch('/checkins/today');
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

export async function getSettings() {
  const response = await fetch('/settings');
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

export async function updateSettings(update) {
  const response = await fetch('/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  });
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/** @returns {Promise<Array<{thread_id: string, keyword: string, last_activity: number}>>} */
export async function listThreads() {
  const response = await fetch('/threads');
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/** @returns {Promise<{thread_id: string, keyword: string}>} */
export async function createNewThread() {
  const response = await fetch('/threads/new', { method: 'POST' });
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/** @returns {Promise<Array<{role: string, content: string}>>} */
export async function getThreadMessages(threadId) {
  const response = await fetch(`/threads/${encodeURIComponent(threadId)}/messages`);
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  const data = await response.json();
  return data.messages;
}

/**
 * Fire a /debug/* test endpoint (no request body) — shared by every
 * button on the Testing page. See main.py's POST /debug/* routes.
 * @returns {Promise<object>} the endpoint's small status JSON
 */
export async function triggerDebug(path) {
  const response = await fetch(path, { method: 'POST' });
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/**
 * Fetch JSON from a read-only /debug/* endpoint — shared by the Testing
 * page's Device Status and Preview Sync Payload cards.
 * @returns {Promise<object>}
 */
export async function fetchDebug(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/**
 * Upload an audio file to be converted into a 16kHz/16-bit mono PCM WAV
 * alert sound. @param {File} file
 * @returns {Promise<{id: string, display_name: string, duration_seconds: number, size_bytes: number, sha256: string, created_at: number}>}
 */
export async function uploadAlertSound(file) {
  const formData = new FormData();
  formData.append('file', file, file.name);

  const response = await fetch('/alert-sounds', {
    method: 'POST',
    credentials: 'same-origin',
    body: formData,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Server returned ${response.status}`);
  }
  return response.json();
}

/** @returns {Promise<{alert_sounds: Array<{id: string, display_name: string, duration_seconds: number, size_bytes: number, sha256: string, created_at: number}>}>} */
export async function listAlertSounds() {
  const response = await fetch('/alert-sounds');
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

export async function deleteAlertSound(id) {
  const response = await fetch(`/alert-sounds/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/** @returns {Promise<{errors: Array<{id: string, error_type: string, message: string|null, firmware_version: string|null, reset_reason: string|null, wake_reason: string|null, battery_mv: number|null, battery_pct: number|null, rssi_dbm: number|null, free_internal_heap_bytes: number|null, alerted: boolean, created_at: number}>}>} */
export async function listDeviceErrors() {
  const response = await fetch('/device/errors');
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/** @returns {Promise<{entries: Array<{id: string, occurred_at: number, activity_type: string, subject: string, duration: string|null, mood_energy: number|null, reflection: string|null, created_at: number}>}>} */
export async function getActivityLog({ days = 30, activityType = null } = {}) {
  const params = new URLSearchParams({ days: String(days) });
  if (activityType) params.set('activity_type', activityType);
  const response = await fetch(`/activity-log?${params}`);
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

/** @returns {Promise<{mood_by_day: Array<{date: string, avg_mood: number, count: number}>, duration_by_type: Array<{activity_type: string, total_minutes: number, entry_count: number}>}>} */
export async function getActivityLogSummary({ days = 30 } = {}) {
  const response = await fetch(`/activity-log/summary?days=${days}`);
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}
