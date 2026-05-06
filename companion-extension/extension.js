'use strict';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

// Phase 2: import SocketClient once implemented
// import { SocketClient } from './socket_client.js';

export default class GSEProfilerBridge extends Extension {
    /** @type {import('./socket_client.js').SocketClient | null} */
    _socketClient = null;

    enable() {
        log('[gse-profiler-bridge] Enabled');
        // Phase 2: start socket client and connect to app
    }

    disable() {
        log('[gse-profiler-bridge] Disabled');
        // Phase 2: disconnect and clean up — no signals left connected
        this._socketClient = null;
    }
}
