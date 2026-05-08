'use strict';

/**
 * DevToolsClient — opt-in developer API for GSE Profiler.
 *
 * Import this in your GNOME Shell extension to enable deeper profiling
 * integration. All methods silently no-op when gse-profiler is not running,
 * so your extension continues to work normally with zero overhead.
 *
 * @example
 *   import { DevToolsClient } from '/path/to/api/devtools-api.js';
 *
 *   const devtools = new DevToolsClient();
 *   devtools.connect('my-extension@example.com');
 *
 *   devtools.mark('init-start');
 *   // ... your initialization code ...
 *   devtools.mark('init-end');
 *   devtools.measure('init', 'init-start', 'init-end');
 *
 *   devtools.counter('network-requests', 1);
 *   devtools.watch(myObject, ['property1', 'property2']);
 *
 * Phase 7: full implementation.
 */
export class DevToolsClient {
    #connected = false;
    #uuid = null;

    /**
     * Connect to the GSE Profiler bridge extension.
     * @param {string} uuid - Your extension's UUID.
     */
    connect(uuid) {
        this.#uuid = uuid;
        // Phase 7: locate and connect to bridge socket
    }

    /** Disconnect from the bridge. */
    disconnect() {
        this.#connected = false;
        this.#uuid = null;
    }

    /**
     * Record a named timestamp marker.
     * @param {string} name
     */
    mark(_name) {
        if (!this.#connected) { return; }
        // Phase 7: send { type: 'devtools_mark', name, ts: Date.now() }
    }

    /**
     * Record a duration between two previously recorded marks.
     * @param {string} name
     * @param {string} startMark
     * @param {string} endMark
     */
    measure(_name, _startMark, _endMark) {
        if (!this.#connected) { return; }
        // Phase 7: send { type: 'devtools_measure', name, startMark, endMark }
    }

    /**
     * Increment a named counter.
     * @param {string} name
     * @param {number} value
     */
    counter(_name, _value) {
        if (!this.#connected) { return; }
        // Phase 7: send { type: 'devtools_counter', name, value }
    }

    /**
     * Watch an object for property changes and emit events on mutation.
     * @param {object} object
     * @param {string[]} properties
     */
    watch(_object, _properties) {
        if (!this.#connected) { return; }
        // Phase 7: install property change listeners via Object.defineProperty
    }
}
