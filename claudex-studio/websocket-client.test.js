const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadClientModule() {
    const source = fs.readFileSync(path.join(__dirname, 'websocket-client.js'), 'utf8');
    const context = {
        console,
        WebSocket: class FakeWebSocket {
            static OPEN = 1;
            static CONNECTING = 0;
            static CLOSED = 3;
            constructor(url) {
                this.url = url;
                this.readyState = FakeWebSocket.CONNECTING;
                this.sent = [];
                this.onopen = null;
                this.onmessage = null;
                this.onerror = null;
                this.onclose = null;
            }
            send(payload) {
                this.sent.push(payload);
            }
            close() {
                this.readyState = FakeWebSocket.CLOSED;
                if (this.onclose) this.onclose();
            }
        },
        setTimeout,
        clearTimeout,
    };

    vm.runInNewContext(source, context);
    return context.ClaudexWebSocketClient;
}

function makeWebSocketStub() {
    return {
        readyState: 1,
        sent: [],
        send(payload) {
            this.sent.push(payload);
        },
    };
}

test('subscribe message uses the expected B7 schema', () => {
    const ClaudexWebSocketClient = loadClientModule();
    const client = new ClaudexWebSocketClient({ wsUrl: 'ws://127.0.0.1:8765' });
    const ws = makeWebSocketStub();
    client.ws = ws;

    client.subscribe('run-123');

    assert.deepStrictEqual(JSON.parse(ws.sent[0]), {
        type: 'subscribe',
        run_id: 'run-123',
    });
});

test('start message preserves punctuation and sends one authoritative prompt', () => {
    const ClaudexWebSocketClient = loadClientModule();
    const client = new ClaudexWebSocketClient({ wsUrl: 'ws://127.0.0.1:8765' });
    const ws = makeWebSocketStub();
    client.ws = ws;

    const prompt = 'hi, please state your name';
    client.startSession({ framework: 'claude', prompt });

    const payload = JSON.parse(ws.sent[0]);
    assert.equal(payload.prompt, prompt);
    assert.equal(Object.hasOwn(payload, 'data'), false);
});

test('input approval and cancel messages use the exact runtime protocols', () => {
    const ClaudexWebSocketClient = loadClientModule();
    const client = new ClaudexWebSocketClient({ wsUrl: 'ws://127.0.0.1:8765' });
    const ws = makeWebSocketStub();
    client.ws = ws;

    client.sendInput('run-abc', 'hello');
    client.sendApproval('run-abc', true);
    client.cancel('run-abc');

    const payloads = ws.sent.map((p) => JSON.parse(p));

    assert.deepStrictEqual(payloads[0], {
        type: 'input',
        run_id: 'run-abc',
        data: { text: 'hello' },
    });

    test('approval acknowledgements are delivered to the UI callback', () => {
        const ClaudexWebSocketClient = loadClientModule();
        let acknowledgedRunId = null;
        const client = new ClaudexWebSocketClient({
            wsUrl: 'ws://127.0.0.1:8765',
            onAcknowledged: (runId) => { acknowledgedRunId = runId; },
        });

        client._handleMessage({ type: 'ack', run_id: 'run-ack' });

        assert.equal(acknowledgedRunId, 'run-ack');
    });
    assert.deepStrictEqual(payloads[1], {
        type: 'approval',
        run_id: 'run-abc',
        data: { approved: true },
    });
    assert.deepStrictEqual(payloads[2], {
        type: 'cancel',
        run_id: 'run-abc',
    });
});

test('malformed server messages are ignored without crashing', () => {
    const ClaudexWebSocketClient = loadClientModule();
    const client = new ClaudexWebSocketClient({
        wsUrl: 'ws://127.0.0.1:8765',
        onError: () => {},
        onEvent: () => {},
    });

    assert.doesNotThrow(() => {
        client._handleMessage({});
    });
    assert.doesNotThrow(() => {
        client._handleMessage(null);
    });
});
