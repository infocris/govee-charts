(() => {
  const deviceList = document.getElementById("device-list");
  const currentEl = document.getElementById("current");
  const statusEl = document.getElementById("status");
  const overviewBody = document.getElementById("overview-body");
  const overviewStatus = document.getElementById("overview-status");
  const modelFiltersEl = document.getElementById("model-filters");
  const compareModelFiltersEl = document.getElementById("compare-model-filters");
  const nodeLineEl = document.getElementById("node-line");
  const peerLinksEl = document.getElementById("peer-links");
  const viewOverview = document.getElementById("view-overview");
  const viewCompare = document.getElementById("view-compare");
  const selectAllBtn = document.getElementById("select-all");
  const selectNoneBtn = document.getElementById("select-none");
  const rangeButtons = [...document.querySelectorAll(".ranges button")];
  const viewButtons = [...document.querySelectorAll(".views [data-view]")];
  const sortButtons = [...document.querySelectorAll(".sort-btn")];
  const restartBtn = document.getElementById("restart-btn");
  const restartStatusEl = document.getElementById("restart-status");

  const PALETTE = [
    "#e8a87c",
    "#7cb8e8",
    "#6fbf73",
    "#d4a5e8",
    "#e8d07c",
    "#7ce8d0",
    "#e87c9a",
    "#a5b4e8",
  ];

  const STORAGE_KEY = "govee-charts.selected";
  const VIEW_KEY = "govee-charts.view";
  const MODEL_KEY = "govee-charts.model";
  const SORT_KEY = "govee-charts.sort";
  const FORECAST_KEY = "govee-charts.forecast";
  const GEO_KEY = "govee-charts.geo";
  const CAT_FILTER_KEY = "govee-charts.catFilters";

  let hours = 24;
  let devices = [];
  let taxonomyData = { zones: [], heights: [], rooms: [] };
  let selected = new Set();
  let modelFilter = localStorage.getItem(MODEL_KEY) || "all";
  let catFilters = loadCatFilters();
  let sortState = loadSortState();
  let currentView = localStorage.getItem(VIEW_KEY) === "compare" ? "compare" : "overview";
  let showForecast = localStorage.getItem(FORECAST_KEY) !== "0";
  /** @type {{latitude:number, longitude:number, accuracy?:number, at?:number}|null} */
  let browserGeo = loadStoredGeo();
  let geoStatus = browserGeo ? "cached" : "idle";
  let tempChart = null;
  let humChart = null;
  let dewChart = null;
  let historyLoaded = false;
  let localNodeId = "";
  /** @type {Map<string, string>} node_id → url */
  let peerByNodeId = new Map();
  const showForecastEl = document.getElementById("show-forecast");
  const projectionsEl = document.getElementById("projections");
  const locateBtn = document.getElementById("locate-btn");
  const geoStatusEl = document.getElementById("geo-status");
  const zoneFiltersEl = document.getElementById("zone-filters");
  const heightFiltersEl = document.getElementById("height-filters");
  const roomFiltersEl = document.getElementById("room-filters");
  const compareZoneFiltersEl = document.getElementById("compare-zone-filters");
  const compareHeightFiltersEl = document.getElementById("compare-height-filters");
  const compareRoomFiltersEl = document.getElementById("compare-room-filters");

  const chartDefaults = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    scales: {
      x: {
        type: "time",
        time: { tooltipFormat: "dd/MM HH:mm" },
        ticks: { color: "#8a9a88", maxRotation: 0 },
        grid: { color: "rgba(42,53,44,0.7)" },
      },
      y: {
        ticks: { color: "#8a9a88" },
        grid: { color: "rgba(42,53,44,0.7)" },
      },
    },
    plugins: {
      legend: {
        display: true,
        position: "top",
        align: "start",
        labels: {
          color: "#8a9a88",
          boxWidth: 12,
          boxHeight: 12,
          padding: 12,
          usePointStyle: true,
          pointStyle: "line",
        },
      },
      tooltip: {
        backgroundColor: "#1a221c",
        titleColor: "#e8efe6",
        bodyColor: "#e8efe6",
        borderColor: "#2a352c",
        borderWidth: 1,
      },
    },
  };

  function loadStoredGeo() {
    try {
      const raw = localStorage.getItem(GEO_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (
        !parsed ||
        typeof parsed.latitude !== "number" ||
        typeof parsed.longitude !== "number"
      ) {
        return null;
      }
      return parsed;
    } catch {
      return null;
    }
  }

  function persistGeo(geo) {
    browserGeo = geo;
    if (geo) {
      localStorage.setItem(GEO_KEY, JSON.stringify(geo));
    } else {
      localStorage.removeItem(GEO_KEY);
    }
    updateGeoStatus();
  }

  function updateGeoStatus() {
    if (!geoStatusEl) return;
    if (!showForecast) {
      geoStatusEl.textContent = "";
      return;
    }
    if (geoStatus === "pending") {
      geoStatusEl.textContent = "Locating…";
      return;
    }
    if (geoStatus === "denied") {
      geoStatusEl.textContent = "Location denied — using config fallback";
      return;
    }
    if (geoStatus === "unavailable") {
      geoStatusEl.textContent =
        "Geolocation unavailable (needs HTTPS or localhost)";
      return;
    }
    if (geoStatus === "error") {
      geoStatusEl.textContent = "Location failed — using config fallback";
      return;
    }
    if (browserGeo) {
      geoStatusEl.textContent = `GPS ${browserGeo.latitude.toFixed(3)}, ${browserGeo.longitude.toFixed(3)}`;
      return;
    }
    geoStatusEl.textContent = "No GPS — config fallback";
  }

  function requestBrowserGeo(force = false) {
    return new Promise((resolve) => {
      if (!showForecast) {
        resolve(browserGeo);
        return;
      }
      if (!force && browserGeo && browserGeo.at && Date.now() - browserGeo.at < 30 * 60 * 1000) {
        geoStatus = "cached";
        updateGeoStatus();
        resolve(browserGeo);
        return;
      }
      if (!navigator.geolocation) {
        geoStatus = "unavailable";
        updateGeoStatus();
        resolve(null);
        return;
      }
      // Non-secure LAN origins (http://192.168.x) usually block geolocation.
      if (
        typeof window.isSecureContext === "boolean" &&
        !window.isSecureContext &&
        location.hostname !== "localhost" &&
        location.hostname !== "127.0.0.1"
      ) {
        geoStatus = "unavailable";
        updateGeoStatus();
        resolve(browserGeo);
        return;
      }

      geoStatus = "pending";
      updateGeoStatus();
      if (locateBtn) locateBtn.disabled = true;

      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const geo = {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            at: Date.now(),
          };
          geoStatus = "ok";
          persistGeo(geo);
          if (locateBtn) locateBtn.disabled = false;
          resolve(geo);
        },
        (err) => {
          geoStatus = err && err.code === 1 ? "denied" : "error";
          updateGeoStatus();
          if (locateBtn) locateBtn.disabled = false;
          resolve(browserGeo);
        },
        {
          enableHighAccuracy: false,
          timeout: 12000,
          maximumAge: 15 * 60 * 1000,
        }
      );
    });
  }

  function loadCatFilters() {
    try {
      const raw = localStorage.getItem(CAT_FILTER_KEY);
      if (!raw) return { zone: "all", height: "all", room: "all" };
      const parsed = JSON.parse(raw);
      return {
        zone: parsed.zone || "all",
        height: parsed.height || "all",
        room: parsed.room || "all",
      };
    } catch {
      return { zone: "all", height: "all", room: "all" };
    }
  }

  function persistCatFilters() {
    localStorage.setItem(CAT_FILTER_KEY, JSON.stringify(catFilters));
  }

  function loadPersistedSelection() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : null;
    } catch {
      return null;
    }
  }

  function persistSelection() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...selected]));
  }

  function loadSortState() {
    try {
      const raw = localStorage.getItem(SORT_KEY);
      if (!raw) return { key: "temperature_c", dir: "desc" };
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed.key !== "string") {
        return { key: "temperature_c", dir: "desc" };
      }
      return {
        key: parsed.key,
        dir: parsed.dir === "asc" ? "asc" : "desc",
      };
    } catch {
      return { key: "temperature_c", dir: "desc" };
    }
  }

  function persistSortState() {
    localStorage.setItem(SORT_KEY, JSON.stringify(sortState));
  }

  function persistModelFilter() {
    localStorage.setItem(MODEL_KEY, modelFilter);
  }

  function peerHostLabel(url) {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  async function probePeer(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    try {
      const res = await fetch(`${url}/api/health`, { signal: controller.signal });
      if (!res.ok) return { url, node_id: peerHostLabel(url), online: false };
      const data = await res.json();
      return {
        url,
        node_id: data.node_id || peerHostLabel(url),
        online: true,
      };
    } catch {
      return { url, node_id: peerHostLabel(url), online: false };
    } finally {
      clearTimeout(timer);
    }
  }

  function renderPeers(peers) {
    peerByNodeId = new Map();
    for (const peer of peers) {
      if (peer.node_id) peerByNodeId.set(peer.node_id, peer.url);
    }

    if (localNodeId && nodeLineEl) {
      nodeLineEl.hidden = false;
      nodeLineEl.textContent = `Node · ${localNodeId}`;
    }

    if (!peerLinksEl) return;
    peerLinksEl.innerHTML = "";
    if (!peers.length) {
      peerLinksEl.hidden = true;
      return;
    }
    peerLinksEl.hidden = false;
    for (const peer of peers) {
      const a = document.createElement("a");
      a.href = peer.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = peer.node_id;
      a.title = peer.url;
      if (!peer.online) a.classList.add("offline");
      peerLinksEl.appendChild(a);
    }
  }

  async function loadFederation() {
    const res = await fetch("/api/federation");
    if (!res.ok) throw new Error(`federation HTTP ${res.status}`);
    const data = await res.json();
    localNodeId = data.node_id || "";
    const urls = (data.peers || []).map((p) => p.url).filter(Boolean);
    const peers = await Promise.all(urls.map(probePeer));
    renderPeers(peers);
  }

  function sourceHtml(source) {
    if (!source || source === "—") return "—";
    const url = peerByNodeId.get(source);
    if (!url) return escapeHtml(source);
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${escapeHtml(source)}</a>`;
  }

  function availableModels() {
    return [...new Set(devices.map((d) => (d.model || "").toLowerCase()).filter(Boolean))].sort();
  }

  function filteredDevices() {
    return devices.filter((d) => {
      if (modelFilter !== "all" && (d.model || "").toLowerCase() !== modelFilter) {
        return false;
      }
      if (catFilters.zone !== "all" && (d.zone || "") !== catFilters.zone) {
        return false;
      }
      if (catFilters.height !== "all" && (d.height || "") !== catFilters.height) {
        return false;
      }
      if (catFilters.room !== "all" && (d.room || "") !== catFilters.room) {
        return false;
      }
      return true;
    });
  }

  function colorFor(address) {
    const idx = devices.findIndex((d) => d.address === address);
    return PALETTE[(idx >= 0 ? idx : 0) % PALETTE.length];
  }

  function hexToRgba(hex, alpha) {
    const h = hex.replace("#", "");
    const n = parseInt(h, 16);
    const r = (n >> 16) & 255;
    const g = (n >> 8) & 255;
    const b = n & 255;
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function fmtNum(v, digits, suffix) {
    if (v == null || Number.isNaN(v)) return "—";
    return `${Number(v).toFixed(digits)}${suffix}`;
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString("en-GB", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function deviceLabel(device) {
    return device ? device.name : "—";
  }

  function selectedDevices() {
    return filteredDevices().filter((d) => selected.has(d.address));
  }

  function sortValue(device, key) {
    if (key === "name") return (device.name || "").toLowerCase();
    if (key === "last_source") return (device.last_source || "").toLowerCase();
    if (key === "zone" || key === "height" || key === "room") {
      return (device[key] || "").toLowerCase();
    }
    if (key === "last_reading_ts") {
      return device.last_reading_ts ?? device.last_seen ?? null;
    }
    return device[key] ?? null;
  }

  function sortedDevices(list) {
    const { key, dir } = sortState;
    const factor = dir === "asc" ? 1 : -1;
    return [...list].sort((a, b) => {
      const va = sortValue(a, key);
      const vb = sortValue(b, key);
      if (va == null && vb == null) {
        return a.name.localeCompare(b.name, "fr");
      }
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "string" && typeof vb === "string") {
        const cmp = va.localeCompare(vb, "fr");
        return cmp !== 0 ? cmp * factor : a.name.localeCompare(b.name, "fr");
      }
      if (va !== vb) return (va < vb ? -1 : 1) * factor;
      return a.name.localeCompare(b.name, "fr");
    });
  }

  function updateSortButtons() {
    for (const btn of sortButtons) {
      const active = btn.dataset.sort === sortState.key;
      btn.classList.toggle("active", active);
      btn.classList.toggle("asc", active && sortState.dir === "asc");
      btn.classList.toggle("desc", active && sortState.dir === "desc");
      btn.setAttribute(
        "aria-sort",
        active ? (sortState.dir === "asc" ? "ascending" : "descending") : "none"
      );
    }
  }

  function renderModelFilters(container) {
    if (!container) return;
    const models = availableModels();
    if (modelFilter !== "all" && !models.includes(modelFilter)) {
      modelFilter = "all";
      persistModelFilter();
    }
    container.innerHTML = "";
    const options = [{ id: "all", label: "All models" }].concat(
      models.map((m) => ({ id: m, label: m.toUpperCase() }))
    );
    for (const opt of options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.model = opt.id;
      btn.textContent = opt.label;
      btn.classList.toggle("active", modelFilter === opt.id);
      btn.addEventListener("click", () => {
        if (modelFilter === opt.id) return;
        modelFilter = opt.id;
        persistModelFilter();
        syncModelFilterButtons();
        fillDeviceList();
        updateOverview();
        updateCurrent();
        if (currentView === "compare") {
          loadHistory().catch((err) => {
            statusEl.textContent = `Error: ${err.message}`;
          });
        }
      });
      container.appendChild(btn);
    }
  }

  function syncModelFilterButtons() {
    renderModelFilters(modelFiltersEl);
    renderModelFilters(compareModelFiltersEl);
    renderAllCategoryFilters();
  }

  function categoryLabel(kind, id) {
    if (!id) return "—";
    const list =
      kind === "zone"
        ? taxonomyData.zones
        : kind === "height"
          ? taxonomyData.heights
          : taxonomyData.rooms;
    const hit = (list || []).find((x) => x.id === id);
    return hit ? hit.label : id;
  }

  function renderCategoryFilterRow(container, kind, options) {
    if (!container) return;
    container.dataset.label =
      kind === "zone" ? "Zone" : kind === "height" ? "Height" : "Room";
    container.innerHTML = "";
    const items = [{ id: "all", label: "All" }].concat(options || []);
    for (const opt of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.value = opt.id;
      btn.textContent = opt.label;
      btn.classList.toggle("active", catFilters[kind] === opt.id);
      btn.addEventListener("click", () => {
        if (catFilters[kind] === opt.id) return;
        catFilters[kind] = opt.id;
        persistCatFilters();
        renderAllCategoryFilters();
        fillDeviceList();
        updateOverview();
        updateCurrent();
        if (currentView === "compare") {
          loadHistory().catch((err) => {
            statusEl.textContent = `Error: ${err.message}`;
          });
        }
      });
      container.appendChild(btn);
    }
  }

  function renderAllCategoryFilters() {
    renderCategoryFilterRow(zoneFiltersEl, "zone", taxonomyData.zones);
    renderCategoryFilterRow(heightFiltersEl, "height", taxonomyData.heights);
    renderCategoryFilterRow(roomFiltersEl, "room", taxonomyData.rooms);
    renderCategoryFilterRow(compareZoneFiltersEl, "zone", taxonomyData.zones);
    renderCategoryFilterRow(compareHeightFiltersEl, "height", taxonomyData.heights);
    renderCategoryFilterRow(compareRoomFiltersEl, "room", taxonomyData.rooms);
  }

  function makeCategorySelect(device, field, options) {
    const select = document.createElement("select");
    select.className = "cat-select";
    select.dataset.address = device.address;
    select.dataset.field = field;
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "—";
    select.appendChild(empty);
    for (const opt of options || []) {
      const option = document.createElement("option");
      option.value = opt.id;
      option.textContent = opt.label;
      select.appendChild(option);
    }
    select.value = device[field] || "";
    select.addEventListener("click", (ev) => ev.stopPropagation());
    select.addEventListener("mousedown", (ev) => ev.stopPropagation());
    select.addEventListener("change", async (ev) => {
      ev.stopPropagation();
      const value = select.value === "" ? null : select.value;
      select.disabled = true;
      try {
        const res = await fetch(
          `/api/devices/${encodeURIComponent(device.address)}/categories`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ [field]: value }),
          }
        );
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const updated = await res.json();
        const idx = devices.findIndex((d) => d.address === device.address);
        if (idx >= 0) {
          devices[idx] = { ...devices[idx], ...updated };
        }
        fillDeviceList();
        updateOverview();
        updateCurrent();
      } catch (err) {
        console.error(err);
        select.value = device[field] || "";
        overviewStatus.textContent = `Category update failed: ${err.message}`;
      } finally {
        select.disabled = false;
      }
    });
    return select;
  }

  function setView(view) {
    currentView = view;
    localStorage.setItem(VIEW_KEY, view);
    const isOverview = view === "overview";
    viewOverview.hidden = !isOverview;
    viewCompare.hidden = isOverview;
    viewButtons.forEach((btn) => {
      const active = btn.dataset.view === view;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (!isOverview && !historyLoaded) {
      loadHistory().catch((err) => {
        statusEl.textContent = `Error: ${err.message}`;
      });
    } else if (!isOverview && tempChart && humChart) {
      tempChart.resize();
      humChart.resize();
      if (dewChart) dewChart.resize();
    }
  }

  /**
   * Magnus formula (August-Roche-Magnus approximation).
   * Returns dew point in °C.  Valid for −40 … +60 °C, 1 … 100 % RH.
   */
  function dewPoint(tempC, rh) {
    const a = 17.625;
    const b = 243.04; // °C
    const alpha = (a * tempC) / (b + tempC) + Math.log(rh / 100.0);
    return (b * alpha) / (a - alpha);
  }

  function ensureCharts() {
    if (tempChart && humChart && dewChart) return;
    tempChart = new Chart(document.getElementById("temp-chart"), {
      type: "line",
      data: { datasets: [] },
      options: structuredClone(chartDefaults),
    });
    humChart = new Chart(document.getElementById("hum-chart"), {
      type: "line",
      data: { datasets: [] },
      options: structuredClone(chartDefaults),
    });
    dewChart = new Chart(document.getElementById("dew-chart"), {
      type: "line",
      data: { datasets: [] },
      options: structuredClone(chartDefaults),
    });
  }

  function makeDataset(label, color, data, fill, extra = {}) {
    return {
      label,
      data,
      borderColor: color,
      backgroundColor: fill ? hexToRgba(color, 0.12) : "transparent",
      fill,
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2,
      borderDash: [],
      spanGaps: true,
      ...extra,
    };
  }

  function clearProjections() {
    if (!projectionsEl) return;
    projectionsEl.hidden = true;
    projectionsEl.innerHTML = "";
  }

  function renderProjections(forecast) {
    if (!projectionsEl) return;
    if (!showForecast || !forecast || !forecast.enabled) {
      clearProjections();
      return;
    }

    const cards = [];
    const loc = forecast.location;
    if (loc && (forecast.outdoor || []).length) {
      const temps = forecast.outdoor.map((p) => p.temperature_c);
      const hums = forecast.outdoor.map((p) => p.humidity);
      const where = [loc.name, loc.admin1].filter(Boolean).join(", ");
      cards.push(`
        <article class="projection-card projection-weather">
          <h4>Weather · ${escapeHtml(where || "Open-Meteo")}</h4>
          <p class="projection-meta">
            Temp ${Math.min(...temps).toFixed(1)}–${Math.max(...temps).toFixed(1)} °C
            · Hum ${Math.min(...hums).toFixed(0)}–${Math.max(...hums).toFixed(0)} %
            · next ${hours} h
          </p>
        </article>
      `);
    }

    const projections = forecast.projections || {};
    for (const device of selectedDevices()) {
      const proj = projections[device.address];
      if (!proj || !proj.summary) continue;
      const s = proj.summary;
      cards.push(`
        <article class="projection-card" style="--device-color:${colorFor(device.address)}">
          <h4>${escapeHtml(deviceLabel(device))} · projected</h4>
          <p class="projection-meta">
            Temp ${s.temp_min.toFixed(1)}–${s.temp_max.toFixed(1)} °C
            · Hum ${s.humidity_min.toFixed(0)}–${s.humidity_max.toFixed(0)} %
            · bias ${proj.bias_temp >= 0 ? "+" : ""}${proj.bias_temp.toFixed(1)} °C
          </p>
        </article>
      `);
    }

    if (!cards.length) {
      clearProjections();
      return;
    }
    projectionsEl.hidden = false;
    projectionsEl.innerHTML = cards.join("");
  }

  async function fetchForecast(addresses) {
    if (!showForecast) {
      return { enabled: false, outdoor: [], projections: {} };
    }
    await requestBrowserGeo(false);
    const params = new URLSearchParams({ hours: String(hours) });
    for (const address of addresses) {
      params.append("address", address);
    }
    if (browserGeo) {
      params.set("latitude", String(browserGeo.latitude));
      params.set("longitude", String(browserGeo.longitude));
    }
    const res = await fetch(`/api/forecast?${params}`);
    if (!res.ok) throw new Error(`forecast HTTP ${res.status}`);
    return res.json();
  }

  function updateOverview() {
    overviewBody.innerHTML = "";
    updateSortButtons();
    const visible = filteredDevices();
    if (!devices.length) {
      overviewBody.innerHTML =
        '<tr><td colspan="9" class="overview-empty">No devices detected</td></tr>';
      overviewStatus.textContent = "Waiting for BLE devices…";
      return;
    }
    if (!visible.length) {
      overviewBody.innerHTML =
        '<tr><td colspan="9" class="overview-empty">No sensors for these filters</td></tr>';
      overviewStatus.textContent = `0 / ${devices.length} sensor(s) · filters active`;
      return;
    }

    const ranked = sortedDevices(visible);
    for (const device of ranked) {
      const tr = document.createElement("tr");
      tr.style.setProperty("--device-color", colorFor(device.address));
      const source = device.last_source || "—";

      const nameTd = document.createElement("td");
      nameTd.innerHTML = `
        <span class="overview-name">
          <span class="device-swatch" aria-hidden="true"></span>
          ${escapeHtml(deviceLabel(device))}
        </span>
        <span class="overview-meta">${escapeHtml(device.model)} · ${escapeHtml(device.address)}</span>
      `;

      const zoneTd = document.createElement("td");
      zoneTd.className = "cat-cell";
      zoneTd.appendChild(makeCategorySelect(device, "zone", taxonomyData.zones));

      const heightTd = document.createElement("td");
      heightTd.className = "cat-cell";
      heightTd.appendChild(makeCategorySelect(device, "height", taxonomyData.heights));

      const roomTd = document.createElement("td");
      roomTd.className = "cat-cell";
      roomTd.appendChild(makeCategorySelect(device, "room", taxonomyData.rooms));

      const tempTd = document.createElement("td");
      tempTd.className = "num temp";
      tempTd.textContent = fmtNum(device.temperature_c, 1, " °C");

      const humTd = document.createElement("td");
      humTd.className = "num";
      humTd.textContent = fmtNum(device.humidity, 1, " %");

      const battTd = document.createElement("td");
      battTd.className = "num";
      battTd.textContent = device.battery != null ? `${device.battery} %` : "—";

      const sourceTd = document.createElement("td");
      sourceTd.className = "overview-source";
      sourceTd.innerHTML = sourceHtml(source);

      const timeTd = document.createElement("td");
      timeTd.textContent = fmtTime(device.last_reading_ts || device.last_seen);

      tr.append(nameTd, zoneTd, heightTd, roomTd, tempTd, humTd, battTd, sourceTd, timeTd);
      tr.addEventListener("click", (ev) => {
        if (ev.target.closest("select, a, button")) return;
        selected = new Set([device.address]);
        persistSelection();
        fillDeviceList();
        updateCurrent();
        setView("compare");
        loadHistory().catch((err) => {
          statusEl.textContent = `Error: ${err.message}`;
        });
      });
      overviewBody.appendChild(tr);
    }

    const temps = ranked
      .map((d) => d.temperature_c)
      .filter((t) => t != null && !Number.isNaN(t));
    const span =
      temps.length >= 2
        ? ` · Δ ${(Math.max(...temps) - Math.min(...temps)).toFixed(1)} °C`
        : "";
    const activeCats = ["zone", "height", "room"]
      .filter((k) => catFilters[k] !== "all")
      .map((k) => catFilters[k]);
    const filterNote = [
      modelFilter === "all" ? "" : modelFilter.toUpperCase(),
      ...activeCats,
    ]
      .filter(Boolean)
      .join(" · ");
    overviewStatus.textContent =
      `${ranked.length}${ranked.length === devices.length ? "" : ` / ${devices.length}`} sensor(s)` +
      `${filterNote ? ` · ${filterNote}` : ""}${span} · updated ${new Date().toLocaleTimeString("en-GB")}`;
  }

  function updateCurrent() {
    currentEl.innerHTML = "";
    const picked = selectedDevices();
    if (!picked.length) {
      const empty = document.createElement("div");
      empty.className = "metric metric-empty";
      empty.innerHTML =
        '<span class="metric-label">Selection</span>' +
        '<span class="metric-value metric-time">No devices</span>';
      currentEl.appendChild(empty);
      return;
    }

    for (const device of picked) {
      const card = document.createElement("article");
      card.className = "device-current";
      card.style.setProperty("--device-color", colorFor(device.address));
      card.innerHTML = `
        <h3 class="device-current-name">${escapeHtml(deviceLabel(device))}</h3>
        <div class="device-current-metrics">
          <div class="metric">
            <span class="metric-label">Temperature</span>
            <span class="metric-value">${fmtNum(device.temperature_c, 1, " °C")}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Humidity</span>
            <span class="metric-value">${fmtNum(device.humidity, 1, " %")}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Dew point</span>
            <span class="metric-value">${
              device.temperature_c != null && device.humidity != null && device.humidity > 0
                ? fmtNum(dewPoint(device.temperature_c, device.humidity), 1, " °C")
                : "—"
            }</span>
          </div>
          <div class="metric">
            <span class="metric-label">Battery</span>
            <span class="metric-value">${device.battery != null ? `${device.battery} %` : "—"}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Last reading</span>
            <span class="metric-value metric-time">${fmtTime(device.last_reading_ts || device.last_seen)}</span>
          </div>
        </div>
      `;
      currentEl.appendChild(card);
    }
  }

  function escapeHtml(text) {
    return String(text)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function fillDeviceList() {
    const previous = new Set(selected);
    const persisted = previous.size ? null : loadPersistedSelection();
    deviceList.innerHTML = "";
    const visible = filteredDevices();

    if (!devices.length) {
      deviceList.innerHTML = '<p class="device-empty">No devices detected</p>';
      selected = new Set();
      return;
    }
    if (!visible.length) {
      deviceList.innerHTML = '<p class="device-empty">No sensors for this model</p>';
      return;
    }

    const known = new Set(devices.map((d) => d.address));
    if (previous.size) {
      selected = new Set([...previous].filter((a) => known.has(a)));
    } else if (persisted && persisted.length) {
      selected = new Set(persisted.filter((a) => known.has(a)));
    }
    const visibleAddrs = new Set(visible.map((d) => d.address));
    const selectedVisible = [...selected].filter((a) => visibleAddrs.has(a));
    if (!selectedVisible.length) {
      selected = new Set([visible[0].address]);
    }

    for (const d of visible) {
      const id = `dev-${d.address.replaceAll(":", "")}`;
      const label = document.createElement("label");
      label.className = "device-item";
      label.htmlFor = id;
      label.style.setProperty("--device-color", colorFor(d.address));

      const input = document.createElement("input");
      input.type = "checkbox";
      input.id = id;
      input.value = d.address;
      input.checked = selected.has(d.address);

      const swatch = document.createElement("span");
      swatch.className = "device-swatch";
      swatch.setAttribute("aria-hidden", "true");

      const text = document.createElement("span");
      text.className = "device-item-text";
      const bits = [
        categoryLabel("zone", d.zone),
        categoryLabel("height", d.height),
        categoryLabel("room", d.room),
      ].filter((x) => x && x !== "—");
      text.textContent = bits.length
        ? `${d.name} (${bits.join(" · ")})`
        : `${d.name} (${d.model})`;

      label.append(input, swatch, text);
      deviceList.appendChild(label);
    }

    persistSelection();
  }

  async function loadDevices() {
    const [devicesRes, taxRes] = await Promise.all([
      fetch("/api/devices"),
      fetch("/api/categories"),
    ]);
    if (!devicesRes.ok) throw new Error(`devices HTTP ${devicesRes.status}`);
    devices = await devicesRes.json();
    if (taxRes.ok) {
      taxonomyData = await taxRes.json();
    }
    syncModelFilterButtons();
    fillDeviceList();
    updateOverview();
    updateCurrent();
  }

  async function fetchHistory(address) {
    const res = await fetch(
      `/api/history?address=${encodeURIComponent(address)}&hours=${hours}`
    );
    if (!res.ok) throw new Error(`history HTTP ${res.status}`);
    return res.json();
  }

  async function loadHistory() {
    ensureCharts();
    const picked = selectedDevices();
    if (!picked.length) {
      tempChart.data.datasets = [];
      humChart.data.datasets = [];
      dewChart.data.datasets = [];
      tempChart.update();
      humChart.update();
      dewChart.update();
      clearProjections();
      statusEl.textContent = "Select at least one device…";
      historyLoaded = true;
      return;
    }

    const [results, forecast] = await Promise.all([
      Promise.all(
        picked.map(async (device) => {
          const payload = await fetchHistory(device.address);
          return { device, points: payload.points || [] };
        })
      ),
      fetchForecast(picked.map((d) => d.address)).catch((err) => {
        console.warn(err);
        return { enabled: false, outdoor: [], projections: {}, error: err.message };
      }),
    ]);

    const multi = results.length > 1;
    const tempDatasets = results.map(({ device, points }) => {
      const color = colorFor(device.address);
      return makeDataset(
        deviceLabel(device),
        color,
        points.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
        !multi
      );
    });
    const humDatasets = results.map(({ device, points }) => {
      const color = colorFor(device.address);
      return makeDataset(
        deviceLabel(device),
        color,
        points.map((p) => ({ x: p.ts * 1000, y: p.humidity })),
        !multi
      );
    });
    const dewDatasets = results.map(({ device, points }) => {
      const color = colorFor(device.address);
      return makeDataset(
        deviceLabel(device),
        color,
        points
          .filter((p) => p.temperature_c != null && p.humidity != null && p.humidity > 0)
          .map((p) => ({ x: p.ts * 1000, y: dewPoint(p.temperature_c, p.humidity) })),
        !multi
      );
    });

    if (forecast && forecast.enabled) {
      const outdoor = forecast.outdoor || [];
      if (outdoor.length) {
        const weatherColor = "#c5c9c4";
        const locName = (forecast.location && forecast.location.name) || "Weather";
        tempDatasets.push(
          makeDataset(
            `${locName} (forecast)`,
            weatherColor,
            outdoor.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
            false,
            { borderDash: [6, 4], borderWidth: 1.75 }
          )
        );
        humDatasets.push(
          makeDataset(
            `${locName} (forecast)`,
            weatherColor,
            outdoor.map((p) => ({ x: p.ts * 1000, y: p.humidity })),
            false,
            { borderDash: [6, 4], borderWidth: 1.75 }
          )
        );
        dewDatasets.push(
          makeDataset(
            `${locName} (forecast)`,
            weatherColor,
            outdoor
              .filter((p) => p.humidity > 0)
              .map((p) => ({ x: p.ts * 1000, y: dewPoint(p.temperature_c, p.humidity) })),
            false,
            { borderDash: [6, 4], borderWidth: 1.75 }
          )
        );
      }

      const projections = forecast.projections || {};
      for (const { device } of results) {
        const proj = projections[device.address];
        if (!proj || !(proj.points || []).length) continue;
        const color = colorFor(device.address);
        tempDatasets.push(
          makeDataset(
            `${deviceLabel(device)} (proj.)`,
            color,
            proj.points.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
            false,
            { borderDash: [2, 4], borderWidth: 1.5 }
          )
        );
        humDatasets.push(
          makeDataset(
            `${deviceLabel(device)} (proj.)`,
            color,
            proj.points.map((p) => ({ x: p.ts * 1000, y: p.humidity })),
            false,
            { borderDash: [2, 4], borderWidth: 1.5 }
          )
        );
        dewDatasets.push(
          makeDataset(
            `${deviceLabel(device)} (proj.)`,
            color,
            proj.points
              .filter((p) => p.humidity > 0)
              .map((p) => ({ x: p.ts * 1000, y: dewPoint(p.temperature_c, p.humidity) })),
            false,
            { borderDash: [2, 4], borderWidth: 1.5 }
          )
        );
      }
    }

    tempChart.data.datasets = tempDatasets;
    humChart.data.datasets = humDatasets;
    dewChart.data.datasets = dewDatasets;
    const showLegend = tempDatasets.length > 1;
    tempChart.options.plugins.legend.display = showLegend;
    humChart.options.plugins.legend.display = showLegend;
    dewChart.options.plugins.legend.display = showLegend;
    tempChart.update();
    humChart.update();
    dewChart.update();
    renderProjections(forecast);
    historyLoaded = true;

    const totalPoints = results.reduce((n, r) => n + r.points.length, 0);
    const names = results.map((r) => deviceLabel(r.device)).join(", ");
    let extra = "";
    if (forecast && forecast.enabled && forecast.location) {
      const src = forecast.location.source === "browser" ? "GPS" : "config";
      const cache = forecast.cache_hit ? (forecast.stale ? ", stale cache" : ", cached") : "";
      extra = ` · forecast ${forecast.location.name} (${src}${cache})`;
    } else if (forecast && forecast.error) {
      extra = ` · forecast off (${forecast.error})`;
    } else if (showForecast && forecast && !forecast.enabled) {
      extra = " · forecast off (allow location or set [weather] place)";
    }
    statusEl.textContent =
      `${names} · ${totalPoints} point(s) · window ${hours} h${extra} · updated ` +
      new Date().toLocaleTimeString("en-GB");
  }

  async function refresh() {
    try {
      await loadFederation();
      await loadDevices();
      if (currentView === "compare") {
        await loadHistory();
      }
    } catch (err) {
      console.error(err);
      const msg = `Error: ${err.message}`;
      overviewStatus.textContent = msg;
      statusEl.textContent = msg;
    }
  }

  function onSelectionChange() {
    selected = new Set(
      [...deviceList.querySelectorAll('input[type="checkbox"]:checked')].map(
        (el) => el.value
      )
    );
    persistSelection();
    updateCurrent();
    loadHistory().catch((err) => {
      statusEl.textContent = `Error: ${err.message}`;
    });
  }

  viewButtons.forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });

  deviceList.addEventListener("change", onSelectionChange);

  selectAllBtn.addEventListener("click", () => {
    const visible = filteredDevices();
    selected = new Set(visible.map((d) => d.address));
    for (const input of deviceList.querySelectorAll('input[type="checkbox"]')) {
      input.checked = true;
    }
    persistSelection();
    updateCurrent();
    loadHistory().catch((err) => {
      statusEl.textContent = `Error: ${err.message}`;
    });
  });

  selectNoneBtn.addEventListener("click", () => {
    selected = new Set();
    for (const input of deviceList.querySelectorAll('input[type="checkbox"]')) {
      input.checked = false;
    }
    persistSelection();
    updateCurrent();
    loadHistory().catch((err) => {
      statusEl.textContent = `Error: ${err.message}`;
    });
  });

  sortButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.sort;
      if (sortState.key === key) {
        sortState.dir = sortState.dir === "asc" ? "desc" : "asc";
      } else {
        sortState.key = key;
        sortState.dir =
          key === "name" || key === "last_source" ? "asc" : "desc";
      }
      persistSortState();
      updateOverview();
    });
  });

  rangeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      rangeButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      hours = Number(btn.dataset.hours);
      loadHistory().catch((err) => {
        statusEl.textContent = `Error: ${err.message}`;
      });
    });
  });

  if (showForecastEl) {
    showForecastEl.checked = showForecast;
    showForecastEl.addEventListener("change", () => {
      showForecast = showForecastEl.checked;
      localStorage.setItem(FORECAST_KEY, showForecast ? "1" : "0");
      if (!showForecast) clearProjections();
      updateGeoStatus();
      if (currentView === "compare") {
        loadHistory().catch((err) => {
          statusEl.textContent = `Error: ${err.message}`;
        });
      }
    });
  }

  if (locateBtn) {
    locateBtn.addEventListener("click", () => {
      requestBrowserGeo(true)
        .then(() => {
          if (currentView === "compare" && showForecast) {
            return loadHistory();
          }
        })
        .catch((err) => {
          statusEl.textContent = `Error: ${err.message}`;
        });
    });
  }

  async function waitForHealth(timeoutMs = 45000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (res.ok) return true;
      } catch {
        // still down
      }
    }
    return false;
  }

  if (restartBtn) {
    restartBtn.addEventListener("click", async () => {
      if (
        !window.confirm(
          "Restart Govee Charts now? The page will reload when the service is back."
        )
      ) {
        return;
      }
      restartBtn.disabled = true;
      if (restartStatusEl) {
        restartStatusEl.hidden = false;
        restartStatusEl.textContent = "Restarting…";
      }
      try {
        const res = await fetch("/api/restart", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || `HTTP ${res.status}`);
        }
        if (restartStatusEl) {
          restartStatusEl.textContent = data.message || "Restarting…";
        }
        const ok = await waitForHealth();
        if (ok) {
          if (restartStatusEl) restartStatusEl.textContent = "Back online — reloading…";
          window.location.reload();
          return;
        }
        if (restartStatusEl) {
          restartStatusEl.textContent =
            "Service did not come back — if not under systemd, start it manually.";
        }
      } catch (err) {
        // Expected while the process is down
        if (restartStatusEl) {
          restartStatusEl.textContent = "Waiting for service…";
        }
        const ok = await waitForHealth();
        if (ok) {
          window.location.reload();
          return;
        }
        if (restartStatusEl) {
          restartStatusEl.textContent = `Restart failed: ${err.message}`;
        }
      } finally {
        restartBtn.disabled = false;
      }
    });
  }

  updateGeoStatus();
  setView(currentView);
  refresh();
  setInterval(refresh, 30000);
})();
