const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function makeElement() {
    return {
        textContent: '',
        value: '',
        style: {},
        className: '',
        disabled: false,
        listeners: {},
        classList: {
            add() {},
            remove() {},
        },
        addEventListener(type, handler) {
            this.listeners[type] = handler;
        },
        click() {
            if (this.listeners.click) {
                this.listeners.click();
            }
        },
        getBoundingClientRect() {
            return { width: 800, height: 600 };
        },
    };
}

function buildFakeDocument() {
    const ids = [
        'statusText', 'connectionStatus', 'dashState', 'dashFramework', 'dashModel', 'dashProvider',
        'dashRunId', 'dashElapsed', 'metricOutput', 'metricErrors', 'metricExit', 'statusBox',
        'frameworkInput', 'executableInput', 'modelInput', 'providerInput', 'workingDirectoryInput', 'promptInput',
        'startSessionBtn', 'subscribeInput', 'subscribeBtn', 'disconnectBtn', 'inputSection', 'approvalSection',
        'cancelSection', 'errorSection', 'errorMessage', 'userInput', 'sendInputBtn', 'approveBtn',
        'rejectBtn', 'cancelBtn', 'clearTerminalBtn', 'terminal', 'terminalFallback'
    ];

    const map = {};
    for (const id of ids) {
        map[id] = makeElement();
    }

    return {
        getElementById(id) {
            if (!map[id]) {
                map[id] = makeElement();
            }
            return map[id];
        },
    };
}

function loadAppModule() {
    const clientSource = fs.readFileSync(path.join(__dirname, 'websocket-client.js'), 'utf8');
    const appSource = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
    const context = {
        console,
        setTimeout,
        clearTimeout,
        WebSocket: class FakeWebSocket {
            static OPEN = 1;
            constructor(url) {
                this.url = url;
                this.readyState = 1;
            }
            send() {}
            close() {}
        },
        document: buildFakeDocument(),
        window: {},
    };

    context.window = context;
    vm.runInNewContext(clientSource, context);
    vm.runInNewContext(appSource, context);
    return context;
}

test('start form validation prevents empty prompts and duplicate starts', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const started = [];
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        startSession(payload) {
            started.push(payload);
        },
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };

    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });
    app.state.connected = true;
    doc.getElementById('promptInput').value = '';
    doc.getElementById('startSessionBtn').click();
    assert.equal(started.length, 0);

    doc.getElementById('promptInput').value = 'reply ok';
    doc.getElementById('startSessionBtn').click();
    assert.equal(started.length, 1);

    doc.getElementById('startSessionBtn').click();
    assert.equal(started.length, 1);
});

test('start form permits Ollama model IDs for Claude', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const started = [];
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        startSession(payload) {
            started.push(payload);
        },
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };

    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });
    app.state.connected = true;
    doc.getElementById('frameworkInput').value = 'claude';
    doc.getElementById('providerInput').value = 'Ollama';
    doc.getElementById('modelInput').value = 'gpt-oss:120b-cloud';
    doc.getElementById('promptInput').value = 'What is your name?';
    doc.getElementById('startSessionBtn').click();

    assert.equal(started.length, 1);
    assert.equal(started[0].model, 'gpt-oss:120b-cloud');
});

test('start session uses the runtime start request without requiring manual subscription', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const started = [];
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        startSession(payload) {
            started.push(payload);
        },
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };

    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });
    app.state.connected = true;
    doc.getElementById('frameworkInput').value = 'codex';
    doc.getElementById('promptInput').value = 'reply ok';
    doc.getElementById('startSessionBtn').click();

    assert.equal(started.length, 1);
    assert.equal(started[0].framework, 'codex');
    assert.equal(started[0].prompt, 'reply ok');
});

test('run_id propagation and final states are reflected in the dashboard', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };
    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });

    app.handleSessionStarted('run-88');
    assert.equal(doc.getElementById('dashRunId').textContent, 'run-88');
    assert.equal(doc.getElementById('subscribeInput').value, 'run-88');

    app.handleEvent({ event_type: 'process_completed', data: { exit_code: 0 } });
    assert.equal(doc.getElementById('dashState').textContent, 'completed');
    assert.equal(doc.getElementById('metricExit').textContent, '0');
});

test('failed sessions show the runtime failure reason', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };
    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });

    app.handleEvent({
        event_type: 'process_failed',
        data: { exit_code: 1, reason: 'Selected model is unavailable' },
    });

    assert.equal(doc.getElementById('dashState').textContent, 'failed');
    assert.equal(doc.getElementById('errorMessage').textContent, 'Selected model is unavailable');
});

test('output events write to the terminal and state changes update dashboard values', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const terminal = { writes: [], write(text) { this.writes.push(text); } };
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };

    const app = new context.ClaudexStudioApp({
        document: doc,
        client,
        term: terminal,
    });

    app.handleEvent({ event_type: 'output', data: { text: 'hello\n' } });
    assert.deepStrictEqual(terminal.writes, ['hello\n']);

    app.handleEvent({
        event_type: 'state_changed',
        state: 'running',
        framework: 'codex',
        model: 'gpt-4',
        provider: 'openai',
        run_id: 'run-1',
    });

    assert.equal(doc.getElementById('dashState').textContent, 'running');
    assert.equal(doc.getElementById('dashFramework').textContent, 'codex');
    assert.equal(doc.getElementById('dashRunId').textContent, 'run-1');
});

test('line-oriented output without a delimiter remains visible as separate terminal lines', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const terminal = { writes: [], write(text) { this.writes.push(text); } };
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };
    const app = new context.ClaudexStudioApp({ document: doc, client, term: terminal });

    app.handleEvent({ event_type: 'output', data: { text: 'first line', stream: 'stdout' } });
    app.handleEvent({ event_type: 'output', data: { text: 'second line', stream: 'stdout' } });

    assert.deepStrictEqual(terminal.writes, ['first line\r\n', 'second line\r\n']);
});

test('output remains visible when xterm is unavailable', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };
    const app = new context.ClaudexStudioApp({ document: doc, client });

    app.handleEvent({ event_type: 'output', data: { text: 'fallback output', stream: 'stdout' } });

    assert.equal(doc.getElementById('terminalFallback').textContent, 'fallback output\n');
});

test('input and approval required states expose the expected controls', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };
    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });

    app.handleEvent({ event_type: 'input_required' });
    assert.equal(doc.getElementById('inputSection').style.display, 'block');

    app.handleEvent({ event_type: 'approval_required' });
    assert.equal(doc.getElementById('approvalSection').style.display, 'block');
});

test('error and unknown events do not crash the client', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };
    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });

    assert.doesNotThrow(() => {
        app.handleEvent({ event_type: 'error', data: { message: 'boom' } });
    });
    assert.equal(doc.getElementById('errorMessage').textContent, 'boom');

    assert.doesNotThrow(() => {
        app.handleEvent({ event_type: 'mystery_event' });
    });
});

test('terminal input and approval are sent using the B7 runtime protocol', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const sentInput = [];
    const sentApproval = [];
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput(runId, text) {
            sentInput.push([runId, text]);
        },
        sendApproval(runId, approved) {
            sentApproval.push([runId, approved]);
        },
        cancel() {},
    };

    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });
    app.currentRunId = 'run-42';
    app.state.waitingForInput = true;
    app.handleEvent({ event_type: 'input_required', run_id: 'run-42' });
    app._sendTerminalInput('hello\r');
    assert.deepStrictEqual(sentInput[sentInput.length - 1], ['run-42', 'hello\r']);

    app.handleEvent({ event_type: 'approval_required', run_id: 'run-42' });
    doc.getElementById('approveBtn').click();
    assert.deepStrictEqual(sentApproval[0], ['run-42', true]);
    doc.getElementById('approveBtn').click();
    assert.deepStrictEqual(sentApproval.length, 1);
});

test('disconnected state shows a clear status without crashing the UI', () => {
    const context = loadAppModule();
    const doc = buildFakeDocument();
    const client = {
        connect() {},
        disconnect() {},
        subscribe() {},
        sendInput() {},
        sendApproval() {},
        cancel() {},
    };
    const app = new context.ClaudexStudioApp({ document: doc, client, term: { write() {} } });

    app.updateConnectedState(false);
    assert.equal(doc.getElementById('statusText').textContent, 'Disconnected');
    assert.equal(doc.getElementById('statusBox').textContent, 'Disconnected');
});
