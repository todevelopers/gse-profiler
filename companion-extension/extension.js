'use strict';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import GObject from 'gi://GObject';
import St from 'gi://St';
import { SocketClient } from './socket_client.js';

const COMPANION_UUID = 'gse-profiler-bridge@todevelopers';

const GSEProfilerIndicator = GObject.registerClass(
    class GSEProfilerIndicator extends PanelMenu.Button {
        _init() {
            super._init(0.0, 'GSE Profiler Bridge', true);
            this.add_child(new St.Icon({
                icon_name: 'media-playback-pause-symbolic',
                style_class: 'system-status-icon',
            }));
        }
    }
);

export default class GSEProfilerBridge extends Extension {
    /** @type {GSEProfilerIndicator | null} */
    _indicator = null;

    /** @type {SocketClient | null} */
    _socketClient = null;

    enable() {
        log('[gse-profiler-bridge] Enabled');

        this._indicator = new GSEProfilerIndicator();
        Main.panel.addToStatusArea('gse-profiler-bridge', this._indicator);

        this._socketClient = new SocketClient(COMPANION_UUID, msg => this._onMessage(msg));
        this._socketClient.connect();
    }

    disable() {
        log('[gse-profiler-bridge] Disabled');

        if (this._socketClient) {
            this._socketClient.disconnect();
            this._socketClient = null;
        }

        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }

    /** @param {object} msg */
    _onMessage(msg) {
        log(`[gse-profiler-bridge] message received: type=${msg.type}`);
    }
}
