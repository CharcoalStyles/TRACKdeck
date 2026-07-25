// static/js/api.js
//
// Thin fetch wrappers shared across every dashboard page. Nothing
// framework-specific here — just native ES module exports, imported
// directly by browsers that support <script type="module">.

export const AUTH_TOKEN = 'YOUR_SUPER_SECRET_SECURE_TOKEN';

/**
 * Send one turn to the agent.
 * @returns {Promise<{reply: string, thread_id: string, keyword: string}>}
 */
export async function sendText(text, { threadId = null, oneShot = false, mode = null } = {}) {
  const response = await fetch('/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'auth': AUTH_TOKEN },
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

export async function getSettings() {
  const response = await fetch('/settings');
  if (!response.ok) throw new Error(`Server returned ${response.status}`);
  return response.json();
}

export async function updateSettings(update) {
  const response = await fetch('/settings', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'auth': AUTH_TOKEN,
    },
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
  const response = await fetch('/threads/new', {
    method: 'POST',
    headers: { 'auth': AUTH_TOKEN },
  });
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
