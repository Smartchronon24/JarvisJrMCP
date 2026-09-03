(function (global) {
    class ClaudexStudioApp {
        constructor(options = {}) {
            this.document = options.document || globalThis.document;
            this.client = options.client || new globalThis.ClaudexWebSocketClient({
                wsUrl: options.wsUrl || 'ws://127.0.0.1:8765',
                onConnected: () => this.updateConnectedState(true),
                onDisconnected: () => this.updateConnectedState(false),
                onEvent: (event) => this.handleEvent(event),
                onError: (message) => this.handleError(message),
                onSessionStarted: (runId) => this.handleSessionStarted(runId),
                onAcknowledged: (runId) => {
                    if (runId !== this.currentRunId || !this._approvalPending) return;
                    this._approvalPending = false;
                    this.state.waitingForApproval = false;
                    this._setStatusBox('running', 'Approval accepted');
                    this._setControlVisibility(false, false, true, false);
                },
            });
            this.state = {
                connected: false,
                runId: null,
                framework: null,
                model: null,
                provider: null,
                executionState: 'idle',
                metrics: {},
                waitingForInput: false,
                waitingForApproval: false,
            };

            this.term = options.term || null;
            this.currentRunId = null;
            this._approvalPending = false;
            this._inputPending = false;
            this._startRequestPending = false;
            this._startTimeMs = null;
            this._endTimeMs = null;

            this.ui = this._bindUi();
            this._initTerminal();
            this._initBehavior();
            this.connect();
            this.updateConnectedState(false);
            this.resetStatus();
        }

        _bindUi() {
            const doc = this.document;
            return {
                statusText: doc.getElementById('statusText'),
                connectionStatus: doc.getElementById('connectionStatus'),
                dashState: doc.getElementById('dashState'),
                dashFramework: doc.getElementById('dashFramework'),
                dashModel: doc.getElementById('dashModel'),
                dashProvider: doc.getElementById('dashProvider'),
                dashRunId: doc.getElementById('dashRunId'),
                dashPid: doc.getElementById('dashPid'),
                dashElapsed: doc.getElementById('dashElapsed'),
                metricOutput: doc.getElementById('metricOutput'),
                metricErrors: doc.getElementById('metricErrors'),
                metricExit: doc.getElementById('metricExit'),
                statusBox: doc.getElementById('statusBox'),
                frameworkInput: doc.getElementById('frameworkInput'),
                executableInput: doc.getElementById('executableInput'),
                modelInput: doc.getElementById('modelInput'),
                providerInput: doc.getElementById('providerInput'),
                workingDirectoryInput: doc.getElementById('workingDirectoryInput'),
                promptInput: doc.getElementById('promptInput'),
                startSessionBtn: doc.getElementById('startSessionBtn'),
                clearTerminalBtn: doc.getElementById('clearTerminalBtn'),
                subscribeInput: doc.getElementById('subscribeInput'),
                subscribeBtn: doc.getElementById('subscribeBtn'),
                disconnectBtn: doc.getElementById('disconnectBtn'),
                inputSection: doc.getElementById('inputSection'),
                approvalSection: doc.getElementById('approvalSection'),
                cancelSection: doc.getElementById('cancelSection'),
                errorSection: doc.getElementById('errorSection'),
                errorMessage: doc.getElementById('errorMessage'),
                userInput: doc.getElementById('userInput'),
                sendInputBtn: doc.getElementById('sendInputBtn'),
                approveBtn: doc.getElementById('approveBtn'),
                rejectBtn: doc.getElementById('rejectBtn'),
                cancelBtn: doc.getElementById('cancelBtn'),
                terminalEl: doc.getElementById('terminal'),
                terminalFallback: doc.getElementById('terminalFallback'),
            };
        }

        _fitTerminal() {
            if (!this.term || !this.ui.terminalEl) return;
            const rect = this.ui.terminalEl.getBoundingClientRect();
            if (!rect || rect.width <= 0 || rect.height <= 0) return;
            const cols = Math.max(40, Math.floor(rect.width / 9));
            const rows = Math.max(16, Math.floor(rect.height / 18));
            this.term.resize(cols, rows);
        }

        _initTerminal() {
            if (this.term) {
                return;
            }
            if (!this.ui.terminalEl || typeof globalThis.Terminal === 'undefined') {
                return;
            }
            const term = new globalThis.Terminal({
                cursorBlink: true,
                convertEol: true,
                scrollback: 10000,
                theme: {
                    background: '#0f172a',
                    foreground: '#f8fafc',
                },
            });
            term.open(this.ui.terminalEl);
            term.onData((data) => {
                if (!this.currentRunId || !this.state.waitingForInput) {
                    return;
                }
                this._sendTerminalInput(data);
            });
            this._fitTerminal();
            this.term = term;

            if (typeof globalThis.window !== 'undefined' && typeof globalThis.window.addEventListener === 'function') {
                globalThis.window.addEventListener('resize', () => this._fitTerminal());
            }
        }

        _writeTerminal(text) {
            if (!text) return;
            if (this.term && typeof this.term.write === 'function') {
                const terminalText = text.endsWith('\n') || text.endsWith('\r')
                    ? text
                    : `${text}\r\n`;
                this.term.write(terminalText);
                return;
            }
            if (this.ui.terminalFallback) {
                const existing = this.ui.terminalFallback.textContent || '';
                const suffix = text.endsWith('\n') || text.endsWith('\r') ? text : `${text}\n`;
                this.ui.terminalFallback.textContent = existing + suffix;
            }
        }

        _sendTerminalInput(data) {
            if (!data || !this.currentRunId) {
                return;
            }
            const text = String(data);
            this.client.sendInput(this.currentRunId, text);
        }

        _setStartControlsDisabled(disabled) {
            const ui = this.ui;
            if (ui.startSessionBtn) {
                ui.startSessionBtn.disabled = disabled;
            }
            const fields = [
                ui.frameworkInput,
                ui.executableInput,
                ui.modelInput,
                ui.providerInput,
                ui.workingDirectoryInput,
                ui.promptInput,
            ];
            for (const field of fields) {
                if (field) {
                    field.disabled = disabled;
                }
            }
        }

        _hasActiveSession() {
            if (!this.currentRunId) {
                return false;
            }
            return !['completed', 'failed', 'cancelled', 'idle'].includes(this.state.executionState || 'idle');
        }

        _updateElapsedDisplay() {
            const ui = this.ui;
            if (!ui.dashElapsed) return;
            const state = this.state.executionState || 'idle';
            if (this._startTimeMs && !['completed', 'failed', 'cancelled', 'idle'].includes(state)) {
                const elapsedMs = Math.max(0, Date.now() - this._startTimeMs);
                ui.dashElapsed.textContent = `${(elapsedMs / 1000).toFixed(1)}s`;
                return;
            }
            if (this._startTimeMs && this._endTimeMs && this._endTimeMs >= this._startTimeMs) {
                const elapsedMs = this._endTimeMs - this._startTimeMs;
                ui.dashElapsed.textContent = `${(elapsedMs / 1000).toFixed(1)}s`;
                return;
            }
            ui.dashElapsed.textContent = '—';
        }

        _initBehavior() {
            const ui = this.ui;
            if (ui.clearTerminalBtn) {
                ui.clearTerminalBtn.addEventListener('click', () => {
                    if (this.term && typeof this.term.clear === 'function') {
                        this.term.clear();
                        this.term.focus && this.term.focus();
                    }
                    if (this.ui.terminalFallback) {
                        this.ui.terminalFallback.textContent = '';
                    }
                });
            }

            if (ui.startSessionBtn) {
                ui.startSessionBtn.addEventListener('click', () => {
                    if (!this.state.connected) {
                        this.handleError('Connect to the runtime server before starting a session');
                        return;
                    }
                    if (this._startRequestPending || this._hasActiveSession()) {
                        this.handleError('A runtime session is already active. Finish or cancel it before starting another.');
                        return;
                    }

                    const framework = (ui.frameworkInput && ui.frameworkInput.value) || 'claude';
                    const executablePath = (ui.executableInput && ui.executableInput.value || '').trim() || null;
                    const prompt = (ui.promptInput && ui.promptInput.value || '').trim();
                    const model = (ui.modelInput && ui.modelInput.value || '').trim() || null;
                    const provider = (ui.providerInput && ui.providerInput.value || '').trim() || null;
                    const workingDirectory = (ui.workingDirectoryInput && ui.workingDirectoryInput.value || '').trim() || null;

                    if (!prompt) {
                        this.handleError('Enter a prompt before starting a runtime session');
                        return;
                    }

                    // B16 diagnostic: prompt integrity at UI capture
                    const promptHash = this._hashString(prompt).substring(0, 16);
                    console.log(`[B16-BOUNDARY-UIINPUT] prompt_hash=${promptHash}, prompt_len=${prompt.length}, prompt="${prompt}"`);

                    this._startRequestPending = true;
                    this.state.executionState = 'starting';
                    this._updateValue(ui.dashState, 'starting');
                    this._setStatusBox('running', 'Starting...');
                    this._setStartControlsDisabled(true);

                    if (ui.dashFramework && framework) {
                        this._updateValue(ui.dashFramework, framework);
                    }
                    if (ui.dashModel && model) {
                        this._updateValue(ui.dashModel, model);
                    }
                    if (ui.dashProvider && provider) {
                        this._updateValue(ui.dashProvider, provider);
                    }

                    this.client.startSession({
                        framework,
                        executable_path: executablePath,
                        prompt,
                        model,
                        provider,
                        working_directory: workingDirectory,
                    });
                });
            }


            if (ui.subscribeBtn) {
                ui.subscribeBtn.addEventListener('click', () => {
                    const runId = (ui.subscribeInput.value || '').trim();
                    if (!runId) {
                        this.handleError('Enter a run ID to subscribe');
                        return;
                    }
                    this.currentRunId = runId;
                    this.client.subscribe(runId);
                });
            }

            if (ui.disconnectBtn) {
                ui.disconnectBtn.addEventListener('click', () => {
                    this.client.disconnect();
                });
            }

            if (ui.sendInputBtn) {
                ui.sendInputBtn.addEventListener('click', () => {
                    const typed = ui.userInput.value || '';
                    if (!this.currentRunId) return;
                    if (!typed) return;
                    const payload = typed.endsWith('\n') || typed.endsWith('\r') ? typed : `${typed}\n`;
                    this.client.sendInput(this.currentRunId, payload);
                    ui.userInput.value = '';
                });
            }

            ui.approveBtn.addEventListener('click', () => {
                if (!this.currentRunId || this._approvalPending) return;
                this._approvalPending = true;
                ui.approveBtn.disabled = true;
                ui.rejectBtn.disabled = true;
                this.client.sendApproval(this.currentRunId, true);
            });

            ui.rejectBtn.addEventListener('click', () => {
                if (!this.currentRunId || this._approvalPending) return;
                this._approvalPending = true;
                ui.approveBtn.disabled = true;
                ui.rejectBtn.disabled = true;
                this.client.sendApproval(this.currentRunId, false);
            });

            ui.cancelBtn.addEventListener('click', () => {
                if (!this.currentRunId) return;
                this.client.cancel(this.currentRunId);
            });
        }

        updateConnectedState(connected) {
            this.state.connected = connected;
            const ui = this.ui;
            if (!ui.statusText || !ui.connectionStatus) return;

            if (connected) {
                ui.statusText.textContent = 'Connected';
                ui.connectionStatus.classList.add('connected');
                ui.connectionStatus.classList.remove('disconnected');
                if (!this._hasActiveSession()) {
                    this._setStatusBox('idle', 'Connected / idle');
                }
            } else {
                ui.statusText.textContent = 'Disconnected';
                ui.connectionStatus.classList.remove('connected');
                ui.connectionStatus.classList.add('disconnected');
                this._setStatusBox('idle', 'Disconnected');
            }
        }

        resetStatus() {
            const ui = this.ui;
            if (!ui.statusBox) return;
            this._approvalPending = false;
            this._inputPending = false;
            this._startRequestPending = false;
            this._startTimeMs = null;
            this._endTimeMs = null;
            this.state.executionState = 'idle';
            this._setStartControlsDisabled(false);
            this._setStatusBox('idle', this.state.connected ? 'Connected / idle' : 'No execution running');
            this._updateValue(ui.dashState, 'idle');
            this._updateValue(ui.dashFramework, '—');
            this._updateValue(ui.dashModel, '—');
            this._updateValue(ui.dashProvider, '—');
            this._updateValue(ui.dashRunId, '—');
            this._updateValue(ui.dashPid, '—');
            this._updateValue(ui.dashElapsed, '—');
            ui.metricOutput.textContent = '0';
            ui.metricErrors.textContent = '0';
            ui.metricExit.textContent = '—';
            this._setControlVisibility(false, false, false, false);
            this._hideError();
        }

        _toggleSection(el, visible) {
            if (!el) return;
            el.style.display = visible ? 'block' : 'none';
        }

        _setControlVisibility(waitingForInput, waitingForApproval, showCancel, showError) {
            const ui = this.ui;
            this._toggleSection(ui.inputSection, waitingForInput);
            this._toggleSection(ui.approvalSection, waitingForApproval);
            this._toggleSection(ui.cancelSection, showCancel);
            this._toggleSection(ui.errorSection, showError);

            if (ui.userInput) {
                ui.userInput.disabled = !waitingForInput;
            }
            if (ui.sendInputBtn) {
                ui.sendInputBtn.disabled = !waitingForInput;
            }
            if (ui.approveBtn) {
                ui.approveBtn.disabled = !waitingForApproval || this._approvalPending;
            }
            if (ui.rejectBtn) {
                ui.rejectBtn.disabled = !waitingForApproval || this._approvalPending;
            }
            if (ui.cancelBtn) {
                ui.cancelBtn.disabled = !showCancel;
            }
        }

        _setStatusBox(state, text) {
            const ui = this.ui;
            if (!ui.statusBox) return;
            ui.statusBox.className = 'status-' + state;
            ui.statusBox.textContent = text;
        }

        _updateValue(element, value) {
            if (!element) return;
            element.textContent = value;
        }

        _hideError() {
            const ui = this.ui;
            if (!ui.errorSection) return;
            ui.errorSection.style.display = 'none';
        }

        handleError(message) {
            const ui = this.ui;
            if (!ui.errorSection || !ui.errorMessage) return;
            ui.errorMessage.textContent = String(message || 'Unknown runtime error');
            ui.errorSection.style.display = 'block';
        }

        handleSessionStarted(runId) {
            if (!runId) return;
            this._startRequestPending = false;
            this.currentRunId = runId;
            this.state.runId = runId;
            this.state.executionState = 'starting';
            if (this.ui.subscribeInput) {
                this.ui.subscribeInput.value = runId;
            }
            this._updateValue(this.ui.dashRunId, runId);
            this._updateValue(this.ui.dashState, 'starting');
            this._setStatusBox('running', 'Session started');
            this._setStartControlsDisabled(false);
            if (this.term && typeof this.term.focus === 'function') {
                this.term.focus();
            }
        }

        _setRuntimeInfoFromEvent(event) {
            if (!event) return;
            if (event.framework) this.state.framework = event.framework;
            if (event.model) this.state.model = event.model;
            if (event.provider) this.state.provider = event.provider;
            if (event.run_id) {
                this.state.runId = event.run_id;
                this.currentRunId = event.run_id;
                this.ui.dashRunId.textContent = event.run_id;
            }
        }

        handleEvent(event) {
            if (!event || typeof event !== 'object') {
                return;
            }

            const eventType = event.event_type;
            const ui = this.ui;

            if (!eventType) {
                return;
            }

            switch (eventType) {
                case 'process_started':
                    this._setRuntimeInfoFromEvent(event);
                    if (event.data && event.data.pid) {
                        this._updateValue(ui.dashPid, String(event.data.pid));
                        this._writeTerminal(`[PROCESS] PID ${event.data.pid}`);
                    }
                    this._startTimeMs = event.timestamp_ms || this._startTimeMs || Date.now();
                    this.state.executionState = 'starting';
                    this._updateValue(ui.dashState, this.state.executionState);
                    this._updateElapsedDisplay();
                    this._setStatusBox('running', 'Runtime starting');
                    this._setControlVisibility(false, false, true, false);
                    if (this.term && typeof this.term.focus === 'function') {
                        this.term.focus();
                    }
                    break;

                case 'state_changed':
                    this.state.executionState = event.state || this.state.executionState;
                    if (event.state === 'running' && !this._startTimeMs && event.timestamp_ms) {
                        this._startTimeMs = event.timestamp_ms;
                    }
                    this._updateValue(ui.dashState, this.state.executionState);
                    this._setStatusBox(this.state.executionState === 'running' ? 'running' : this.state.executionState === 'completed' ? 'completed' : this.state.executionState === 'failed' ? 'failed' : this.state.executionState === 'waiting_for_input' || this.state.executionState === 'waiting_for_approval' ? 'waiting' : this.state.executionState === 'cancelled' ? 'failed' : 'idle', 'State: ' + this.state.executionState);

                    if (event.framework) this.state.framework = event.framework;
                    if (event.model) this.state.model = event.model;
                    if (event.provider) this.state.provider = event.provider;

                    if (this.state.framework) this._updateValue(ui.dashFramework, this.state.framework);
                    if (this.state.model) this._updateValue(ui.dashModel, this.state.model);
                    if (this.state.provider) this._updateValue(ui.dashProvider, this.state.provider);
                    if (event.run_id) {
                        this.state.runId = event.run_id;
                        this.currentRunId = event.run_id;
                        this._updateValue(ui.dashRunId, event.run_id);
                    }

                    const isWaitingForInput = this.state.executionState === 'waiting_for_input';
                    const isWaitingForApproval = this.state.executionState === 'waiting_for_approval';
                    this.state.waitingForInput = isWaitingForInput;
                    this.state.waitingForApproval = isWaitingForApproval;
                    this._setControlVisibility(isWaitingForInput, isWaitingForApproval, !['completed', 'failed', 'cancelled'].includes(this.state.executionState), false);
                    this._updateElapsedDisplay();
                    break;

                case 'output': {
                    const stream = (event.data && event.data.stream) || 'stdout';
                    const text = (event.data && event.data.text) ? event.data.text : '';
                    this._writeTerminal(stream === 'stderr' ? `[STDERR] ${text}` : text);
                    if (stream === 'stderr') {
                        const errorCount = Number(ui.metricErrors.textContent || '0');
                        ui.metricErrors.textContent = String(errorCount + 1);
                    } else {
                        const lines = Number(ui.metricOutput.textContent || '0');
                        ui.metricOutput.textContent = String(lines + 1);
                    }
                    this._updateElapsedDisplay();
                    break;
                }

                case 'input_required':
                    this.state.waitingForInput = true;
                    this.state.executionState = 'waiting_for_input';
                    this._inputPending = true;
                    this._updateValue(ui.dashState, this.state.executionState);
                    this._setStatusBox('waiting', 'Input required');
                    this._setControlVisibility(true, false, true, false);
                    this._updateElapsedDisplay();
                    break;

                case 'approval_required':
                    this.state.waitingForApproval = true;
                    this.state.executionState = 'waiting_for_approval';
                    this._approvalPending = false;
                    this._updateValue(ui.dashState, this.state.executionState);
                    this._setStatusBox('waiting', 'Approval required');
                    this._setControlVisibility(false, true, true, false);
                    this._updateElapsedDisplay();
                    break;

                case 'process_completed':
                    this.state.executionState = 'completed';
                    this._approvalPending = false;
                    this._inputPending = false;
                    this._endTimeMs = event.timestamp_ms || Date.now();
                    this._updateValue(ui.dashState, 'completed');
                    this._setStatusBox('completed', 'Execution completed');
                    this._writeTerminal(`[RUNTIME] Process exited: ${event.data && event.data.exit_code !== undefined ? event.data.exit_code : 0}`);
                    this._writeTerminal('[CLEANUP] Process completed');
                    this._setControlVisibility(false, false, false, false);
                    this._setStartControlsDisabled(false);
                    if (event.data && event.data.exit_code !== undefined) {
                        ui.metricExit.textContent = String(event.data.exit_code);
                    }
                    this._updateElapsedDisplay();
                    break;

                case 'process_failed':
                    this.state.executionState = 'failed';
                    this._approvalPending = false;
                    this._inputPending = false;
                    this._endTimeMs = event.timestamp_ms || Date.now();
                    this._updateValue(ui.dashState, 'failed');
                    this._setStatusBox('failed', 'Execution failed');
                    this._writeTerminal(`[RUNTIME] Process failed: ${event.data && event.data.reason ? event.data.reason : 'unknown error'}`);
                    this._setControlVisibility(false, false, true, false);
                    this._setStartControlsDisabled(false);
                    if (event.data && event.data.exit_code !== undefined) {
                        ui.metricExit.textContent = String(event.data.exit_code);
                    }
                    if (event.data && event.data.reason) {
                        this.handleError(event.data.reason);
                        this._setControlVisibility(false, false, false, true);
                    }
                    this._updateElapsedDisplay();
                    break;

                case 'process_cancelled':
                    this.state.executionState = 'cancelled';
                    this._approvalPending = false;
                    this._inputPending = false;
                    this._endTimeMs = event.timestamp_ms || Date.now();
                    this._updateValue(ui.dashState, 'cancelled');
                    this._setStatusBox('failed', 'Execution cancelled');
                    this._writeTerminal('[CLEANUP] Process terminated');
                    this._setControlVisibility(false, false, false, false);
                    this._setStartControlsDisabled(false);
                    this._updateElapsedDisplay();
                    break;

                case 'error':
                    this.state.executionState = 'failed';
                    this.handleError((event.data && event.data.message) || 'Runtime error');
                    this._writeTerminal(`[RUNTIME] ${ (event.data && event.data.message) || 'Runtime error' }`);
                    this._setStatusBox('failed', 'Runtime error');
                    this._setControlVisibility(false, false, false, true);
                    this._setStartControlsDisabled(false);
                    break;

                default:
                    return;
            }

            if (event.run_id) {
                this.state.runId = event.run_id;
                this.currentRunId = event.run_id;
                this._updateValue(ui.dashRunId, event.run_id);
            }

            if (event.framework) {
                this.state.framework = event.framework;
                this._updateValue(ui.dashFramework, event.framework);
            }
            if (event.model) {
                this.state.model = event.model;
                this._updateValue(ui.dashModel, event.model);
            }
            if (event.provider) {
                this.state.provider = event.provider;
                this._updateValue(ui.dashProvider, event.provider);
            }

            if (event.timestamp_ms) {
                const elapsed = Math.max(0, Date.now() - event.timestamp_ms);
                this._updateValue(ui.dashElapsed, (elapsed / 1000).toFixed(1) + 's');
            }
        }

        connect() {
            this.client.connect();
        }
        
        /**
         * Simple string hash for diagnostics (not cryptographic)
         */
        _hashString(str) {
            let hash = 0;
            for (let i = 0; i < str.length; i++) {
                const char = str.charCodeAt(i);
                hash = ((hash << 5) - hash) + char;
                hash |= 0; // Convert to 32bit integer
            }
            return Math.abs(hash).toString(16).padStart(16, '0');
        }
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            ClaudexStudioApp,
        };
    }
    globalThis.ClaudexStudioApp = ClaudexStudioApp;

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                new ClaudexStudioApp();
            });
        } else {
            new ClaudexStudioApp();
        }
    }
})(typeof window !== 'undefined' ? window : globalThis);
