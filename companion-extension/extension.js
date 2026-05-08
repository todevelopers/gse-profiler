'use strict';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Gio from 'gi://Gio';

// Phase 2: import SocketClient once implemented
// import { SocketClient } from './socket_client.js';

const GSEProfilerIndicator = GObject.registerClass(
    class GSEProfilerIndicator extends PanelMenu.Button {
        _init() {
            super._init(0.0, 'GSE Profiler Bridge', true);
            this.add_child(new St.Icon({
                gicon: new Gio.ThemedIcon({ name: ' user-available-symbolic' }),
                style_class: 'system-status-icon',
            }));
        }
    }
);

export default class GSEProfilerBridge extends Extension {
    /** @type {GSEProfilerIndicator | null} */
    _indicator = null;

    /** @type {import('./socket_client.js').SocketClient | null} */
    _socketClient = null;

    enable() {
        log('[gse-profiler-bridge] Enabled');
        this._indicator = new GSEProfilerIndicator();
        Main.panel.addToStatusArea('gse-profiler-bridge', this._indicator);
        // Phase 2: start socket client and connect to app
    }

    disable() {
        log('[gse-profiler-bridge] Disabled');
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
        // Phase 2: disconnect and clean up — no signals left connected
        this._socketClient = null;
    }
}
