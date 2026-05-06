'use strict';

/**
 * Extension function profiler — monkey-patches a target extension's exported
 * object and records per-call timing events.
 *
 * Emits: { type: "profile_event", extensionUuid, function, start, end, depth }
 *
 * Phase 4: full implementation.
 */
export class Profiler {
    #running = false;
    #targetUuid = null;
    #originalFunctions = new Map();

    startProfiling(_uuid) {
        // Phase 4: monkey-patch all functions on extension's exported object
        this.#running = true;
    }

    stopProfiling() {
        // Phase 4: restore original functions from #originalFunctions map
        this.#running = false;
        this.#originalFunctions.clear();
        this.#targetUuid = null;
    }
}
