/* filepath: c:\Navaneth\Study\JarvisMCP\frontend\src\js\activity.js */
/**
 * Activity Screen & Tool Execution Display
 * Shows MCP tool calls, results, and execution logs
 */

class ActivityScreen {
    constructor() {
        this.activityList = document.getElementById('activity-list');
        this.filterButtons = document.querySelectorAll('.filter-btn');
        this.mcpSelect = document.getElementById('mcp-select');
        this.currentFilter = 'all';
        this.currentMcpFilter = '';

        this.setupEventListeners();
        this.renderActivity();

        appState.on('tool_call_started', () => this.renderActivity());
        appState.on('tool_call_completed', () => this.renderActivity());
        appState.on('tool_call_failed', () => this.renderActivity());
        appState.on('plan_created', () => this.renderActivity());
    }

    setupEventListeners() {
        this.filterButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                this.filterButtons.forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentFilter = btn.dataset.filter;
                this.renderActivity();
            });
        });

        this.mcpSelect.addEventListener('change', (e) => {
            this.currentMcpFilter = e.target.value;
            this.renderActivity();
        });
    }

    renderActivity() {
        const executions = appState.getToolExecutions(this.currentFilter, this.currentMcpFilter);
        const plans = appState.getWorkerPlans();

        if (executions.length === 0 && plans.length === 0) {
            this.activityList.innerHTML = `
                <div style="text-align: center; padding: 40px; color: var(--text-tertiary);">
                    <p>No tool executions matching your filters</p>
                </div>
            `;
            return;
        }

        this.activityList.innerHTML = plans.map((plan) => this.createPlanCard(plan)).join('')
            + executions.map((exec) => this.createToolCard(exec)).join('');

        this.setupToolCardListeners();
    }

    createToolCard(execution) {
        const statusClass = execution.status;
        const statusLabel = execution.status.charAt(0).toUpperCase() + execution.status.slice(1);
        const durationMs = execution.duration;
        const durationSec = (durationMs / 1000).toFixed(2);
        const argsJson = JSON.stringify(execution.arguments, null, 2);
        const resultJson = typeof execution.result === 'string' 
            ? execution.result 
            : JSON.stringify(execution.result, null, 2);

        return `
            <div class="tool-card" data-exec-id="${execution.id}">
                <div class="tool-card-header">
                    <div class="tool-info">
                        <div class="tool-status ${statusClass}">
                            <span class="status-dot ${statusClass}"></span>
                            <span>${statusLabel}</span>
                        </div>
                        <div>
                            <strong>${execution.mcpServer}</strong>
                            <div style="font-size: var(--text-sm); color: var(--text-tertiary);">
                                ${execution.tool}
                            </div>
                        </div>
                    </div>
                    <div class="tool-meta">
                        <div class="tool-duration">${durationSec}s</div>
                        <button class="tool-expand-btn">
                            <svg viewBox="0 0 24 24" style="width: 18px; height: 18px;">
                                <path d="M7 10l5 5 5-5z" fill="currentColor"/>
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="tool-card-content">
                    <div class="tool-section">
                        <div class="tool-section-title">Arguments</div>
                        <div class="tool-args">${this.escapeHtml(argsJson)}</div>
                    </div>
                    <div class="tool-section">
                        <div class="tool-section-title">Result</div>
                        <div class="tool-result">${this.escapeHtml(resultJson)}</div>
                    </div>
                </div>
            </div>
        `;
    }

    createPlanCard(plan) {
        const steps = plan.steps.map((step, index) => `
            <li><span>${index + 1}.</span> ${this.escapeHtml(step)}</li>
        `).join('');
        return `
            <div class="worker-plan-card">
                <div class="worker-plan-header">
                    <strong>Worker plan</strong>
                    <span>Planning</span>
                </div>
                <ol>${steps}</ol>
            </div>
        `;
    }

    setupToolCardListeners() {
        document.querySelectorAll('.tool-card-header').forEach((header) => {
            header.addEventListener('click', () => {
                const card = header.closest('.tool-card');
                card.classList.toggle('expanded');
            });
        });
    }

    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;',
        };
        return text.replace(/[&<>"']/g, (m) => map[m]);
    }
}

const activityScreen = new ActivityScreen();