/* filepath: c:\Navaneth\Study\JarvisMCP\frontend\src\js\events.js */
/**
 * Event Emitter Utilities
 * Clean event handling architecture
 */

class EventBus {
    constructor() {
        this.events = {};
    }

    on(event, callback) {
        if (!this.events[event]) {
            this.events[event] = [];
        }
        this.events[event].push(callback);
    }

    off(event, callback) {
        if (this.events[event]) {
            this.events[event] = this.events[event].filter((cb) => cb !== callback);
        }
    }

    emit(event, data) {
        if (this.events[event]) {
            this.events[event].forEach((cb) => cb(data));
        }
    }

    once(event, callback) {
        const wrapper = (data) => {
            callback(data);
            this.off(event, wrapper);
        };
        this.on(event, wrapper);
    }
}

const eventBus = new EventBus();

// Application events (can be extended for Phase 2.2 backend integration)
const AppEvents = {
    // Messages
    MESSAGE_ADDED: 'message_added',
    MESSAGE_STREAMED: 'message_streamed',
    STREAM_STARTED: 'stream_started',
    STREAM_ENDED: 'stream_ended',

    // Tool execution
    TOOL_CALL_STARTED: 'tool_call_started',
    TOOL_CALL_RESULT: 'tool_call_result',
    TOOL_CALL_FAILED: 'tool_call_failed',
    PLAN_CREATED: 'plan_created',

    // MCP
    MCP_STATUS_CHANGED: 'mcp_status_changed',
    MCP_TOGGLED: 'mcp_toggled',

    // Settings
    SETTINGS_CHANGED: 'settings_changed',

    // UI
    PAGE_CHANGED: 'page_changed',
    THEME_CHANGED: 'theme_changed',
};