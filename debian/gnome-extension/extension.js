// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Indicateur TRX distant dans la barre du haut de GNOME (45 et suivants), à gauche du son et du réseau.
// LECTURE SEULE : lit chaque seconde les fichiers publiés par la station ; ne commande jamais la station ni le poste.
// La logique (voyant, texte, lignes du menu) est dans status.js, testée sous Node.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {summarize} from './status.js';

const FILES = {
    status: '/run/trx-remote/gateway-status.json',
    safeMode: '/var/lib/trx-remote/safe_mode',
    cluster: '/var/lib/trx-remote/cluster/status.json',
    update: '/var/lib/trx-remote/update/latest.json',
    stationId: '/var/lib/trx-remote/station-id',
    config: '/etc/trx-remote/station.toml',
};
const CURRENT = '/opt/trx-remote/current';
const TERMINALS = [['kgx', '--'], ['gnome-terminal', '--'], ['x-terminal-emulator', '-e']];

Gio._promisify(Gio.File.prototype, 'load_contents_async', 'load_contents_finish');

async function readText(path) {
    try {
        const [bytes] = await Gio.File.new_for_path(path).load_contents_async(null);
        return new TextDecoder().decode(bytes);
    } catch {
        return null;                                    // absent ou illisible : traité comme « rien à dire »
    }
}

function parseJson(text) {
    try {
        return text ? JSON.parse(text) : null;
    } catch {
        return null;
    }
}

function installedVersion() {
    try {
        return GLib.path_get_basename(GLib.file_read_link(CURRENT));
    } catch {
        return '';
    }
}

const TrxIndicator = GObject.registerClass(
class TrxIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'TRX distant');
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._dot = new St.Label({text: '●', y_align: Clutter.ActorAlign.CENTER, style_class: 'trx-dot trx-off'});
        this._label = new St.Label({text: 'TRX', y_align: Clutter.ActorAlign.CENTER, style_class: 'trx-label'});
        box.add_child(this._dot);
        box.add_child(this._label);
        this.add_child(box);

        this._section = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(this._section);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Ouvrir la page web de la station', () => this._openPage());
        this.menu.addAction('Ouvrir TRX Console', () => this._launchDesktop('trx-console.desktop'));
        this.menu.addAction('Ouvrir le tableau de bord', () => this._inTerminal('trx-monitor'));

        this._shown = '';
        this._busy = false;
        this._refresh();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    async _refresh() {
        if (this._busy)
            return;
        this._busy = true;
        try {
            const [status, safeMode, cluster, update, stationId] = await Promise.all([
                readText(FILES.status), readText(FILES.safeMode), readText(FILES.cluster),
                readText(FILES.update), readText(FILES.stationId)]);
            const view = summarize({
                status: parseJson(status), nowS: GLib.get_real_time() / 1e6, safeMode: safeMode,
                cluster: parseJson(cluster), update: parseJson(update), stationId: stationId, version: installedVersion(),
            });
            this._show(view);
        } finally {
            this._busy = false;
        }
    }

    _show(view) {
        if (!this._dot)
            return;                                     // détruit entre-temps
        this._dot.style_class = `trx-dot trx-${view.level}`;
        this._label.text = view.label;
        this._label.style_class = view.level === 'tx' ? 'trx-label trx-label-tx' : 'trx-label';
        const shown = JSON.stringify(view.lines);
        if (shown === this._shown)
            return;                                     // menu inchangé : pas de reconstruction (pas de scintillement)
        this._shown = shown;
        this._section.removeAll();
        for (const line of view.lines) {
            const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
            item.add_child(new St.Label({text: line.key, style_class: 'trx-key'}));
            item.add_child(new St.Label({text: line.text, style_class: `trx-value trx-${line.level}`, x_expand: true}));
            this._section.addMenuItem(item);
        }
    }

    async _openPage() {
        const config = (await readText(FILES.config)) || '';
        const port = (config.match(/^\s*gateway_port\s*=\s*(\d+)/m) || [])[1] || '8443';
        const tls = /^\s*tls_cert\s*=\s*"[^"]+"/m.test(config);
        try {
            Gio.AppInfo.launch_default_for_uri(`${tls ? 'https' : 'http'}://localhost:${port}/`, null);
        } catch (e) {
            Main.notify('TRX distant', `Page web impossible à ouvrir : ${e.message}`);
        }
    }

    _launchDesktop(id) {
        const app = Gio.DesktopAppInfo.new(id);
        if (app)
            app.launch([], null);
        else
            Main.notify('TRX distant', 'TRX Console introuvable : relance l\'installation.');
    }

    _inTerminal(command) {
        for (const [terminal, flag] of TERMINALS) {
            if (GLib.find_program_in_path(terminal)) {
                GLib.spawn_async(null, [terminal, flag, command], null, GLib.SpawnFlags.SEARCH_PATH, null);
                return;
            }
        }
        Main.notify('TRX distant', 'Aucun terminal trouvé pour le tableau de bord.');
    }

    destroy() {
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = 0;
        }
        this._dot = null;
        super.destroy();
    }
});

export default class TrxDistantExtension extends Extension {
    enable() {
        this._indicator = new TrxIndicator();
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');   // à gauche du son, du réseau et de l'arrêt
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
