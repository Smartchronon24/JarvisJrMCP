/**
 * Claudex Studio WebSocket Client
 * 
 * Minimal WebSocket client that connects to the B8 runtime server
 * and handles the B7 protocol for subscribing to runtime sessions.
 * 
 * Protocol:
 * - Inbound (browser → server):
 *   { "type": "subscribe", "run_id": "..." }
 *   { "type": "input", "run_id": "...", "data": { "text": "..." } }
 *   { "type": "approval", "run_id": "...", "data": { "approved": true } }
 *   { "type": "cancel", "run_id": "..." }
 * 
 * - Outbound (server → browser):
 *   { "event_type": "...", "run_id": "...", "timestamp_ms": ..., ... }
 */

class ClaudexWebSocketClient {
    constructor(options = {}) {
        this.wsUrl = options.wsUrl || 'ws://127.0.0.1:8765';
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 3;
        this.reconnectDelay = 1000;
        this._pendingStart = false;
        
        // Callbacks
        this.onConnected = options.onConnected || null;
        this.onDisconnected = options.onDisconnected || null;
        this.onEvent = options.onEvent || null;
        this.onError = options.onError || null;
        this.onSessionStarted = options.onSessionStarted || null;
        
        this.subscriptions = new Set();
    }

    /**
     * Connect to the WebSocket server
     */
    connect() {
        try {
            this.ws = new WebSocket(this.wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected:', this.wsUrl);
                this.reconnectAttempts = 0;
                if (this.onConnected) this.onConnected();
            };

            this.ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this._handleMessage(message);
                } catch (err) {
                    console.error('Failed to parse server message:', err);
                    if (this.onError) this.onError('Malformed server message');
                }
            };

            this.ws.onerror = (event) => {
                console.error('WebSocket error:', event);
                if (this.onError) this.onError('WebSocket connection error');
            };

            this.ws.onclose = () => {
                console.log('WebSocket closed');
                if (this.onDisconnected) this.onDisconnected();
                this._attemptReconnect();
            };
        } catch (err) {
            console.error('Failed to create WebSocket:', err);
            if (this.onError) this.onError('Failed to connect');
            this._attemptReconnect();
        }
    }

    /**
     * Attempt reconnection with exponential backoff
     */
    _attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            setTimeout(() => this.connect(), delay);
        }
    }

    /**
     * Disconnect from WebSocket
     */
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.subscriptions.clear();
    }

    /**
     * Start a new runtime session.
     */
    startSession(options = {}) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            if (this.onError) this.onError('Not connected to server');
            return;
        }

        const prompt = options.prompt || '';
        
        // B16 diagnostic: prompt integrity at frontend
        const promptHash = this._hashString(prompt).substring(0, 16);
        console.log(`[B16-BOUNDARY-FRONTEND] prompt_hash=${promptHash}, prompt_len=${prompt.length}, timestamp=${Date.now()}`);

        const payload = {
            type: 'start',
            framework: options.framework || 'claude',
            prompt: prompt,
            model: options.model || null,
            provider: options.provider || null,
            endpoint_url: options.endpoint_url || null,
            working_directory: options.working_directory || null,
            executable_path: options.executable_path || null,
            environment: options.environment || {},
            data: {
                framework: options.framework || 'claude',
                prompt: prompt,
                model: options.model || null,
                provider: options.provider || null,
                endpoint_url: options.endpoint_url || null,
                working_directory: options.working_directory || null,
                executable_path: options.executable_path || null,
                environment: options.environment || {},
            }
        };

        if (!payload.prompt || !String(payload.prompt).trim()) {
            if (this.onError) this.onError('Prompt is required to start a runtime session');
            return;
        }

        try {
            this._pendingStart = true;
            const payloadStr = JSON.stringify(payload);
            const payloadHash = this._hashString(payloadStr).substring(0, 16);
            console.log(`[B16-BOUNDARY-TRANSPORT] payload_hash=${payloadHash}, payload_len=${payloadStr.length}`);
            this.ws.send(payloadStr);
            console.log('Started runtime session for framework:', payload.framework);
        } catch (err) {
            console.error('Failed to send start message:', err);
            this._pendingStart = false;
            if (this.onError) this.onError('Failed to start session');
        }
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

    /**
     * Subscribe to a runtime session
     */
    subscribe(runId) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            if (this.onError) this.onError('Not connected to server');
            return;
        }

        const message = {
            type: 'subscribe',
            run_id: runId
        };

        try {
            this.ws.send(JSON.stringify(message));
            this.subscriptions.add(runId);
            console.log('Subscribed to run:', runId);
        } catch (err) {
            console.error('Failed to send subscribe message:', err);
            if (this.onError) this.onError('Failed to subscribe');
        }
    }

    /**
     * Send user input to a running session
     */
    sendInput(runId, text) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            if (this.onError) this.onError('Not connected');
            return;
        }

        const message = {
            type: 'input',
            run_id: runId,
            data: { text: text }
        };

        try {
            this.ws.send(JSON.stringify(message));
            console.log('Sent input for run:', runId);
        } catch (err) {
            console.error('Failed to send input:', err);
            if (this.onError) this.onError('Failed to send input');
        }
    }

    /**
     * Send approval response
     */
    sendApproval(runId, approved) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            if (this.onError) this.onError('Not connected');
            return;
        }

        const message = {
            type: 'approval',
            run_id: runId,
            data: { approved: approved }
        };

        try {
            this.ws.send(JSON.stringify(message));
            console.log('Sent approval for run:', runId, 'approved:', approved);
        } catch (err) {
            console.error('Failed to send approval:', err);
            if (this.onError) this.onError('Failed to send approval');
        }
    }

    /**
     * Cancel a running session
     */
    cancel(runId) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            if (this.onError) this.onError('Not connected');
            return;
        }

        const message = {
            type: 'cancel',
            run_id: runId
        };

        try {
            this.ws.send(JSON.stringify(message));
            console.log('Sent cancel for run:', runId);
        } catch (err) {
            console.error('Failed to send cancel:', err);
            if (this.onError) this.onError('Failed to cancel');
        }
    }

    /**
     * Check if connected
     */
    isConnected() {
        return this.ws && this.ws.readyState === WebSocket.OPEN;
    }

    /**
     * Handle incoming server message
     */
    _handleMessage(message) {
        if (!message || typeof message !== 'object') {
            console.warn('Ignoring malformed server message:', message);
            return;
        }

        // Handle different message types
        if (message.type === 'error') {
            console.error('Server error:', message.code, message.message);
            if (this.onError) this.onError(message.message);
            return;
        }

        if (message.type === 'ack') {
            if (this._pendingStart && message.run_id) {
                this._pendingStart = false;
                if (this.onSessionStarted) this.onSessionStarted(message.run_id);
            }
            console.log('Acknowledged for run:', message.run_id);
            return;
        }

        // All other messages are treated as runtime events
        if (message.event_type) {
            if (this.onEvent) this.onEvent(message);
            return;
        }

        // Unknown message type
        console.warn('Unknown message type:', message.type);
    }
}

// Export to global scope
(globalThis).ClaudexWebSocketClient = ClaudexWebSocketClient;
