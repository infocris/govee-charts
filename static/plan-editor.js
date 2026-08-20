/**
 * Apartment floor-plan editor (free rectangles or partition walls).
 * Exposes window.GoveePlanEditor.init({ onLayoutChanged }).
 */
(function () {
  "use strict";

  const SNAP = 8;
  const MIN_SIZE = 16;
  const HANDLE = 7;
  const HISTORY_MAX = 60;
  const VIEW_PAD = 40;
  const ZOOM_MIN = 0.5;
  const ZOOM_MAX = 8;

  /** @type {ReturnType<typeof createState> | null} */
  let state = null;
  /** @type {{ onLayoutChanged?: () => void | Promise<void> } | null} */
  let opts = null;

  function createState() {
    return {
      plans: [],
      activePlanId: null,
      roomOptions: [],
      plan: null,
      tool: "select",
      selectedId: null,
      selectedKind: null, // shape | face | wall | opening | envelope
      drag: null,
      dirty: false,
      status: "",
      undoStack: [],
      redoStack: [],
      historySuspended: false,
      /** @type {{ x: number, y: number, w: number, h: number } | null} */
      viewBox: null,
      snapEnabled: true,
    };
  }

  function fitViewBox() {
    const env = state.plan && state.plan.envelope;
    if (!env) return { x: 0, y: 0, w: 100, h: 100 };
    return {
      x: env.x - VIEW_PAD,
      y: env.y - VIEW_PAD,
      w: env.w + VIEW_PAD * 2,
      h: env.h + VIEW_PAD * 2,
    };
  }

  function currentViewBox() {
    return state.viewBox ? { ...state.viewBox } : fitViewBox();
  }

  function zoomLevel() {
    if (!state.plan) return 1;
    const fit = fitViewBox();
    const vb = currentViewBox();
    return fit.w / vb.w;
  }

  function applyViewBox() {
    const svg = $("plan-editor-svg");
    if (!svg || !state.plan) return;
    const vb = currentViewBox();
    svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
    const label = $("plan-zoom-label");
    if (label) label.textContent = `${Math.round(zoomLevel() * 100)}%`;
  }

  function resetView() {
    state.viewBox = null;
    applyViewBox();
  }

  /** Zoom by factor (>1 zoom out). Anchor stays under client point when provided. */
  function zoomBy(factor, clientX, clientY) {
    if (!state.plan) return;
    const svg = $("plan-editor-svg");
    if (!svg) return;
    const fit = fitViewBox();
    const vb = currentViewBox();
    const aspect = fit.w / fit.h;
    let newW = vb.w * factor;
    let newH = newW / aspect;
    let z = fit.w / newW;
    if (z < ZOOM_MIN) {
      newW = fit.w / ZOOM_MIN;
      newH = fit.h / ZOOM_MIN;
    } else if (z > ZOOM_MAX) {
      newW = fit.w / ZOOM_MAX;
      newH = fit.h / ZOOM_MAX;
    }
    let anchor;
    if (clientX != null && clientY != null) {
      anchor = svgPoint(svg, { clientX, clientY });
    } else {
      const r = svg.getBoundingClientRect();
      anchor = svgPoint(svg, {
        clientX: r.left + r.width / 2,
        clientY: r.top + r.height / 2,
      });
    }
    const newX = anchor.x - (anchor.x - vb.x) * (newW / vb.w);
    const newY = anchor.y - (anchor.y - vb.y) * (newH / vb.h);
    state.viewBox = { x: newX, y: newY, w: newW, h: newH };
    applyViewBox();
  }

  function onWheelZoom(evt) {
    if (!state.plan) return;
    evt.preventDefault();
    const factor = evt.deltaY > 0 ? 1.12 : 1 / 1.12;
    zoomBy(factor, evt.clientX, evt.clientY);
  }

  function clonePlanSnapshot(plan) {
    if (!plan) return null;
    return JSON.parse(
      JSON.stringify({
        name: plan.name,
        north_deg: plan.north_deg,
        meters_per_unit: plan.meters_per_unit,
        envelope: plan.envelope,
        shapes: plan.shapes || [],
        walls: plan.walls || [],
        faces: plan.faces || [],
        openings: plan.openings || [],
      })
    );
  }

  function applyPlanSnapshot(plan, snap) {
    if (!plan || !snap) return;
    plan.name = snap.name;
    plan.north_deg = snap.north_deg;
    plan.meters_per_unit = snap.meters_per_unit;
    plan.envelope = snap.envelope;
    plan.shapes = snap.shapes || [];
    plan.walls = snap.walls || [];
    plan.faces = snap.faces || [];
    plan.openings = snap.openings || [];
  }

  function clearHistory() {
    if (!state) return;
    state.undoStack = [];
    state.redoStack = [];
  }

  /** Snapshot current plan before a mutating edit (no-op if identical to last). */
  function captureBeforeEdit() {
    if (!state || !state.plan || state.historySuspended) return;
    const snap = {
      plan: clonePlanSnapshot(state.plan),
      selectedId: state.selectedId,
      selectedKind: state.selectedKind,
      dirty: state.dirty,
    };
    const last = state.undoStack[state.undoStack.length - 1];
    if (last && JSON.stringify(last.plan) === JSON.stringify(snap.plan)) {
      return;
    }
    state.undoStack.push(snap);
    if (state.undoStack.length > HISTORY_MAX) state.undoStack.shift();
    state.redoStack = [];
  }

  function restoreHistoryEntry(entry) {
    if (!state || !state.plan || !entry) return;
    state.historySuspended = true;
    applyPlanSnapshot(state.plan, entry.plan);
    if (state.plan.mode === "partition") refreshPartitionFaces();
    constrainContentsToEnvelope();
    state.selectedId = entry.selectedId;
    state.selectedKind = entry.selectedKind;
    state.dirty = !!entry.dirty;
    state.historySuspended = false;
    renderToolbar();
    renderSvg();
    renderPlanSelect();
    updateActionButtons();
  }

  function undoEdit() {
    if (!state || !state.plan) return;
    if (!state.undoStack.length) {
      setStatus("Nothing to undo");
      return;
    }
    const current = {
      plan: clonePlanSnapshot(state.plan),
      selectedId: state.selectedId,
      selectedKind: state.selectedKind,
      dirty: state.dirty,
    };
    const prev = state.undoStack.pop();
    state.redoStack.push(current);
    restoreHistoryEntry(prev);
    setStatus("Undo");
  }

  function redoEdit() {
    if (!state || !state.plan) return;
    if (!state.redoStack.length) {
      setStatus("Nothing to redo");
      return;
    }
    const current = {
      plan: clonePlanSnapshot(state.plan),
      selectedId: state.selectedId,
      selectedKind: state.selectedKind,
      dirty: state.dirty,
    };
    const next = state.redoStack.pop();
    state.undoStack.push(current);
    restoreHistoryEntry(next);
    setStatus("Redo");
  }

  function onEditorKeyDown(evt) {
    if (!state || !state.plan) return;
    const mod = evt.metaKey || evt.ctrlKey;
    if (!mod) return;
    const t = evt.target;
    if (
      t &&
      (t.tagName === "INPUT" ||
        t.tagName === "TEXTAREA" ||
        t.tagName === "SELECT" ||
        t.isContentEditable)
    ) {
      return;
    }
    const key = String(evt.key || "").toLowerCase();
    if (key === "z" && !evt.shiftKey) {
      evt.preventDefault();
      undoEdit();
    } else if ((key === "z" && evt.shiftKey) || key === "y") {
      evt.preventDefault();
      redoEdit();
    }
  }

  function $(id) {
    return document.getElementById(id);
  }

  function uid(prefix) {
    return `${prefix}-${Math.random().toString(16).slice(2, 10)}`;
  }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function snap(v, guides) {
    if (!state || !state.snapEnabled) return v;
    let best = v;
    let bestD = SNAP;
    for (const g of guides) {
      const d = Math.abs(v - g);
      if (d < bestD) {
        bestD = d;
        best = g;
      }
    }
    return best;
  }

  function rectGuides(plan, excludeId) {
    const g = [];
    const env = plan.envelope;
    if (env) {
      g.push(env.x, env.y, env.x + env.w, env.y + env.h);
    }
    const items = plan.mode === "free" ? plan.shapes : plan.faces;
    for (const s of items || []) {
      if (s.id === excludeId) continue;
      g.push(s.x, s.y, s.x + s.w, s.y + s.h);
    }
    return g;
  }

  function normalizeRect(x, y, w, h) {
    if (w < 0) {
      x += w;
      w = -w;
    }
    if (h < 0) {
      y += h;
      h = -h;
    }
    return { x, y, w: Math.max(MIN_SIZE, w), h: Math.max(MIN_SIZE, h) };
  }

  function metersPerUnit() {
    const v = Number(state.plan && state.plan.meters_per_unit);
    return Number.isFinite(v) && v > 0 ? v : 0.05;
  }

  /** Geometric area in m² from canvas rect (ignores lock). */
  function geometricAreaM2(rect) {
    if (!rect) return null;
    const w = Number(rect.w);
    const h = Number(rect.h);
    if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return null;
    const mpu = metersPerUnit();
    return w * h * mpu * mpu;
  }

  /** Display / compile area: locked value when set, else geometry minus nested holes. */
  function effectiveAreaM2(rect) {
    if (!rect) return null;
    if (rect.area_locked && Number(rect.area_m2) > 0) {
      return Number(rect.area_m2);
    }
    const geo = geometricAreaM2(rect);
    if (geo == null) return null;
    const mpu = metersPerUnit();
    const mpu2 = mpu * mpu;
    const myA = Number(rect.w) * Number(rect.h);
    let sub = 0;
    for (const other of roomItems()) {
      if (!other || other.id === rect.id) continue;
      if (!(other.room_id || "").trim()) continue;
      const otherA = Number(other.w) * Number(other.h);
      if (!(otherA > 0) || otherA >= myA - 1e-6) continue;
      if (!isNestedInside(other, rect)) continue;
      sub += intersectionAreaCanvas(rect, other);
    }
    return Math.max(0, geo - sub * mpu2);
  }

  function intersectionAreaCanvas(a, b) {
    const ax2 = Number(a.x) + Number(a.w);
    const ay2 = Number(a.y) + Number(a.h);
    const bx2 = Number(b.x) + Number(b.w);
    const by2 = Number(b.y) + Number(b.h);
    const ow = Math.max(0, Math.min(ax2, bx2) - Math.max(Number(a.x), Number(b.x)));
    const oh = Math.max(0, Math.min(ay2, by2) - Math.max(Number(a.y), Number(b.y)));
    return ow * oh;
  }

  function isNestedInside(inner, outer) {
    const ia = Number(inner.w) * Number(inner.h);
    const oa = Number(outer.w) * Number(outer.h);
    if (!(ia > 0) || !(oa > 0) || ia >= oa - 1e-6) return false;
    const cx = Number(inner.x) + Number(inner.w) / 2;
    const cy = Number(inner.y) + Number(inner.h) / 2;
    if (
      cx < Number(outer.x) ||
      cx > Number(outer.x) + Number(outer.w) ||
      cy < Number(outer.y) ||
      cy > Number(outer.y) + Number(outer.h)
    ) {
      return false;
    }
    return intersectionAreaCanvas(inner, outer) >= 0.85 * ia;
  }

  function formatAreaM2(m2) {
    if (m2 == null || !Number.isFinite(m2)) return "—";
    if (m2 < 10) return `${m2.toFixed(2)} m²`;
    return `${m2.toFixed(1)} m²`;
  }

  function formatLengthM(meters) {
    if (meters == null || !Number.isFinite(meters) || meters <= 0) return "";
    if (meters < 10) return `${meters.toFixed(2)} m`;
    return `${meters.toFixed(1)} m`;
  }

  function roomItems() {
    if (!state.plan) return [];
    return state.plan.mode === "free" ? state.plan.shapes || [] : state.plan.faces || [];
  }

  function itemKind() {
    return state.plan && state.plan.mode === "free" ? "shape" : "face";
  }

  function findItemForRoom(roomId) {
    const rid = String(roomId || "")
      .trim()
      .toLowerCase();
    if (!rid) return null;
    return roomItems().find((x) => (x.room_id || "").toLowerCase() === rid) || null;
  }

  function selectedRoomItem() {
    if (!state.plan || !state.selectedId) return null;
    if (state.selectedKind !== "shape" && state.selectedKind !== "face") return null;
    return roomItems().find((x) => x.id === state.selectedId) || null;
  }

  /** Keep center; set w×h so geometric area matches areaM2. */
  function reshapeToAreaM2(rect, areaM2) {
    const mpu = metersPerUnit();
    const target = Math.max(1e-6, Number(areaM2) / (mpu * mpu));
    const aspect = Math.max(1e-6, Number(rect.w) / Math.max(Number(rect.h), 1e-6));
    let h = Math.sqrt(target / aspect);
    let w = target / h;
    w = Math.max(MIN_SIZE, w);
    h = Math.max(MIN_SIZE, h);
    const cx = Number(rect.x) + Number(rect.w) / 2;
    const cy = Number(rect.y) + Number(rect.h) / 2;
    rect.w = w;
    rect.h = h;
    rect.x = cx - w / 2;
    rect.y = cy - h / 2;
    if (state.plan && state.plan.envelope) {
      const c = clampRectInEnvelope(rect, state.plan.envelope);
      rect.x = c.x;
      rect.y = c.y;
      rect.w = c.w;
      rect.h = c.h;
    }
  }

  /**
   * Keep canvas area A = w×h while the user drags a handle.
   * Only the aspect ratio changes (area is fixed).
   */
  function applyLockedCanvasArea(r, lockedCanvasArea, handle, orig) {
    const A = Math.max(MIN_SIZE * MIN_SIZE, Number(lockedCanvasArea) || 0);
    if (!(A > 0)) return r;
    const hdl = String(handle || "");
    let x = Number(orig.x);
    let y = Number(orig.y);
    let w = Number(orig.w);
    let h = Number(orig.h);

    // Edge handles: that edge follows the pointer; the orthogonal size is A / size.
    if (hdl === "e" || hdl === "w") {
      w = Math.max(MIN_SIZE, Number(r.w));
      h = Math.max(MIN_SIZE, A / w);
      x = hdl === "w" ? Number(orig.x) + Number(orig.w) - w : Number(orig.x);
      y = Number(orig.y) + (Number(orig.h) - h) / 2; // keep vertical center
    } else if (hdl === "n" || hdl === "s") {
      h = Math.max(MIN_SIZE, Number(r.h));
      w = Math.max(MIN_SIZE, A / h);
      y = hdl === "n" ? Number(orig.y) + Number(orig.h) - h : Number(orig.y);
      x = Number(orig.x) + (Number(orig.w) - w) / 2; // keep horizontal center
    } else {
      // Corner: drive by the larger pointer delta vs original size.
      const dw = Math.abs(Number(r.w) - Number(orig.w));
      const dh = Math.abs(Number(r.h) - Number(orig.h));
      if (dw >= dh) {
        w = Math.max(MIN_SIZE, Number(r.w));
        h = Math.max(MIN_SIZE, A / w);
      } else {
        h = Math.max(MIN_SIZE, Number(r.h));
        w = Math.max(MIN_SIZE, A / h);
      }
      x = hdl.includes("w") ? Number(orig.x) + Number(orig.w) - w : Number(orig.x);
      y = hdl.includes("n") ? Number(orig.y) + Number(orig.h) - h : Number(orig.y);
    }
    return normalizeRect(x, y, w, h);
  }

  /** Clamp into envelope while trying to keep locked canvas area A. */
  function clampLockedRectInEnvelope(r, env, lockedCanvasArea, handle, orig) {
    const A = Math.max(MIN_SIZE * MIN_SIZE, Number(lockedCanvasArea) || 0);
    let c = clampRectInEnvelope(r, env);
    if (!(A > 0) || !env) return c;
    if (Math.abs(c.w * c.h - A) <= 0.5) return c;
    // Recover area inside remaining room: prefer the dragged axis.
    c = applyLockedCanvasArea(c, A, handle, orig);
    c = clampRectInEnvelope(c, env);
    if (Math.abs(c.w * c.h - A) <= 0.5) return c;
    // Last resort: fit max width under envelope, height = A/w (or vice versa).
    const maxW = Math.max(MIN_SIZE, env.w);
    const maxH = Math.max(MIN_SIZE, env.h);
    let w = Math.min(Math.max(MIN_SIZE, c.w), maxW);
    let h = A / w;
    if (h > maxH) {
      h = maxH;
      w = Math.min(maxW, Math.max(MIN_SIZE, A / h));
      h = A / w;
    }
    if (w > maxW) {
      w = maxW;
      h = Math.min(maxH, Math.max(MIN_SIZE, A / w));
    }
    return clampRectInEnvelope(
      {
        x: Number(orig.x),
        y: Number(orig.y),
        w,
        h,
      },
      env
    );
  }

  function syncLockedShapesGeometry() {
    if (!state.plan || state.plan.mode !== "free") return;
    for (const s of state.plan.shapes || []) {
      if (!s.area_locked || !(Number(s.area_m2) > 0)) continue;
      reshapeToAreaM2(s, s.area_m2);
    }
  }

  function assignSelectedToRoom(roomId) {
    const rid = String(roomId || "")
      .trim()
      .toLowerCase();
    if (!rid) return;
    const item = selectedRoomItem();
    if (!item) {
      setStatus("Select a shape on the plan first");
      return;
    }
    if (state.selectedKind === "face") {
      // Faces are derived; assignment is ok, lock not applicable.
    }
    captureBeforeEdit();
    const others = roomItems().filter((x) => x.id !== item.id);
    const prior = others.find((x) => (x.room_id || "").toLowerCase() === rid);
    if (prior) {
      prior.room_id = "";
      prior.label = "";
    }
    item.room_id = rid;
    const opt = state.roomOptions.find((r) => r.id === rid);
    item.label = opt ? opt.label : item.label || rid;
    state.dirty = true;
    setStatus(`Assigned shape → ${item.label || rid}`);
    renderSvg();
  }

  function selectRoomFromList(roomId) {
    const item = findItemForRoom(roomId);
    if (!item) {
      setStatus(`No shape assigned to ${roomId} yet — select a shape, then Assign`);
      return;
    }
    selectItem(itemKind(), item.id);
  }

  /** Keep a rect fully inside the apartment envelope (shrink if needed). */
  function clampRectInEnvelope(rect, env) {
    if (!env) return { ...rect };
    const maxW = Math.max(MIN_SIZE, env.w);
    const maxH = Math.max(MIN_SIZE, env.h);
    let w = Math.min(Math.max(MIN_SIZE, rect.w), maxW);
    let h = Math.min(Math.max(MIN_SIZE, rect.h), maxH);
    let x = clamp(rect.x, env.x, env.x + env.w - w);
    let y = clamp(rect.y, env.y, env.y + env.h - h);
    return { x, y, w, h };
  }

  function clampPointInEnvelope(x, y, env) {
    if (!env) return { x, y };
    return {
      x: clamp(x, env.x, env.x + env.w),
      y: clamp(y, env.y, env.y + env.h),
    };
  }

  function clampSegmentInEnvelope(x1, y1, x2, y2, env) {
    const a = clampPointInEnvelope(x1, y1, env);
    const b = clampPointInEnvelope(x2, y2, env);
    return { x1: a.x, y1: a.y, x2: b.x, y2: b.y };
  }

  /** After envelope moves/resizes, pull room shapes (and walls/openings) back inside. */
  function constrainContentsToEnvelope() {
    const plan = state.plan;
    if (!plan || !plan.envelope) return;
    const env = plan.envelope;
    if (plan.mode === "free") {
      for (const s of plan.shapes || []) {
        const c = clampRectInEnvelope(s, env);
        s.x = c.x;
        s.y = c.y;
        s.w = c.w;
        s.h = c.h;
      }
    } else {
      for (const w of plan.walls || []) {
        const c = clampSegmentInEnvelope(w.x1, w.y1, w.x2, w.y2, env);
        w.x1 = c.x1;
        w.y1 = c.y1;
        w.x2 = c.x2;
        w.y2 = c.y2;
      }
      refreshPartitionFaces();
    }
    for (const op of plan.openings || []) {
      const c = clampSegmentInEnvelope(op.x1, op.y1, op.x2, op.y2, env);
      op.x1 = c.x1;
      op.y1 = c.y1;
      op.x2 = c.x2;
      op.y2 = c.y2;
    }
  }

  function svgPoint(svg, evt) {
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }

  async function api(path, init) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(init && init.headers) },
      ...init,
    });
    const text = await res.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { detail: text };
    }
    if (!res.ok) {
      const detail =
        (body && (body.detail || body.error || body.message)) || res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return body;
  }

  // --- Partition face split (mirrors server BSP) ----------------------------

  function overlap1d(a0, a1, b0, b1) {
    const lo = Math.max(Math.min(a0, a1), Math.min(b0, b1));
    const hi = Math.min(Math.max(a0, a1), Math.max(b0, b1));
    return Math.max(0, hi - lo);
  }

  function partitionFaces(envelope, walls, previous) {
    let cells = [{ x: envelope.x, y: envelope.y, w: envelope.w, h: envelope.h }];
    const eps = 0.75;
    for (const wall of walls || []) {
      const x1 = wall.x1;
      const y1 = wall.y1;
      const x2 = wall.x2;
      const y2 = wall.y2;
      const vertical = Math.abs(x2 - x1) < eps;
      const horizontal = Math.abs(y2 - y1) < eps;
      if (!vertical && !horizontal) continue;
      const next = [];
      for (const cell of cells) {
        const cx = cell.x;
        const cy = cell.y;
        const cw = cell.w;
        const ch = cell.h;
        const cx2 = cx + cw;
        const cy2 = cy + ch;
        if (vertical) {
          const x = (x1 + x2) / 2;
          const yLo = Math.min(y1, y2);
          const yHi = Math.max(y1, y2);
          if (x <= cx + eps || x >= cx2 - eps) {
            next.push(cell);
            continue;
          }
          if (yHi < cy + eps || yLo > cy2 - eps) {
            next.push(cell);
            continue;
          }
          const cover = overlap1d(yLo, yHi, cy, cy2);
          if (cover < Math.min(ch, Math.abs(yHi - yLo)) - eps && cover < ch * 0.9) {
            next.push(cell);
            continue;
          }
          const leftW = x - cx;
          const rightW = cx2 - x;
          if (leftW >= 1) next.push({ x: cx, y: cy, w: leftW, h: ch });
          if (rightW >= 1) next.push({ x: x, y: cy, w: rightW, h: ch });
        } else {
          const y = (y1 + y2) / 2;
          const xLo = Math.min(x1, x2);
          const xHi = Math.max(x1, x2);
          if (y <= cy + eps || y >= cy2 - eps) {
            next.push(cell);
            continue;
          }
          if (xHi < cx + eps || xLo > cx2 - eps) {
            next.push(cell);
            continue;
          }
          const cover = overlap1d(xLo, xHi, cx, cx2);
          if (cover < Math.min(cw, Math.abs(xHi - xLo)) - eps && cover < cw * 0.9) {
            next.push(cell);
            continue;
          }
          const topH = y - cy;
          const botH = cy2 - y;
          if (topH >= 1) next.push({ x: cx, y: cy, w: cw, h: topH });
          if (botH >= 1) next.push({ x: cx, y: y, w: cw, h: botH });
        }
      }
      cells = next;
    }
    const faces = cells.map((c, i) => ({
      id: `face-${i + 1}`,
      type: "rect",
      room_id: "",
      label: "",
      x: c.x,
      y: c.y,
      w: c.w,
      h: c.h,
    }));
    const used = new Set();
    return faces.map((face) => {
      const cx = face.x + face.w / 2;
      const cy = face.y + face.h / 2;
      for (const prev of previous || []) {
        if (
          prev.x - eps <= cx &&
          cx <= prev.x + prev.w + eps &&
          prev.y - eps <= cy &&
          cy <= prev.y + prev.h + eps
        ) {
          const rid = (prev.room_id || "").trim().toLowerCase();
          if (rid && used.has(rid)) continue;
          const row = { ...face, room_id: rid, label: prev.label || "" };
          if (rid) used.add(rid);
          if (Math.abs(prev.x - face.x) < eps * 2) row.id = prev.id || row.id;
          return row;
        }
      }
      return face;
    });
  }

  function refreshPartitionFaces() {
    if (!state.plan || state.plan.mode !== "partition") return;
    state.plan.faces = partitionFaces(
      state.plan.envelope,
      state.plan.walls,
      state.plan.faces
    );
  }

  // --- Rendering ------------------------------------------------------------

  function setStatus(msg) {
    state.status = msg || "";
    const el = $("plan-editor-status");
    if (el) el.textContent = state.status;
  }

  function renderPlanSelect() {
    const sel = $("plan-editor-select");
    if (!sel) return;
    const cur = state.plan && state.plan.id;
    sel.replaceChildren();
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "Select a plan…";
    sel.appendChild(blank);
    for (const p of state.plans) {
      const opt = document.createElement("option");
      opt.value = p.id;
      const active = p.id === state.activePlanId ? " ★" : "";
      opt.textContent = `${p.name} (${p.mode})${active}`;
      if (p.id === cur) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  function renderToolbar() {
    const bar = $("plan-editor-tools");
    if (!bar || !state.plan) {
      if (bar) bar.hidden = true;
      return;
    }
    bar.hidden = false;
    const mode = state.plan.mode;
    const tools =
      mode === "free"
        ? [
            ["select", "Select"],
            ["rect", "Room"],
            ["opening", "Opening"],
            ["delete", "Delete"],
          ]
        : [
            ["select", "Select"],
            ["wall", "Wall"],
            ["opening", "Opening"],
            ["delete", "Delete"],
          ];
    bar.replaceChildren();
    for (const [id, label] of tools) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "plan-tool-btn" + (state.tool === id ? " active" : "");
      btn.dataset.tool = id;
      btn.textContent = label;
      btn.addEventListener("click", () => {
        state.tool = id;
        renderToolbar();
        setStatus(
          id === "rect"
            ? "Drag inside the envelope to draw a room"
            : id === "wall"
              ? "Drag to draw an axis-aligned wall"
              : id === "opening"
                ? "Drag along a shared edge or façade for a door/window"
                : id === "delete"
                  ? "Click a shape, wall, or opening to delete"
                  : "Select and drag handles to move / resize"
        );
      });
      bar.appendChild(btn);
    }

    const snapLab = document.createElement("label");
    snapLab.className = "plan-snap-toggle";
    const snapCb = document.createElement("input");
    snapCb.type = "checkbox";
    snapCb.checked = !!state.snapEnabled;
    snapCb.addEventListener("change", () => {
      state.snapEnabled = snapCb.checked;
      setStatus(state.snapEnabled ? "Snap enabled" : "Snap disabled");
    });
    const t =
      window.I18n && typeof window.I18n.t === "function"
        ? window.I18n.t.bind(window.I18n)
        : (k) => k;
    const snapTxt = document.createElement("span");
    const snapLabel = t("map.plan.snap");
    snapTxt.textContent = snapLabel === "map.plan.snap" ? "Snap" : snapLabel;
    snapLab.appendChild(snapCb);
    snapLab.appendChild(snapTxt);
    bar.appendChild(snapLab);
  }

  function renderProps() {
    const panel = $("plan-editor-props");
    if (!panel) return;
    if (!state.plan) {
      panel.hidden = true;
      panel.replaceChildren();
      return;
    }
    const prevList = panel.querySelector(".plan-room-list");
    const prevScroll = prevList ? prevList.scrollTop : 0;

    panel.hidden = false;
    panel.replaceChildren();

    const meta = document.createElement("div");
    meta.className = "plan-props-block";
    meta.innerHTML = `
      <label>Name <input type="text" id="plan-prop-name" maxlength="120" /></label>
      <label>North (° clockwise from top)
        <input type="number" id="plan-prop-north" step="1" min="0" max="359" />
      </label>
      <label>Meters / unit
        <input type="number" id="plan-prop-mpu" step="0.001" min="0.0001" />
      </label>
      <p class="plan-props-mode">Mode: <strong>${state.plan.mode}</strong> (locked)</p>
    `;
    panel.appendChild(meta);
    const nameEl = meta.querySelector("#plan-prop-name");
    const northEl = meta.querySelector("#plan-prop-north");
    const mpuEl = meta.querySelector("#plan-prop-mpu");
    nameEl.value = state.plan.name || "";
    northEl.value = String(state.plan.north_deg ?? 0);
    mpuEl.value = String(state.plan.meters_per_unit ?? 0.05);
    nameEl.addEventListener("change", () => {
      captureBeforeEdit();
      state.plan.name = nameEl.value.trim() || "Untitled";
      state.dirty = true;
      renderPlanSelect();
    });
    northEl.addEventListener("change", () => {
      captureBeforeEdit();
      state.plan.north_deg = ((Number(northEl.value) || 0) % 360 + 360) % 360;
      state.dirty = true;
    });
    mpuEl.addEventListener("change", () => {
      const v = Number(mpuEl.value);
      if (v > 0) {
        captureBeforeEdit();
        state.plan.meters_per_unit = v;
        syncLockedShapesGeometry();
        state.dirty = true;
        renderSvg();
      }
    });

    // Live metrics
    const metrics = document.createElement("div");
    metrics.className = "plan-props-block plan-props-metrics";
    const items = roomItems();
    let total = 0;
    let named = 0;
    for (const it of items) {
      if (!(it.room_id || "").trim()) continue;
      const a = effectiveAreaM2(it);
      if (a != null) {
        total += a;
        named += 1;
      }
    }
    const envArea = geometricAreaM2(state.plan.envelope);
    const sel = selectedRoomItem();
    const selArea = effectiveAreaM2(sel);
    metrics.innerHTML = `
      <p class="plan-metrics-line"><span data-i18n-skip>Total rooms</span>
        <strong>${formatAreaM2(total)}</strong>
        <span class="muted">(${named})</span></p>
      <p class="plan-metrics-line"><span>Envelope</span>
        <strong>${formatAreaM2(envArea)}</strong></p>
      <p class="plan-metrics-line"><span>Selected</span>
        <strong>${formatAreaM2(selArea)}</strong>${
          sel && sel.area_locked ? ' <span class="plan-area-lock-badge">locked</span>' : ""
        }</p>
    `;
    panel.appendChild(metrics);

    // Selected shape: lock / set area (free mode only)
    if (sel && state.selectedKind === "shape") {
      const lockBlock = document.createElement("div");
      lockBlock.className = "plan-props-block";

      const lockRow = document.createElement("label");
      lockRow.className = "plan-props-check plan-props-lock-area";
      const lockCb = document.createElement("input");
      lockCb.type = "checkbox";
      lockCb.id = "plan-prop-area-lock";
      lockCb.checked = !!sel.area_locked;
      lockRow.appendChild(lockCb);
      const lockTxt = document.createElement("span");
      lockTxt.textContent = "Lock area — resize only changes the ratio";
      lockRow.appendChild(lockTxt);
      lockBlock.appendChild(lockRow);

      const geo = geometricAreaM2(sel);
      const areaVal =
        sel.area_locked && Number(sel.area_m2) > 0
          ? Number(sel.area_m2)
          : geo != null
            ? Math.round(geo * 100) / 100
            : "";
      const areaLab = document.createElement("label");
      areaLab.textContent = "Area (m²)";
      const areaInp = document.createElement("input");
      areaInp.type = "number";
      areaInp.id = "plan-prop-area";
      areaInp.min = "0.1";
      areaInp.step = "0.1";
      areaInp.value = areaVal === "" ? "" : String(areaVal);
      areaInp.disabled = !sel.area_locked;
      areaLab.appendChild(areaInp);
      lockBlock.appendChild(areaLab);

      if (sel.area_locked) {
        const hint = document.createElement("p");
        hint.className = "plan-props-hint";
        hint.textContent =
          "Surface fixed. Drag handles to change width/height ratio only.";
        lockBlock.appendChild(hint);
      }

      lockCb.addEventListener("change", () => {
        if (lockCb.checked) {
          const g = geometricAreaM2(sel);
          if (g == null || g <= 0) {
            lockCb.checked = false;
            setStatus("Shape has no area to lock");
            return;
          }
          captureBeforeEdit();
          sel.area_m2 = Math.round(g * 1000) / 1000;
          sel.area_locked = true;
          setStatus(`Area locked at ${formatAreaM2(sel.area_m2)} — drag to change ratio only`);
        } else {
          captureBeforeEdit();
          sel.area_locked = false;
          setStatus("Area unlocked — free resize");
        }
        state.dirty = true;
        renderSvg();
      });

      areaInp.addEventListener("change", () => {
        if (!sel.area_locked) return;
        const v = Number(areaInp.value);
        if (!(v > 0)) {
          areaInp.value = String(sel.area_m2 || "");
          return;
        }
        captureBeforeEdit();
        sel.area_m2 = Math.round(v * 1000) / 1000;
        reshapeToAreaM2(sel, sel.area_m2);
        state.dirty = true;
        renderSvg();
      });
      panel.appendChild(lockBlock);
    }

    // Scrollable room list
    const listBlock = document.createElement("div");
    listBlock.className = "plan-props-block plan-props-rooms";
    const listTitle = document.createElement("p");
    listTitle.className = "plan-room-list-title";
    listTitle.textContent = "Rooms";
    listBlock.appendChild(listTitle);
    const hint = document.createElement("p");
    hint.className = "plan-props-hint";
    hint.textContent =
      "Click a room to select its shape. Assign links the selected shape.";
    listBlock.appendChild(hint);

    const list = document.createElement("div");
    list.className = "plan-room-list";
    list.setAttribute("role", "list");

    const assignedExtra = [];
    for (const it of items) {
      const rid = (it.room_id || "").trim().toLowerCase();
      if (!rid) continue;
      if (!state.roomOptions.some((r) => r.id === rid)) {
        assignedExtra.push({ id: rid, label: it.label || rid });
      }
    }
    const rooms = [...state.roomOptions, ...assignedExtra];
    const seen = new Set();
    for (const r of rooms) {
      if (seen.has(r.id)) continue;
      seen.add(r.id);
      const item = findItemForRoom(r.id);
      const area = effectiveAreaM2(item);
      const isSelShape =
        item &&
        state.selectedId === item.id &&
        (state.selectedKind === "shape" || state.selectedKind === "face");
      const row = document.createElement("div");
      row.className =
        "plan-room-row" +
        (isSelShape ? " selected" : "") +
        (item ? " assigned" : " unassigned");
      row.setAttribute("role", "listitem");
      row.tabIndex = 0;
      row.dataset.roomId = r.id;

      const main = document.createElement("button");
      main.type = "button";
      main.className = "plan-room-row-main";
      main.innerHTML = `
        <span class="plan-room-row-name">${escapeHtml(r.label || r.id)}</span>
        <span class="plan-room-row-id">${escapeHtml(r.id)}</span>
        <span class="plan-room-row-area">${formatAreaM2(area)}${
          item && item.area_locked ? " · locked" : ""
        }</span>
      `;
      main.addEventListener("click", () => selectRoomFromList(r.id));
      row.appendChild(main);

      const assignBtn = document.createElement("button");
      assignBtn.type = "button";
      assignBtn.className = "plan-room-assign";
      assignBtn.textContent = "Assign";
      assignBtn.title = "Assign selected shape to this room";
      const canAssign =
        !!selectedRoomItem() &&
        (state.selectedKind === "shape" || state.selectedKind === "face");
      assignBtn.disabled = !canAssign;
      assignBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        assignSelectedToRoom(r.id);
      });
      row.appendChild(assignBtn);
      list.appendChild(row);
    }
    listBlock.appendChild(list);
    panel.appendChild(listBlock);
    list.scrollTop = prevScroll;

    // Opening props (unchanged)
    const selKind = state.selectedKind;
    const selId = state.selectedId;
    if (selKind === "opening") {
      const op = (state.plan.openings || []).find((x) => x.id === selId);
      if (!op) return;
      const block = document.createElement("div");
      block.className = "plan-props-block";
      const kindLabel = document.createElement("label");
      kindLabel.textContent = "Opening ";
      const kindSel = document.createElement("select");
      for (const k of ["door", "window"]) {
        const opt = document.createElement("option");
        opt.value = k;
        opt.textContent = k;
        if (op.kind === k) opt.selected = true;
        kindSel.appendChild(opt);
      }
      kindSel.addEventListener("change", () => {
        captureBeforeEdit();
        op.kind = kindSel.value;
        state.dirty = true;
        renderSvg();
      });
      kindLabel.appendChild(kindSel);
      block.appendChild(kindLabel);

      const roomsNamed = namedRooms(state.plan);
      for (const field of ["room_a", "room_b"]) {
        const lab = document.createElement("label");
        lab.textContent = field === "room_a" ? "Room A " : "Room B ";
        const selOp = document.createElement("select");
        const out = document.createElement("option");
        out.value = "outdoor";
        out.textContent = "outdoor";
        selOp.appendChild(out);
        for (const rid of roomsNamed) {
          const opt = document.createElement("option");
          opt.value = rid;
          opt.textContent = rid;
          selOp.appendChild(opt);
        }
        selOp.value = op[field] || "outdoor";
        selOp.addEventListener("change", () => {
          captureBeforeEdit();
          op[field] = selOp.value;
          state.dirty = true;
        });
        lab.appendChild(selOp);
        block.appendChild(lab);
      }
      panel.appendChild(block);
    }
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function namedRooms(plan) {
    const items = plan.mode === "free" ? plan.shapes : plan.faces;
    const ids = [];
    for (const it of items || []) {
      const rid = (it.room_id || "").trim().toLowerCase();
      if (rid && !ids.includes(rid)) ids.push(rid);
    }
    return ids.sort();
  }

  function roomLabel(plan, roomId) {
    if (!roomId) return "";
    const items = plan.mode === "free" ? plan.shapes : plan.faces;
    const hit = (items || []).find((x) => x.room_id === roomId);
    if (hit && hit.label) return hit.label;
    const opt = state.roomOptions.find((r) => r.id === roomId);
    return opt ? opt.label : roomId;
  }

  function renderSvg() {
    const svg = $("plan-editor-svg");
    if (!svg || !state.plan) {
      if (svg) svg.replaceChildren();
      return;
    }
    const plan = state.plan;
    const env = plan.envelope;
    applyViewBox();
    svg.replaceChildren();

    const gEnv = svgEl("rect", {
      x: env.x,
      y: env.y,
      width: env.w,
      height: env.h,
      class: "plan-envelope" + (state.selectedKind === "envelope" ? " selected" : ""),
      "data-kind": "envelope",
      "data-id": "envelope",
    });
    svg.appendChild(gEnv);
    drawEnvelopeDimensions(svg, env);

    if (plan.mode === "free") {
      for (const s of plan.shapes || []) {
        svg.appendChild(drawRoomRect(s, "shape"));
      }
    } else {
      for (const f of plan.faces || []) {
        svg.appendChild(drawRoomRect(f, "face"));
      }
      for (const w of plan.walls || []) {
        const line = svgEl("line", {
          x1: w.x1,
          y1: w.y1,
          x2: w.x2,
          y2: w.y2,
          class: "plan-wall" + (state.selectedId === w.id ? " selected" : ""),
          "data-kind": "wall",
          "data-id": w.id,
        });
        svg.appendChild(line);
      }
    }

    for (const op of plan.openings || []) {
      const line = svgEl("line", {
        x1: op.x1,
        y1: op.y1,
        x2: op.x2,
        y2: op.y2,
        class:
          "plan-opening plan-opening-" +
          (op.kind || "door") +
          (state.selectedId === op.id ? " selected" : ""),
        "data-kind": "opening",
        "data-id": op.id,
      });
      svg.appendChild(line);
    }

    // Handles for selected room rect or envelope (not derived partition faces)
    if (state.selectedKind === "shape" || state.selectedKind === "envelope") {
      const rect =
        state.selectedKind === "envelope"
          ? env
          : (plan.shapes || []).find((x) => x.id === state.selectedId);
      if (rect) drawHandles(svg, rect);
    }

    // North indicator
    const nx = env.x + env.w + 18;
    const ny = env.y + 24;
    const ang = ((plan.north_deg || 0) * Math.PI) / 180;
    // Arrow points toward north (top when north_deg=0)
    const ax = nx + Math.sin(ang) * 18;
    const ay = ny - Math.cos(ang) * 18;
    svg.appendChild(
      svgEl("line", {
        x1: nx,
        y1: ny,
        x2: ax,
        y2: ay,
        class: "plan-north-arrow",
      })
    );
    const nt = svgEl("text", { x: nx, y: ny + 16, class: "plan-north-label" });
    nt.textContent = "N";
    svg.appendChild(nt);

    renderProps();
    updateActionButtons();
  }

  function svgEl(name, attrs) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null) continue;
      el.setAttribute(k, String(v));
    }
    return el;
  }

  /** Width under the bottom edge, height along the left edge (meters). */
  function drawEnvelopeDimensions(svg, env) {
    const mpu = metersPerUnit();
    const wTxt = formatLengthM(Number(env.w) * mpu);
    const hTxt = formatLengthM(Number(env.h) * mpu);
    const gap = 14;

    if (wTxt) {
      const wt = svgEl("text", {
        x: env.x + env.w / 2,
        y: env.y + env.h + gap,
        class: "plan-envelope-dim",
      });
      wt.textContent = wTxt;
      svg.appendChild(wt);
    }
    if (hTxt) {
      const hx = env.x - gap;
      const hy = env.y + env.h / 2;
      const ht = svgEl("text", {
        x: hx,
        y: hy,
        class: "plan-envelope-dim",
        transform: `rotate(-90 ${hx} ${hy})`,
      });
      ht.textContent = hTxt;
      svg.appendChild(ht);
    }
  }

  function drawRoomRect(item, kind) {
    const g = svgEl("g", {
      class: "plan-room-group",
      "data-kind": kind,
      "data-id": item.id,
    });
    const selected = state.selectedId === item.id && state.selectedKind === kind;
    g.appendChild(
      svgEl("rect", {
        x: item.x,
        y: item.y,
        width: item.w,
        height: item.h,
        class: "plan-room" + (selected ? " selected" : "") + (item.room_id ? "" : " unnamed"),
        "data-kind": kind,
        "data-id": item.id,
      })
    );
    const label = roomLabel(state.plan, item.room_id) || "(unnamed)";
    const area = effectiveAreaM2(item);
    const areaTxt = area != null ? formatAreaM2(area) : "";
    const t = svgEl("text", {
      x: item.x + item.w / 2,
      y: item.y + item.h / 2 - (areaTxt ? 5 : 0),
      class: "plan-room-label",
      "data-kind": kind,
      "data-id": item.id,
    });
    t.textContent = label;
    g.appendChild(t);
    if (areaTxt) {
      const t2 = svgEl("text", {
        x: item.x + item.w / 2,
        y: item.y + item.h / 2 + 9,
        class: "plan-room-label plan-room-area-label",
        "data-kind": kind,
        "data-id": item.id,
      });
      t2.textContent = areaTxt + (item.area_locked ? " *" : "");
      g.appendChild(t2);
    }
    return g;
  }

  function drawHandles(svg, rect) {
    const pts = [
      ["nw", rect.x, rect.y],
      ["n", rect.x + rect.w / 2, rect.y],
      ["ne", rect.x + rect.w, rect.y],
      ["e", rect.x + rect.w, rect.y + rect.h / 2],
      ["se", rect.x + rect.w, rect.y + rect.h],
      ["s", rect.x + rect.w / 2, rect.y + rect.h],
      ["sw", rect.x, rect.y + rect.h],
      ["w", rect.x, rect.y + rect.h / 2],
    ];
    for (const [name, x, y] of pts) {
      svg.appendChild(
        svgEl("rect", {
          x: x - HANDLE / 2,
          y: y - HANDLE / 2,
          width: HANDLE,
          height: HANDLE,
          class: "plan-handle",
          "data-handle": name,
        })
      );
    }
  }

  function updateActionButtons() {
    const saveBtn = $("plan-editor-save");
    const actBtn = $("plan-editor-activate");
    const deactBtn = $("plan-editor-deactivate");
    const dupBtn = $("plan-editor-duplicate");
    const delBtn = $("plan-editor-delete");
    const has = !!state.plan;
    if (saveBtn) saveBtn.disabled = !has;
    if (dupBtn) dupBtn.disabled = !has;
    if (delBtn) delBtn.disabled = !has;
    if (actBtn) {
      actBtn.disabled = !has;
      actBtn.textContent =
        has && state.plan.id === state.activePlanId ? "Re-activate" : "Activate";
    }
    if (deactBtn) {
      deactBtn.disabled = !(has && state.plan.id === state.activePlanId);
    }
    const dirtyEl = $("plan-editor-dirty");
    if (dirtyEl) dirtyEl.hidden = !state.dirty;
  }

  // --- Interaction ----------------------------------------------------------

  function hitTarget(evt) {
    const t = evt.target;
    if (!t || !t.getAttribute) return null;
    if (t.getAttribute("data-handle")) {
      return { kind: "handle", handle: t.getAttribute("data-handle") };
    }
    const kind = t.getAttribute("data-kind");
    const id = t.getAttribute("data-id");
    if (kind && id) return { kind, id };
    return null;
  }

  function selectItem(kind, id) {
    state.selectedKind = kind;
    state.selectedId = id;
    renderSvg();
  }

  function deleteSelected() {
    if (!state.plan || !state.selectedKind || !state.selectedId) return;
    const plan = state.plan;
    const id = state.selectedId;
    if (state.selectedKind === "envelope") {
      setStatus("Envelope cannot be deleted — resize it instead");
      return;
    }
    captureBeforeEdit();
    if (state.selectedKind === "shape") {
      plan.shapes = (plan.shapes || []).filter((x) => x.id !== id);
    } else if (state.selectedKind === "face") {
      // Faces are derived; clear room assignment instead of deleting geometry
      const face = (plan.faces || []).find((x) => x.id === id);
      if (face) {
        face.room_id = "";
        face.label = "";
      }
    } else if (state.selectedKind === "wall") {
      plan.walls = (plan.walls || []).filter((x) => x.id !== id);
      refreshPartitionFaces();
    } else if (state.selectedKind === "opening") {
      plan.openings = (plan.openings || []).filter((x) => x.id !== id);
    }
    state.selectedId = null;
    state.selectedKind = null;
    state.dirty = true;
    renderSvg();
  }

  function onPointerDown(evt) {
    if (!state.plan) return;
    evt.preventDefault();
    const sel = window.getSelection && window.getSelection();
    if (sel && sel.removeAllRanges) sel.removeAllRanges();
    const svg = $("plan-editor-svg");
    const p = svgPoint(svg, evt);
    const hit = hitTarget(evt);

    // Middle button or Alt+drag → pan
    if (evt.button === 1 || (evt.button === 0 && evt.altKey)) {
      const vb = currentViewBox();
      const rect = svg.getBoundingClientRect();
      state.drag = {
        type: "pan",
        clientX0: evt.clientX,
        clientY0: evt.clientY,
        orig: vb,
        scaleX: vb.w / Math.max(1, rect.width),
        scaleY: vb.h / Math.max(1, rect.height),
      };
      svg.setPointerCapture(evt.pointerId);
      return;
    }

    if (state.tool === "delete") {
      if (hit && hit.kind && hit.kind !== "handle" && hit.kind !== "envelope") {
        selectItem(hit.kind, hit.id);
        deleteSelected();
      }
      return;
    }

    if (state.tool === "rect" && state.plan.mode === "free") {
      const env = state.plan.envelope;
      const start = clampPointInEnvelope(p.x, p.y, env);
      state.drag = {
        type: "draw-rect",
        x0: start.x,
        y0: start.y,
        preview: null,
      };
      svg.setPointerCapture(evt.pointerId);
      return;
    }

    if (state.tool === "wall" && state.plan.mode === "partition") {
      const start = clampPointInEnvelope(p.x, p.y, state.plan.envelope);
      state.drag = { type: "draw-wall", x0: start.x, y0: start.y };
      svg.setPointerCapture(evt.pointerId);
      return;
    }

    if (state.tool === "opening") {
      const start = clampPointInEnvelope(p.x, p.y, state.plan.envelope);
      state.drag = { type: "draw-opening", x0: start.x, y0: start.y };
      svg.setPointerCapture(evt.pointerId);
      return;
    }

    // select tool
    if (hit && hit.kind === "handle" && state.selectedKind) {
      const rect =
        state.selectedKind === "envelope"
          ? state.plan.envelope
          : ((state.selectedKind === "shape" ? state.plan.shapes : state.plan.faces) || []).find(
              (x) => x.id === state.selectedId
            );
      if (!rect) return;
      const mpu = metersPerUnit();
      const lockedCanvas =
        state.selectedKind === "shape" && rect.area_locked
          ? Number(rect.area_m2) > 0
            ? Number(rect.area_m2) / (mpu * mpu)
            : Number(rect.w) * Number(rect.h)
          : null;
      captureBeforeEdit();
      state.drag = {
        type: "resize",
        handle: hit.handle,
        orig: { ...rect },
        kind: state.selectedKind,
        id: state.selectedId,
        lockedCanvasArea: lockedCanvas,
      };
      svg.setPointerCapture(evt.pointerId);
      return;
    }

    if (hit && (hit.kind === "shape" || hit.kind === "face" || hit.kind === "envelope")) {
      selectItem(hit.kind, hit.id);
      const rect =
        hit.kind === "envelope"
          ? state.plan.envelope
          : ((hit.kind === "shape" ? state.plan.shapes : state.plan.faces) || []).find(
              (x) => x.id === hit.id
            );
      if (!rect) return;
      // Faces move by editing walls in partition mode — allow room select only
      if (hit.kind === "face") return;
      captureBeforeEdit();
      state.drag = {
        type: "move",
        x0: p.x,
        y0: p.y,
        orig: { x: rect.x, y: rect.y, w: rect.w, h: rect.h },
        lastX: rect.x,
        lastY: rect.y,
        kind: hit.kind,
        id: hit.id,
      };
      svg.setPointerCapture(evt.pointerId);
      return;
    }

    if (hit && (hit.kind === "wall" || hit.kind === "opening")) {
      selectItem(hit.kind, hit.id);
      return;
    }

    state.selectedId = null;
    state.selectedKind = null;
    renderSvg();
  }

  function onPointerMove(evt) {
    if (!state.drag || !state.plan) return;
    const svg = $("plan-editor-svg");
    const p = svgPoint(svg, evt);
    const drag = state.drag;
    const guides = rectGuides(state.plan, drag.id);

    if (drag.type === "pan") {
      const dx = (evt.clientX - drag.clientX0) * drag.scaleX;
      const dy = (evt.clientY - drag.clientY0) * drag.scaleY;
      state.viewBox = {
        x: drag.orig.x - dx,
        y: drag.orig.y - dy,
        w: drag.orig.w,
        h: drag.orig.h,
      };
      applyViewBox();
      return;
    }

    if (drag.type === "draw-rect" || drag.type === "draw-wall" || drag.type === "draw-opening") {
      const env = state.plan.envelope;
      const pt = clampPointInEnvelope(p.x, p.y, env);
      let x1 = drag.x0;
      let y1 = drag.y0;
      let x2 = pt.x;
      let y2 = pt.y;
      if (drag.type !== "draw-rect") {
        // Axis-align wall/opening
        if (Math.abs(x2 - x1) >= Math.abs(y2 - y1)) y2 = y1;
        else x2 = x1;
        const seg = clampSegmentInEnvelope(x1, y1, x2, y2, env);
        x1 = seg.x1;
        y1 = seg.y1;
        x2 = seg.x2;
        y2 = seg.y2;
      }
      drag.x1 = x1;
      drag.y1 = y1;
      drag.x2 = x2;
      drag.y2 = y2;
      let preview = svg.querySelector(".plan-preview");
      if (!preview) {
        preview = svgEl(
          drag.type === "draw-rect" ? "rect" : "line",
          { class: "plan-preview" }
        );
        svg.appendChild(preview);
      }
      if (drag.type === "draw-rect") {
        let r = normalizeRect(x1, y1, x2 - x1, y2 - y1);
        r = clampRectInEnvelope(r, env);
        preview.setAttribute("x", r.x);
        preview.setAttribute("y", r.y);
        preview.setAttribute("width", r.w);
        preview.setAttribute("height", r.h);
      } else {
        preview.setAttribute("x1", x1);
        preview.setAttribute("y1", y1);
        preview.setAttribute("x2", x2);
        preview.setAttribute("y2", y2);
      }
      return;
    }

    if (drag.type === "move") {
      const dx = p.x - drag.x0;
      const dy = p.y - drag.y0;
      let nx = snap(drag.orig.x + dx, guides);
      let ny = snap(drag.orig.y + dy, guides);
      const target =
        drag.kind === "envelope"
          ? state.plan.envelope
          : (state.plan.shapes || []).find((x) => x.id === drag.id);
      if (!target) return;
      if (drag.kind === "envelope") {
        const shiftX = nx - (drag.lastX ?? target.x);
        const shiftY = ny - (drag.lastY ?? target.y);
        target.x = nx;
        target.y = ny;
        drag.lastX = nx;
        drag.lastY = ny;
        if (shiftX || shiftY) {
          for (const s of state.plan.shapes || []) {
            s.x += shiftX;
            s.y += shiftY;
          }
          for (const w of state.plan.walls || []) {
            w.x1 += shiftX;
            w.y1 += shiftY;
            w.x2 += shiftX;
            w.y2 += shiftY;
          }
          for (const f of state.plan.faces || []) {
            f.x += shiftX;
            f.y += shiftY;
          }
          for (const op of state.plan.openings || []) {
            op.x1 += shiftX;
            op.y1 += shiftY;
            op.x2 += shiftX;
            op.y2 += shiftY;
          }
        }
      } else {
        const c = clampRectInEnvelope(
          { x: nx, y: ny, w: drag.orig.w, h: drag.orig.h },
          state.plan.envelope
        );
        target.x = c.x;
        target.y = c.y;
      }
      state.dirty = true;
      renderSvg();
      return;
    }

    if (drag.type === "resize") {
      const o = drag.orig;
      let x = o.x;
      let y = o.y;
      let w = o.w;
      let h = o.h;
      const hx = snap(p.x, guides);
      const hy = snap(p.y, guides);
      const handle = drag.handle;
      if (handle.includes("w")) {
        w = o.x + o.w - hx;
        x = hx;
      }
      if (handle.includes("e")) w = hx - o.x;
      if (handle.includes("n")) {
        h = o.y + o.h - hy;
        y = hy;
      }
      if (handle.includes("s")) h = hy - o.y;
      let r = normalizeRect(x, y, w, h);
      const target =
        drag.kind === "envelope"
          ? state.plan.envelope
          : drag.kind === "shape"
            ? (state.plan.shapes || []).find((x) => x.id === drag.id)
            : null;
      if (!target) return;
      if (drag.kind === "shape" && target.area_locked) {
        const lockedCanvas =
          drag.lockedCanvasArea != null
            ? drag.lockedCanvasArea
            : Number(o.w) * Number(o.h);
        r = applyLockedCanvasArea(r, lockedCanvas, handle, o);
        r = clampLockedRectInEnvelope(
          r,
          state.plan.envelope,
          lockedCanvas,
          handle,
          o
        );
      } else if (drag.kind === "shape") {
        r = clampRectInEnvelope(r, state.plan.envelope);
      }
      target.x = r.x;
      target.y = r.y;
      target.w = r.w;
      target.h = r.h;
      if (drag.kind === "envelope") {
        constrainContentsToEnvelope();
      }
      state.dirty = true;
      renderSvg();
      return;
    }
  }

  function inferOpeningRooms(x1, y1, x2, y2) {
    const plan = state.plan;
    const items = plan.mode === "free" ? plan.shapes : plan.faces;
    const named = (items || []).filter((s) => (s.room_id || "").trim());
    const midX = (x1 + x2) / 2;
    const midY = (y1 + y2) / 2;
    const vertical = Math.abs(x2 - x1) < 1;
    const hits = [];
    for (const s of named) {
      if (vertical) {
        const onEdge =
          Math.abs(midX - s.x) < SNAP || Math.abs(midX - (s.x + s.w)) < SNAP;
        const along = midY >= s.y - SNAP && midY <= s.y + s.h + SNAP;
        if (onEdge && along) hits.push(s.room_id);
      } else {
        const onEdge =
          Math.abs(midY - s.y) < SNAP || Math.abs(midY - (s.y + s.h)) < SNAP;
        const along = midX >= s.x - SNAP && midX <= s.x + s.w + SNAP;
        if (onEdge && along) hits.push(s.room_id);
      }
    }
    const uniq = [...new Set(hits)];
    if (uniq.length >= 2) return { room_a: uniq[0], room_b: uniq[1] };
    if (uniq.length === 1) return { room_a: uniq[0], room_b: "outdoor" };
    return { room_a: "", room_b: "outdoor" };
  }

  function onPointerUp(evt) {
    if (!state.drag || !state.plan) return;
    const drag = state.drag;
    state.drag = null;
    const svg = $("plan-editor-svg");
    const preview = svg && svg.querySelector(".plan-preview");
    if (preview) preview.remove();

    if (drag.type === "draw-rect") {
      let r = normalizeRect(
        drag.x0,
        drag.y0,
        (drag.x2 ?? drag.x0) - drag.x0,
        (drag.y2 ?? drag.y0) - drag.y0
      );
      r = clampRectInEnvelope(r, state.plan.envelope);
      if (r.w < MIN_SIZE || r.h < MIN_SIZE) return;
      captureBeforeEdit();
      const shape = {
        id: uid("shape"),
        type: "rect",
        room_id: "",
        label: "",
        x: r.x,
        y: r.y,
        w: r.w,
        h: r.h,
        area_locked: false,
      };
      state.plan.shapes = state.plan.shapes || [];
      state.plan.shapes.push(shape);
      state.dirty = true;
      state.tool = "select";
      selectItem("shape", shape.id);
      renderToolbar();
      setStatus("Select a room in the list, then Assign");
      return;
    }

    if (drag.type === "draw-wall") {
      let x1 = drag.x0;
      let y1 = drag.y0;
      let x2 = drag.x2 ?? drag.x0;
      let y2 = drag.y2 ?? drag.y0;
      if (Math.abs(x2 - x1) >= Math.abs(y2 - y1)) y2 = y1;
      else x2 = x1;
      const seg = clampSegmentInEnvelope(x1, y1, x2, y2, state.plan.envelope);
      x1 = seg.x1;
      y1 = seg.y1;
      x2 = seg.x2;
      y2 = seg.y2;
      if (Math.hypot(x2 - x1, y2 - y1) < MIN_SIZE) return;
      captureBeforeEdit();
      const wall = { id: uid("wall"), x1, y1, x2, y2 };
      state.plan.walls = state.plan.walls || [];
      state.plan.walls.push(wall);
      refreshPartitionFaces();
      state.dirty = true;
      state.tool = "select";
      selectItem("wall", wall.id);
      renderToolbar();
      return;
    }

    if (drag.type === "draw-opening") {
      let x1 = drag.x0;
      let y1 = drag.y0;
      let x2 = drag.x2 ?? drag.x0;
      let y2 = drag.y2 ?? drag.y0;
      if (Math.abs(x2 - x1) >= Math.abs(y2 - y1)) y2 = y1;
      else x2 = x1;
      const seg = clampSegmentInEnvelope(x1, y1, x2, y2, state.plan.envelope);
      x1 = seg.x1;
      y1 = seg.y1;
      x2 = seg.x2;
      y2 = seg.y2;
      if (Math.hypot(x2 - x1, y2 - y1) < MIN_SIZE / 2) return;
      captureBeforeEdit();
      const rooms = inferOpeningRooms(x1, y1, x2, y2);
      const op = {
        id: uid("open"),
        kind: "door",
        x1,
        y1,
        x2,
        y2,
        room_a: rooms.room_a,
        room_b: rooms.room_b,
      };
      state.plan.openings = state.plan.openings || [];
      state.plan.openings.push(op);
      state.dirty = true;
      state.tool = "select";
      selectItem("opening", op.id);
      renderToolbar();
      return;
    }

    if (drag.type === "move" || drag.type === "resize") {
      // Drop empty gestures (click without geometry change).
      const last = state.undoStack[state.undoStack.length - 1];
      if (
        last &&
        JSON.stringify(last.plan) === JSON.stringify(clonePlanSnapshot(state.plan))
      ) {
        state.undoStack.pop();
        state.dirty = !!last.dirty;
      } else {
        state.dirty = true;
      }
      renderSvg();
    }
  }

  // --- CRUD -----------------------------------------------------------------

  async function refreshList() {
    const data = await api("/api/apartment/plans");
    state.plans = data.plans || [];
    state.activePlanId = data.active_plan_id || null;
    state.roomOptions = data.room_options || [];
    renderPlanSelect();
    updateActionButtons();
    const meta = $("plan-editor-meta");
    if (meta) {
      const active = state.plans.find((p) => p.id === state.activePlanId);
      const t =
        window.I18n && typeof window.I18n.t === "function"
          ? window.I18n.t.bind(window.I18n)
          : (k, vars) => k;
      if (active) {
        meta.textContent = t("map.plan.metaActive", {
          name: active.name,
          mode: active.mode,
        });
        if (meta.textContent === "map.plan.metaActive") {
          meta.textContent = `Active: ${active.name} (${active.mode})`;
        }
      } else {
        meta.textContent = t("map.plan.metaIdle");
        if (meta.textContent === "map.plan.metaIdle") {
          meta.textContent = "Create a plan or select one to edit";
        }
      }
    }
  }

  async function loadPlan(id) {
    clearHistory();
    state.viewBox = null;
    if (!id) {
      state.plan = null;
      state.selectedId = null;
      state.selectedKind = null;
      state.dirty = false;
      renderToolbar();
      renderSvg();
      renderProps();
      updateActionButtons();
      return;
    }
    const plan = await api(`/api/apartment/plans/${encodeURIComponent(id)}`);
    state.plan = plan;
    if (plan.mode === "partition") refreshPartitionFaces();
    constrainContentsToEnvelope();
    state.selectedId = null;
    state.selectedKind = null;
    state.dirty = false;
    state.tool = "select";
    renderToolbar();
    renderSvg();
    setStatus(`Loaded “${plan.name}” (${plan.mode})`);
  }

  async function savePlan() {
    if (!state.plan) return;
    const body = {
      name: state.plan.name,
      north_deg: state.plan.north_deg,
      meters_per_unit: state.plan.meters_per_unit,
      envelope: state.plan.envelope,
      shapes: state.plan.shapes || [],
      walls: state.plan.walls || [],
      faces: state.plan.faces || [],
      openings: state.plan.openings || [],
    };
    const updated = await api(`/api/apartment/plans/${encodeURIComponent(state.plan.id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    state.plan = updated;
    state.dirty = false;
    await refreshList();
    renderSvg();
    setStatus("Saved");
    if (state.plan.id === state.activePlanId && opts && opts.onLayoutChanged) {
      await opts.onLayoutChanged();
    }
  }

  async function createPlan() {
    const nameEl = $("plan-editor-new-name");
    const modeEl = $("plan-editor-new-mode");
    const name = (nameEl && nameEl.value.trim()) || "New plan";
    const mode = (modeEl && modeEl.value) || "free";
    const plan = await api("/api/apartment/plans", {
      method: "POST",
      body: JSON.stringify({ name, mode }),
    });
    await refreshList();
    const sel = $("plan-editor-select");
    if (sel) sel.value = plan.id;
    await loadPlan(plan.id);
    setStatus(`Created “${plan.name}” — mode ${plan.mode} is locked`);
  }

  async function activatePlan() {
    if (!state.plan) return;
    if (state.dirty) await savePlan();
    const res = await api(
      `/api/apartment/plans/${encodeURIComponent(state.plan.id)}/activate`,
      { method: "POST", body: "{}" }
    );
    state.activePlanId = res.active_plan_id;
    await refreshList();
    const warns = (res.compiled && res.compiled.warnings) || [];
    setStatus(
      warns.length
        ? `Activated — ${warns.join(" ")}`
        : `Activated “${state.plan.name}”`
    );
    if (opts && opts.onLayoutChanged) await opts.onLayoutChanged();
  }

  async function deactivatePlan() {
    if (!state.plan) return;
    await api(
      `/api/apartment/plans/${encodeURIComponent(state.plan.id)}/deactivate`,
      { method: "POST", body: "{}" }
    );
    state.activePlanId = null;
    await refreshList();
    setStatus("Deactivated — restored config layout");
    if (opts && opts.onLayoutChanged) await opts.onLayoutChanged();
  }

  async function duplicatePlan() {
    if (!state.plan) return;
    const clone = await api(
      `/api/apartment/plans/${encodeURIComponent(state.plan.id)}/duplicate`,
      { method: "POST", body: "{}" }
    );
    await refreshList();
    const sel = $("plan-editor-select");
    if (sel) sel.value = clone.id;
    await loadPlan(clone.id);
    setStatus(`Duplicated as “${clone.name}”`);
  }

  async function deletePlan() {
    if (!state.plan) return;
    if (!window.confirm(`Delete plan “${state.plan.name}”?`)) return;
    const id = state.plan.id;
    await api(`/api/apartment/plans/${encodeURIComponent(id)}`, { method: "DELETE" });
    state.plan = null;
    clearHistory();
    await refreshList();
    renderToolbar();
    renderSvg();
    renderProps();
    setStatus("Plan deleted");
    if (opts && opts.onLayoutChanged) await opts.onLayoutChanged();
  }

  function bind() {
    document.removeEventListener("keydown", onEditorKeyDown);
    document.addEventListener("keydown", onEditorKeyDown);
    const svg = $("plan-editor-svg");
    if (svg) {
      svg.addEventListener("pointerdown", onPointerDown);
      svg.addEventListener("pointermove", onPointerMove);
      svg.addEventListener("pointerup", onPointerUp);
      svg.addEventListener("pointercancel", onPointerUp);
      svg.addEventListener("wheel", onWheelZoom, { passive: false });
      svg.addEventListener("selectstart", (evt) => evt.preventDefault());
      svg.addEventListener("dragstart", (evt) => evt.preventDefault());
      svg.addEventListener("auxclick", (evt) => {
        if (evt.button === 1) evt.preventDefault();
      });
    }
    const zoomIn = $("plan-zoom-in");
    if (zoomIn) {
      zoomIn.addEventListener("click", () => zoomBy(1 / 1.25));
    }
    const zoomOut = $("plan-zoom-out");
    if (zoomOut) {
      zoomOut.addEventListener("click", () => zoomBy(1.25));
    }
    const zoomReset = $("plan-zoom-reset");
    if (zoomReset) {
      zoomReset.addEventListener("click", () => resetView());
    }
    const sel = $("plan-editor-select");
    if (sel) {
      sel.addEventListener("change", async () => {
        try {
          if (state.dirty && state.plan) {
            if (!window.confirm("Discard unsaved changes?")) {
              sel.value = state.plan.id;
              return;
            }
          }
          await loadPlan(sel.value);
        } catch (err) {
          setStatus(String(err.message || err));
        }
      });
    }
    const createBtn = $("plan-editor-create");
    if (createBtn) {
      createBtn.addEventListener("click", () =>
        createPlan().catch((err) => setStatus(String(err.message || err)))
      );
    }
    const saveBtn = $("plan-editor-save");
    if (saveBtn) {
      saveBtn.addEventListener("click", () =>
        savePlan().catch((err) => setStatus(String(err.message || err)))
      );
    }
    const actBtn = $("plan-editor-activate");
    if (actBtn) {
      actBtn.addEventListener("click", () =>
        activatePlan().catch((err) => setStatus(String(err.message || err)))
      );
    }
    const deactBtn = $("plan-editor-deactivate");
    if (deactBtn) {
      deactBtn.addEventListener("click", () =>
        deactivatePlan().catch((err) => setStatus(String(err.message || err)))
      );
    }
    const dupBtn = $("plan-editor-duplicate");
    if (dupBtn) {
      dupBtn.addEventListener("click", () =>
        duplicatePlan().catch((err) => setStatus(String(err.message || err)))
      );
    }
    const delBtn = $("plan-editor-delete");
    if (delBtn) {
      delBtn.addEventListener("click", () =>
        deletePlan().catch((err) => setStatus(String(err.message || err)))
      );
    }
  }

  async function init(options) {
    opts = options || {};
    state = createState();
    bind();
    try {
      await refreshList();
      setStatus("Create a plan or select one to edit");
    } catch (err) {
      setStatus(String(err.message || err));
    }
  }

  window.GoveePlanEditor = { init };
})();
