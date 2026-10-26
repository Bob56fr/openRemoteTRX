// Mises en page personnalisées (designer) : choix de la variante, plan d'affichage et application à la page.
// Partie pure (selectVariant, detectDevice, blockFor, buildPlan) testée sous Node ; applyPlan agit sur le DOM.
//
// Principe : la page garde ses éléments (ui.js les met à jour par leur identifiant) ; un profil ne fait que les
// DÉPLACER dans une grille. Un élément absent du profil est masqué ; un widget sans élément correspondant
// (fonction encore non prise en charge par la page) est ignoré et signalé. Les widgets de sécurité (PTT,
// état d'émission, liaison, « Émission autorisée ») doivent être présents : sinon, écran de sécurité.
// Les règles de la station s'appliquent quel que soit le profil : rien ici ne donne de droit.
(function (root) {
  "use strict";

  const DEVICES = ["phone", "tablet", "desktop"];                     // du plus petit au plus grand : la cascade monte
  const ORIENTATIONS = ["portrait", "landscape"];
  const DEVICE_LABELS = { phone: "smartphone", tablet: "tablette", desktop: "ordinateur" };
  const GRID_COLUMNS = { phone: 4, tablet: 8, desktop: 12 };
  const MAX_WIDTH = { phone: "44rem", tablet: "64rem", desktop: "none" };   // largeur d'affichage d'une variante
  const LOCKED = { ptt: "ptt", tx_indicator: "ptt-state", link_status: "status", tx_armed: "blk-armed" };
  const TAP_DEBOUNCE_MS = 350, DOUBLE_TAP_MS = 300, LONG_PRESS_MS = 550, SWIPE_PX = 40;

  // Élément de la page affiché par un widget (type + liaison + apparence) ; null = pas encore pris en charge.
  const BY_BIND = {
    switch: { NR: "ctl-nr", NB: "ctl-nb", AIP: "ctl-aip", COMP: "ctl-comp", TUNER: "ctl-tuner" },
    select: { PREAMP: "ctl-preamp", AGC: "ctl-agc", RFPOWER: "ctl-pwr" },
    slider: { SQL: "blk-sql" },
    meter: { RFPOWER_METER: "blk-po", SWR: "blk-swr", ALC: "blk-alc" },
  };
  const BY_TYPE = {
    ptt: "ptt", stop: "stop", tx_armed: "blk-armed", tx_indicator: "ptt-state", link_status: "status", tot: "tot",
    smeter: "blk-smeter", waterfall: "waterfall", filter: "ctl-fil", bands: "bands", steps: "blk-steps", memories: "blk-memories",
  };
  const ALL_BLOCKS = Array.from(new Set(Object.values(BY_TYPE).concat(...Object.values(BY_BIND).map((m) => Object.values(m)),
    ["blk-freq", "blk-freqinput", "blk-mode", "blk-modeset"])));

  // ------------------------------------------------------------------ cascade (même règle que trxstation/layout/cascade.py)
  function selectVariant(variants, device, orientation, forced) {
    if (!DEVICES.includes(device) || !ORIENTATIONS.includes(orientation)) throw new Error("appareil ou orientation inconnu");
    let effective = device;
    if (DEVICES.includes(forced) && DEVICES.indexOf(forced) <= DEVICES.indexOf(device)) effective = forced;
    for (let i = DEVICES.indexOf(effective); i >= 0; i--) {
      const candidate = DEVICES[i];
      const available = variants && typeof variants === "object" ? variants[candidate] : null;
      if (!available || typeof available !== "object" || !Object.keys(available).length) continue;
      const smaller = candidate !== device;
      if (available[orientation]) return { device: candidate, orientation: orientation, display: smaller ? "centered" : "native" };
      if (orientation === "landscape" && available.portrait) return { device: candidate, orientation: "portrait", display: "centered" };
      if (orientation === "portrait" && available.landscape) return { device: candidate, orientation: "landscape", display: "rotate" };
    }
    return null;
  }

  // Catégorie d'après la taille de l'écran en pixels CSS (le plus petit côté) et le type de pointeur.
  function detectDevice(width, height, coarse) {
    const small = Math.min(width, height), large = Math.max(width, height);
    if (small < 600) return "phone";
    if (small < 900 || (coarse && large < 1400)) return "tablet";
    return "desktop";
  }

  function blockFor(w) {
    if (!w || typeof w !== "object") return null;
    if (w.target && w.target !== "current" && w.target !== "main") return null;   // un seul récepteur affiché pour l'instant
    if (BY_BIND[w.type]) return BY_BIND[w.type][w.bind] || null;
    if (w.type === "frequency") return w.appearance === "field" ? "blk-freqinput" : "blk-freq";
    if (w.type === "mode") return w.appearance === "select" || w.appearance === "buttons" ? "blk-modeset" : "blk-mode";
    return BY_TYPE[w.type] || null;
  }

  // ------------------------------------------------------------------ plan d'affichage
  function buildPlan(profile, device, orientation, forced) {
    const variants = profile && profile.variants;
    const choice = selectVariant(variants, device, orientation, forced);
    const plan = { choice: choice, device: device, safe: false, reason: "", cols: 4, maxWidth: MAX_WIDTH.phone,
                   top: [], bottom: [], blocks: [], unsupported: [] };
    if (!choice) { plan.reason = "no_variant"; return plan; }
    if (choice.display === "rotate") { plan.reason = "rotate"; return plan; }
    const widgets = (variants[choice.device][choice.orientation] || {}).widgets;
    if (!Array.isArray(widgets)) { plan.reason = "invalid"; return plan; }
    plan.cols = GRID_COLUMNS[choice.device];
    plan.maxWidth = MAX_WIDTH[choice.device];
    const used = new Set();
    const node = (w) => {
      if (!w || typeof w !== "object" || w.hidden) return null;
      const box = { id: w.id, x: w.x | 0, y: w.y | 0, w: Math.max(1, w.w | 0), h: Math.max(1, w.h | 0) };
      if (w.type === "label") return Object.assign(box, { kind: "label", text: String(w.text || w.label || "") });
      if (w.type === "separator") return Object.assign(box, { kind: "separator" });
      if (w.type === "layers") {
        const groups = (Array.isArray(w.groups) ? w.groups : []).map((group) => (Array.isArray(group) ? group : []).map((layer) => ({
          title: layer && layer.title ? String(layer.title) : "", items: grid(layer && layer.widgets) })));
        const gestures = Object.assign({ next_layer: "tap", next_group: "double_tap" }, w.gestures || {});
        return Object.assign(box, { kind: "layers", cols: box.w, groups: groups, gestures: gestures });
      }
      const block = blockFor(w);
      if (!block || used.has(block)) { plan.unsupported.push(w.id); return null; }
      used.add(block);
      return Object.assign(box, { kind: "block", block: block, type: w.type });
    };
    const grid = (list) => (Array.isArray(list) ? list : []).filter((w) => w && w.type !== "accordion").map(node).filter(Boolean);
    const ordered = widgets.slice().sort((a, b) => ((a && a.y) | 0) - ((b && b.y) | 0) || ((a && a.x) | 0) - ((b && b.x) | 0));
    plan.top = grid(ordered);
    for (const w of ordered) {                                       // les accordéons vont dans la partie qui défile
      if (!w || w.type !== "accordion" || w.hidden) continue;
      plan.bottom.push({ id: w.id, sections: (Array.isArray(w.sections) ? w.sections : []).map((s) => ({
        title: String((s && s.title) || ""), open: !!(s && s.open), cols: Math.max(1, w.w | 0), items: grid(s && s.widgets) })) });
    }
    plan.blocks = Array.from(used);
    const topBlocks = new Set(plan.top.filter((n) => n.kind === "block").map((n) => n.block));
    const missing = Object.keys(LOCKED).filter((type) => !topBlocks.has(LOCKED[type]));
    if (missing.length) { plan.reason = "locked_missing"; plan.missing = missing; return plan; }
    plan.safe = true;
    if (choice.display === "centered") plan.maxWidth = MAX_WIDTH[choice.device];
    else if (choice.device !== "phone") plan.maxWidth = "none";
    return plan;
  }

  function safeText(plan) {
    if (plan.reason === "rotate") return "Tourne l'appareil : cette interface est prévue en paysage.";
    if (plan.reason === "locked_missing") return "Ce profil est incomplet (widgets de sécurité manquants) : il ne peut pas s'afficher.";
    if (plan.reason === "invalid") return "Ce profil est illisible.";
    return "Ce profil n'a pas d'interface pour un " + (DEVICE_LABELS[plan.device] || "appareil") +
      " : ajoute-la avec le designer, ou reviens à l'interface d'usine.";
  }

  // ------------------------------------------------------------------ application à la page (DOM)
  const parentOf = (n) => (n ? n.parentNode || n.parent || null : null);
  const INTERACTIVE = ["button", "input", "select", "option", "textarea", "a", "label", "summary"];
  function interactive(target) {
    if (!target) return false;
    if (typeof target.closest === "function") return !!target.closest("button,input,select,textarea,a,label,summary");
    return INTERACTIVE.includes(String(target.tagName || "").toLowerCase());
  }

  class Layout {
    constructor(doc, hooks) {
      this.doc = doc; this.hooks = hooks || {};
      this.homes = new Map();             // bloc -> repère laissé à sa place d'origine (null si l'élément n'avait pas de parent)
      this.created = [];                  // éléments fabriqués par le plan en cours
      this.offs = [];                     // blocs absents du profil, masqués sur place
      this.names = new Map();             // élément déplacé -> identifiant de bloc
      this.timers = [];
      this.active = null;                 // plan appliqué
    }

    _el(tag, className, text) {
      const e = this.doc.createElement(tag);
      if (className) e.className = className;
      if (text !== undefined) e.textContent = text;
      return e;
    }

    _move(blockId, into) {
      const block = this.doc.getElementById(blockId);
      if (!block) return null;
      if (!this.homes.has(blockId)) {
        const parent = parentOf(block);
        let mark = null;
        if (parent) { mark = this._el("span", "laymark"); mark.hidden = true; parent.insertBefore(mark, block); }
        this.homes.set(blockId, mark);
      }
      block.removeAttribute("data-lay");
      into.appendChild(block);
      this.names.set(block, blockId);
      return block;
    }

    _place(element, n) {
      element.style.gridColumn = (n.x + 1) + " / span " + n.w;
      element.style.gridRow = (n.y + 1) + " / span " + n.h;
    }

    _grid(container, items, cols) {
      container.className = (container.className ? container.className + " " : "") + "laygrid";
      container.style.gridTemplateColumns = "repeat(" + cols + ", minmax(0, 1fr))";
      for (const n of items) {
        let element = null;
        if (n.kind === "block") element = this._move(n.block, container);
        else if (n.kind === "label") element = container.appendChild(this._el("div", "laylabel", n.text));
        else if (n.kind === "separator") element = container.appendChild(this._el("div", "laysep"));
        else if (n.kind === "layers") element = container.appendChild(this._layers(n));
        if (element) this._place(element, n);
      }
    }

    _layers(n) {
      const box = this._el("div", "laylayers");
      const pages = n.groups.map((group) => group.map((layer) => {
        const page = this._el("div", "laypage");
        page.setAttribute("title", layer.title);
        this._grid(page, layer.items, n.cols);
        box.appendChild(page);
        return page;
      }));
      const dots = box.appendChild(this._el("div", "laydots"));
      const store = this.hooks.store, key = "trx.lay." + n.id;
      let saved = null;
      try { saved = store ? JSON.parse(store.get(key, "null")) : null; } catch (e) { saved = null; }
      const state = { g: 0, l: 0 };
      if (Array.isArray(saved) && pages[saved[0]] && pages[saved[0]][saved[1]]) { state.g = saved[0]; state.l = saved[1]; }
      const show = () => {
        pages.forEach((group, g) => group.forEach((page, l) => page.setAttribute("data-lay", g === state.g && l === state.l ? "on" : "off")));
        const group = pages[state.g] || [];
        dots.textContent = group.length > 1 || pages.length > 1
          ? group.map((_, l) => (l === state.l ? "●" : "○")).join(" ") + (pages.length > 1 ? "  ·  groupe " + (state.g + 1) + "/" + pages.length : "")
          : "";
        if (store) store.set(key, JSON.stringify([state.g, state.l]));
        this._shown();
      };
      const act = (gesture) => {
        if (gesture === n.gestures.next_layer && pages[state.g] && pages[state.g].length > 1) {
          state.l = (state.l + 1) % pages[state.g].length; show();
        } else if (gesture === n.gestures.next_group && pages.length > 1) {
          state.g = (state.g + 1) % pages.length; state.l = 0; show();
        }
      };
      const now = this.hooks.now || (() => Date.now());
      const later = this.hooks.setTimeout || ((fn, ms) => setTimeout(fn, ms));
      const cancel = this.hooks.clearTimeout || ((t) => clearTimeout(t));
      const severalLayers = pages.some((group) => group.length > 1), severalGroups = pages.length > 1;
      const useful = (gesture) => (n.gestures.next_layer === gesture && severalLayers) || (n.gestures.next_group === gesture && severalGroups);
      const usesDouble = useful("double_tap");                       // sinon un double appui ne compte que pour UN appui
      let lastTap = -1e9, pendingTap = null, press = null, swallowClick = false;
      box.addEventListener("pointerdown", (ev) => { press = { t: now(), x: ev.clientX || 0 }; });
      box.addEventListener("pointerup", (ev) => {
        if (!press || interactive(ev.target)) { press = null; return; }
        const dt = now() - press.t, dx = (ev.clientX || 0) - press.x;
        press = null;
        if (Math.abs(dx) >= SWIPE_PX) { swallowClick = true; act("swipe"); }
        else if (dt >= LONG_PRESS_MS) { swallowClick = true; act("long_press"); }
      });
      box.addEventListener("click", (ev) => {
        if (interactive(ev.target)) return;                         // un bouton dans un calque garde ses propres appuis
        if (swallowClick) { swallowClick = false; return; }
        if (usesDouble) {                                           // attendre de savoir si c'est un double appui
          if (pendingTap !== null) { cancel(pendingTap); pendingTap = null; act("double_tap"); return; }
          pendingTap = later(() => { pendingTap = null; act("tap"); }, DOUBLE_TAP_MS);
          this.timers.push(pendingTap);
          return;
        }
        const t = now();
        if (t - lastTap < TAP_DEBOUNCE_MS) return;                  // double appui = UN seul changement
        lastTap = t;
        act("tap");
      });
      box._layShow = show;
      return box;
    }

    // Blocs actuellement visibles (pour démarrer ou arrêter ce qui coûte : analyse du waterfall...).
    visibleBlocks() {
      const visible = new Set();
      const walk = (container) => {
        for (const child of container.children || []) {
          if (child.getAttribute && child.getAttribute("data-lay") === "off") continue;
          if (this.names.has(child)) visible.add(this.names.get(child));
          if (child.className && /\blay(grid|layers|page)\b/.test(child.className)) walk(child);
        }
      };
      for (const element of this.created) if (element.className && /\blay(grid|layers|page)\b/.test(element.className)) walk(element);
      return visible;
    }

    _shown() { if (this.hooks.onShown && this.active) this.hooks.onShown(this.visibleBlocks()); }

    // Remet la page telle qu'elle a été écrite (interface d'usine faite main).
    restore() {
      for (const t of this.timers) (this.hooks.clearTimeout || clearTimeout)(t);
      this.timers = [];
      for (const [blockId, mark] of this.homes) {
        const block = this.doc.getElementById(blockId);
        if (!block) continue;
        block.removeAttribute("data-lay");
        block.style.gridColumn = ""; block.style.gridRow = "";
        const now = parentOf(block);
        if (mark && parentOf(mark)) { parentOf(mark).insertBefore(block, mark); parentOf(mark).removeChild(mark); }
        else if (now) { now.removeChild(block); block.parent = null; }
      }
      this.homes.clear();
      this.names.clear();
      for (const element of this.offs) element.removeAttribute("data-lay");
      this.offs = [];
      for (const element of this.created) { const p = parentOf(element); if (p) p.removeChild(element); }
      this.created = [];
      const app = this.doc.getElementById("app");
      app.removeAttribute("data-layout"); app.style.maxWidth = "";
      const safe = this.doc.getElementById("safe-screen");
      if (safe) safe.hidden = true;
      this.active = null;
      if (this.hooks.onShown) this.hooks.onShown(null);           // null : disposition d'origine
    }

    apply(plan) {
      this.restore();
      const app = this.doc.getElementById("app");
      if (!plan.safe) {
        const body = this.doc.getElementById("safe-body");
        for (const id of ["status", "ptt-state", "stop", "fault"]) this._move(id, body);   // état, coupure et défaut restent accessibles
        this.doc.getElementById("safe-text").textContent = safeText(plan);
        this.doc.getElementById("safe-screen").hidden = false;
        app.setAttribute("data-layout", "safe");
        this.active = plan;
        if (this.hooks.onShown) this.hooks.onShown(new Set());
        return;
      }
      const top = this._el("div", "laytop"); top.id = "lay-top";
      const topHost = this.doc.getElementById("top");
      topHost.insertBefore(top, topHost.firstChild);
      this.created.push(top);
      this._grid(top, plan.top, plan.cols);
      const bottom = this._el("div", "laybottom"); bottom.id = "lay-bottom";
      const bottomHost = this.doc.getElementById("bottom"), connect = this.doc.getElementById("sec-connect");
      bottomHost.insertBefore(bottom, connect && parentOf(connect) === bottomHost ? connect.nextSibling || null : bottomHost.firstChild);
      this.created.push(bottom);
      for (const accordion of plan.bottom) {
        for (const section of accordion.sections) {
          const details = bottom.appendChild(this._el("details", "laysec"));
          details.open = section.open;
          details.appendChild(this._el("summary", "", section.title));
          const body = details.appendChild(this._el("div", "body"));
          this._grid(body, section.items, section.cols);
          this.created.push(body);
        }
      }
      for (const id of ALL_BLOCKS) {
        const element = plan.blocks.includes(id) ? null : this.doc.getElementById(id);
        if (element) { element.setAttribute("data-lay", "off"); this.offs.push(element); }   // absent du profil : masqué
      }
      app.setAttribute("data-layout", "profile");
      app.style.maxWidth = plan.maxWidth;
      this.active = plan;
      for (const element of this.created) this._initLayers(element);
      this._shown();
    }

    _initLayers(container) {
      for (const child of container.children || []) {
        if (child._layShow) child._layShow();
        if (child.className && /\blaygrid\b/.test(child.className)) this._initLayers(child);
      }
    }
  }

  const api = { DEVICES, ORIENTATIONS, GRID_COLUMNS, LOCKED, ALL_BLOCKS, selectVariant, detectDevice, blockFor, buildPlan, safeText, Layout };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxLayout = api; }
})(typeof window !== "undefined" ? window : globalThis);
