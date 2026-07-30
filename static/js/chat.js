// static/js/chat.js
//
// A minimal, reusable chat widget: renders a scrolling message list and
// an input row, and handles the send -> loading -> reply cycle against
// /text. This is deliberately small rather than a general framework —
// it only needs to do a few things. If a page's needs grow past this,
// that's the signal to reach for something heavier, not before.
//
// Single-conversation usage (onboarding.html, profile.html):
//   const chat = new ChatWidget(document.getElementById('chat-root'), {
//     threadId: 'onboarding',   // fixed thread -> continuable across visits
//     mode: 'onboarding',       // 'onboarding' | 'profile_chat' | null
//     greeting: "Let's get to know you a bit. What do you do for work?",
//   });
//
// Multi-conversation usage (index.html's sidebar):
//   const chat = new ChatWidget(document.getElementById('chat-root'), {
//     onReply: () => refreshSidebar(),   // e.g. reorder by recency
//   });
//   chat.setThread(threadId, historyMessages);  // switch/load on click

import { sendText } from './api.js';
import { attachVoiceButton } from './voiceInput.js';

export class ChatWidget {
  constructor(rootEl, { threadId = null, mode = null, oneShot = false, greeting = null, onReply = null } = {}) {
    this.threadId = threadId;
    this.mode = mode;
    this.oneShot = oneShot;
    this.onReply = onReply;

    rootEl.innerHTML = `
      <div class="chat-log"></div>
      <form class="chat-input-row">
        <input type="text" class="chat-input" placeholder="Type a message..." autocomplete="off" />
        <button type="button" class="mic-btn" aria-label="Dictate message" title="Dictate message">🎙️</button>
        <button type="submit">Send</button>
      </form>
    `;

    this.logEl = rootEl.querySelector('.chat-log');
    this.formEl = rootEl.querySelector('.chat-input-row');
    this.inputEl = rootEl.querySelector('.chat-input');
    this.micBtn = rootEl.querySelector('.mic-btn');

    attachVoiceButton(this.micBtn, {
      onTranscript: (text) => this._sendDictated(text),
      onError: (err) => this._handleVoiceError(err),
    });

    this.formEl.addEventListener('submit', (event) => {
      event.preventDefault();
      this._handleSend();
    });

    if (greeting) {
      this._appendMessage('assistant', greeting);
    }

    this.inputEl.focus();
  }

  clear() {
    this.logEl.innerHTML = '';
  }

  /** Populate the log from a list of {role, content} messages, replacing
   * whatever's currently shown. Doesn't touch this.threadId. */
  loadHistory(messages) {
    this.clear();
    for (const m of messages) {
      this._appendMessage(m.role === 'user' ? 'user' : 'assistant', m.content);
    }
  }

  /** Switch this widget to a different thread — used by the sidebar when
   * a different conversation is clicked, or a new one is started. */
  setThread(threadId, messages = []) {
    this.threadId = threadId;
    if (messages.length > 0) {
      this.loadHistory(messages);
    } else {
      this.clear();
    }
    this.inputEl.disabled = false;
    this.inputEl.focus();
  }

  _appendMessage(role, text) {
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble chat-bubble-${role}`;
    bubble.textContent = text;
    this.logEl.appendChild(bubble);
    this.logEl.scrollTop = this.logEl.scrollHeight;
    return bubble;
  }

  _appendLoading() {
    const bubble = this._appendMessage('assistant', '...');
    bubble.classList.add('chat-bubble-loading');
    return bubble;
  }

  async _handleSend() {
    const text = this.inputEl.value.trim();
    if (!text) return;

    this.inputEl.value = '';
    this.inputEl.disabled = true;
    this.micBtn.disabled = true;
    this._appendMessage('user', text);
    const loadingBubble = this._appendLoading();

    try {
      const data = await sendText(text, {
        threadId: this.threadId,
        oneShot: this.oneShot,
        mode: this.mode,
      });
      loadingBubble.remove();
      this._appendMessage('assistant', data.reply);

      // A chat started with no fixed threadId mints a real one on its
      // first call — lock onto it so the rest of this conversation
      // stays in the same thread rather than drifting per message.
      if (!this.threadId) {
        this.threadId = data.thread_id;
      }

      if (this.onReply) this.onReply(data);
    } catch (err) {
      console.error('Chat send failed:', err);
      loadingBubble.remove();
      this._appendMessage('assistant', '(Something went wrong sending that — try again.)');
    } finally {
      this.inputEl.disabled = false;
      this.micBtn.disabled = false;
      this.inputEl.focus();
    }
  }

  /** Called with the transcribed text once dictation finishes — feeds it
   * through the exact same send path as a typed message. */
  _sendDictated(text) {
    if (!text.trim()) {
      this._appendMessage('assistant', "(Didn't catch that — try again.)");
      return;
    }
    this.inputEl.value = text;
    this._handleSend();
  }

  _handleVoiceError(err) {
    console.error('Dictation failed:', err);
    this._appendMessage('assistant', '(Could not use the microphone — try typing instead.)');
  }
}
