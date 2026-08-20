/**
 * Apartment floor-plan editor (free rectangles or partition walls).
 * Exposes window.GoveePlanEditor.init({ onLayoutChanged }).
 */
(function () {
  "use strict";

  const SNAP = 8;
  const MIN_SIZE = 16;
  const HANDLE = 7;

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
    };
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
  }

  function renderProps() {
    const panel = $("plan-editor-props");
    if (!panel) return;
    if (!state.plan) {
      panel.hidden = true;
      panel.replaceChildren();
      return;
    }
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
      state.plan.name = nameEl.value.trim() || "Untitled";
      state.dirty = true;
      renderPlanSelect();
    });
    northEl.addEventListener("change", () => {
      state.plan.north_deg = ((Number(northEl.value) || 0) % 360 + 360) % 360;
      state.dirty = true;
    });
    mpuEl.addEventListener("change", () => {
      const v = Number(mpuEl.value);
      if (v > 0) {
        state.plan.meters_per_unit = v;
        state.dirty = true;
      }
    });

    const selKind = state.selectedKind;
    const selId = state.selectedId;
    if (!selKind || !selId) return;

    if (selKind === "shape" || selKind === "face") {
      const list = selKind === "shape" ? state.plan.shapes : state.plan.faces;
      const item = (list || []).find((x) => x.id === selId);
      if (!item) return;
      const block = document.createElement("div");
      block.className = "plan-props-block";
      const label = document.createElement("label");
      label.textContent = "Room id ";
      const select = document.createElement("select");
      select.id = "plan-prop-room";
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "(unassigned)";
      select.appendChild(empty);
      for (const r of state.roomOptions) {
        const opt = document.createElement("option");
        opt.value = r.id;
        opt.textContent = `${r.label} (${r.id})`;
        if (item.room_id === r.id) opt.selected = true;
        select.appendChild(opt);
      }
      // Keep current value even if not in taxonomy
      if (item.room_id && ![...select.options].some((o) => o.value === item.room_id)) {
        const opt = document.createElement("option");
        opt.value = item.room_id;
        opt.textContent = item.room_id;
        opt.selected = true;
        select.appendChild(opt);
      }
      select.addEventListener("change", () => {
        const rid = select.value.trim().toLowerCase();
        const others = (list || []).filter((x) => x.id !== item.id);
        if (rid && others.some((x) => (x.room_id || "").toLowerCase() === rid)) {
          setStatus(`Room id "${rid}" already used in this plan`);
          select.value = item.room_id || "";
          return;
        }
        item.room_id = rid;
        const opt = state.roomOptions.find((r) => r.id === rid);
        item.label = opt ? opt.label : item.label || "";
        state.dirty = true;
        renderSvg();
      });
      label.appendChild(select);
      block.appendChild(label);
      if (!item.room_id) {
        const warn = document.createElement("p");
        warn.className = "plan-props-warn";
        warn.textContent = "Assign a logical room id (e.g. bedroom, corridor).";
        block.appendChild(warn);
      }
      panel.appendChild(block);
    }

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
        op.kind = kindSel.value;
        state.dirty = true;
        renderSvg();
      });
      kindLabel.appendChild(kindSel);
      block.appendChild(kindLabel);

      const rooms = namedRooms(state.plan);
      for (const field of ["room_a", "room_b"]) {
        const lab = document.createElement("label");
        lab.textContent = field === "room_a" ? "Room A " : "Room B ";
        const sel = document.createElement("select");
        const out = document.createElement("option");
        out.value = "outdoor";
        out.textContent = "outdoor";
        sel.appendChild(out);
        for (const r of rooms) {
          const opt = document.createElement("option");
          opt.value = r;
          opt.textContent = r;
          sel.appendChild(opt);
        }
        sel.value = op[field] || "outdoor";
        sel.addEventListener("change", () => {
          op[field] = sel.value;
          state.dirty = true;
        });
        lab.appendChild(sel);
        block.appendChild(lab);
      }
      panel.appendChild(block);
    }
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
    const pad = 40;
    const vbX = env.x - pad;
    const vbY = env.y - pad;
    const vbW = env.w + pad * 2;
    const vbH = env.h + pad * 2;
    svg.setAttribute("viewBox", `${vbX} ${vbY} ${vbW} ${vbH}`);
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
    const t = svgEl("text", {
      x: item.x + item.w / 2,
      y: item.y + item.h / 2,
      class: "plan-room-label",
      "data-kind": kind,
      "data-id": item.id,
    });
    t.textContent = label;
    g.appendChild(t);
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
    } else if (state.selectedKind === "envelope") {
      setStatus("Envelope cannot be deleted — resize it instead");
      return;
    }
    state.selectedId = null;
    state.selectedKind = null;
    state.dirty = true;
    renderSvg();
  }

  function onPointerDown(evt) {
    if (!state.plan) return;
    const svg = $("plan-editor-svg");
    const p = svgPoint(svg, evt);
    const hit = hitTarget(evt);

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
      state.drag = {
        type: "resize",
        handle: hit.handle,
        orig: { ...rect },
        kind: state.selectedKind,
        id: state.selectedId,
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
      if (drag.kind === "shape") {
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
      const shape = {
        id: uid("shape"),
        type: "rect",
        room_id: "",
        label: "",
        x: r.x,
        y: r.y,
        w: r.w,
        h: r.h,
      };
      state.plan.shapes = state.plan.shapes || [];
      state.plan.shapes.push(shape);
      state.dirty = true;
      state.tool = "select";
      selectItem("shape", shape.id);
      renderToolbar();
      setStatus("Assign a room id in the properties panel");
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
      state.dirty = true;
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
    await refreshList();
    renderToolbar();
    renderSvg();
    renderProps();
    setStatus("Plan deleted");
    if (opts && opts.onLayoutChanged) await opts.onLayoutChanged();
  }

  function bind() {
    const svg = $("plan-editor-svg");
    if (svg) {
      svg.addEventListener("pointerdown", onPointerDown);
      svg.addEventListener("pointermove", onPointerMove);
      svg.addEventListener("pointerup", onPointerUp);
      svg.addEventListener("pointercancel", onPointerUp);
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
