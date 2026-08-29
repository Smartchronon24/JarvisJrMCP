/* filepath: c:\Navaneth\Study\JarvisMCP\frontend\src\js\chat.js */
/**
 * Chat Interface & Messaging Logic
 * Handles user input, message display, real SSE streaming responses.
 *
 * HARD TASKS (pipeline visibility):
 *  11. Real-time pipeline updates via existing SSE stream — planning_mode passed to backend.
 *  12. Failed/skipped stages correctly rendered with ⚠ / ○ icons.
 *  13. Selected tools reflect actual ToolSnapshot (list(snapshot.tool_names) from backend).
 *  14. Model names obtained dynamically from /api/settings/llm on init.
 *  15. No duplicate backend decision logic in frontend — heuristics live in ollama_agent.py only.
 */

class ChatInterface {
    constructor() {
        this.messageInput = document.getElementById('message-input');
        this.sendBtn = document.getElementById('send-btn');
        this.stopBtn = document.getElementById('stop-btn');
        this.conversationContainer = document.getElementById('conversation');
        this.composerContainer = document.querySelector('.composer-container');

        // Pipeline state: kept in memory, never reconstructed from DOM
        this.currentPipeline = null;

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

        // Hard 14: Fetch live model config from backend on startup
        this._loadModelInfo();
    }

    // -------------------------------------------------------------------------
    // Hard 14: Fetch actual model names from backend (no hardcoded strings)
    // -------------------------------------------------------------------------
    async _loadModelInfo() {
        try {
            const res = await fetch('/api/settings/llm');
            if (!res.ok) return;
            const cfg = await res.json();
            const el = document.getElementById('header-model-info');
            if (!el) return;
            const router = cfg.router?.model || '—';
            const worker = cfg.worker?.model || '—';
            el.textContent = `Router: ${router} · Worker: ${worker}`;
        } catch (e) {
            // Silently fail — server may still be starting
        }
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
            // Hard 14: Refresh model info after request (model may have been active during stream)
            this._loadModelInfo();
        }
    }

    async _streamResponse(userMessage, assistantMsg) {
        // Hard 11: Pass planning_mode from UI selector to backend.
        // Hard 15: NO heuristic here — the backend (ollama_agent.py) decides what to do with it.
        const planningMode = document.getElementById('planning-mode-select')?.value || 'AUTO';

        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: userMessage, planning_mode: planningMode }),
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

            // SSE frames are separated by double newlines
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
            case 'request_start':
                // Hard 11: Create pipeline widget at the start of every real request
                this.currentPipeline = this._createPipelineWidget();
                break;

            case 'pipeline_state':
                // Hard 11/12/13: All stage transitions go through one handler — no branching in JS
                if (this.currentPipeline) this._updatePipelineStage(this.currentPipeline, event);
                break;

            case 'assistant_start':
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
                exec.id = event.id;
                activeToolExecs[event.id] = exec;

                // Show MCP tool execution in pipeline (skip internal router/worker pseudo-calls)
                if (this.currentPipeline && event.server !== 'router' && event.server !== 'worker') {
                    this._updatePipelineStage(this.currentPipeline, {
                        stage: `mcp__${event.id}`,
                        status: 'running',
                        _is_mcp_call: true,
                        _tool_name: event.tool,
                        _server: event.server,
                        _args: event.arguments,
                    });
                }
                break;
            }

            case 'plan_created':
                appState.addWorkerPlan(event.steps);
                break;

            case 'tool_call_result': {
                const exec = activeToolExecs[event.id];
                if (exec) {
                    appState.completeToolExecution(exec.id, event.result);
                    if (this.currentPipeline && event.server !== 'router' && event.server !== 'worker') {
                        this._updatePipelineStage(this.currentPipeline, {
                            stage: `mcp__${event.id}`,
                            status: 'completed',
                            _is_mcp_call: true,
                            _result: event.result,
                        });
                    }
                }
                break;
            }

            case 'tool_call_error': {
                const exec = activeToolExecs[event.id];
                if (exec) {
                    appState.failToolExecution(exec.id, event.error);
                    if (this.currentPipeline && event.server !== 'router' && event.server !== 'worker') {
                        this._updatePipelineStage(this.currentPipeline, {
                            stage: `mcp__${event.id}`,
                            status: 'failed',
                            _is_mcp_call: true,
                            _error: event.error,
                        });
                    }
                    // Hard 12: If router explicitly failed, mark remaining stages skipped
                    if (event.server === 'router') {
                        this._markRemainingSkipped(this.currentPipeline, ['tool_search', 'tool_selection', 'worker']);
                    }
                }
                break;
            }

            case 'request_error':
                assistantMsg.content = assistantMsg.content
                    ? assistantMsg.content + `\n\n⚠️ ${event.error}`
                    : `⚠️ Error: ${event.error}`;
                this.renderConversation();
                // Hard 12: On any request_error, ensure pipeline shows the failure state
                if (this.currentPipeline) {
                    this._markPipelineErrored(this.currentPipeline, event.error);
                }
                break;

            case 'request_complete':
                this.renderConversation();
                // Hard 11: Pin the pipeline permanently after completion — don't auto-dismiss
                this.currentPipeline = null;
                break;
        }
    }

    // =========================================================================
    // Pipeline Widget — created once per request, mutated in-place via stage map
    // Hard 11: All updates go directly to the live DOM node via stored refs.
    //          renderConversation() re-inserts the node from memory, not innerHTML.
    // =========================================================================

    _createPipelineWidget() {
        const id = 'pipeline-' + Date.now();
        const wrapper = document.createElement('div');
        wrapper.className = 'message pipeline-message';
        wrapper.id = id;
        wrapper.innerHTML = `
            <div class="message-avatar pipeline-avatar">⚙</div>
            <div class="message-content pipeline-content">
                <div class="pipeline-container">
                    <div class="pipeline-header">
                        <span>Execution Pipeline</span>
                        <span class="pipeline-mode-badge" id="${id}-mode"></span>
                    </div>
                    <div class="pipeline-stages" id="${id}-stages"></div>
                </div>
            </div>
        `;

        this.conversationContainer.appendChild(wrapper);
        this._scrollToBottom();

        // Set planning mode badge
        const modeEl = wrapper.querySelector(`#${id}-mode`);
        const mode = document.getElementById('planning-mode-select')?.value || 'AUTO';
        if (modeEl) {
            modeEl.textContent = `Planning: ${mode}`;
            modeEl.dataset.mode = mode;
        }

        return {
            id,
            node: wrapper,
            stagesContainer: wrapper.querySelector(`#${id}-stages`),
            // Hard 13: stages map stores full data, not just DOM references
            stages: {},   // stageName → { node, iconEl, statusEl, detailsEl, data }
        };
    }

    _updatePipelineStage(pipeline, event) {
        if (!pipeline || !pipeline.stagesContainer) return;

        const { stage, status } = event;
        let stageEntry = pipeline.stages[stage];

        if (!stageEntry) {
            // Create stage row
            const stageNode = document.createElement('div');
            stageNode.className = 'pipeline-stage';
            stageNode.id = `${pipeline.id}-stage-${CSS.escape(stage)}`;

            // Determine human-readable label
            const label = this._stageLabel(stage, event);

            stageNode.innerHTML = `
                <div class="stage-icon pending">●</div>
                <div class="stage-content">
                    <div class="stage-title">
                        <span class="stage-label">${label}</span>
                        <span class="stage-status-text"></span>
                    </div>
                    <div class="stage-details"></div>
                </div>
            `;

            // Toggle details on click
            const titleEl = stageNode.querySelector('.stage-title');
            const detailsEl = stageNode.querySelector('.stage-details');
            titleEl.addEventListener('click', () => detailsEl.classList.toggle('expanded'));

            pipeline.stagesContainer.appendChild(stageNode);

            stageEntry = {
                node: stageNode,
                iconEl: stageNode.querySelector('.stage-icon'),
                statusEl: stageNode.querySelector('.stage-status-text'),
                labelEl: stageNode.querySelector('.stage-label'),
                detailsEl,
                // Hard 13: store raw data payload — safe reference even after DOM mutations
                data: {},
            };
            pipeline.stages[stage] = stageEntry;
        }

        // Update icon & status
        const icons = { running: '●', completed: '✓', failed: '⚠', skipped: '○', pending: '●' };
        stageEntry.iconEl.textContent = icons[status] || '●';
        stageEntry.iconEl.className = `stage-icon ${status}`;
        stageEntry.statusEl.textContent = status;

        // Merge new data into stored data
        Object.assign(stageEntry.data, event);

        // Rebuild details HTML from stored data (Hard 13: uses server-provided data only)
        this._renderStageDetails(stage, stageEntry);

        // Hard 14: Update header model info when worker starts
        if (stage === 'worker' && event.model) {
            const el = document.getElementById('header-model-info');
            if (el) {
                // Keep both router and worker models visible
                const current = el.dataset.routerModel || '';
                el.textContent = `Router: ${current} · Worker: ${event.model}`;
                el.dataset.workerModel = event.model;
            }
        }
        if (stage === 'router' && event.model) {
            const el = document.getElementById('header-model-info');
            if (el) {
                el.dataset.routerModel = event.model;
                const worker = el.dataset.workerModel || '—';
                el.textContent = `Router: ${event.model} · Worker: ${worker}`;
            }
        }

        this._scrollToBottom();
    }

    _stageLabel(stage, event) {
        // Hard 15: Only label/display logic here, no decision logic
        if (stage === 'planner') return 'Planner';
        if (stage === 'router') return 'Router';
        if (stage === 'tool_search') return 'Tool Discovery';
        if (stage === 'tool_selection') return 'Tool Selection';
        if (stage === 'worker') return 'Worker';
        if (stage.startsWith('mcp__')) return `MCP: ${event._tool_name || stage.replace('mcp__', '')}`;
        return stage.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    _renderStageDetails(stage, stageEntry) {
        const d = stageEntry.data;
        let html = '';

        // Hard 14: Always display model if provided by backend
        if (d.model) {
            html += `<div class="detail-row"><span class="detail-key">Model</span><span class="detail-val">${this._esc(d.model)}</span></div>`;
        }

        if (stage === 'planner') {
            if (d.mode) {
                html += `<div class="detail-row"><span class="detail-key">Mode</span><span class="detail-val">${this._esc(d.mode)}</span></div>`;
            }
            if (d.result) {
                html += `<div class="detail-row"><span class="detail-key">Goal</span><span class="detail-val">${this._esc(d.result.goal || '')}</span></div>`;
                if (d.result.complexity) {
                    html += `<div class="detail-row"><span class="detail-key">Complexity</span><span class="detail-val">${this._esc(d.result.complexity)}</span></div>`;
                }
                if (d.result.steps?.length) {
                    html += `<div class="detail-section-title">Steps</div>`;
                    html += d.result.steps.map((s, i) => `<div class="detail-step">${i + 1}. ${this._esc(s)}</div>`).join('');
                }
                if (d.result.capabilities?.length) {
                    html += `<div class="detail-row"><span class="detail-key">Capabilities</span><span class="detail-val">${d.result.capabilities.map(c => `<span class="pill">${this._esc(c)}</span>`).join(' ')}</span></div>`;
                }
            }
            if (d.error) html += `<div class="detail-error">⚠ ${this._esc(d.error)}</div>`;
        }

        else if (stage === 'router') {
            if (d.decision) {
                html += `<div class="detail-row"><span class="detail-key">Task</span><span class="detail-val">${this._esc(d.decision.task_type || '—')}</span></div>`;
                html += `<div class="detail-row"><span class="detail-key">Action</span><span class="detail-val">${this._esc(d.decision.action || '—')}</span></div>`;
                if (d.decision.capabilities?.length) {
                    html += `<div class="detail-row"><span class="detail-key">Capabilities</span><span class="detail-val">${d.decision.capabilities.map(c => `<span class="pill">${this._esc(c)}</span>`).join(' ')}</span></div>`;
                }
                if (d.decision.reason) {
                    html += `<div class="detail-row"><span class="detail-key">Reason</span><span class="detail-val">${this._esc(d.decision.reason)}</span></div>`;
                }
            }
            if (d.status === 'failed') {
                html += `<div class="detail-warn">⚠ Fallback single-agent mode activated</div>`;
            }
        }

        else if (stage === 'tool_search') {
            if (d.count !== undefined) {
                html += `<div class="detail-row"><span class="detail-key">Candidates found</span><span class="detail-val">${d.count}</span></div>`;
                if (d.count === 0) {
                    html += `<div class="detail-warn">No semantic matches — using full capability set</div>`;
                }
            }
        }

        else if (stage === 'tool_selection') {
            // Hard 13: tools list comes directly from snapshot.tool_names — no frontend filtering
            if (d.tools?.length) {
                html += `<div class="detail-section-title">Selected (${d.tools.length})</div>`;
                html += d.tools.map(t => `<div class="detail-tool-row">✓ <code>${this._esc(t)}</code></div>`).join('');
            } else if (d.status === 'completed') {
                html += `<div class="detail-warn">⚠ Fallback used — full capability tools passed to Worker</div>`;
            }
        }

        else if (stage === 'worker') {
            if (d.status === 'running') {
                html += `<div class="detail-row"><span class="detail-key">Status</span><span class="detail-val">Running…</span></div>`;
            } else if (d.status === 'completed') {
                html += `<div class="detail-row"><span class="detail-key">Status</span><span class="detail-val">Completed</span></div>`;
            } else if (d.status === 'skipped') {
                html += `<div class="detail-row"><span class="detail-key">Status</span><span class="detail-val">Skipped (direct response)</span></div>`;
            }
        }

        // MCP tool calls
        else if (stage.startsWith('mcp__')) {
            if (d._tool_name) {
                stageEntry.labelEl.textContent = `MCP: ${d._tool_name}`;
            }
            if (d._args && Object.keys(d._args).length > 0) {
                html += `<div class="detail-section-title">Arguments</div>`;
                html += `<pre class="detail-pre">${this._esc(JSON.stringify(d._args, null, 2))}</pre>`;
            }
            if (d._result !== undefined) {
                const resultStr = typeof d._result === 'object'
                    ? JSON.stringify(d._result, null, 2)
                    : String(d._result);
                // Truncate large results
                const truncated = resultStr.length > 800 ? resultStr.slice(0, 800) + '\n… (truncated)' : resultStr;
                html += `<div class="detail-section-title">Result</div>`;
                html += `<pre class="detail-pre">${this._esc(truncated)}</pre>`;
            }
            if (d._error) {
                html += `<div class="detail-error">⚠ ${this._esc(d._error)}</div>`;
            }
        }

        stageEntry.detailsEl.innerHTML = html;
    }

    // Hard 12: Mark all listed stages as skipped (e.g. when Router fails → fallback)
    _markRemainingSkipped(pipeline, stageNames) {
        if (!pipeline) return;
        for (const s of stageNames) {
            if (!pipeline.stages[s]) {
                this._updatePipelineStage(pipeline, { stage: s, status: 'skipped' });
            }
        }
    }

    // Hard 12: On fatal request_error, mark any in-progress stages failed
    _markPipelineErrored(pipeline, errorMsg) {
        if (!pipeline) return;
        for (const [name, entry] of Object.entries(pipeline.stages)) {
            if (entry.iconEl.className.includes('running') || entry.iconEl.className.includes('pending')) {
                entry.iconEl.textContent = '⚠';
                entry.iconEl.className = 'stage-icon failed';
                entry.statusEl.textContent = 'failed';
                if (errorMsg) {
                    const errDiv = document.createElement('div');
                    errDiv.className = 'detail-error';
                    errDiv.textContent = `⚠ ${errorMsg}`;
                    entry.detailsEl.appendChild(errDiv);
                }
            }
        }
    }

    _esc(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    _scrollToBottom() {
        setTimeout(() => {
            this.conversationContainer.scrollTop = this.conversationContainer.scrollHeight;
        }, 0);
    }

    // =========================================================================
    // Conversation rendering
    // Hard 11: Pipeline node is a live DOM element stored in memory —
    //          renderConversation() re-inserts it without losing stage references.
    // =========================================================================

    renderConversation() {
        const messages = appState.getMessages();
        const isEmpty = messages.length === 0;

        // Detach pipeline node before wiping innerHTML (preserve stage references)
        const pipelineNode = this.currentPipeline ? this.currentPipeline.node : null;
        if (pipelineNode && pipelineNode.parentNode) {
            pipelineNode.parentNode.removeChild(pipelineNode);
        }

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

        // Render all messages
        this.conversationContainer.innerHTML = messages
            .map((msg) => this.createMessageElement(msg))
            .join('');

        // Re-insert live pipeline node before the last assistant message
        if (pipelineNode) {
            const assistantEls = this.conversationContainer.querySelectorAll('.message.assistant');
            if (assistantEls.length > 0) {
                const last = assistantEls[assistantEls.length - 1];
                last.parentNode.insertBefore(pipelineNode, last);
            } else {
                this.conversationContainer.appendChild(pipelineNode);
            }
        }

        this._scrollToBottom();
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