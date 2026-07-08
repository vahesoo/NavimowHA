/*
 * Navimow Map Card  (v6.2 — dock icon, appearance config, zoom, calibration, channels)
 *
 * A self-contained Lovelace custom card. Plots the mower's local (x,y) meter
 * coordinates with a heading arrow and the path of the CURRENT mowing session,
 * optionally over a calibrated aerial/satellite image. The session path is
 * rebuilt from Home Assistant's recorder history on load, so it survives page
 * reloads and navigation, and resets automatically when a new session starts
 * (docked -> mowing). Auto-learns the dock position via the integration's dock
 * sensors (fork v1.1.0+position.4) with a local-learning fallback for older
 * forks. No external dependencies.
 *
 * Install:
 *   1. Put this file at /config/www/navimow-map-card.js
 *   2. Add a Lovelace resource: URL /local/navimow-map-card.js?v=N, type
 *      "JavaScript Module" (bump ?v=N when you update the file)
 *   3. Add a card:  type: custom:navimow-map-card
 *
 * Config (all optional, defaults shown):
 *   type: custom:navimow-map-card
 *   title: Navimow Map
 *   x_entity: sensor.peter_griffin_position_x
 *   y_entity: sensor.peter_griffin_position_y
 *   heading_entity: sensor.peter_griffin_heading
 *   zone_entity: sensor.navimow_current_zone
 *   status_entity: lawn_mower.peter_griffin
 *   battery_entity:           # e.g. sensor.peter_griffin_battery (optional)
 *   trail_length: 2000        # max trail points kept (older points are thinned,
 *                             #   not dropped, so the whole path keeps its shape)
 *   history_hours: 24         # how far back to look for the session start
 *   dock_x_entity:            # integration dock sensors (auto-derived from
 *   dock_y_entity:            #   x_entity/y_entity names if not set)
 *   dock_x:                   # manual dock override (meters); disables auto-learn
 *   dock_y:                   #   (both must be set)
 *   dock_samples: 25          # rolling samples averaged while docked (fallback)
 *
 * Satellite / aerial overlay (optional):
 *   overlay_image: /local/yard.png    # your property image under /config/www
 *   overlay_opacity: 0.9
 *   calibration:                      # EXACTLY 2 reference points that map
 *     - m: [0.0, 0.0]                 #   mower meter coords [x, y] ...
 *       px: [512, 800]                #   ... to image pixel coords [x, y]
 *     - m: [12.4, -3.1]               # tip: point 1 = the dock (read the
 *       px: [220, 410]                #   dock_x/dock_y sensors); point 2 = any
 *                                     #   landmark you can park the mower at
 *
 * Dock marker priority: dock_x/dock_y config > integration dock sensors >
 * locally learned average while docked (localStorage) > origin (0,0).
 */
class NavimowMapCard extends HTMLElement {
  setConfig(config) {
    this._config = Object.assign({
      title: 'Navimow Map',
      x_entity: 'sensor.peter_griffin_position_x',
      y_entity: 'sensor.peter_griffin_position_y',
      heading_entity: 'sensor.peter_griffin_heading',
      zone_entity: 'sensor.navimow_current_zone',
      status_entity: 'lawn_mower.peter_griffin',
      battery_entity: null,
      trail_length: 2000,
      history_hours: 24,
      session_count: 6,
      show_controls: true,
      zone_names: {},
      enable_zoom: true,
      channel_entities: [],
      channel_fill: 'rgba(244, 67, 54, 0.35)',
      channel_stroke: 'rgba(244, 67, 54, 0.80)',
      calibration_mode: false,
      trails: {
        active: {
          color: 'var(--primary-color)',
          opacity: 0.70,
          width: 5.2,
        },
        previous: {
          color: 'var(--secondary-text-color)',
          width: 5.2,
          opacity: {
            first: 0.46,
            last: 0.12,
          },
        },
        fade_mode: 'linear',
      },
      appearance: {
        trails: null,
        channel: {
          fill: 'rgba(244, 67, 54, 0.35)',
          stroke: 'rgba(244, 67, 54, 0.80)',
          width: 2.5,
        },
        robot: {
          scale: 1.0,
        },
        dock: {
          scale: 1.0,
          icon: 'mdi:lightning-bolt-circle',
        },
      },
      dock_x_entity: null,
      dock_y_entity: null,
      dock_x: null,
      dock_y: null,
      dock_samples: 25,
      overlay_image: null,
      overlay_opacity: 0.9,
      calibration: null,
      straighten: true,   // draw the image upright (rotate the trail instead);
                          // set false to keep the mower's coordinate frame
    }, config || {});
    // derive dock sensor names from the position sensors if not configured
    if (!this._config.dock_x_entity && /position_x/.test(this._config.x_entity))
      this._config.dock_x_entity = this._config.x_entity.replace('position_x', 'dock_x');
    if (!this._config.dock_y_entity && /position_y/.test(this._config.y_entity))
      this._config.dock_y_entity = this._config.y_entity.replace('position_y', 'dock_y');
    this._trail = [];
    this._sessions = [];
    this._lastKey = null;
    this._prevState = null;
    this._histLoaded = false;
    this._imgMeta = null;       // {w, h} once the overlay image loads
    this._imgLoading = false;
    this._cal = this._solveCalibration(this._config.calibration);
    this._zoom = { scale: 1, cx: 500, cy: 500 };
    this._pointers = new Map();
    this._panStart = null;
    this._pinchStart = null;
    this._calibrationClicks = [];
    this._lastDraw = null;
    this._dock = null;          // learned [x, y], meters (localStorage fallback)
    this._dockBuf = [];         // rolling samples while docked
    this._dockKey = 'navimow-map-card-dock:' + this._config.x_entity;
    try {
      const v = JSON.parse(localStorage.getItem(this._dockKey));
      if (Array.isArray(v) && isFinite(v[0]) && isFinite(v[1])) this._dock = v;
    } catch (e) { /* storage unavailable — auto-learn still works per-session */ }
    this.innerHTML = `
      <ha-card>
        <div class="nm-hdr"></div>
        <div class="nm-wrap">
          <svg class="nm-map" preserveAspectRatio="xMidYMid meet"></svg>
          <svg class="nm-mwr" preserveAspectRatio="xMidYMid meet"></svg>
        </div>
        <div class="nm-ftr"></div>
        <div class="nm-cal"></div>
        <div class="nm-controls">
          <button type="button" class="nm-btn nm-start" data-action="mow">Mow</button>
          <button type="button" class="nm-btn nm-pause" data-action="pause">Pause</button>
          <button type="button" class="nm-btn nm-dock" data-action="dock">Dock</button>
        </div>
      </ha-card>
      <style>
        ha-card { padding: 12px; }
        .nm-hdr { font-weight: 600; margin-bottom: 6px; }
        .nm-wrap { position: relative; width: 100%; aspect-ratio: 1 / 1;
          background: var(--secondary-background-color); border-radius: 8px; overflow: hidden; touch-action: none; cursor: grab; }
        .nm-wrap:active { cursor: grabbing; }
        svg.nm-map { position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: block; }
        svg.nm-mwr { position: absolute; top: 0; left: 0; width: 100%; height: 100%;
          display: block; pointer-events: none; }
        .nm-mwr-grp { transition: transform 1.8s linear; }
        .nm-ftr { margin-top: 8px; font-size: 0.9em; color: var(--secondary-text-color);
          display: flex; gap: 14px; flex-wrap: wrap; }
        .nm-ftr b { color: var(--primary-text-color); }
        .nm-cal { display: none; margin-top: 8px; padding: 8px; border-radius: 8px;
          background: var(--secondary-background-color); font-size: 0.85em; }
        .nm-cal pre { white-space: pre-wrap; margin: 6px 0 0; font-family: monospace; }
        .nm-cal button { margin-top: 6px; border: none; border-radius: 8px; padding: 7px 10px;
          font-weight: 700; cursor: pointer; background: var(--primary-color); color: var(--text-primary-color); }
        .nm-controls { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }
        .nm-btn { border: none; border-radius: 12px; padding: 11px 8px; font-weight: 700;
          color: white; cursor: pointer; font-family: inherit; font-size: 13px;
          transition: transform 0.12s ease, filter 0.12s ease; }
        .nm-btn:active { transform: scale(0.96); }
        .nm-btn:hover { filter: brightness(1.08); }
        .nm-start { background: linear-gradient(145deg,#1b5e20,#2e7d32); }
        .nm-pause { background: linear-gradient(145deg,#bf360c,#e64a19); }
        .nm-dock { background: linear-gradient(145deg,#0d47a1,#1565c0); }
      </style>`;
    this._bindControls();
    this._bindGestures();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._histLoaded && hass) {
      this._histLoaded = true;
      this._loadSessionHistory();
    }
    this._update();
  }

  // Solve a 2-point similarity transform (scale+rotation+translation) from
  // image pixels (y down) to mower meters (y up), via complex arithmetic.
  // Returns {ar, ai, br, bi} such that:
  //   mx = ar*px + ai*py + br ;  my = ai*px - ar*py + bi
  _solveCalibration(cal) {
    if (!Array.isArray(cal) || cal.length !== 2) return null;
    const ok = p => p && Array.isArray(p.m) && Array.isArray(p.px) &&
      p.m.length === 2 && p.px.length === 2 && p.m.concat(p.px).every(isFinite);
    if (!ok(cal[0]) || !ok(cal[1])) return null;
    // q = pixel with y flipped (image y-down -> math y-up)
    const q1 = { r: cal[0].px[0], i: -cal[0].px[1] };
    const q2 = { r: cal[1].px[0], i: -cal[1].px[1] };
    const m1 = { r: cal[0].m[0], i: cal[0].m[1] };
    const m2 = { r: cal[1].m[0], i: cal[1].m[1] };
    const dq = { r: q2.r - q1.r, i: q2.i - q1.i };
    const dm = { r: m2.r - m1.r, i: m2.i - m1.i };
    const den = dq.r * dq.r + dq.i * dq.i;
    if (den < 1e-9) return null; // identical pixel points
    // a = dm / dq  (complex division)
    const ar = (dm.r * dq.r + dm.i * dq.i) / den;
    const ai = (dm.i * dq.r - dm.r * dq.i) / den;
    // b = m1 - a*q1
    const br = m1.r - (ar * q1.r - ai * q1.i);
    const bi = m1.i - (ai * q1.r + ar * q1.i);
    return { ar, ai, br, bi };
  }

  // image pixel -> meters using the solved calibration
  _pxToM(px, py) {
    const c = this._cal;
    return [c.ar * px + c.ai * py + c.br, c.ai * px - c.ar * py + c.bi];
  }

  // meters -> image pixel (inverse calibration): q = (m - b) / a
  _mToPx(mx, my) {
    const c = this._cal;
    const wr = mx - c.br, wi = my - c.bi;
    const den = c.ar * c.ar + c.ai * c.ai;
    const qr = (wr * c.ar + wi * c.ai) / den;
    const qi = (wi * c.ar - wr * c.ai) / den;
    return [qr, -qi]; // flip back to image y-down
  }



  _updateCalibrationUi() {
    const el = this.querySelector('.nm-cal');
    if (!el) return;
    if (!this._config.calibration_mode) {
      el.style.display = 'none';
      el.innerHTML = '';
      return;
    }

    el.style.display = 'block';
    const clicks = this._calibrationClicks || [];
    const yaml = clicks.length === 2
      ? `calibration:\n  - m: [${clicks[0].m[0].toFixed(3)}, ${clicks[0].m[1].toFixed(3)}]\n    px: [${Math.round(clicks[0].px[0])}, ${Math.round(clicks[0].px[1])}]\n  - m: [${clicks[1].m[0].toFixed(3)}, ${clicks[1].m[1].toFixed(3)}]\n    px: [${Math.round(clicks[1].px[0])}, ${Math.round(clicks[1].px[1])}]`
      : '';

    el.innerHTML = `
      <b>Calibration mode</b><br>
      Click two known points on the map image. At each click, the card stores the clicked image pixel and the mower's current RTK X/Y position.<br>
      Points selected: <b>${clicks.length}/2</b>
      ${clicks.map((p, i) => `<br>Point ${i + 1}: m=[${p.m[0].toFixed(3)}, ${p.m[1].toFixed(3)}], px=[${Math.round(p.px[0])}, ${Math.round(p.px[1])}]`).join('')}
      ${yaml ? `<pre>${yaml}</pre><button type="button" class="nm-reset-cal">Reset points</button>` : `<br><button type="button" class="nm-reset-cal">Reset points</button>`}
    `;
    const reset = el.querySelector('.nm-reset-cal');
    if (reset) {
      reset.onclick = () => {
        this._calibrationClicks = [];
        this._updateCalibrationUi();
        this._update();
      };
    }
  }

  _screenToWorld(clientX, clientY) {
    const [sx, sy] = this._screenToSvgPoint(clientX, clientY);
    const d = this._lastDraw;
    if (!d) return null;
    const wx = d.x0 + sx / d.k;
    const wy = d.upright ? (d.y0 + sy / d.k) : (d.y0 + (d.V - sy) / d.k);
    return [wx, wy];
  }

  _handleCalibrationClick(e) {
    if (!this._config.calibration_mode || !this._lastDraw || !this._lastDraw.overlayReady) return false;
    const x = this._num(this._config.x_entity);
    const y = this._num(this._config.y_entity);
    if (x === null || y === null) return false;

    const world = this._screenToWorld(e.clientX, e.clientY);
    if (!world) return false;

    let px = world;
    if (!this._lastDraw.upright) {
      // In mower-frame view, click world coordinates are mower meters; convert to image pixels.
      if (!this._cal) return false;
      px = this._mToPx(world[0], world[1]);
    }

    this._calibrationClicks.push({ m: [x, y], px });
    this._calibrationClicks = this._calibrationClicks.slice(-2);
    this._updateCalibrationUi();
    this._update();
    return true;
  }

  _channelBoxes() {
    const c = this._config;
    const entities = Array.isArray(c.channel_entities) ? c.channel_entities : (c.channel_entity ? [c.channel_entity] : []);
    if (!this._hass || !entities.length) return [];
    const boxes = [];
    for (const entity of entities) {
      const st = this._hass.states[entity];
      if (!st || !st.attributes) continue;
      const a = st.attributes;
      const x1 = parseFloat(a.x_min), x2 = parseFloat(a.x_max);
      const y1 = parseFloat(a.y_min), y2 = parseFloat(a.y_max);
      if ([x1, x2, y1, y2].some(v => isNaN(v))) continue;
      boxes.push({ entity, name: a.channel_name || entity, x_min: Math.min(x1, x2), x_max: Math.max(x1, x2), y_min: Math.min(y1, y2), y_max: Math.max(y1, y2) });
    }
    return boxes;
  }

  _applyViewBox() {
    const svg = this.querySelector('svg.nm-map');
    const mwrSvg = this.querySelector('svg.nm-mwr');
    if (!svg || !mwrSvg) return;
    const V = 1000;
    const scale = Math.max(1, Math.min(12, this._zoom?.scale || 1));
    const size = V / scale, half = size / 2;
    let cx = this._zoom?.cx ?? 500, cy = this._zoom?.cy ?? 500;
    cx = Math.max(half, Math.min(V - half, cx));
    cy = Math.max(half, Math.min(V - half, cy));
    this._zoom = { scale, cx, cy };
    const vb = `${(cx - half).toFixed(2)} ${(cy - half).toFixed(2)} ${size.toFixed(2)} ${size.toFixed(2)}`;
    svg.setAttribute('viewBox', vb);
    mwrSvg.setAttribute('viewBox', vb);
  }

  _screenToSvgPoint(clientX, clientY) {
    const wrap = this.querySelector('.nm-wrap');
    if (!wrap) return [500, 500];
    const rect = wrap.getBoundingClientRect();
    const V = 1000;
    const scale = Math.max(1, Math.min(12, this._zoom?.scale || 1));
    const size = V / scale, half = size / 2;
    const left = (this._zoom?.cx ?? 500) - half;
    const top = (this._zoom?.cy ?? 500) - half;
    const rx = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const ry = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    return [left + rx * size, top + ry * size];
  }

  _zoomAt(factor, clientX, clientY) {
    if (!this._config.enable_zoom) return;
    const wrap = this.querySelector('.nm-wrap');
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();
    const V = 1000;
    const oldScale = Math.max(1, Math.min(12, this._zoom?.scale || 1));
    const oldSize = V / oldScale;
    const [sx, sy] = this._screenToSvgPoint(clientX, clientY);
    const newScale = Math.max(1, Math.min(12, oldScale * factor));
    const newSize = V / newScale;
    const rx = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const ry = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    this._zoom = { scale: newScale, cx: sx - rx * newSize + newSize / 2, cy: sy - ry * newSize + newSize / 2 };
    this._applyViewBox();
  }

  _bindGestures() {
    if (!this._config || !this._config.enable_zoom) return;
    const wrap = this.querySelector('.nm-wrap');
    if (!wrap || wrap._nmZoomBound) return;
    wrap._nmZoomBound = true;
    wrap.addEventListener('wheel', e => {
      e.preventDefault();
      this._zoomAt(e.deltaY < 0 ? 1.18 : 1 / 1.18, e.clientX, e.clientY);
    }, { passive: false });
    wrap.addEventListener('dblclick', e => {
      e.preventDefault();
      this._zoom = { scale: 1, cx: 500, cy: 500 };
      this._applyViewBox();
    });
    wrap.addEventListener('pointerdown', e => {
      if (this._config.calibration_mode && this._handleCalibrationClick(e)) {
        e.preventDefault();
        return;
      }
      wrap.setPointerCapture(e.pointerId);
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (this._pointers.size === 1) this._panStart = { x: e.clientX, y: e.clientY, cx: this._zoom.cx, cy: this._zoom.cy, scale: this._zoom.scale };
      if (this._pointers.size === 2) {
        const pts = Array.from(this._pointers.values());
        this._pinchStart = { dist: Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y) || 1, scale: this._zoom.scale, cx: this._zoom.cx, cy: this._zoom.cy };
      }
    });
    wrap.addEventListener('pointermove', e => {
      if (!this._pointers.has(e.pointerId)) return;
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const rect = wrap.getBoundingClientRect(), V = 1000;
      if (this._pointers.size === 1 && this._panStart && this._zoom.scale > 1) {
        const size = V / this._panStart.scale;
        this._zoom = { scale: this._panStart.scale, cx: this._panStart.cx - (e.clientX - this._panStart.x) / rect.width * size, cy: this._panStart.cy - (e.clientY - this._panStart.y) / rect.height * size };
        this._applyViewBox();
      } else if (this._pointers.size === 2 && this._pinchStart) {
        const pts = Array.from(this._pointers.values());
        const dist = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y) || 1;
        const midX = (pts[0].x + pts[1].x) / 2, midY = (pts[0].y + pts[1].y) / 2;
        this._zoom = { scale: this._pinchStart.scale, cx: this._pinchStart.cx, cy: this._pinchStart.cy };
        this._zoomAt(dist / this._pinchStart.dist, midX, midY);
      }
    });
    const end = e => {
      this._pointers.delete(e.pointerId);
      this._panStart = null; this._pinchStart = null;
      if (this._pointers.size === 1) {
        const pt = Array.from(this._pointers.values())[0];
        this._panStart = { x: pt.x, y: pt.y, cx: this._zoom.cx, cy: this._zoom.cy, scale: this._zoom.scale };
      }
    };
    wrap.addEventListener('pointerup', end);
    wrap.addEventListener('pointercancel', end);
    wrap.addEventListener('pointerleave', end);
  }

  _num(entity) {
    if (!entity || !this._hass) return null;
    const s = this._hass.states[entity];
    if (!s) return null;
    const v = parseFloat(s.state);
    return isNaN(v) ? null : v;
  }

  // Evenly thin the trail to the cap so long sessions keep their full shape
  // (always keeps the final point).
  _decimate(pts, cap) {
    let out = pts;
    while (out.length > cap) {
      const last = out[out.length - 1];
      out = out.filter((_, i) => i % 2 === 0);
      if (out[out.length - 1] !== last) out.push(last);
    }
    return out;
  }




  _appearanceConfig() {
    const a = this._config.appearance || {};
    const channel = a.channel || {};
    const robot = a.robot || {};
    const dock = a.dock || {};
    return {
      channel: {
        fill: channel.fill || this._config.channel_fill || 'rgba(244, 67, 54, 0.35)',
        stroke: channel.stroke || this._config.channel_stroke || 'rgba(244, 67, 54, 0.80)',
        width: Number.isFinite(Number(channel.width)) ? Number(channel.width) : 2.5,
      },
      robot: {
        scale: Number.isFinite(Number(robot.scale)) ? Number(robot.scale) : 1.0,
      },
      dock: {
        scale: Number.isFinite(Number(dock.scale)) ? Number(dock.scale) : 1.0,
        icon: dock.icon || 'mdi:lightning-bolt-circle',
      },
      trails: a.trails || this._config.trails || {},
    };
  }

  _trailConfig() {
    const t = this._appearanceConfig().trails || {};
    const active = t.active || {};
    const previous = t.previous || {};
    const prevOpacity = previous.opacity || {};
    return {
      active: {
        color: active.color || 'var(--primary-color)',
        opacity: Number.isFinite(Number(active.opacity)) ? Number(active.opacity) : 0.70,
        width: Number.isFinite(Number(active.width)) ? Number(active.width) : 5.2,
      },
      previous: {
        color: previous.color || 'var(--secondary-text-color)',
        width: Number.isFinite(Number(previous.width)) ? Number(previous.width) : 5.2,
        opacityFirst: Number.isFinite(Number(prevOpacity.first)) ? Number(prevOpacity.first) : 0.46,
        opacityLast: Number.isFinite(Number(prevOpacity.last)) ? Number(prevOpacity.last) : 0.12,
      },
      fadeMode: (t.fade_mode || 'linear').toString().toLowerCase(),
    };
  }

  _historyTrailOpacity(ageFromNewest, historyCount, cfg) {
    if (historyCount <= 1) return cfg.previous.opacityFirst;
    const first = cfg.previous.opacityFirst;
    const last = cfg.previous.opacityLast;
    const t = Math.max(0, Math.min(1, (historyCount - 1 - ageFromNewest) / (historyCount - 1)));

    if (cfg.fadeMode === 'exponential') {
      const curved = Math.pow(t, 2.2);
      return last + (first - last) * curved;
    }

    return last + (first - last) * t;
  }

  _zoneName(zone) {
    const names = this._config.zone_names || {};
    if (zone === null || zone === undefined || zone === 'unknown' || zone === 'unavailable') return '—';
    return names[String(zone)] || zone;
  }

  _startNewSession() {
    if (this._trail && this._trail.length) {
      this._sessions.push({ points: this._trail });
      this._sessions = this._sessions.slice(-Math.max(0, this._config.session_count - 1));
    }
    this._trail = [];
    this._lastKey = null;
  }

  _bindControls() {
    if (!this._config || !this._config.show_controls) return;
    const controls = this.querySelector('.nm-controls');
    if (!controls || controls._bound) return;
    controls._bound = true;
    controls.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-action]');
      if (!btn || !this._hass) return;
      const entity_id = this._config.status_entity;
      const action = btn.dataset.action;
      if (action === 'mow') this._hass.callService('lawn_mower', 'start_mowing', { entity_id });
      if (action === 'pause') this._hass.callService('lawn_mower', 'pause', { entity_id });
      if (action === 'dock') this._hass.callService('lawn_mower', 'dock', { entity_id });
    });
  }

  // Rebuild recent session paths from HA's recorder.
  async _loadSessionHistory() {
    const c = this._config, hass = this._hass;
    try {
      const end = new Date();
      const start = new Date(Date.now() - c.history_hours * 3600e3);
      const r = await hass.callWS({
        type: 'history/history_during_period',
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        entity_ids: [c.status_entity, c.x_entity, c.y_entity],
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      const st = (r && r[c.status_entity]) || [];
      const xs = (r && r[c.x_entity]) || [];
      const ys = (r && r[c.y_entity]) || [];

      let starts = [];
      for (let i = 1; i < st.length; i++) {
        if (st[i].s === 'mowing' && st[i - 1].s === 'docked') starts.push(st[i].lu);
      }
      if (!starts.length) return;
      starts = starts.slice(-Math.max(1, c.session_count));

      const allPts = [];
      let yi = 0, lastY = null;
      for (const ex of xs) {
        const x = parseFloat(ex.s);
        while (yi < ys.length && ys[yi].lu <= ex.lu) {
          const v = parseFloat(ys[yi].s);
          if (!isNaN(v)) lastY = v;
          yi++;
        }
        if (!isNaN(x) && lastY !== null) allPts.push({ t: ex.lu, p: [x, lastY] });
      }

      const sessions = [];
      for (let i = 0; i < starts.length; i++) {
        const t0 = starts[i];
        const t1 = starts[i + 1] || Number.POSITIVE_INFINITY;
        let pts = allPts.filter(o => o.t >= t0 && o.t < t1).map(o => o.p);
        if (pts.length) sessions.push({ points: this._decimate(pts, c.trail_length), start: t0 });
      }

      if (sessions.length) {
        const newest = sessions[sessions.length - 1];
        this._sessions = sessions.slice(0, -1).slice(-Math.max(0, c.session_count - 1));
        this._trail = this._decimate(newest.points.concat(this._trail), c.trail_length);
        this._lastKey = null;
        this._update();
      }
    } catch (e) {
      // recorder disabled or entities excluded -> live-only trail
    }
  }

  _update() {
    if (!this._hass || !this._config) return;
    const c = this._config;
    const controls = this.querySelector('.nm-controls');
    if (controls) controls.style.display = c.show_controls ? 'grid' : 'none';
    this._updateCalibrationUi();
    const x = this._num(c.x_entity);
    const y = this._num(c.y_entity);
    const headingDeg = this._num(c.heading_entity);
    const rawZone = this._hass.states[c.zone_entity] ? this._hass.states[c.zone_entity].state : '—';
    const zone = this._zoneName(rawZone);
    const stObj = this._hass.states[c.status_entity];
    const status = stObj ? stObj.state : '—';

    let translatedStatus = status;

    if (stObj && this._hass.localize) {
      const domain = c.status_entity.split('.')[0];

      // Try the primary core domain path, then the entity_component fallback, then default to original status
      translatedStatus = this._hass.localize(`component.${domain}.state._.${status}`) ||
          this._hass.localize(`component.${domain}.entity_component._.state.${status}`) ||
          status;
    }

    // Raw mower status for dock learning. The lawn_mower entity STATE maps
    // 'idle' to 'docked' (activity), so a mower stopped mid-lawn would look
    // docked and poison the dock estimate — prefer the raw 'status' attribute.
    const rawStatus = stObj ? ((stObj.attributes && stObj.attributes.status) || stObj.state) : '';
    const batt = c.battery_entity ? this._num(c.battery_entity) : null;

    // new mowing session (docked -> mowing) -> reset the path
    if (this._prevState === 'docked' && status === 'mowing') {
      this._startNewSession();
    }
    this._prevState = status;

    if (x !== null && y !== null) {
      const key = x.toFixed(3) + ',' + y.toFixed(3);
      if (key !== this._lastKey) {
        this._trail.push([x, y]);
        this._lastKey = key;
        if (this._trail.length > c.trail_length)
          this._trail = this._decimate(this._trail, c.trail_length);
      }
    }

    // integration dock sensors (server-side learned, persisted in HA)
    const sensorDockX = this._num(c.dock_x_entity);
    const sensorDockY = this._num(c.dock_y_entity);
    const haveSensorDock = sensorDockX !== null && sensorDockY !== null;

    // local auto-learn fallback: average position while docked/charging
    // (skipped when the integration provides dock sensors)
    if (!haveSensorDock && (c.dock_x === null || c.dock_y === null)) {
      const docked = /^(docked|charging)$/i.test(rawStatus);
      if (docked && x !== null && y !== null) {
        this._dockBuf.push([x, y]);
        if (this._dockBuf.length > c.dock_samples) this._dockBuf.shift();
        const n = this._dockBuf.length;
        this._dock = [
          this._dockBuf.reduce((a, p) => a + p[0], 0) / n,
          this._dockBuf.reduce((a, p) => a + p[1], 0) / n,
        ];
        try { localStorage.setItem(this._dockKey, JSON.stringify(this._dock)); } catch (e) {}
      } else if (!docked && this._dockBuf.length) {
        this._dockBuf = [];
      }
    }

    this.querySelector('.nm-hdr').textContent = c.title;
    const parts = [
      `Zone: <b>${zone}</b>`,
      `Status: <b>${translatedStatus}</b>`,
      (x !== null && y !== null) ? `Pos: <b>${x.toFixed(1)}, ${y.toFixed(1)} m</b>` : `Pos: <b>—</b>`,
    ];
    if (batt !== null) parts.push(`Battery: <b>${batt}%</b>`);
    this.querySelector('.nm-ftr').innerHTML = parts.join('');

    const dock = (c.dock_x !== null && c.dock_y !== null)
      ? [c.dock_x, c.dock_y]
      : haveSensorDock
        ? [sensorDockX, sensorDockY]
        : (this._dock || [0, 0]);
    this._draw(x, y, headingDeg, dock);
  }

  _draw(x, y, headingDeg, dock) {
    const svg = this.querySelector('svg.nm-map');
    const mwrSvg = this.querySelector('svg.nm-mwr');
    const c = this._config;
    const pts = this._trail;
    const V = 1000;

    // lazy-load the overlay image to learn its pixel size
    if (c.overlay_image && this._cal && !this._imgMeta && !this._imgLoading) {
      this._imgLoading = true;
      const im = new Image();
      im.onload = () => {
        this._imgMeta = { w: im.naturalWidth, h: im.naturalHeight };
        this._update();
      };
      im.onerror = () => { this._imgLoading = false; };
      im.src = c.overlay_image;
    }
    const overlayReady = !!(this._imgMeta && this._cal);

    if (!overlayReady && pts.length === 0 && (x === null || y === null)) {
      this._applyViewBox();
      svg.innerHTML = `<text x="${V/2}" y="${V/2}" fill="var(--secondary-text-color)" font-size="34" text-anchor="middle">Waiting for position…</text>`;
      return;
    }

    // Working space: with an overlay (and straighten on, the default) we draw
    // in IMAGE PIXEL space so the image stays upright and the trail rotates;
    // otherwise in mower meter space (y up).
    const upright = overlayReady && c.straighten !== false;
    const M2W = upright ? ((mx, my) => this._mToPx(mx, my)) : ((mx, my) => [mx, my]);

    // view extents: trail + dock + live pos (+ image corners when present)
    const historyPts = (this._sessions || []).flatMap(sess => sess.points || []);
    const allTrailPts = historyPts.concat(pts);
    const channelBoxes = this._channelBoxes();
    const channelCorners = [];
    for (const b of channelBoxes) channelCorners.push([b.x_min, b.y_min], [b.x_min, b.y_max], [b.x_max, b.y_min], [b.x_max, b.y_max]);
    const wpts = pts.map(p => M2W(p[0], p[1]));
    const wallpts = allTrailPts.concat(channelCorners).map(p => M2W(p[0], p[1]));
    const wdock = M2W(dock[0], dock[1]);
    const xs = wallpts.map(p => p[0]).concat([wdock[0]]);
    const ys = wallpts.map(p => p[1]).concat([wdock[1]]);
    let wpos = null;
    if (x !== null && y !== null) {
      wpos = M2W(x, y);
      xs.push(wpos[0]); ys.push(wpos[1]);
    }
    if (overlayReady) {
      const { w, h } = this._imgMeta;
      for (const [ix, iy] of [[0, 0], [w, 0], [0, h], [w, h]]) {
        const p = upright ? [ix, iy] : this._pxToM(ix, iy);
        xs.push(p[0]); ys.push(p[1]);
      }
    }
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
    let size = Math.max(maxX - minX, maxY - minY, upright ? 50 : 2);
    size += size * (overlayReady ? 0.04 : 0.24); // padding
    const x0 = cx - size / 2, y0 = cy - size / 2;
    const k = V / size;
    const tx = wx => (wx - x0) * k;
    // image pixel y already points down; meter y points up and needs the flip
    const ty = upright ? (wy => (wy - y0) * k) : (wy => V - (wy - y0) * k);
    this._lastDraw = { x0, y0, k, V, upright, overlayReady };
    this._applyViewBox();

    let s = '';
    if (overlayReady && upright) {
      // axis-aligned image
      const { w, h } = this._imgMeta;
      s += `<image href="${c.overlay_image}" x="${tx(0).toFixed(1)}" y="${ty(0).toFixed(1)}"
              width="${(w * k).toFixed(1)}" height="${(h * k).toFixed(1)}"
              opacity="${c.overlay_opacity}" preserveAspectRatio="none"/>`;
    } else if (overlayReady) {
      // mower-frame view: compose pixel->meter (calibration) with meter->screen
      const { ar, ai, br, bi } = this._cal;
      const A = k * ar, B = -k * ai, C = k * ai, D = k * ar;
      const E = k * (br - x0), F = V - k * (bi - y0);
      s += `<image href="${c.overlay_image}" width="${this._imgMeta.w}" height="${this._imgMeta.h}"
              transform="matrix(${A} ${B} ${C} ${D} ${E} ${F})"
              opacity="${c.overlay_opacity}" preserveAspectRatio="none"/>`;
    }
    // Configured channel boxes from integration binary_sensor attributes.
    // Drawn below mower trails, above the optional overlay image.
    const appearance = this._appearanceConfig();
    for (const box of channelBoxes) {
      const p1 = M2W(box.x_min, box.y_min);
      const p2 = M2W(box.x_max, box.y_min);
      const p3 = M2W(box.x_max, box.y_max);
      const p4 = M2W(box.x_min, box.y_max);
      const d = `M${tx(p1[0]).toFixed(1)} ${ty(p1[1]).toFixed(1)} ` +
                `L${tx(p2[0]).toFixed(1)} ${ty(p2[1]).toFixed(1)} ` +
                `L${tx(p3[0]).toFixed(1)} ${ty(p3[1]).toFixed(1)} ` +
                `L${tx(p4[0]).toFixed(1)} ${ty(p4[1]).toFixed(1)} Z`;
      s += `<path d="${d}" fill="${appearance.channel.fill}" stroke="${appearance.channel.stroke}" stroke-width="${appearance.channel.width}" stroke-opacity="0.95"/>`;
    }

    // Calibration click markers.
    if (c.calibration_mode && this._calibrationClicks && this._calibrationClicks.length) {
      this._calibrationClicks.forEach((pt, i) => {
        let wp;
        if (upright) {
          wp = pt.px;
        } else {
          wp = this._pxToM(pt.px[0], pt.px[1]);
        }
        s += `<g transform="translate(${tx(wp[0]).toFixed(1)},${ty(wp[1]).toFixed(1)})">
                <circle r="12" fill="rgba(255,0,0,0.85)" stroke="white" stroke-width="3"/>
                <text x="18" y="8" font-size="28" fill="white" style="paint-order:stroke" stroke="rgba(0,0,0,0.8)" stroke-width="5">${i + 1}</text>
              </g>`;
      });
    }

    // Draw older sessions first, newest/current last so it stays on top.
    const trailCfg = this._trailConfig();
    const allSessions = (this._sessions || []).concat([{ points: pts, current: true }]);
    const drawSessions = allSessions.filter(sess => sess.points && sess.points.length > 1);
    const historyCount = Math.max(0, drawSessions.length - 1);
    drawSessions.forEach((sess, idx) => {
      const sp = sess.points.map(p => M2W(p[0], p[1]));
      const d = sp.map((p, i) => `${i === 0 ? 'M' : 'L'}${tx(p[0]).toFixed(1)} ${ty(p[1]).toFixed(1)}`).join(' ');
      const isCurrent = idx === drawSessions.length - 1;
      const ageFromNewest = drawSessions.length - 1 - idx;
      const opacity = isCurrent
        ? trailCfg.active.opacity
        : this._historyTrailOpacity(ageFromNewest, historyCount, trailCfg);
      const stroke = isCurrent ? trailCfg.active.color : trailCfg.previous.color;
      const width = isCurrent ? trailCfg.active.width : trailCfg.previous.width;
      s += `<path d="${d}" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-opacity="${Math.max(0, Math.min(1, opacity)).toFixed(2)}" stroke-linejoin="round" stroke-linecap="round"/>`;
    });
    // dock marker (configured > auto-learned > origin fallback)
    const dockScale = Math.max(0.2, appearance.dock.scale || 1);
    const dockIconSize = 28 * dockScale;
    const dockIconColor = overlayReady ? 'white' : 'var(--secondary-text-color)';
    s += `<g transform="translate(${tx(wdock[0]).toFixed(1)},${ty(wdock[1]).toFixed(1)})">
            <circle r="${(10 * dockScale).toFixed(1)}" fill="none" stroke="${dockIconColor}" stroke-width="3"/>
            <foreignObject x="${(-dockIconSize / 2).toFixed(1)}" y="${(-44 * dockScale).toFixed(1)}"
              width="${dockIconSize.toFixed(1)}" height="${dockIconSize.toFixed(1)}">
              <ha-icon icon="${appearance.dock.icon}" style="width:${dockIconSize.toFixed(1)}px;height:${dockIconSize.toFixed(1)}px;color:${dockIconColor};filter:${overlayReady ? 'drop-shadow(0 0 3px rgba(0,0,0,0.85))' : 'none'};"></ha-icon>
            </foreignObject>
          </g>`;
    svg.innerHTML = s;

    // Mower marker lives in the persistent overlay SVG so CSS transition survives
    // the main SVG's innerHTML rebuild. The group's transform is transitioned
    // (1.8s linear, matching the ~2s MQTT position interval) for smooth movement.
    if (wpos !== null) {
      const px = tx(wpos[0]), py = ty(wpos[1]);

      // Build mower icon content.
      // The SVG file should be placed at /config/www/Navimow_top_low.svg.
      // It is drawn with the mower nose facing up. We rotate it to match heading.
      let mwrInner = '';
      let iconRot = 0;
      if (headingDeg !== null) {
        const rad = headingDeg * Math.PI / 180;
        let ux = Math.cos(rad), uy = -Math.sin(rad);
        if (upright) {
          const { ar, ai } = this._cal;
          const den = ar * ar + ai * ai;
          const dpr = (Math.cos(rad) * ar + Math.sin(rad) * ai) / den;
          const dpi = (Math.sin(rad) * ar - Math.cos(rad) * ai) / den;
          const n = Math.hypot(dpr, dpi) || 1;
          ux = dpr / n; uy = -dpi / n;
        }
        iconRot = Math.atan2(ux, -uy) * 180 / Math.PI;
      }
      const robotScale = Math.max(0.2, appearance.robot.scale || 1);
      const robotW = 44 * robotScale;
      const robotH = 60 * robotScale;
      mwrInner += `
        <g transform="rotate(${iconRot.toFixed(1)})">
          <image
            href="/local/Navimow_top_low.svg"
            x="${(-robotW / 2).toFixed(1)}"
            y="${(-robotH / 2).toFixed(1)}"
            width="${robotW.toFixed(1)}"
            height="${robotH.toFixed(1)}"
            preserveAspectRatio="xMidYMid meet"
          />
        </g>`;

      let grp = mwrSvg.querySelector('.nm-mwr-grp');
      if (!grp) {
        // First appearance: create element and set position instantly (no animation)
        grp = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        grp.setAttribute('class', 'nm-mwr-grp');
        mwrSvg.appendChild(grp);
        grp.style.transition = 'none';
        grp.style.transform = `translate(${px.toFixed(1)}px, ${py.toFixed(1)}px)`;
        // Re-enable transition after layout so the NEXT update animates
        requestAnimationFrame(() => requestAnimationFrame(() => { grp.style.transition = ''; }));
      } else {
        grp.style.transform = `translate(${px.toFixed(1)}px, ${py.toFixed(1)}px)`;
      }
      grp.innerHTML = mwrInner;
    } else {
      // No position — remove the marker
      const grp = mwrSvg.querySelector('.nm-mwr-grp');
      if (grp) grp.remove();
    }
  }

  getCardSize() { return 6; }
}

customElements.define('navimow-map-card', NavimowMapCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'navimow-map-card',
  name: 'Navimow Map',
  description: 'Live Navimow position + session path, zoom, channels, and optional satellite overlay.',
});
