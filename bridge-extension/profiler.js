'use strict';

import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

/**
 * Extension function profiler — monkey-patches a target extension's exported
 * object and records per-call timing events.
 *
 * Emits: { type: "profile_event", extensionUuid, function, start, end, depth }
 */
export class Profiler {
    #running = false;
    #targetUuid = null;
    /** @type {Map<string, {holder: object, name: string, original: Function}>} */
    #patches = new Map();
    #callDepth = 0;
    /** @type {(event: object) => void} */
    #onEvent;

    /** @param {(event: object) => void} onEvent - called for each recorded call */
    constructor(onEvent) {
        this.#onEvent = onEvent;
    }

    get isRunning() {
        return this.#running;
    }

    /**
     * Monkey-patch all functions on the extension's stateObj (instance + prototype).
     * @param {string} uuid
     * @returns {boolean} whether patching succeeded
     */
    startProfiling(uuid) {
        if (this.#running) {
            this.stopProfiling();
        }

        const ext = Main.extensionManager.lookup(uuid);
        if (!ext?.stateObj) {
            log(`[gse-profiler-bridge] startProfiling: no stateObj for ${uuid}`);
            return false;
        }

        this.#targetUuid = uuid;
        this.#callDepth = 0;

        const target = ext.stateObj;
        log(`[gse-profiler-bridge] stateObj type=${typeof target} keys=${Object.getOwnPropertyNames(target).join(',')}`);

        // Patch own properties first (instance wins over prototype).
        this.#patchObject(target, target);
        // Then patch prototype chain (one level deep).
        const proto = Object.getPrototypeOf(target);
        log(`[gse-profiler-bridge] proto=${proto?.constructor?.name ?? 'none'}`);
        if (proto && proto !== Object.prototype) {
            this.#patchObject(target, proto);
        }

        this.#running = true;
        log(`[gse-profiler-bridge] profiling started: ${uuid} (${this.#patches.size} functions patched: ${[...this.#patches.keys()].join(',')})`);
        return true;
    }

    /** Restore all original functions and reset state. */
    stopProfiling() {
        if (!this.#running && this.#patches.size === 0) {
            return;
        }
        for (const { holder, name, original } of this.#patches.values()) {
            try {
                holder[name] = original;
            } catch (_e) {
                // Property may have become non-writable — ignore.
            }
        }
        this.#patches.clear();
        this.#running = false;
        this.#targetUuid = null;
        this.#callDepth = 0;
        log('[gse-profiler-bridge] profiling stopped');
    }

    // ── Private ───────────────────────────────────────────────────────────

    /**
     * Enumerate own function-valued properties of `source` and install
     * timing wrappers on `holder`.
     * @param {object} holder - object to write the patched functions onto
     * @param {object} source - object whose properties are enumerated
     */
    #patchObject(holder, source) {
        for (const name of Object.getOwnPropertyNames(source)) {
            if (name === 'constructor') { continue; }
            if (this.#patches.has(name)) { continue; } // instance already patched this name

            let desc;
            try {
                desc = Object.getOwnPropertyDescriptor(source, name);
            } catch (_e) {
                continue;
            }
            if (!desc || typeof desc.value !== 'function') { continue; }

            const original = desc.value;
            this.#patches.set(name, { holder, name, original });

            // Closure over `profiler` and `funcName` to record each call.
            const profiler = this;
            const funcName = name;
            holder[name] = function profiled(...args) {
                if (!profiler.#running) {
                    return original.apply(this, args);
                }

                const depth = profiler.#callDepth++;
                // GLib.get_monotonic_time() returns µs as an integer — convert to seconds.
                const start = GLib.get_monotonic_time() / 1e6;
                try {
                    return original.apply(this, args);
                } finally {
                    const end = GLib.get_monotonic_time() / 1e6;
                    profiler.#callDepth--;
                    profiler.#onEvent({
                        type: 'profile_event',
                        extensionUuid: profiler.#targetUuid,
                        function: funcName,
                        start,
                        end,
                        depth,
                    });
                }
            };
        }
    }
}
