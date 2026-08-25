/* Usage and bookkeeping dashboard */

class UsageScreen {
    constructor() {
        this.providerGrid = document.getElementById('provider-grid');
        this.llmGrid = document.getElementById('llm-grid');
        this.recentList = document.getElementById('recent-activity-list');
        this.status = document.getElementById('usage-status');
        this.refreshButton = document.getElementById('usage-refresh-btn');
        this.detail = document.getElementById('usage-detail');
        this.providers = [];
        this.hasLoaded = false;

        this.refreshButton.addEventListener('click', () => this.load(true));
        this.providerGrid.addEventListener('click', (event) => {
            const card = event.target.closest('[data-provider]');
            if (card) this.showProviderDetail(card.dataset.provider);
        });
        this.load();
    }

    async load(manual = false) {
        this.setLoading(manual);
        const [providersResult, llmResult] = await Promise.allSettled([
            this.fetchJson('/api/usage/providers'),
            this.fetchJson('/api/usage/llm'),
        ]);

        const providerError = providersResult.status === 'rejected';
        const llmError = llmResult.status === 'rejected';

        if (providerError) {
            this.providerGrid.innerHTML = this.errorState('Provider usage is unavailable.');
        } else {
            this.providers = Array.isArray(providersResult.value) ? providersResult.value : [];
            this.renderProviders();
        }

        if (llmError) {
            this.llmGrid.innerHTML = this.errorState('LLM usage is unavailable.');
        } else {
            this.renderLlm(Array.isArray(llmResult.value) ? llmResult.value : []);
        }

        await this.loadRecentActivity();
        this.hasLoaded = true;
        this.refreshButton.disabled = false;
        this.status.textContent = providerError || llmError
            ? 'Some usage data could not be loaded.'
            : 'Usage data updated';
        this.status.className = `usage-status ${providerError || llmError ? 'error' : 'success'}`;
        window.setTimeout(() => {
            if (this.status.classList.contains('success')) this.status.textContent = '';
        }, 2500);
    }

    async loadRecentActivity() {
        const providerPromises = this.providers.map((provider) =>
            this.fetchJson(`/api/usage/providers/${encodeURIComponent(provider.provider)}/recent?limit=10`)
                .then((items) => (Array.isArray(items) ? items : []))
                .catch(() => [])
        );
        const [providerItems, llmItems] = await Promise.all([
            Promise.all(providerPromises),
            this.fetchJson('/api/usage/llm/recent?limit=10').catch(() => []),
        ]);
        const providerActivity = providerItems.flat();
        const llmActivity = Array.isArray(llmItems) ? llmItems : [];
        const activity = providerActivity.map((item) => ({ ...item, kind: 'provider' }))
            .concat(llmActivity.map((item) => ({ ...item, kind: 'llm' })))
            .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
            .slice(0, 10);
        this.recentList.innerHTML = activity.length
            ? activity.map((item) => this.activityRow(item)).join('')
            : '<div class="usage-empty">No recorded activity yet.</div>';
    }

    async showProviderDetail(providerName) {
        const provider = this.providers.find((item) => item.provider === providerName);
        if (!provider) return;
        this.detail.hidden = false;
        this.detail.innerHTML = '<div class="usage-loading">Loading provider details...</div>';
        const recent = await this.fetchJson(`/api/usage/providers/${encodeURIComponent(providerName)}/recent?limit=20`).catch(() => []);
        this.detail.innerHTML = this.providerDetail(provider, Array.isArray(recent) ? recent : []);
        this.detail.querySelector('.usage-detail-close').addEventListener('click', () => {
            this.detail.hidden = true;
        });
        this.detail.querySelector('form').addEventListener('submit', (event) => {
            event.preventDefault();
            this.saveQuota(providerName, event.currentTarget);
        });
    }

    async saveQuota(providerName, form) {
        const button = form.querySelector('button');
        button.disabled = true;
        const payload = {
            quota_limit: Number(form.elements.quota_limit.value),
            period_start: form.elements.period_start.value,
            baseline_used: Number(form.elements.baseline_used.value),
        };
        try {
            const updated = await this.fetchJson(`/api/usage/providers/${encodeURIComponent(providerName)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const index = this.providers.findIndex((item) => item.provider === providerName);
            if (index >= 0) this.providers[index] = updated;
            this.renderProviders();
            this.showProviderDetail(providerName);
            this.status.textContent = `${this.displayName(providerName)} quota saved`;
            this.status.className = 'usage-status success';
        } catch (error) {
            this.status.textContent = error.message || 'Unable to save quota';
            this.status.className = 'usage-status error';
            button.disabled = false;
        }
    }

    renderProviders() {
        if (!this.providers.length) {
            this.providerGrid.innerHTML = '<div class="usage-empty">No provider usage has been recorded yet.</div>';
            return;
        }
        this.providerGrid.innerHTML = this.providers.map((provider) => {
            const percentage = Math.min(100, Math.max(0, Number(provider.percentage_used) || 0));
            const state = percentage >= 90 ? 'critical' : percentage >= 70 ? 'warning' : 'normal';
            return `
                <button class="provider-card ${state}" type="button" data-provider="${this.escape(provider.provider)}">
                    <span class="provider-card-top"><span>${this.escape(this.displayName(provider.provider))}</span><span class="provider-action">Configure ↗</span></span>
                    <strong>${this.formatNumber(provider.used)} <small>/ ${this.formatNumber(provider.quota_limit)}</small></strong>
                    <span class="provider-percent">${percentage.toFixed(1)}% used</span>
                    <span class="usage-progress"><span style="width:${percentage}%"></span></span>
                    <span class="provider-period">${this.escape(this.periodLabel(provider.period_start))} · ${this.formatNumber(provider.remaining)} remaining</span>
                </button>
            `;
        }).join('');
    }

    renderLlm(rows) {
        const byRole = { router: [], worker: [], fallback: [] };
        rows.forEach((row) => {
            if (byRole[row.role]) byRole[row.role].push(row);
        });
        this.llmGrid.innerHTML = ['router', 'worker'].map((role) => {
            const roleRows = byRole[role];
            const requests = roleRows.reduce((total, row) => total + (Number(row.request_count) || 0), 0);
            const tokens = roleRows.reduce((total, row) => total + (Number(row.total_tokens) || 0), 0);
            const models = roleRows.map((row) => row.model).filter(Boolean);
            return `
                <article class="llm-card ${role}">
                    <div class="llm-card-heading"><span class="role-mark">${role === 'router' ? 'R' : 'W'}</span><div><p>${role}</p><span>${role === 'router' ? 'Fast-path decisions' : 'Delegated execution'}</span></div></div>
                    <strong>${this.formatNumber(requests)} <small>invocations</small></strong>
                    <dl><div><dt>Models</dt><dd>${this.escape(models.length ? models.join(', ') : 'Unavailable')}</dd></div><div><dt>Tokens</dt><dd>${tokens ? this.formatNumber(tokens) : 'Unavailable'}</dd></div></dl>
                </article>
            `;
        }).join('');
    }

    activityRow(item) {
        const source = item.kind === 'provider' ? this.displayName(item.provider) : this.displayName(item.role);
        const detail = item.kind === 'provider' ? item.operation : item.model;
        const success = item.success === 1 || item.success === true;
        return `<div class="recent-activity-row"><span class="activity-source ${item.kind}">${this.escape(source)}</span><strong>${this.escape(detail || 'Invocation')}</strong><span>${this.formatTime(item.timestamp)}</span><span class="activity-result ${success ? 'ok' : 'failed'}">${success ? 'OK' : 'Failed'}</span></div>`;
    }

    providerDetail(provider, recent) {
        return `<div class="usage-detail-header"><div><p class="usage-kicker">Provider details</p><h2>${this.escape(this.displayName(provider.provider))}</h2></div><button class="usage-detail-close" type="button" title="Close details">×</button></div>
            <div class="detail-stats"><div><span>Used</span><strong>${this.formatNumber(provider.used)} / ${this.formatNumber(provider.quota_limit)}</strong></div><div><span>Remaining</span><strong>${this.formatNumber(provider.remaining)}</strong></div><div><span>Period start</span><strong>${this.escape(provider.period_start || 'Unavailable')}</strong></div></div>
            <form class="quota-form"><label>Quota limit<input name="quota_limit" type="number" min="0" required value="${Number(provider.quota_limit) || 0}"></label><label>Starting usage<input name="baseline_used" type="number" min="0" required value="${Number(provider.baseline_used) || 0}"></label><label>Period start<input name="period_start" type="date" required value="${this.escape(provider.period_start || '')}"></label><button type="submit">Save quota</button></form>
            <div class="detail-activity"><h3>Recent operations</h3>${recent.length ? recent.map((item) => this.activityRow({ ...item, kind: 'provider' })).join('') : '<div class="usage-empty">No recent operations.</div>'}</div>`;
    }

    setLoading(manual) {
        this.refreshButton.disabled = true;
        this.status.textContent = manual ? 'Refreshing usage...' : 'Loading usage...';
        this.status.className = 'usage-status loading';
        if (!this.hasLoaded) {
            this.providerGrid.innerHTML = '<div class="usage-loading">Loading provider usage...</div>';
            this.llmGrid.innerHTML = '<div class="usage-loading">Loading model usage...</div>';
            this.recentList.innerHTML = '<div class="usage-loading">Loading recent activity...</div>';
        }
    }

    async fetchJson(url, options = {}) {
        const response = await fetch(url, options);
        if (!response.ok) throw new Error(`Request failed (${response.status})`);
        return response.json();
    }

    displayName(value) { return String(value || 'Unknown').replace(/^./, (char) => char.toUpperCase()); }
    formatNumber(value) { return Number(value || 0).toLocaleString(); }
    formatTime(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? 'Unknown time' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
    periodLabel(value) { return value ? `Since ${value}` : 'Period unavailable'; }
    escape(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char])); }
    errorState(message) { return `<div class="usage-error">${this.escape(message)}</div>`; }
}

const usageScreen = new UsageScreen();
