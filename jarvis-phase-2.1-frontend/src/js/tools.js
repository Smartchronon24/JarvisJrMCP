/* filepath: c:\Navaneth\Study\JarvisMCP\jarvis-phase-2.1-frontend\src\js\tools.js */
/**
 * Tools Screen
 * Displays available MCP capabilities
 */

class ToolsScreen {
    constructor() {
        this.toolsGrid = document.getElementById('tools-grid');
        this.renderTools();

        appState.on('mcp_toggled', () => this.renderTools());
    }

    renderTools() {
        const mcpServers = appState.mcpServers;

        this.toolsGrid.innerHTML = mcpServers
            .map((server) => this.createToolCard(server))
            .join('');
    }

    createToolCard(server) {
        const enabled = appState.isMcpEnabled(server.id);
        const toolList = server.tools.map((t) => `<li>${t}</li>`).join('');

        return `
            <div class="tool-overview-card">
                <div class="tool-overview-header">
                    <div class="tool-overview-info">
                        <h3>${server.icon} ${server.name}</h3>
                        <p>${server.description}</p>
                    </div>
                    <div class="tool-status-badge ${!enabled ? 'disconnected' : ''}">
                        <span class="status-dot ${enabled ? 'completed' : 'failed'}"></span>
                        <span>${enabled ? 'Connected' : 'Disconnected'}</span>
                    </div>
                </div>
                <div class="tool-count">
                    <span>${server.tools.length} tools available</span>
                </div>
                <details class="tool-details" style="cursor: pointer; margin-top: var(--spacing-md);">
                    <summary style="color: var(--accent); font-size: var(--text-sm); font-weight: var(--weight-medium); cursor: pointer;">
                        View tools
                    </summary>
                    <div style="margin-top: var(--spacing-md); padding-top: var(--spacing-md); border-top: 1px solid var(--border);">
                        <ul style="list-style: none; display: flex; flex-direction: column; gap: var(--spacing-sm);">
                            ${toolList}
                        </ul>
                    </div>
                </details>
            </div>
        `;
    }
}

const toolsScreen = new ToolsScreen();