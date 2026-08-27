/* filepath: c:\Navaneth\Study\JarvisMCP\frontend\src\js\settings.js */
/**
 * Settings Screen
 * User preferences, theme, and MCP toggles
 */

class SettingsScreen {
    constructor() {
        this.jarvisNameInput = document.getElementById('jarvis-name');
        this.startupBehaviorSelect = document.getElementById('startup-behavior');
        this.densityRadios = document.querySelectorAll('.density-radio');
        this.themeRadios = document.querySelectorAll('.theme-radio');
        this.colorOptions = document.querySelectorAll('.color-option');
        this.animationsToggle = document.getElementById('animations-toggle');
        this.mcpTogglesContainer = document.getElementById('mcp-toggles');
        this.llmStatus = document.getElementById('llm-status');
        this.llmSaveButton = document.getElementById('llm-save-btn');
        this.llmDraft = { router: {}, worker: {} };
        this.llmProviders = {};

        this.setupEventListeners();
        this.renderMcpToggles();
        this.loadSettings();
        this.loadLlmSettings();

        appState.on('mcp_status_changed', () => this.renderMcpToggles());
    }

    setupEventListeners() {
        this.jarvisNameInput.addEventListener('change', (e) => {
            appState.updateSetting('general', 'jarvisName', e.target.value);
        });

        this.startupBehaviorSelect.addEventListener('change', (e) => {
            appState.updateSetting('general', 'startupBehavior', e.target.value);
        });

        this.densityRadios.forEach((radio) => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    appState.updateSetting('general', 'density', e.target.value);
                    this.applyDensity(e.target.value);
                }
            });
        });

        this.themeRadios.forEach((radio) => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    appState.updateSetting('appearance', 'theme', e.target.value);
                    themeManager.applyTheme(e.target.value);
                }
            });
        });

        this.colorOptions.forEach((btn) => {
            btn.addEventListener('click', () => {
                const color = btn.dataset.color;
                this.colorOptions.forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                appState.updateSetting('appearance', 'accentColor', color);
                themeManager.applyAccentColor(color);
            });
        });

        this.animationsToggle.addEventListener('change', (e) => {
            appState.updateSetting('appearance', 'animations', e.checked);
            this.applyAnimations(e.checked);
        });

        ['router', 'worker'].forEach((role) => {
            const providerSelect = document.getElementById(`${role}-provider`);
            const modelSelect = document.getElementById(`${role}-model`);
            providerSelect.addEventListener('change', () => {
                this.llmDraft[role].provider = providerSelect.value;
                this.loadLlmModels(role, providerSelect.value);
            });
            modelSelect.addEventListener('change', () => {
                this.llmDraft[role].model = modelSelect.value;
            });
        });
        this.llmSaveButton.addEventListener('click', () => this.saveLlmSettings());
    }

    async loadLlmSettings() {
        try {
            const response = await fetch('/api/settings/llm');
            if (!response.ok) throw new Error('Could not load LLM settings.');
            const data = await response.json();
            this.llmProviders = data.providers || {};
            ['router', 'worker'].forEach((role) => {
                this.llmDraft[role] = { ...data[role] };
                this.renderLlmProviders(role);
                this.loadLlmModels(role, data[role].provider, data[role].model);
            });
            this.renderKeyStatuses();
        } catch (error) {
            this.setLlmStatus(error.message, true);
        }
    }

    renderLlmProviders(role) {
        const select = document.getElementById(`${role}-provider`);
        select.innerHTML = Object.keys(this.llmProviders).map((provider) => {
            const label = provider === 'ollama' ? 'Ollama (local)' : provider[0].toUpperCase() + provider.slice(1);
            return `<option value="${provider}">${label}</option>`;
        }).join('');
        select.value = this.llmDraft[role].provider;
    }

    async loadLlmModels(role, provider, selectedModel = '') {
        const select = document.getElementById(`${role}-model`);
        select.disabled = true;
        select.innerHTML = '<option>Loading models...</option>';
        try {
            const response = await fetch(`/api/settings/llm/models?provider=${encodeURIComponent(provider)}`);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Unable to retrieve models.');
            const models = Array.isArray(data.models) ? data.models : [];
            if (selectedModel && !models.includes(selectedModel)) models.unshift(selectedModel);
            select.innerHTML = models.length
                ? models.map((model) => `<option value="${this.escapeHtml(model)}">${this.escapeHtml(model)}</option>`).join('')
                : '<option value="">No models found</option>';
            select.value = selectedModel || models[0] || '';
            this.llmDraft[role].model = select.value;
        } catch (error) {
            select.innerHTML = `<option value="">${this.escapeHtml(error.message)}</option>`;
            this.setLlmStatus(`${provider}: ${error.message}`, true);
        } finally {
            select.disabled = false;
        }
    }

    renderKeyStatuses() {
        Object.keys(this.llmProviders).filter((provider) => provider !== 'ollama').forEach((provider) => {
            const status = document.getElementById(`llm-key-status-${provider}`);
            if (status) status.textContent = this.llmProviders[provider].configured ? 'Configured' : 'Not configured';
        });
    }

    async saveLlmSettings() {
        this.llmSaveButton.disabled = true;
        this.setLlmStatus('Saving...');
        try {
            for (const role of ['router', 'worker']) {
                if (!this.llmDraft[role].provider || !this.llmDraft[role].model) throw new Error(`${role} provider and model are required.`);
                const provider = this.llmDraft[role].provider;
                const providerInfo = this.llmProviders[provider];
                const keyInput = provider === 'ollama' ? null : document.getElementById(`llm-key-${provider}`);
                if (providerInfo?.requires_api_key && !providerInfo.configured && !keyInput?.value.trim()) {
                    throw new Error(`${provider[0].toUpperCase() + provider.slice(1)} API key is required before saving ${role}.`);
                }
            }
            for (const role of ['router', 'worker']) {
                const response = await fetch(`/api/settings/llm/${role}`, {
                    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.llmDraft[role]),
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || `Could not save ${role} settings.`);
            }
            for (const provider of ['gemini', 'anthropic', 'openai']) {
                const input = document.getElementById(`llm-key-${provider}`);
                if (!input.value.trim()) continue;
                const response = await fetch(`/api/settings/keys/${provider}`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: input.value.trim() }),
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || `Could not save ${provider} key.`);
                input.value = '';
                this.llmProviders[provider].configured = true;
            }
            this.renderKeyStatuses();
            this.setLlmStatus('Changes saved.');
        } catch (error) {
            this.setLlmStatus(error.message, true);
        } finally {
            this.llmSaveButton.disabled = false;
        }
    }

    setLlmStatus(message, isError = false) {
        this.llmStatus.textContent = message;
        this.llmStatus.classList.toggle('error', isError);
    }

    escapeHtml(value) {
        return String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
    }

    loadSettings() {
        const settings = appState.getSettings();

        // General
        this.jarvisNameInput.value = settings.general.jarvisName;
        this.startupBehaviorSelect.value = settings.general.startupBehavior;

        this.densityRadios.forEach((radio) => {
            radio.checked = radio.value === settings.general.density;
        });

        // Appearance
        this.themeRadios.forEach((radio) => {
            radio.checked = radio.value === settings.appearance.theme;
        });

        this.colorOptions.forEach((btn) => {
            if (btn.dataset.color === settings.appearance.accentColor) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        this.animationsToggle.checked = settings.appearance.animations;
    }

    renderMcpToggles() {
        const mcpSettings = appState.settings.mcp;

        this.mcpTogglesContainer.innerHTML = Object.keys(mcpSettings)
            .map((mcpId) => {
                const server = appState.mcpServers.find((s) => s.id === mcpId);
                const enabled = mcpSettings[mcpId];

                if (!server) return '';

                return `
                    <div class="mcp-toggle-item ${!enabled ? 'disabled' : ''}">
                        <div class="mcp-toggle-info">
                            <h3>${server.name}</h3>
                            <p>${server.description}</p>
                            <div class="mcp-disabled-message">
                                Jarvis cannot use this capability when disabled.
                            </div>
                        </div>
                        <div class="toggle-switch ${enabled ? 'active' : ''}" data-mcp-id="${mcpId}">
                        </div>
                    </div>
                `;
            })
            .join('');

        this.setupToggleSwitches();
    }

    setupToggleSwitches() {
        document.querySelectorAll('.toggle-switch').forEach((toggle) => {
            toggle.addEventListener('click', async () => {
                const mcpId = toggle.dataset.mcpId;
                const currentlyEnabled = toggle.classList.contains('active');
                const newEnabled = !currentlyEnabled;

                // Optimistically update UI
                appState.toggleMcp(mcpId, newEnabled);
                toggle.classList.toggle('active');
                toggle.closest('.mcp-toggle-item').classList.toggle('disabled');

                // Enforce on backend — backend is authoritative
                try {
                    const res = await fetch('/api/settings/mcp', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ server_name: mcpId, enabled: newEnabled }),
                    });
                    if (!res.ok) {
                        console.warn(`[MCP Policy] Backend rejected toggle for '${mcpId}':`, await res.json());
                        // Revert UI if backend rejected
                        appState.toggleMcp(mcpId, currentlyEnabled);
                        toggle.classList.toggle('active');
                        toggle.closest('.mcp-toggle-item').classList.toggle('disabled');
                    }
                } catch (e) {
                    console.warn('[MCP Policy] Could not reach backend to enforce toggle:', e);
                }
            });
        });
    }

    applyDensity(density) {
        document.body.setAttribute('data-density', density);
    }

    applyAnimations(enabled) {
        if (!enabled) {
            document.body.style.setProperty('--transition-fast', '0ms');
            document.body.style.setProperty('--transition-normal', '0ms');
            document.body.style.setProperty('--transition-slow', '0ms');
        } else {
            document.body.style.removeProperty('--transition-fast');
            document.body.style.removeProperty('--transition-normal');
            document.body.style.removeProperty('--transition-slow');
        }
    }
}

const settingsScreen = new SettingsScreen();