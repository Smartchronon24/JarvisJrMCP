/* filepath: c:\Navaneth\Study\JarvisMCP\jarvis-phase-2.1-frontend\src\js\chat.js */
/**
 * Chat Interface & Messaging Logic
 * Handles user input, message display, real SSE streaming responses
 */

class ChatInterface {
    constructor() {
        this.messageInput = document.getElementById('message-input');
        this.sendBtn = document.getElementById('send-btn');
        this.stopBtn = document.getElementById('stop-btn');
        this.conversationContainer = document.getElementById('conversation');
        this.composerContainer = document.querySelector('.composer-container');

        this.setupEventListeners();
        this.renderConversation();

        appState.on('message_added', () => this.renderConversation());
        appState.on('streaming_changed', () => this.onStreamingStateChanged());

        // Stop button
        this.stopBtn.addEventListener('click', async () => {
            try {
                await fetch('/api/chat/cancel', { method: 'POST' });
            } catch (e) {
                console.warn('Cancel request failed:', e);
            }
        });
    }

    setupEventListeners() {
        this.sendBtn.addEventListener('click', () => this.sendMessage());

        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        this.messageInput.addEventListener('input', () => {
            this.autoResizeTextarea();
        });

        // Suggestion cards
        document.querySelectorAll('.suggestion-card').forEach((card) => {
            card.addEventListener('click', () => {
                const suggestion = card.dataset.suggestion;
                this.insertSuggestion(suggestion);
            });
        });
    }

    autoResizeTextarea() {
        this.messageInput.style.height = 'auto';
        this.messageInput.style.height = Math.min(this.messageInput.scrollHeight, 200) + 'px';
    }

    insertSuggestion(suggestion) {
        const suggestions = {
            research: 'Research the latest AI developments',
            compare: 'Compare RTX 4090 vs RTX 5090 specifications',
            files: 'Show me files modified in the last 7 days',
            message: 'Send a WhatsApp message to Alex',
        };
        this.messageInput.value = suggestions[suggestion] || '';
        this.autoResizeTextarea();
        this.messageInput.focus();
    }

    async sendMessage() {
        const content = this.messageInput.value.trim();
        if (!content || appState.isStreaming) {
            return;
        }

        // Add user message to UI immediately
        appState.addMessage('user', content);
        this.messageInput.value = '';
        this.messageInput.style.height = 'auto';

        appState.setStreaming(true);

        // Add placeholder assistant message for live updates
        const assistantMsg = appState.addMessage('assistant', '');
        this.renderConversation();

        try {
            await this._streamResponse(content, assistantMsg);
        } catch (err) {
            assistantMsg.content = `Connection error: ${err.message}`;
            this.renderConversation();
        } finally {
            appState.setStreaming(false);
        }
    }

    async _streamResponse(userMessage, assistantMsg) {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: userMessage }),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ error: 'Server error' }));
            assistantMsg.content = `Error: ${err.error || 'Unknown server error'}`;
            this.renderConversation();
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        // Track active tool executions by id
        const activeToolExecs = {};

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // SSE frames are separated by double newlines (may include carriage returns on Windows/standard SSE)
            const frames = buffer.split(/\r?\n\r?\n/);
            buffer = frames.pop(); // keep last incomplete frame

            for (const frame of frames) {
                const line = frame.trim();
                if (!line.startsWith('data:')) continue;

                const jsonStr = line.slice(5).trim();
                if (!jsonStr) continue;

                let event;
                try {
                    event = JSON.parse(jsonStr);
                } catch (e) {
                    continue;
                }

                this._handleEvent(event, assistantMsg, activeToolExecs);
            }
        }
    }

    _handleEvent(event, assistantMsg, activeToolExecs) {
        switch (event.type) {
            case 'assistant_start':
                // Ensure placeholder is ready
                if (!assistantMsg.content) {
                    assistantMsg.content = '';
                }
                break;

            case 'assistant_delta':
                assistantMsg.content += (event.content || '');
                this.renderConversation();
                break;

            case 'assistant_complete':
                this.renderConversation();
                break;

            case 'tool_call_start': {
                const exec = appState.addToolExecution(
                    event.server,
                    event.tool,
                    event.arguments || {}
                );
                // Override the auto-generated id with the server-side one for correlation
                exec.id = event.id;
                activeToolExecs[event.id] = exec;
                break;
            }

            case 'plan_created':
                appState.addWorkerPlan(event.steps);
                break;

            case 'tool_call_result': {
                const exec = activeToolExecs[event.id];
                if (exec) {
                    appState.completeToolExecution(exec.id, event.result);
                }
                break;
            }

            case 'tool_call_error': {
                const exec = activeToolExecs[event.id];
                if (exec) {
                    appState.failToolExecution(exec.id, event.error);
                }
                break;
            }

            case 'request_error':
                assistantMsg.content = assistantMsg.content
                    ? assistantMsg.content + `\n\n⚠️ ${event.error}`
                    : `⚠️ Error: ${event.error}`;
                this.renderConversation();
                break;

            case 'request_complete':
                // Ensure final render
                this.renderConversation();
                break;
        }
    }

    renderConversation() {
        const messages = appState.getMessages();
        const isEmpty = messages.length === 0;

        if (isEmpty) {
            this.conversationContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">
                        <svg viewBox="0 0 60 60">
                            <circle cx="30" cy="30" r="28" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"/>
                            <circle cx="30" cy="30" r="18" fill="none" stroke="currentColor" stroke-width="1" opacity="0.2"/>
                            <circle cx="30" cy="30" r="8" fill="currentColor" opacity="0.15"/>
                        </svg>
                    </div>
                    <h2>Welcome to Jarvis</h2>
                    <p>Your personal AI assistant, powered by advanced tools and reasoning.</p>
                    <div class="suggestion-cards">
                        <button class="suggestion-card" data-suggestion="research">
                            <span class="suggestion-icon">🔍</span>
                            <span class="suggestion-text">Research something</span>
                        </button>
                        <button class="suggestion-card" data-suggestion="compare">
                            <span class="suggestion-icon">⚖️</span>
                            <span class="suggestion-text">Compare products</span>
                        </button>
                        <button class="suggestion-card" data-suggestion="files">
                            <span class="suggestion-icon">📁</span>
                            <span class="suggestion-text">Manage my files</span>
                        </button>
                        <button class="suggestion-card" data-suggestion="message">
                            <span class="suggestion-icon">💬</span>
                            <span class="suggestion-text">Send a message</span>
                        </button>
                    </div>
                </div>
            `;
            this.setupSuggestionListeners();
            return;
        }

        this.conversationContainer.innerHTML = messages
            .map((msg) => this.createMessageElement(msg))
            .join('');

        // Scroll to bottom
        setTimeout(() => {
            this.conversationContainer.scrollTop = this.conversationContainer.scrollHeight;
        }, 0);
    }

    createMessageElement(message) {
        const isUser = message.role === 'user';
        const avatar = isUser ? 'You' : 'J';
        const time = this.formatTime(message.timestamp);

        const formattedContent = this.formatContent(message.content);

        return `
            <div class="message ${message.role}">
                <div class="message-avatar">${avatar}</div>
                <div class="message-content">
                    <div class="message-bubble">
                        <div class="message-text">${formattedContent}</div>
                    </div>
                    <div class="message-time">${time}</div>
                </div>
            </div>
        `;
    }

    formatContent(content) {
        let formatted = content
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank">$1</a>')
            .replace(/`(.*?)`/g, '<code>$1</code>')
            .replace(/^- (.*?)$/gm, '<li>$1</li>')
            .replace(/(<li>.*?<\/li>)/s, '<ul>$1</ul>');

        return formatted;
    }

    formatTime(date) {
        if (!date) return 'just now';
        const now = new Date();
        const diff = now - date;
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);

        if (minutes < 1) {
            return 'just now';
        } else if (minutes < 60) {
            return `${minutes}m ago`;
        } else if (hours < 24) {
            return `${hours}h ago`;
        } else {
            return date.toLocaleDateString();
        }
    }

    onStreamingStateChanged() {
        if (appState.isStreaming) {
            this.sendBtn.disabled = true;
            this.sendBtn.style.display = 'none';
            this.stopBtn.style.display = '';
            this.messageInput.disabled = true;
        } else {
            this.sendBtn.disabled = false;
            this.sendBtn.style.display = '';
            this.stopBtn.style.display = 'none';
            this.messageInput.disabled = false;
            this.messageInput.focus();
        }
    }

    setupSuggestionListeners() {
        document.querySelectorAll('.suggestion-card').forEach((card) => {
            card.addEventListener('click', () => {
                const suggestion = card.dataset.suggestion;
                this.insertSuggestion(suggestion);
            });
        });
    }
}

const chatInterface = new ChatInterface();