/* filepath: c:\Navaneth\Study\JarvisMCP\jarvis-phase-2.1-frontend\src\js\state.js */
/**
 * Application State Management
 * Centralized state for messages, tool executions, settings
 */

class AppState {
    constructor() {
        this.messages = [];
        this.toolExecutions = [];
        this.workerPlans = [];
        this.mcpServers = [...mockMcpServers];
        this.settings = JSON.parse(JSON.stringify(mockSettings));
        this.currentPage = 'home';
        this.isStreaming = false;
        this.listeners = [];
        this.loadActivity();
    }

    // Messages
    addMessage(role, content) {
        const message = {
            id: this.messages.length + 1,
            role,
            content,
            timestamp: new Date(),
        };
        this.messages.push(message);
        this.notify('message_added', message);
        return message;
    }

    getMessages() {
        return this.messages;
    }

    // Tool Executions
    addToolExecution(mcpServer, tool, arguments_) {
        const execution = {
            id: `exec-${Date.now()}`,
            mcpServer,
            tool,
            status: 'running',
            startTime: new Date(),
            duration: 0,
            arguments: arguments_,
            result: null,
        };
        this.toolExecutions.unshift(execution);
        this.saveActivity();
        this.notify('tool_call_started', execution);
        return execution;
    }

    completeToolExecution(id, result) {
        const execution = this.toolExecutions.find((e) => e.id === id);
        if (execution) {
            execution.status = 'completed';
            execution.duration = new Date() - execution.startTime;
            execution.result = result;
            this.saveActivity();
            this.notify('tool_call_completed', execution);
        }
        return execution;
    }

    failToolExecution(id, error) {
        const execution = this.toolExecutions.find((e) => e.id === id);
        if (execution) {
            execution.status = 'failed';
            execution.duration = new Date() - execution.startTime;
            execution.result = error;
            this.saveActivity();
            this.notify('tool_call_failed', execution);
        }
        return execution;
    }

    getToolExecutions(filter = 'all', mcpFilter = '') {
        let filtered = this.toolExecutions;

        if (filter !== 'all') {
            filtered = filtered.filter((e) => e.status === filter);
        }

        if (mcpFilter) {
            filtered = filtered.filter((e) => e.mcpServer === mcpFilter);
        }

        return filtered;
    }

    addWorkerPlan(steps) {
        const plan = {
            id: `plan-${Date.now()}`,
            steps: Array.isArray(steps) ? steps : [],
            createdAt: new Date(),
        };
        this.workerPlans.unshift(plan);
        this.saveActivity();
        this.notify('plan_created', plan);
        return plan;
    }

    getWorkerPlans() {
        return this.workerPlans;
    }

    saveActivity() {
        try {
            sessionStorage.setItem('jarvis_activity', JSON.stringify({
                toolExecutions: this.toolExecutions,
                workerPlans: this.workerPlans,
            }));
        } catch (e) {
            console.warn('Unable to save activity state:', e);
        }
    }

    loadActivity() {
        try {
            const stored = sessionStorage.getItem('jarvis_activity');
            if (!stored) return;

            const activity = JSON.parse(stored);
            this.toolExecutions = Array.isArray(activity.toolExecutions)
                ? activity.toolExecutions.map((execution) => ({
                    ...execution,
                    startTime: new Date(execution.startTime),
                }))
                : [];
            this.workerPlans = Array.isArray(activity.workerPlans)
                ? activity.workerPlans.map((plan) => ({
                    ...plan,
                    createdAt: new Date(plan.createdAt),
                }))
                : [];
        } catch (e) {
            console.warn('Unable to load activity state:', e);
            this.toolExecutions = [];
            this.workerPlans = [];
        }
    }

    // Settings
    updateSetting(section, key, value) {
        if (this.settings[section]) {
            this.settings[section][key] = value;
            this.saveSetting(section, key, value);
            this.notify('settings_changed', { section, key, value });
        }
    }

    getSetting(section, key) {
        return this.settings[section]?.[key];
    }

    getSettings() {
        return this.settings;
    }

    saveSetting(section, key, value) {
        const key_ = `jarvis_${section}_${key}`;
        localStorage.setItem(key_, JSON.stringify(value));
    }

    loadSettings() {
        Object.keys(this.settings).forEach((section) => {
            Object.keys(this.settings[section]).forEach((key) => {
                const key_ = `jarvis_${section}_${key}`;
                const stored = localStorage.getItem(key_);
                if (stored) {
                    try {
                        this.settings[section][key] = JSON.parse(stored);
                    } catch (e) {
                        // Ignore parse errors
                    }
                }
            });
        });
    }

    // MCP Settings
    toggleMcp(mcpId, enabled) {
        this.settings.mcp[mcpId] = enabled;
        this.saveSetting('mcp', mcpId, enabled);
        this.notify('mcp_toggled', { mcpId, enabled });
    }

    isMcpEnabled(mcpId) {
        return this.settings.mcp[mcpId] !== false;
    }

    // Page Navigation
    setCurrentPage(page) {
        this.currentPage = page;
        this.notify('page_changed', page);
    }

    getCurrentPage() {
        return this.currentPage;
    }

    // Streaming State
    setStreaming(isStreaming) {
        this.isStreaming = isStreaming;
        this.notify('streaming_changed', isStreaming);
    }

    isStreaming_() {
        return this.isStreaming;
    }

    // Event System
    on(event, callback) {
        if (!this.listeners[event]) {
            this.listeners[event] = [];
        }
        this.listeners[event].push(callback);
    }

    off(event, callback) {
        if (this.listeners[event]) {
            this.listeners[event] = this.listeners[event].filter((cb) => cb !== callback);
        }
    }

    notify(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach((cb) => cb(data));
        }
    }

    async loadBackendData() {
        try {
            // Load messages
            const msgsRes = await fetch('/api/messages');
            if (msgsRes.ok) {
                const msgs = await msgsRes.json();
                this.messages = msgs.map(m => ({
                    ...m,
                    timestamp: m.timestamp ? new Date(m.timestamp) : new Date()
                }));
                this.notify('message_added', null);
            }
            
            // Load tools/MCP status
            const statusRes = await fetch('/api/status');
            if (statusRes.ok) {
                const status = await statusRes.json();
                // Map the connected MCPs and their tools
                this.mcpServers = this.mcpServers.map(server => {
                    const backendServer = status.mcp_servers.find(s => s.id === server.id);
                    if (backendServer) {
                        return {
                            ...server,
                            connected: true,
                            tools: backendServer.tools
                        };
                    } else {
                        return {
                            ...server,
                            connected: false,
                            tools: []
                        };
                    }
                });
                this.notify('mcp_status_changed', this.mcpServers);
            }
        } catch (e) {
            console.error("Failed to load initial backend data:", e);
        }
    }
}

const appState = new AppState();
appState.loadSettings();
appState.loadBackendData();