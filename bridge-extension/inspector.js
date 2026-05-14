'use strict';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const _MAX_CHILDREN = 50;
const _MAX_STRING_LEN = 200;

/**
 * Extension state object inspector — enumerates properties and methods on
 * a running extension's exported object.
 *
 * Emits: { type: "inspect_result", extensionUuid, properties: [...] }
 */
export class Inspector {
    /**
     * Inspect the stateObj of the given extension.
     * @param {string} uuid
     * @returns {{ properties: object[] }}
     */
    inspect(uuid) {
        const ext = Main.extensionManager.lookup(uuid);
        if (!ext?.stateObj) {
            log(`[gse-profiler-bridge] inspector: no stateObj for ${uuid}`);
            return { properties: [] };
        }
        try {
            return { properties: _serializeObject(ext.stateObj) };
        } catch (e) {
            logError(e, '[gse-profiler-bridge] inspector.inspect');
            return { properties: [] };
        }
    }

    /**
     * Update a writable own property on the extension's stateObj.
     * @param {string} uuid
     * @param {string} name
     * @param {*} value
     * @returns {{ ok: boolean, error?: string }}
     */
    setProperty(uuid, name, value) {
        const ext = Main.extensionManager.lookup(uuid);
        if (!ext?.stateObj)
            return { ok: false, error: 'extension not found' };
        try {
            const desc = Object.getOwnPropertyDescriptor(ext.stateObj, name);
            if (!desc)
                return { ok: false, error: 'property not found on stateObj' };
            if (!desc.writable && typeof desc.set !== 'function')
                return { ok: false, error: 'property is not writable' };
            ext.stateObj[name] = value;
            return { ok: true };
        } catch (e) {
            return { ok: false, error: e.message };
        }
    }
}

// ── Serialization helpers ────────────────────────────────────────────────────

function _serializeObject(obj) {
    const seen = new WeakSet();
    seen.add(obj);

    // Collect from prototype chain 1 level up (excluding Object.prototype).
    const propsMap = new Map();
    const proto = Object.getPrototypeOf(obj);
    if (proto && proto !== Object.prototype) {
        for (const name of Object.getOwnPropertyNames(proto)) {
            if (name === 'constructor') continue;
            const desc = _safeDescriptor(proto, name);
            if (desc) propsMap.set(name, { desc, isOwn: false, holder: obj });
        }
    }

    // Own properties override prototype entries.
    for (const name of Object.getOwnPropertyNames(obj)) {
        const desc = _safeDescriptor(obj, name);
        if (desc) propsMap.set(name, { desc, isOwn: true, holder: obj });
    }

    const result = [];
    for (const [name, { desc, isOwn, holder }] of propsMap)
        result.push(_serializeProp(name, desc, isOwn, holder, seen));
    return result;
}

function _serializeProp(name, desc, isOwn, holder, seen) {
    const writable = isOwn && (desc.writable === true || typeof desc.set === 'function');
    let type, value, children;

    if (typeof desc.get === 'function') {
        try {
            const v = desc.get.call(holder);
            [type, value, children] = _describeValue(v, seen);
        } catch (e) {
            type = 'error';
            value = `[getter error: ${e.message}]`;
        }
    } else {
        [type, value, children] = _describeValue(desc.value, seen);
    }

    const result = { name, type, value, writable };
    if (children) result.children = children;
    return result;
}

function _describeValue(v, seen) {
    if (v === null) return ['null', 'null', null];
    if (v === undefined) return ['undefined', 'undefined', null];

    const t = typeof v;
    if (t === 'function') return ['function', `function ${v.name || '?'}() { … }`, null];
    if (t === 'symbol') return ['symbol', v.toString(), null];
    if (t === 'number') return ['number', String(v), null];
    if (t === 'boolean') return ['boolean', String(v), null];
    if (t === 'string') {
        const s = v.length > _MAX_STRING_LEN ? `${v.slice(0, _MAX_STRING_LEN)}…` : v;
        return ['string', s, null];
    }

    if (seen.has(v)) return ['object', '[Circular]', null];

    if (Array.isArray(v)) {
        seen.add(v);
        const children = [];
        const limit = Math.min(v.length, _MAX_CHILDREN);
        for (let i = 0; i < limit; i++) {
            const [ct, cv] = _describeValue(v[i], seen);
            children.push({ name: String(i), type: ct, value: String(cv), writable: true });
        }
        if (v.length > _MAX_CHILDREN)
            children.push({ name: '…', type: 'info', value: `${v.length - _MAX_CHILDREN} more`, writable: false });
        seen.delete(v);
        return ['array', `Array(${v.length})`, children.length > 0 ? children : null];
    }

    // Plain object / GObject instance.
    seen.add(v);
    const children = [];
    try {
        const keys = Object.getOwnPropertyNames(v).slice(0, _MAX_CHILDREN);
        for (const k of keys) {
            if (k === '__proto__') continue;
            const desc = _safeDescriptor(v, k);
            if (!desc) continue;
            let ct, cv;
            if (typeof desc.get === 'function') {
                ct = 'getter';
                try { [, cv] = _describeValue(desc.get.call(v), seen); } catch (_) { cv = '[error]'; }
            } else {
                [ct, cv] = _describeValue(desc.value, seen);
            }
            children.push({ name: k, type: ct, value: String(cv), writable: desc.writable ?? false });
        }
    } catch (_) { /* skip on enumeration errors */ }
    seen.delete(v);

    const ctorName = v.constructor?.name ?? '';
    const label = ctorName && ctorName !== 'Object' ? `[${ctorName}]` : '{…}';
    return ['object', label, children.length > 0 ? children : null];
}

function _safeDescriptor(obj, name) {
    try {
        return Object.getOwnPropertyDescriptor(obj, name) ?? null;
    } catch (_) {
        return null;
    }
}
