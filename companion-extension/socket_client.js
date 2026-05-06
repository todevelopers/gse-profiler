'use strict';

/**
 * Unix socket client — connects to $XDG_RUNTIME_DIR/gse-profiler.sock.
 * Sends/receives newline-delimited JSON messages.
 *
 * Phase 2: full implementation.
 */
export class SocketClient {
    #connected = false;

    connect() {
        // Phase 2: open Gio.UnixSocketAddress connection with reconnect loop
    }

    disconnect() {
        this.#connected = false;
        // Phase 2: close socket and cancel reconnect
    }

    send(_message) {
        if (!this.#connected) return;
        // Phase 2: serialize to JSON and write to socket
    }
}
