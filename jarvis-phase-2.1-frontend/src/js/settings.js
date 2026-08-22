/* filepath: c:\Navaneth\Study\JarvisMCP\jarvis-phase-2.1-frontend\src\js\settings.js */
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

        this.setupEventListeners();
        this.renderMcpToggles();
        this.loadSettings();

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