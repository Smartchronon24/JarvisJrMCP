/* filepath: c:\Navaneth\Study\JarvisMCP\jarvis-phase-2.1-frontend\src\js\chat.js */
/**
 * Chat Interface & Messaging Logic
 * Handles user input, message display, streaming responses
 */

class ChatInterface {
    constructor() {
        this.messageInput = document.getElementById('message-input');
        this.sendBtn = document.getElementById('send-btn');
        this.conversationContainer = document.getElementById('conversation');
        this.composerContainer = document.querySelector('.composer-container');

        this.setupEventListeners();
        this.renderConversation();

        appState.on('message_added', () => this.renderConversation());
        appState.on('streaming_changed', () => this.onStreamingStateChanged());
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

    sendMessage() {
        const content = this.messageInput.value.trim();
        if (!content) {
            return;
        }

        // Add user message
        appState.addMessage('user', content);
        this.messageInput.value = '';
        this.messageInput.style.height = 'auto';

        // Simulate assistant response with streaming
        this.simulateAssistantResponse(content);
    }

    simulateAssistantResponse(userMessage) {
        appState.setStreaming(true);

        // Add empty assistant message
        const assistantMsg = appState.addMessage('assistant', '');

        // Simulate streaming with mock data
        const mockResponses = {
            research: 'I\'ll search for the latest information on that topic.\n\n[Initiating Tavily search...]\n\nSearch completed. I found 5 relevant sources with recent updates. Would you like me to dive deeper into any specific aspect?',
            compare: 'Let me gather the specifications for both graphics cards...\n\n[Running comparison analysis...]\n\nBased on current benchmarks:\n- RTX 5090: ~600W TDP, 32GB VRAM\n- RTX 4090: ~450W TDP, 24GB VRAM\n\nThe RTX 5090 offers approximately 35% better performance.',
            files: 'Scanning your filesystem for recent changes...\n\n[Filesystem search in progress...]\n\nFound 12 files modified in the last 7 days:\n- Documents/report.pdf (2 days ago)\n- Projects/code.js (1 day ago)\n- Notes/ideas.txt (today)\n\nWould you like more details?',
            message: 'I\'ll compose and send that message for you.\n\n[WhatsApp integration ready...]\n\nMessage queued for sending: "Hi Alex! How are you doing?"\n\nReady to send. Please confirm.',
            default: 'I\'ve processed your request and initiated the necessary tools to help you. Let me compile the results...\n\n[Processing with multiple MCP servers...]\n\nHere\'s what I found...',
        };

        const response = Object.keys(mockResponses).find((key) =>
            userMessage.toLowerCase().includes(key)
        );
        const mockResponse = mockResponses[response] || mockResponses.default;

        // Stream character by character
        let index = 0;
        const streamInterval = setInterval(() => {
            if (index < mockResponse.length) {
                assistantMsg.content += mockResponse[index];
                this.renderConversation();
                index++;
            } else {
                clearInterval(streamInterval);
                appState.setStreaming(false);
            }
        }, 20);
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
        // Basic markdown-like formatting
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
        if (appState.isStreaming_()) {
            this.sendBtn.disabled = true;
            this.messageInput.disabled = true;
        } else {
            this.sendBtn.disabled = false;
            this.messageInput.disabled = false;
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