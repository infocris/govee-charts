(() => {
  const deviceList = document.getElementById("device-list");
  const currentEl = document.getElementById("current");
  const statusEl = document.getElementById("status");
  const overviewBody = document.getElementById("overview-body");
  const overviewStatus = document.getElementById("overview-status");
  const doorsBody = document.getElementById("doors-body");
  const doorsStatus = document.getElementById("doors-status");
  const modelFiltersEl = document.getElementById("model-filters");
  const compareModelFiltersEl = document.getElementById("compare-model-filters");
  const nodeLineEl = document.getElementById("node-line");
  const peerLinksEl = document.getElementById("peer-links");
  const viewOverview = document.getElementById("view-overview");
  const viewCompare = document.getElementById("view-compare");
  const viewFacades = document.getElementById("view-facades");
  const selectAllBtn = document.getElementById("select-all");
  const selectNoneBtn = document.getElementById("select-none");
  const rangeButtons = [...document.querySelectorAll(".ranges button")];
  const viewButtons = [...document.querySelectorAll(".views [data-view]")];
  const sortButtons = [...document.querySelectorAll(".sort-btn")];
  const restartBtn = document.getElementById("restart-btn");
  const restartStatusEl = document.getElementById("restart-status");
  const facadeBody = document.getElementById("facade-body");
  const facadeMetaEl = document.getElementById("facade-meta");
  const facadeOutdoorEl = document.getElementById("facade-outdoor");
  const facadeChartsEl = document.getElementById("facade-charts");
  const facadeStatusEl = document.getElementById("facade-status");
  const windowBannerEl = document.getElementById("window-banner");
  const windowBannerTitleEl = document.getElementById("window-banner-title");
  const windowBannerDetailEl = document.getElementById("window-banner-detail");
  const backfillPanelEl = document.getElementById("backfill-panel");
  const backfillCurrentEl = document.getElementById("backfill-current");
  const backfillQueueEl = document.getElementById("backfill-queue");
  const backfillStatusEl = document.getElementById("backfill-status");
  const backfillPauseBtn = document.getElementById("backfill-pause");
  const backfillRefreshBtn = document.getElementById("backfill-refresh");
  let backfillTimer = null;
  let backfillSnapshot = null;

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
  const WINDOW_BANDS_KEY = "govee-charts.windowBands";
  const HVAC_KEY = "govee-charts.hvac";
  const WINDOW_NOTIFY_KEY = "govee-charts.windowNotify";
  const WINDOW_NOTIFY_STATE_KEY = "govee-charts.windowNotifyState";
  const FOLD_CURRENT_KEY = "govee-charts.foldCurrent";
  const FOLD_PROJ_KEY = "govee-charts.foldProjections";
  const GEO_KEY = "govee-charts.geo";
  const CAT_FILTER_KEY = "govee-charts.catFilters";
  const CHART_HEIGHT_KEY = "govee-charts.chartHeight";
  const CHART_HEIGHT_DEFAULT = 260;
  const CHART_HEIGHT_MIN = 160;
  const CHART_HEIGHT_MAX = 520;

  let hours = 24;
  let devices = [];
  let taxonomyData = { zones: [], heights: [], rooms: [], contact_kinds: [] };
  /** @type {Array<{sensor_id:string,name:string,state:string,ts:number,room?:string,kind?:string}>} */
  let doorSensors = [];
  let selected = new Set();
  let modelFilter = localStorage.getItem(MODEL_KEY) || "all";
  let catFilters = loadCatFilters();
  let sortState = loadSortState();
  let currentView = ["compare", "facades"].includes(localStorage.getItem(VIEW_KEY))
    ? localStorage.getItem(VIEW_KEY)
    : "overview";
  let showForecast = localStorage.getItem(FORECAST_KEY) !== "0";
  let showWindowBands = localStorage.getItem(WINDOW_BANDS_KEY) !== "0";
  let showHvac = localStorage.getItem(HVAC_KEY) !== "0";
  let windowNotify = localStorage.getItem(WINDOW_NOTIFY_KEY) === "1";
  /** @type {{latitude:number, longitude:number, accuracy?:number, at?:number}|null} */
  let browserGeo = loadStoredGeo();
  let geoStatus = browserGeo ? "cached" : "idle";
  let tempChart = null;
  let humChart = null;
  let dewChart = null;
  /** @type {import('chart.js').Chart[]} */
  let facadeChartInstances = [];
  let historyLoaded = false;
  let localNodeId = "";
  /** @type {Map<string, string>} node_id → url */
  let peerByNodeId = new Map();
  const showForecastEl = document.getElementById("show-forecast");
  const showWindowBandsEl = document.getElementById("show-window-bands");
  const showHvacEl = document.getElementById("show-hvac");
  const windowNotifyEl = document.getElementById("window-notify");
  const windowLegendEl = document.getElementById("window-legend");
  const hvacLegendEl = document.getElementById("hvac-legend");
  const hvacStatusEl = document.getElementById("hvac-status");
  const projectionsEl = document.getElementById("projections");
  const foldCurrentEl = document.getElementById("fold-current");
  const foldProjectionsEl = document.getElementById("fold-projections");
  const foldCurrentMetaEl = document.getElementById("fold-current-meta");
  const foldProjectionsMetaEl = document.getElementById("fold-projections-meta");
  const locateBtn = document.getElementById("locate-btn");
  const geoStatusEl = document.getElementById("geo-status");
  const chartHeightEl = document.getElementById("chart-height");
  const chartHeightValueEl = document.getElementById("chart-height-value");
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

  /** Persist legend visibility across 30s dataset rebuilds (keyed by dataset label). */
  const legendHidden = {
    temp: new Map(),
    hum: new Map(),
    dew: new Map(),
  };

  function legendChartKey(chart) {
    if (chart === tempChart) return "temp";
    if (chart === humChart) return "hum";
    if (chart === dewChart) return "dew";
    return null;
  }

  function onLegendClick(_event, legendItem, legend) {
    const chart = legend.chart;
    const index = legendItem.datasetIndex;
    if (index == null || index < 0) return;
    const ds = chart.data.datasets[index];
    if (!ds) return;
    if (chart.isDatasetVisible(index)) {
      chart.hide(index);
    } else {
      chart.show(index);
    }
    const key = legendChartKey(chart);
    if (key && ds.label != null) {
      legendHidden[key].set(String(ds.label), !chart.isDatasetVisible(index));
    }
  }

  function withLegendState(chartKey, datasets) {
    const map = legendHidden[chartKey] || new Map();
    return datasets.map((ds) => {
      const label = ds.label != null ? String(ds.label) : "";
      if (label && map.has(label)) {
        return { ...ds, hidden: map.get(label) };
      }
      return { ...ds };
    });
  }

  function bindChartLegend(chart) {
    if (!chart || !chart.options || !chart.options.plugins) return;
    if (!chart.options.plugins.legend) chart.options.plugins.legend = {};
    chart.options.plugins.legend.onClick = onLegendClick;
  }

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

  function loadChartHeight() {
    const raw = Number(localStorage.getItem(CHART_HEIGHT_KEY));
    if (!Number.isFinite(raw)) return CHART_HEIGHT_DEFAULT;
    const stepped = Math.round(raw / 20) * 20;
    return Math.min(CHART_HEIGHT_MAX, Math.max(CHART_HEIGHT_MIN, stepped));
  }

  function resizeAllCharts() {
    if (tempChart) tempChart.resize();
    if (humChart) humChart.resize();
    if (dewChart) dewChart.resize();
    facadeChartInstances.forEach((c) => c.resize());
  }

  function applyChartHeight(px, { persist = true } = {}) {
    const height = Math.min(
      CHART_HEIGHT_MAX,
      Math.max(CHART_HEIGHT_MIN, Math.round(Number(px) || CHART_HEIGHT_DEFAULT))
    );
    document.documentElement.style.setProperty("--chart-height", `${height}px`);
    if (chartHeightEl) chartHeightEl.value = String(height);
    if (chartHeightValueEl) chartHeightValueEl.textContent = `${height} px`;
    if (persist) localStorage.setItem(CHART_HEIGHT_KEY, String(height));
    resizeAllCharts();
    return height;
  }

  let chartHeight = loadChartHeight();
  applyChartHeight(chartHeight, { persist: false });

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

  function rssiLevel(rssi) {
    const v = Number(rssi);
    if (!Number.isFinite(v)) return null;
    if (v >= -60) return 4;
    if (v >= -70) return 3;
    if (v >= -80) return 2;
    return 1;
  }

  function rssiClass(rssi) {
    const level = rssiLevel(rssi);
    if (level == null) return "rssi-unknown";
    if (level >= 4) return "rssi-strong";
    if (level >= 3) return "rssi-good";
    if (level >= 2) return "rssi-fair";
    return "rssi-weak";
  }

  function rssiHtml(rssi) {
    if (rssi == null || Number.isNaN(Number(rssi))) {
      return '<span class="rssi rssi-unknown">—</span>';
    }
    const level = rssiLevel(rssi) || 0;
    const bars = [1, 2, 3, 4]
      .map(
        (n) =>
          `<span class="rssi-bar${n <= level ? " on" : ""}" style="--n:${n}"></span>`
      )
      .join("");
    return (
      `<span class="rssi ${rssiClass(rssi)}" title="${Number(rssi)} dBm">` +
      `<span class="rssi-bars" aria-hidden="true">${bars}</span>` +
      `<span class="rssi-dbm">${Number(rssi)} dBm</span>` +
      `</span>`
    );
  }

  function phaseLabel(phase) {
    const map = { hour: "1 h", day: "24 h", week: "7 d", deep: "deep" };
    return map[phase] || phase || "—";
  }

  function renderBackfill(data) {
    backfillSnapshot = data;
    if (!backfillPanelEl) return;
    if (!data || data.worker === "disabled" || data.enabled === false) {
      backfillPanelEl.hidden = true;
      return;
    }
    backfillPanelEl.hidden = false;

    const current = data.current;
    const queue = data.queue || [];
    const totals = data.totals || {};

    if (backfillPauseBtn) {
      backfillPauseBtn.textContent = data.paused ? "Resume" : "Pause";
      backfillPauseBtn.disabled = false;
    }

    if (!current) {
      backfillCurrentEl.innerHTML =
        `<p class="backfill-idle">` +
        (data.paused
          ? "Paused"
          : data.worker === "idle" && !(totals.pending > 0)
            ? "Queue empty — waiting for gaps"
            : `Worker ${escapeHtml(data.worker || "idle")} · ${Number(totals.pending) || 0} job(s) pending`) +
        `</p>`;
    } else {
      const done = Number(current.samples_done) || 0;
      const expected = Math.max(Number(current.samples_expected) || 0, done);
      const pct = expected > 0 ? Math.min(100, Math.round((100 * done) / expected)) : 0;
      const lastTs = current.last_sample_ts
        ? new Date(Number(current.last_sample_ts) * 1000).toLocaleString("en-GB", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })
        : "—";
      const lastTemp =
        current.last_sample_temp != null && Number.isFinite(Number(current.last_sample_temp))
          ? `${Number(current.last_sample_temp).toFixed(1)} °C`
          : "—";
      const batt =
        current.battery != null && Number.isFinite(Number(current.battery))
          ? `${Number(current.battery)} %`
          : "—";
      const remaining = Math.max(0, expected - done);
      backfillCurrentEl.innerHTML = `
        <div class="backfill-job">
          <div class="backfill-job-title">
            <strong>${escapeHtml(current.name || current.address || "Sensor")}</strong>
            · phase ${escapeHtml(phaseLabel(current.phase))}
          </div>
          <div class="backfill-progress" aria-hidden="true"><span style="width:${pct}%"></span></div>
          <div class="backfill-job-meta">
            <span>${done} / ${expected || "?"} samples · ${remaining} left</span>
            <span>Last ${escapeHtml(lastTs)} · ${escapeHtml(lastTemp)}</span>
            <span>${rssiHtml(current.rssi)}</span>
            <span>Battery ${escapeHtml(batt)}</span>
          </div>
        </div>`;
    }

    if (backfillQueueEl) {
      if (!queue.length) {
        backfillQueueEl.hidden = true;
        backfillQueueEl.innerHTML = "";
      } else {
        backfillQueueEl.hidden = false;
        backfillQueueEl.innerHTML = queue
          .slice(0, 12)
          .map(
            (q) =>
              `<li><span class="q-name">${escapeHtml(q.name || q.address)}</span>` +
              `<span>${escapeHtml(phaseLabel(q.phase))} · ~${Number(q.samples_expected) || 0} missing · ${Number(q.jobs) || 0} job(s)</span></li>`
          )
          .join("");
      }
    }

    if (backfillStatusEl) {
      backfillStatusEl.textContent =
        `pending ${totals.pending || 0} · done ${totals.done || 0}` +
        (totals.failed ? ` · failed ${totals.failed}` : "") +
        (data.config && data.config.min_rssi != null
          ? ` · min RSSI ${data.config.min_rssi} dBm`
          : "");
    }
  }

  async function loadBackfill() {
    try {
      const res = await fetch("/api/backfill");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderBackfill(data);
      syncBackfillPolling();
    } catch (err) {
      if (backfillPanelEl) backfillPanelEl.hidden = true;
      console.warn("backfill status:", err);
    }
  }

  function syncBackfillPolling() {
    const shouldPoll =
      currentView === "overview" &&
      backfillPanelEl &&
      !backfillPanelEl.hidden;
    if (shouldPoll && !backfillTimer) {
      backfillTimer = setInterval(loadBackfill, 2500);
    } else if (!shouldPoll && backfillTimer) {
      clearInterval(backfillTimer);
      backfillTimer = null;
    }
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

  function makeDoorSelect(sensor, field, options) {
    const select = document.createElement("select");
    select.className = "cat-select";
    select.dataset.sensorId = sensor.sensor_id;
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
    select.value = sensor[field] || "";
    select.addEventListener("click", (ev) => ev.stopPropagation());
    select.addEventListener("mousedown", (ev) => ev.stopPropagation());
    select.addEventListener("change", async (ev) => {
      ev.stopPropagation();
      const value = select.value === "" ? null : select.value;
      select.disabled = true;
      try {
        const res = await fetch(
          `/api/doors/${encodeURIComponent(sensor.sensor_id)}`,
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
        const idx = doorSensors.findIndex(
          (d) => d.sensor_id === sensor.sensor_id
        );
        if (idx >= 0) {
          doorSensors[idx] = { ...doorSensors[idx], ...updated };
        }
        updateDoorsTable();
        updateWindowBanner(null).catch((err) => console.warn(err));
      } catch (err) {
        select.value = sensor[field] || "";
        if (doorsStatus) {
          doorsStatus.hidden = false;
          doorsStatus.textContent = `Save failed: ${err.message}`;
        }
      } finally {
        select.disabled = false;
      }
    });
    return select;
  }

  function updateDoorsTable() {
    if (!doorsBody) return;
    doorsBody.innerHTML = "";
    if (!doorSensors.length) {
      doorsBody.innerHTML =
        '<tr><td colspan="5" class="overview-empty">No door/window contacts yet</td></tr>';
      if (doorsStatus) {
        doorsStatus.hidden = false;
        doorsStatus.textContent =
          "Waiting for MQTT contact sensors (enable [doors] in config)…";
      }
      return;
    }
    if (doorsStatus) {
      doorsStatus.hidden = true;
      doorsStatus.textContent = "";
    }
    const kinds = taxonomyData.contact_kinds || [];
    const rooms = taxonomyData.rooms || [];
    for (const sensor of doorSensors) {
      const tr = document.createElement("tr");
      const nameTd = document.createElement("td");
      nameTd.innerHTML = `
        <span class="overview-name">${escapeHtml(sensor.name || sensor.sensor_id)}</span>
        <span class="overview-meta">${escapeHtml(sensor.sensor_id)}</span>
      `;

      const stateTd = document.createElement("td");
      const st = sensor.state || "—";
      stateTd.innerHTML = `<span class="door-state door-state-${escapeHtml(st)}">${escapeHtml(st)}</span>`;

      const kindTd = document.createElement("td");
      kindTd.className = "cat-cell";
      kindTd.appendChild(makeDoorSelect(sensor, "kind", kinds));

      const roomTd = document.createElement("td");
      roomTd.className = "cat-cell";
      roomTd.appendChild(makeDoorSelect(sensor, "room", rooms));

      const timeTd = document.createElement("td");
      timeTd.textContent = fmtTime(sensor.ts);

      tr.append(nameTd, stateTd, kindTd, roomTd, timeTd);
      doorsBody.appendChild(tr);
    }
  }

  async function loadDoors() {
    try {
      const res = await fetch("/api/doors");
      if (!res.ok) throw new Error(`doors HTTP ${res.status}`);
      const data = await res.json();
      doorSensors = data.sensors || [];
      updateDoorsTable();
    } catch (err) {
      if (doorsBody) {
        doorsBody.innerHTML =
          '<tr><td colspan="5" class="overview-empty">Doors unavailable</td></tr>';
      }
      if (doorsStatus) {
        doorsStatus.hidden = false;
        doorsStatus.textContent = `Error: ${err.message}`;
      }
    }
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
    if (!["overview", "compare", "facades"].includes(view)) {
      view = "overview";
    }
    currentView = view;
    localStorage.setItem(VIEW_KEY, view);
    if (viewOverview) viewOverview.hidden = view !== "overview";
    if (viewCompare) viewCompare.hidden = view !== "compare";
    if (viewFacades) viewFacades.hidden = view !== "facades";
    viewButtons.forEach((btn) => {
      const active = btn.dataset.view === view;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (view === "compare" && !historyLoaded) {
      loadHistory().catch((err) => {
        statusEl.textContent = `Error: ${err.message}`;
      });
    } else if (view === "compare" && tempChart && humChart) {
      tempChart.resize();
      humChart.resize();
      if (dewChart) dewChart.resize();
    } else if (view === "facades") {
      loadFacades().catch((err) => {
        if (facadeStatusEl) {
          facadeStatusEl.textContent = `Error: ${err.message}`;
        }
      });
      if (facadeChartInstances.length) {
        facadeChartInstances.forEach((c) => c.resize());
      }
    }
    syncBackfillPolling();
  }

  async function loadFacades() {
    if (!facadeBody) return;
    if (facadeStatusEl) facadeStatusEl.textContent = "Loading…";
    await requestBrowserGeo(false);
    const params = new URLSearchParams({ hours: "24" });
    if (browserGeo) {
      params.set("latitude", String(browserGeo.latitude));
      params.set("longitude", String(browserGeo.longitude));
    }
    const res = await fetch(`/api/apartment?${params}`);
    if (!res.ok) throw new Error(`apartment HTTP ${res.status}`);
    const data = await res.json();
    renderFacades(data);
  }

  function destroyFacadeCharts() {
    for (const chart of facadeChartInstances) {
      try {
        chart.destroy();
      } catch {
        /* ignore */
      }
    }
    facadeChartInstances = [];
    if (facadeChartsEl) facadeChartsEl.innerHTML = "";
  }

  function roomColor(roomId, index) {
    let h = 0;
    const s = String(roomId || "");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return PALETTE[(h + (index || 0)) % PALETTE.length];
  }

  function formatClock(tsMs) {
    const d = new Date(tsMs);
    return d.toLocaleString("en-GB", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function formatWindowSchedule(bands) {
    if (!bands || !bands.length) {
      return "No clear open/close windows in this period (±0.5 °C).";
    }
    const byKind = { open: [], close: [], humid: [] };
    const byVent = { natural: [], mechanical: [] };
    for (const b of bands) {
      if (byKind[b.kind]) {
        byKind[b.kind].push(`${formatClock(b.x1)}–${formatClock(b.x2)}`);
      }
      if (b.vent && byVent[b.vent]) {
        byVent[b.vent].push(`${formatClock(b.x1)}–${formatClock(b.x2)}`);
      }
    }
    const parts = [];
    if (byKind.open.length) parts.push(`Open ${byKind.open.join(", ")}`);
    if (byKind.close.length) parts.push(`Close ${byKind.close.join(", ")}`);
    if (byKind.humid.length) parts.push(`Too humid ${byKind.humid.join(", ")}`);
    if (byVent.natural.length) {
      parts.push(`Natural OK ${byVent.natural.join(", ")}`);
    }
    if (byVent.mechanical.length) {
      parts.push(`Mechanical preferred ${byVent.mechanical.join(", ")}`);
    }
    return parts.join(" · ") || "No clear open/close windows in this period.";
  }

  const ORIENTATION_DEG = {
    n: 0,
    ne: 45,
    e: 90,
    se: 135,
    s: 180,
    sw: 225,
    w: 270,
    nw: 315,
  };
  const WIND_MIN_MS = 1.5;

  function angleDiffDeg(a, b) {
    return ((((a - b + 180) % 360) + 360) % 360) - 180;
  }

  function windOnFacadeMs(orientations, windSpeed, windDir) {
    if (
      windSpeed == null ||
      windDir == null ||
      !orientations ||
      !orientations.length ||
      windSpeed <= 0
    ) {
      return 0;
    }
    let best = 0;
    for (const o of orientations) {
      const face = ORIENTATION_DEG[String(o).toLowerCase()];
      if (face == null) continue;
      const cosW = Math.cos((angleDiffDeg(windDir, face) * Math.PI) / 180);
      best = Math.max(best, windSpeed * Math.max(0, cosW));
    }
    return best;
  }

  function crossVentMs(orientations, windSpeed, windDir) {
    if (windSpeed == null || windDir == null || windSpeed <= 0) return 0;
    const faces = [
      ...new Set(
        (orientations || [])
          .map((o) => ORIENTATION_DEG[String(o).toLowerCase()])
          .filter((d) => d != null)
      ),
    ].sort((a, b) => a - b);
    if (faces.length < 2) {
      return windOnFacadeMs(orientations, windSpeed, windDir);
    }
    let best = 0;
    for (let i = 0; i < faces.length; i++) {
      for (let j = i + 1; j < faces.length; j++) {
        const sep = Math.abs(angleDiffDeg(faces[i], faces[j]));
        if (sep < 120) continue;
        const align = Math.max(
          Math.abs(
            Math.cos((angleDiffDeg(windDir, faces[i]) * Math.PI) / 180)
          ),
          Math.abs(
            Math.cos((angleDiffDeg(windDir, faces[j]) * Math.PI) / 180)
          )
        );
        best = Math.max(best, windSpeed * align);
      }
    }
    return best;
  }

  /**
   * natural = open windows + favorable wind
   * mechanical = closed / humid / calm / parallel wind
   */
  function ventilationMode(kind, exterior, allExterior, windSpeed, windDir) {
    if (kind === "close" || kind === "humid") return "mechanical";
    if (kind !== "open") return null;
    if (windSpeed == null || windDir == null) return "mechanical";
    if (windSpeed < WIND_MIN_MS) return "mechanical";
    const pool = allExterior && allExterior.length ? allExterior : exterior;
    const effective = Math.max(
      windOnFacadeMs(exterior, windSpeed, windDir),
      crossVentMs(pool, windSpeed, windDir)
    );
    return effective >= WIND_MIN_MS ? "natural" : "mechanical";
  }

  function compassFromDeg(deg) {
    if (deg == null || Number.isNaN(Number(deg))) return null;
    const orients = ["n", "ne", "e", "se", "s", "sw", "w", "nw"];
    const idx = Math.floor((((Number(deg) % 360) + 360) % 360 + 22.5) / 45) % 8;
    return orients[idx].toUpperCase();
  }

  function formatWindNow(outdoor) {
    if (!outdoor || outdoor.wind_speed_ms == null) return "";
    const spd = Number(outdoor.wind_speed_ms).toFixed(1);
    const dir =
      outdoor.wind_compass ||
      compassFromDeg(outdoor.wind_direction_deg) ||
      (outdoor.wind_direction_deg != null
        ? `${Math.round(outdoor.wind_direction_deg)}°`
        : "");
    return dir ? ` · wind ${spd} m/s ${dir}` : ` · wind ${spd} m/s`;
  }

  function groupRoomsByFacade(rooms) {
    const groups = [];
    const seen = new Map();
    for (const room of rooms) {
      const exterior = room.exterior || [];
      if (!exterior.length) continue;
      const key = exterior.join("+");
      if (!seen.has(key)) {
        const g = {
          key,
          exterior,
          label: exterior.map((o) => o.toUpperCase()).join(" / "),
          rooms: [],
        };
        seen.set(key, g);
        groups.push(g);
      }
      seen.get(key).rooms.push(room);
    }
    return groups;
  }

  function indoorSeriesForFacade(groupRooms) {
    // Prefer room with history and/or projection
    for (const room of groupRooms) {
      const hist = room.room_history;
      const rp = room.room_projection;
      const series = [];
      if (hist && (hist.points || []).length) {
        for (const p of hist.points) {
          series.push({
            ts: p.ts,
            t: p.temperature_c,
            rh: p.humidity,
          });
        }
      }
      if (rp && (rp.points || []).length) {
        for (const p of rp.points) {
          series.push({
            ts: p.ts,
            t: p.temperature_c,
            rh: p.humidity,
          });
        }
      }
      if (series.length) {
        return { room, series, history: hist, projection: rp };
      }
    }
    for (const room of groupRooms) {
      const sensors = (room.sensors || []).filter(
        (s) => (s.zone || "").toLowerCase() !== "exterior"
      );
      const sensor = sensors[0];
      if (sensor && sensor.temperature_c != null) {
        return {
          room,
          series: [
            {
              ts: Date.now() / 1000,
              t: Number(sensor.temperature_c),
              rh: sensor.humidity,
            },
          ],
          history: null,
          projection: null,
        };
      }
    }
    return null;
  }

  function updateFacadeCharts(data) {
    destroyFacadeCharts();
    if (!facadeChartsEl) return;

    const outdoor = data.outdoor || {};
    const rooms = data.rooms || [];
    const groups = groupRoomsByFacade(rooms);
    const outdoorPoints = outdoor.points || [];
    const hours = data.hours || 24;

    if (!groups.length || !outdoor.available || !outdoorPoints.length) {
      facadeChartsEl.hidden = true;
      return;
    }

    facadeChartsEl.hidden = false;
    groups.forEach((group, gIdx) => {
      const figure = document.createElement("figure");
      figure.className = "chart-block facade-chart-block";

      const caption = document.createElement("figcaption");
      const roomNames = group.rooms.map((r) => r.label || r.id).join(", ");
      caption.innerHTML = `${escapeHtml(group.label)} façade
        <span class="overview-meta">${escapeHtml(roomNames)} · ±${hours} h</span>`;

      const canvas = document.createElement("canvas");
      canvas.id = `facade-chart-${gIdx}`;

      const scheduleEl = document.createElement("p");
      scheduleEl.className = "facade-window-schedule";

      const legendHint = document.createElement("p");
      legendHint.className = "facade-window-legend";
      legendHint.innerHTML =
        '<span class="window-swatch window-swatch-open"></span> open cools ' +
        '<span class="window-swatch window-swatch-close"></span> open heats ' +
        '<span class="window-swatch window-swatch-humid"></span> too humid ' +
        '<span class="window-swatch window-swatch-natural"></span> natural OK ' +
        '<span class="window-swatch window-swatch-mechanical"></span> mechanical';

      figure.append(caption, canvas, legendHint, scheduleEl);
      facadeChartsEl.appendChild(figure);

      const datasets = [];
      datasets.push(
        makeDataset(
          "Outdoor air",
          "#c5c9c4",
          outdoorPoints.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
          false,
          { borderDash: [6, 4], borderWidth: 1.75 }
        )
      );

      const fp = group.rooms.map((r) => r.facade_projection).find((p) => p && p.points);
      if (fp && fp.points.length) {
        datasets.push(
          makeDataset(
            `${group.label} effective`,
            roomColor(group.key, gIdx),
            fp.points.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
            false,
            { borderWidth: 2 }
          )
        );
      }

      group.rooms.forEach((room, idx) => {
        const hist = room.room_history;
        const rp = room.room_projection;
        const labelBase = (rp && rp.name) || room.label || room.id;
        const color = roomColor(room.id, gIdx * 3 + idx + 2);
        if (hist && (hist.points || []).length) {
          datasets.push(
            makeDataset(
              `${labelBase} (measured)`,
              color,
              hist.points.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
              false,
              { borderWidth: 2 }
            )
          );
        }
        if (rp && (rp.points || []).length) {
          datasets.push(
            makeDataset(
              `${labelBase} (proj.)`,
              color,
              rp.points.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
              false,
              { borderDash: [2, 4], borderWidth: 1.75 }
            )
          );
        }
      });

      const indoor = indoorSeriesForFacade(group.rooms);
      const allExterior = rooms.flatMap((r) => r.exterior || []);
      let bands = [];
      if (indoor && indoor.series.length) {
        bands = buildWindowBands(
          indoor.series,
          outdoorPoints,
          WINDOW_DELTA_C,
          {
            exterior: group.exterior,
            allExterior,
          }
        );
        scheduleEl.textContent = formatWindowSchedule(bands);
        if (indoor.room) {
          scheduleEl.title = `Based on ${indoor.room.label || indoor.room.id} vs outdoor air + wind (past + forecast)`;
        }
      } else {
        scheduleEl.textContent =
          "Window schedule unavailable (no interior sensor / history for this façade).";
      }

      const opts = structuredClone(chartDefaults);
      opts.plugins.windowBands = { bands };
      opts.plugins.legend.display = datasets.length > 1;

      const chart = new Chart(canvas, {
        type: "line",
        data: { datasets },
        options: opts,
      });
      facadeChartInstances.push(chart);
    });
  }

  function fmtRangeC(minV, maxV) {
    if (minV == null || maxV == null) return "—";
    return `${Number(minV).toFixed(1)}–${Number(maxV).toFixed(1)} °C`;
  }

  function renderFacades(data) {
    if (!facadeBody) return;
    const rooms = data.rooms || [];
    const orients = data.orientations || [];
    const outdoor = data.outdoor || {};
    const hours = data.hours || 24;

    if (facadeOutdoorEl) {
      if (outdoor.available) {
        facadeOutdoorEl.hidden = false;
        const loc = outdoor.location || {};
        const where = [loc.name, loc.admin1].filter(Boolean).join(", ") || "Outdoor";
        facadeOutdoorEl.innerHTML = `
          <div class="facade-outdoor-card">
            <h3>${escapeHtml(where)}</h3>
            <p>
              Now <strong>${Number(outdoor.temp_now).toFixed(1)} °C</strong>
              · ±${hours} h
              <strong>${fmtRangeC(outdoor.temp_min, outdoor.temp_max)}</strong>
              ${
                outdoor.cloud_cover != null
                  ? ` · clouds ${Math.round(outdoor.cloud_cover)} %`
                  : ""
              }
              ${
                outdoor.shortwave_radiation != null
                  ? ` · ${Math.round(outdoor.shortwave_radiation)} W/m²`
                  : ""
              }
              ${formatWindNow(outdoor)}
            </p>
          </div>`;
      } else {
        facadeOutdoorEl.hidden = true;
        facadeOutdoorEl.innerHTML = "";
      }
    }

    if (facadeMetaEl) {
      if (!data.enabled) {
        facadeMetaEl.textContent =
          "Apartment network disabled — enable [apartment] in config.toml to use projections.";
      } else {
        const bits = [
          `Floor ${data.floor}/${data.floors_total}`,
          `${data.area_m2} m²`,
          `${rooms.length} rooms`,
        ];
        facadeMetaEl.textContent = bits.join(" · ");
      }
    }

    updateFacadeCharts(data);

    if (!rooms.length) {
      facadeBody.innerHTML =
        '<tr><td colspan="5" class="overview-empty">No apartment rooms in config</td></tr>';
      if (facadeStatusEl) facadeStatusEl.textContent = "No layout loaded";
      return;
    }

    facadeBody.innerHTML = "";
    for (const room of rooms) {
      const tr = document.createElement("tr");
      const nameTd = document.createElement("td");
      nameTd.innerHTML = `<strong>${escapeHtml(room.label || room.id)}</strong>
        <span class="overview-meta">${escapeHtml(room.id)}</span>`;

      const areaTd = document.createElement("td");
      areaTd.className = "num";
      areaTd.textContent =
        room.area_m2 != null ? `${Number(room.area_m2).toFixed(1)} m²` : "—";

      const facadeTd = document.createElement("td");
      facadeTd.className = "facade-orients";
      const group = document.createElement("div");
      group.className = "facade-orient-group";
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", `Facades for ${room.label || room.id}`);
      const selected = new Set(room.exterior || []);
      for (const o of orients) {
        const lab = document.createElement("label");
        lab.className = "facade-orient";
        lab.title = o.label;
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = o.id;
        input.checked = selected.has(o.id);
        input.addEventListener("change", () => {
          patchFacade(room.id, group).catch((err) => {
            if (facadeStatusEl) {
              facadeStatusEl.textContent = `Save failed: ${err.message}`;
            }
          });
        });
        const span = document.createElement("span");
        span.textContent = o.id.toUpperCase();
        lab.append(input, span);
        group.appendChild(lab);
      }
      facadeTd.appendChild(group);

      const solarTd = document.createElement("td");
      solarTd.className = "num";
      const vent = room.ventilation;
      const solarBits = [];
      if (room.solar_bias_c != null && room.faces_exterior) {
        const v = Number(room.solar_bias_c);
        solarBits.push(`${v >= 0 ? "+" : ""}${v.toFixed(1)} °C`);
      }
      if (vent && vent.mode && room.faces_exterior) {
        solarBits.push(vent.mode === "natural" ? "natural" : "mechanical");
        solarTd.title =
          vent.mode === "natural"
            ? `Wind favors natural draft (${vent.effective_ms} m/s effective)`
            : `Prefer mechanical ventilation (${vent.reason || "weak wind"})`;
      } else if (!room.faces_exterior) {
        solarTd.title = "No exterior façade";
      }
      solarTd.textContent = solarBits.length ? solarBits.join(" · ") : "—";

      const sensorsTd = document.createElement("td");
      const sensors = room.sensors || [];
      if (!sensors.length) {
        sensorsTd.innerHTML = '<span class="overview-meta">none</span>';
      } else {
        sensorsTd.innerHTML = sensors
          .map((s) => {
            const t =
              s.temperature_c != null ? `${Number(s.temperature_c).toFixed(1)} °C` : "";
            return `<span class="facade-sensor">${escapeHtml(s.name)}${
              t ? ` <span class="overview-meta">${t}</span>` : ""
            }</span>`;
          })
          .join("");
      }

      tr.append(nameTd, areaTd, facadeTd, solarTd, sensorsTd);
      facadeBody.appendChild(tr);
    }

    if (facadeStatusEl) {
      facadeStatusEl.textContent =
        `Updated ${new Date().toLocaleTimeString("en-GB")}` +
        (data.enabled ? "" : " · network off") +
        (outdoor.available ? "" : " · outdoor forecast unavailable");
    }
  }  async function patchFacade(roomId, groupEl) {
    const exterior = [...groupEl.querySelectorAll("input:checked")].map(
      (el) => el.value
    );
    const res = await fetch(
      `/api/apartment/rooms/${encodeURIComponent(roomId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ exterior }),
      }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    await loadFacades();
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

  /** Chart.js plugin: shaded time ranges for window open/close advice. */
  const windowBandsPlugin = {
    id: "windowBands",
    beforeDatasetsDraw(chart) {
      const cfg = chart.options.plugins && chart.options.plugins.windowBands;
      const bands = cfg && cfg.bands;
      if (!bands || !bands.length) return;
      const { ctx, chartArea, scales } = chart;
      const xScale = scales.x;
      if (!xScale || !chartArea) return;
      ctx.save();
      for (const band of bands) {
        const x1 = xScale.getPixelForValue(band.x1);
        const x2 = xScale.getPixelForValue(band.x2);
        if (!Number.isFinite(x1) || !Number.isFinite(x2)) continue;
        const left = Math.max(chartArea.left, Math.min(x1, x2));
        const right = Math.min(chartArea.right, Math.max(x1, x2));
        if (right - left < 0.5) continue;
        ctx.fillStyle =
          band.kind === "open"
            ? "rgba(76, 175, 120, 0.16)"
            : band.kind === "humid"
              ? "rgba(90, 140, 170, 0.16)"
              : "rgba(210, 140, 70, 0.14)";
        ctx.fillRect(left, chartArea.top, right - left, chartArea.bottom - chartArea.top);
      }
      ctx.restore();
    },
  };
  if (typeof Chart !== "undefined" && Chart.register) {
    Chart.register(windowBandsPlugin);
  }

  /** Chart.js plugin: shaded time ranges when HVAC / AC is on. */
  const hvacBandsPlugin = {
    id: "hvacBands",
    beforeDatasetsDraw(chart) {
      const cfg = chart.options.plugins && chart.options.plugins.hvacBands;
      const bands = cfg && cfg.bands;
      if (!bands || !bands.length) return;
      const { ctx, chartArea, scales } = chart;
      const xScale = scales.x;
      if (!xScale || !chartArea) return;
      ctx.save();
      for (const band of bands) {
        const x1 = xScale.getPixelForValue(band.x1);
        const x2 = xScale.getPixelForValue(band.x2);
        if (!Number.isFinite(x1) || !Number.isFinite(x2)) continue;
        const left = Math.max(chartArea.left, Math.min(x1, x2));
        const right = Math.min(chartArea.right, Math.max(x1, x2));
        if (right - left < 0.5) continue;
        ctx.fillStyle = "rgba(100, 160, 255, 0.14)";
        ctx.fillRect(left, chartArea.top, right - left, chartArea.bottom - chartArea.top);
      }
      ctx.restore();
    },
  };
  if (typeof Chart !== "undefined" && Chart.register) {
    Chart.register(hvacBandsPlugin);
  }

  const WINDOW_DELTA_C = 0.5;
  /** Outdoor dew point must stay this far below indoor air temp to advise opening. */
  const WINDOW_DEW_MARGIN_C = 0.5;
  const WINDOW_ALIGN_GAP_S = 2700;
  const WINDOW_NOTIFY_COOLDOWN_MS = 15 * 60 * 1000;

  function nearestIndoor(series, ts, maxGapS) {
    if (!series.length) return null;
    let best = null;
    let bestGap = Infinity;
    for (const p of series) {
      const gap = Math.abs(p.ts - ts);
      if (gap < bestGap) {
        bestGap = gap;
        best = p;
      }
    }
    if (!best || bestGap > maxGapS) return null;
    return best;
  }

  /**
   * open  = outdoor cooler and dew point low enough
   * close = outdoor warmer
   * humid = outdoor cooler but dew point too high
   * null  = near balance
   */
  function windowAdviceKind(tin, text, rhOut, thresholdC) {
    if (tin == null || text == null) return null;
    const d = tin - text;
    if (d <= -thresholdC) return "close";
    if (d >= thresholdC) {
      if (rhOut != null && rhOut > 0) {
        const dewOut = dewPoint(text, rhOut);
        if (dewOut >= tin - WINDOW_DEW_MARGIN_C) return "humid";
      }
      return "open";
    }
    return null;
  }

  /**
   * Build open/close bands from indoor vs outdoor temperature and humidity.
   * Optional windOpts → attach natural/mechanical vent mode per band.
   */
  function buildWindowBands(indoorSeries, outdoorPoints, thresholdC, windOpts) {
    if (!indoorSeries.length || !outdoorPoints.length) return [];
    const exterior = (windOpts && windOpts.exterior) || null;
    const allExterior = (windOpts && windOpts.allExterior) || exterior;
    const samples = [];
    for (const p of outdoorPoints) {
      const indoor = nearestIndoor(indoorSeries, p.ts, WINDOW_ALIGN_GAP_S);
      if (!indoor || indoor.t == null || p.temperature_c == null) continue;
      const kind = windowAdviceKind(
        indoor.t,
        p.temperature_c,
        p.humidity,
        thresholdC
      );
      let vent = null;
      if (exterior && exterior.length) {
        vent = ventilationMode(
          kind,
          exterior,
          allExterior,
          p.wind_speed_ms,
          p.wind_direction_deg
        );
      }
      samples.push({ ts: p.ts, kind, vent });
    }
    if (!samples.length) return [];

    const bands = [];
    let i = 0;
    while (i < samples.length) {
      const kind = samples[i].kind;
      const vent = samples[i].vent;
      if (!kind) {
        i += 1;
        continue;
      }
      let j = i;
      while (
        j + 1 < samples.length &&
        samples[j + 1].kind === kind &&
        samples[j + 1].vent === vent
      ) {
        j += 1;
      }
      const start = samples[i].ts;
      const endSample = samples[j];
      const nextTs =
        j + 1 < samples.length ? samples[j + 1].ts : endSample.ts + 3600;
      const end = Math.max(endSample.ts, (endSample.ts + nextTs) / 2);
      bands.push({
        kind,
        vent: vent || undefined,
        x1: start * 1000,
        x2: Math.max(start, end) * 1000,
      });
      i = j + 1;
    }
    return bands;
  }

  function loadWindowNotifyState() {
    try {
      const raw = localStorage.getItem(WINDOW_NOTIFY_STATE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function saveWindowNotifyState(state) {
    localStorage.setItem(WINDOW_NOTIFY_STATE_KEY, JSON.stringify(state));
  }

  function windowAdviceMessage(kind, label, tin, text) {
    const dIn = tin != null ? tin.toFixed(1) : "?";
    const dOut = text != null ? text.toFixed(1) : "?";
    if (kind === "open") {
      return {
        title: `Open windows — ${label}`,
        body: `Outdoor air is cooler (${dOut} °C vs ${dIn} °C indoors) and dry enough.`,
      };
    }
    if (kind === "close") {
      return {
        title: `Close windows — ${label}`,
        body: `Outdoor air is warmer (${dOut} °C vs ${dIn} °C indoors).`,
      };
    }
    if (kind === "humid") {
      return {
        title: `Keep windows closed — ${label}`,
        body: `Outdoor is cooler (${dOut} °C) but too humid (high dew point).`,
      };
    }
    return null;
  }

  /**
   * Prefer window contacts for a room; fall back to doors if none tagged window.
   */
  function contactsForRoom(roomId) {
    const room = String(roomId || "").toLowerCase();
    if (!room) return [];
    const inRoom = doorSensors.filter(
      (s) => String(s.room || "").toLowerCase() === room
    );
    const windows = inRoom.filter((s) => (s.kind || "") === "window");
    if (windows.length) return windows;
    return inRoom.filter((s) => (s.kind || "") === "door");
  }

  function roomOpeningState(roomId) {
    const contacts = contactsForRoom(roomId);
    const openOnes = contacts.filter((s) => s.state === "open");
    const closedOnes = contacts.filter((s) => s.state === "closed");
    return {
      contacts,
      known: contacts.length > 0,
      anyOpen: openOnes.length > 0,
      openNames: openOnes.map((s) => s.name || s.sensor_id),
      closedCount: closedOnes.length,
      openCount: openOnes.length,
    };
  }

  function roomDisplayName(roomId, device) {
    const fromTax = categoryLabel("room", roomId);
    if (fromTax && fromTax !== "—") return fromTax;
    if (device) return deviceLabel(device);
    return roomId;
  }

  function outdoorNowFromForecast(fc) {
    if (!fc || !(fc.outdoor || []).length) return null;
    const now = Date.now() / 1000;
    return fc.outdoor.reduce((best, p) => {
      if (!best) return p;
      return Math.abs(p.ts - now) < Math.abs(best.ts - now) ? p : best;
    }, null);
  }

  /**
   * Cross climate advice with live contact state → banner actions.
   */
  function buildWindowBannerModel(forecast) {
    const outdoorNow = outdoorNowFromForecast(forecast);
    if (!outdoorNow || outdoorNow.temperature_c == null) {
      return { tone: "idle", title: "", detail: "", hidden: true };
    }

    const rooms = interiorRoomDevices();
    if (!rooms.length) {
      return { tone: "idle", title: "", detail: "", hidden: true };
    }

    const closeNow = [];
    const openNow = [];
    const okOpen = [];
    const okClosed = [];
    const openContactNames = [];
    let humidBias = false;

    for (const [room, device] of rooms) {
      const openings = roomOpeningState(room);
      if (!openings.known) continue;

      const tin = Number(device.temperature_c);
      const text = Number(outdoorNow.temperature_c);
      const kind = windowAdviceKind(
        tin,
        text,
        outdoorNow.humidity,
        WINDOW_DELTA_C
      );
      const label = roomDisplayName(room, device);
      for (const name of openings.openNames) {
        if (!openContactNames.includes(name)) openContactNames.push(name);
      }

      if (kind === "close" || kind === "humid") {
        if (kind === "humid") humidBias = true;
        if (openings.anyOpen) closeNow.push(label);
        else okClosed.push(label);
      } else if (kind === "open") {
        if (openings.anyOpen) okOpen.push(label);
        else openNow.push(label);
      }
    }

    if (
      !closeNow.length &&
      !openNow.length &&
      !okOpen.length &&
      !okClosed.length
    ) {
      const hasContacts = doorSensors.some(
        (s) => s.kind === "window" || s.kind === "door"
      );
      return {
        hidden: false,
        tone: "idle",
        title: hasContacts
          ? "No interior rooms with both a sensor and a contact"
          : "No door/window contacts linked to rooms",
        detail: hasContacts
          ? "Assign a room on Overview → Doors & windows to include them here."
          : "Enable [doors] and map contacts to rooms on Overview.",
      };
    }

    const outT = Number(outdoorNow.temperature_c).toFixed(1);
    let climateBit = `Outdoor ${outT} °C`;
    if (outdoorNow.humidity != null && outdoorNow.humidity > 0) {
      const dew = dewPoint(outdoorNow.temperature_c, outdoorNow.humidity);
      climateBit += ` · dew ${dew.toFixed(1)} °C · RH ${Number(outdoorNow.humidity).toFixed(0)} %`;
    }
    const openBit = openContactNames.length
      ? `Open now: ${openContactNames.join(", ")}`
      : "All tracked openings closed";

    const join = (arr) => arr.join(", ");

    let tone = "idle";
    let title = "No strong window action";
    let detail = `${climateBit}. Indoor and outdoor temperatures are close. ${openBit}.`;

    if (closeNow.length) {
      tone = humidBias ? "humid" : "close";
      title = `Close windows — ${join(closeNow)}`;
      detail = humidBias
        ? `${climateBit}. Outdoor is cooler but too humid while openings are still open. ${openBit}.`
        : `${climateBit}. Outdoor air is warmer than indoors. ${openBit}.`;
      if (openNow.length) {
        detail = `${detail} Also open: ${join(openNow)}.`;
      }
    } else if (openNow.length) {
      tone = "open";
      title = `Open windows — ${join(openNow)}`;
      detail = `${climateBit}. Outdoor is cooler and dry enough. ${openBit}.`;
    } else if (okOpen.length) {
      tone = "ok";
      title = `Windows OK open — ${join(okOpen)}`;
      detail = `${climateBit}. Cooling with outdoor air. ${openBit}.`;
      if (okClosed.length) {
        detail = `${detail} Closed OK: ${join(okClosed)}.`;
      }
    } else if (okClosed.length) {
      tone = "ok";
      title = `Windows OK closed — ${join(okClosed)}`;
      detail = `${climateBit}. ${openBit}.`;
    }

    return { hidden: false, tone, title, detail };
  }

  function renderWindowBanner(model) {
    if (!windowBannerEl) return;
    if (!model || model.hidden) {
      windowBannerEl.hidden = true;
      return;
    }
    windowBannerEl.hidden = false;
    windowBannerEl.className = `window-banner window-banner-tone-${model.tone || "idle"}`;
    if (windowBannerTitleEl) windowBannerTitleEl.textContent = model.title || "";
    if (windowBannerDetailEl) windowBannerDetailEl.textContent = model.detail || "";
  }

  async function updateWindowBanner(forecast) {
    let fc = forecast;
    if (!fc || !fc.enabled) {
      const addrs = interiorRoomDevices().map(([, d]) => d.address);
      if (!addrs.length) {
        renderWindowBanner({ hidden: true });
        return;
      }
      try {
        fc = await fetchForecast(addrs);
      } catch (err) {
        console.warn(err);
        renderWindowBanner({
          hidden: false,
          tone: "idle",
          title: "Window advice unavailable",
          detail: err.message || "Could not load outdoor forecast.",
        });
        return;
      }
    }
    if (!fc || !fc.enabled) {
      renderWindowBanner({
        hidden: false,
        tone: "idle",
        title: "Window advice needs outdoor weather",
        detail: "Allow location or set [weather] place in config.",
      });
      return;
    }
    renderWindowBanner(buildWindowBannerModel(fc));
  }

  async function ensureNotifyPermission() {
    if (!("Notification" in window)) {
      return "unsupported";
    }
    if (!window.isSecureContext) {
      return "insecure";
    }
    if (Notification.permission === "granted") return "granted";
    if (Notification.permission === "denied") return "denied";
    const result = await Notification.requestPermission();
    return result;
  }

  function sendWindowNotification(title, body, tag) {
    if (!("Notification" in window) || Notification.permission !== "granted") {
      return;
    }
    try {
      const n = new Notification(title, {
        body,
        tag: tag || "govee-window",
        renotify: true,
      });
      n.onclick = () => {
        window.focus();
        n.close();
      };
    } catch (err) {
      console.warn("Notification failed", err);
    }
  }

  /**
   * Prefer one sensor per interior room (skip exterior / uncategorized).
   */
  function interiorRoomDevices() {
    const byRoom = new Map();
    for (const d of devices) {
      const zone = (d.zone || "").toLowerCase();
      if (zone === "exterior") continue;
      const room = (d.room || "").toLowerCase();
      if (!room || room === "other") continue;
      if (d.temperature_c == null || d.humidity == null) continue;
      if (!byRoom.has(room)) byRoom.set(room, d);
    }
    return [...byRoom.entries()];
  }

  async function evaluateWindowNotifications(forecast) {
    if (!windowNotify) return;
    if (!("Notification" in window) || Notification.permission !== "granted") {
      return;
    }
    let fc = forecast;
    if (!fc || !fc.enabled) {
      const addrs = interiorRoomDevices().map(([, d]) => d.address);
      if (!addrs.length) return;
      try {
        fc = await fetchForecast(addrs);
      } catch (err) {
        console.warn(err);
        return;
      }
    }
    if (!fc || !fc.enabled || !(fc.outdoor || []).length) return;

    const now = Date.now() / 1000;
    const outdoorNow = fc.outdoor.reduce((best, p) => {
      if (!best) return p;
      return Math.abs(p.ts - now) < Math.abs(best.ts - now) ? p : best;
    }, null);
    if (!outdoorNow) return;

    const state = loadWindowNotifyState();
    const nowMs = Date.now();
    let changed = false;

    for (const [room, device] of interiorRoomDevices()) {
      const tin = Number(device.temperature_c);
      const text = Number(outdoorNow.temperature_c);
      const kind = windowAdviceKind(
        tin,
        text,
        outdoorNow.humidity,
        WINDOW_DELTA_C
      );
      const key = room;
      const prev = state[key] || {};
      const prevKind = prev.kind || null;
      const lastAt = Number(prev.at) || 0;

      if (kind === prevKind) {
        continue;
      }
      // First observation: seed silently
      if (!prevKind && !prev.seeded) {
        state[key] = { kind, at: nowMs, seeded: true };
        changed = true;
        continue;
      }
      if (nowMs - lastAt < 60_000) {
        continue;
      }
      // Same actionable kind within cooldown after a flicker through null
      if (
        kind &&
        kind === prev.lastActionable &&
        nowMs - lastAt < WINDOW_NOTIFY_COOLDOWN_MS
      ) {
        state[key] = {
          kind,
          at: nowMs,
          seeded: true,
          lastActionable: kind,
        };
        changed = true;
        continue;
      }

      const label = deviceLabel(device);
      const msg = windowAdviceMessage(kind, label, tin, text);
      if (msg) {
        sendWindowNotification(msg.title, msg.body, `govee-window-${key}`);
      } else if (prevKind === "open" || prevKind === "close" || prevKind === "humid") {
        sendWindowNotification(
          `Windows — ${label}`,
          `Indoor and outdoor temperatures are close (${tin.toFixed(1)} °C / ${text.toFixed(1)} °C).`,
          `govee-window-${key}`
        );
      }

      state[key] = {
        kind,
        at: nowMs,
        seeded: true,
        lastActionable: kind || prev.lastActionable || null,
      };
      changed = true;
    }

    if (changed) saveWindowNotifyState(state);
  }

  function setTempWindowBands(bands, deviceLabel) {
    if (!tempChart) return;
    if (!tempChart.options.plugins) tempChart.options.plugins = {};
    tempChart.options.plugins.windowBands = { bands: bands || [] };
    if (windowLegendEl) {
      const show = bands && bands.length > 0;
      windowLegendEl.hidden = !show;
      if (show && deviceLabel) {
        windowLegendEl.title =
          `Based on ${deviceLabel} vs outdoor (temp ±${WINDOW_DELTA_C} °C, ` +
          `dew point vs indoor air)`;
      } else {
        windowLegendEl.title = "";
      }
    }
  }

  function setTempHvacBands(bands) {
    if (!tempChart) return;
    if (!tempChart.options.plugins) tempChart.options.plugins = {};
    tempChart.options.plugins.hvacBands = { bands: bands || [] };
    if (hvacLegendEl) {
      hvacLegendEl.hidden = !(bands && bands.length > 0);
    }
  }

  function setTempPowerScale(enabled) {
    if (!tempChart) return;
    if (!tempChart.options.scales) tempChart.options.scales = {};
    if (enabled) {
      tempChart.options.scales.y = {
        ...(tempChart.options.scales.y || {}),
        position: "left",
        title: {
          display: true,
          text: "°C",
          color: "#8a9a88",
        },
        ticks: { color: "#8a9a88" },
        grid: { color: "rgba(42,53,44,0.7)" },
      };
      tempChart.options.scales.yPower = {
        position: "right",
        title: {
          display: true,
          text: "W",
          color: "#8aa8d8",
        },
        ticks: { color: "#8aa8d8" },
        grid: { drawOnChartArea: false },
        beginAtZero: true,
      };
    } else if (tempChart.options.scales.yPower) {
      delete tempChart.options.scales.yPower;
      if (tempChart.options.scales.y) {
        delete tempChart.options.scales.y.title;
        tempChart.options.scales.y.position = "left";
      }
    }
  }

  function renderHvacStatus(snapshot) {
    if (!hvacStatusEl) return;
    const climate = snapshot && snapshot.climate;
    const power = snapshot && snapshot.power;
    if (!climate && !power) {
      hvacStatusEl.hidden = true;
      hvacStatusEl.innerHTML = "";
      return;
    }
    hvacStatusEl.hidden = false;
    const active = !!(snapshot && snapshot.active);
    const mode = (climate && (climate.hvac_mode || climate.state)) || "—";
    const target =
      climate && climate.target_temp_c != null
        ? `${Number(climate.target_temp_c).toFixed(1)} °C`
        : "—";
    const current =
      climate && climate.current_temp_c != null
        ? `${Number(climate.current_temp_c).toFixed(1)} °C`
        : "—";
    const watts =
      power && power.watts != null ? `${Math.round(Number(power.watts))} W` : "—";
    const when = climate && climate.ts
      ? new Date(climate.ts * 1000).toLocaleTimeString("en-GB")
      : power && power.ts
        ? new Date(power.ts * 1000).toLocaleTimeString("en-GB")
        : "";
    hvacStatusEl.innerHTML = `
      <span><span class="hvac-pill ${active ? "hvac-pill-on" : "hvac-pill-off"}">${
        active ? "AC on" : "AC off"
      }</span></span>
      <span>Mode <strong>${escapeHtml(String(mode))}</strong></span>
      <span>Setpoint <strong>${escapeHtml(target)}</strong></span>
      <span>AC temp <strong>${escapeHtml(current)}</strong></span>
      <span>Power <strong>${escapeHtml(watts)}</strong></span>
      ${when ? `<span>Updated ${escapeHtml(when)}</span>` : ""}
    `;
  }

  function ensureCharts() {
    if (tempChart && humChart && dewChart) {
      bindChartLegend(tempChart);
      bindChartLegend(humChart);
      bindChartLegend(dewChart);
      return;
    }
    const tempOpts = structuredClone(chartDefaults);
    tempOpts.plugins.windowBands = { bands: [] };
    tempOpts.plugins.hvacBands = { bands: [] };
    tempChart = new Chart(document.getElementById("temp-chart"), {
      type: "line",
      data: { datasets: [] },
      options: tempOpts,
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
    bindChartLegend(tempChart);
    bindChartLegend(humChart);
    bindChartLegend(dewChart);
  }

  function makeDataset(label, color, data, fill, extra = {}) {
    const colorText = String(color || "");
    const hexBody = colorText.startsWith("#") ? colorText.slice(1) : colorText;
    const hexOk = !colorText.startsWith("rgba") && /^[0-9a-fA-F]{6}$/.test(hexBody);
    return {
      label,
      data,
      borderColor: color,
      backgroundColor: fill && hexOk ? hexToRgba(colorText.startsWith("#") ? colorText : `#${hexBody}`, 0.12) : "transparent",
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
    projectionsEl.innerHTML = "";
    if (foldProjectionsEl) foldProjectionsEl.hidden = true;
    if (foldProjectionsMetaEl) foldProjectionsMetaEl.textContent = "";
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
      const nowPt = forecast.outdoor.reduce((best, p) => {
        const now = Date.now() / 1000;
        if (!best) return p;
        return Math.abs(p.ts - now) < Math.abs(best.ts - now) ? p : best;
      }, null);
      const windTxt = formatWindNow({
        wind_speed_ms: nowPt && nowPt.wind_speed_ms,
        wind_direction_deg: nowPt && nowPt.wind_direction_deg,
        wind_compass: null,
      });
      cards.push(`
        <article class="projection-card projection-weather">
          <h4>Weather · ${escapeHtml(where || "Open-Meteo")}</h4>
          <p class="projection-meta">
            Temp ${Math.min(...temps).toFixed(1)}–${Math.max(...temps).toFixed(1)} °C
            · Hum ${Math.min(...hums).toFixed(0)}–${Math.max(...hums).toFixed(0)} %
            · next ${hours} h${windTxt}
          </p>
        </article>
      `);
    }

    const projections = forecast.projections || {};
    let projCount = 0;
    for (const device of selectedDevices()) {
      const proj = projections[device.address];
      if (!proj || !proj.summary) continue;
      projCount += 1;
      const s = proj.summary;
      const delta = proj.bias_temp;
      const deltaTxt = `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} °C`;
      let modelTxt = `Δ ${deltaTxt}`;
      if (proj.model === "network" || proj.model === "network_open") {
        const room = proj.room ? String(proj.room) : "room";
        const openBit = proj.model === "network_open" ? " · windows open" : "";
        modelTxt = `network · ${room}${openBit} · Δ ${deltaTxt}`;
      } else if (proj.model === "rc_open") {
        modelTxt = `τ ${Number(proj.tau_hours).toFixed(1)} h open · Δ ${deltaTxt}`;
      } else if (proj.model === "rc_closed") {
        modelTxt = `τ ${Number(proj.tau_hours).toFixed(1)} h closed · Δ ${deltaTxt}`;
      } else if (proj.model === "rc" && proj.tau_hours > 0) {
        modelTxt = `τ ${Number(proj.tau_hours).toFixed(1)} h · Δ ${deltaTxt}`;
      } else if (proj.model === "offset") {
        modelTxt = `offset · Δ ${deltaTxt}`;
      }
      let scenarioTxt = "";
      const scenarios = proj.window_scenarios || {};
      const closed = scenarios.windows_closed;
      const opened = scenarios.windows_open;
      if (closed && closed.summary && opened && opened.summary) {
        const cSrc = closed.source && closed.source !== "default" ? `/${closed.source}` : "";
        const oSrc = opened.source && opened.source !== "default" ? `/${opened.source}` : "";
        scenarioTxt =
          ` · closed${cSrc} ${Number(closed.summary.temp_min).toFixed(1)}–${Number(closed.summary.temp_max).toFixed(1)} °C` +
          ` · open${oSrc} ${Number(opened.summary.temp_min).toFixed(1)}–${Number(opened.summary.temp_max).toFixed(1)} °C`;
      }
      cards.push(`
        <article class="projection-card" style="--device-color:${colorFor(device.address)}">
          <h4>${escapeHtml(deviceLabel(device))} · projected</h4>
          <p class="projection-meta">
            Temp ${s.temp_min.toFixed(1)}–${s.temp_max.toFixed(1)} °C
            · Hum ${
              s.humidity_min != null && s.humidity_max != null
                ? `${s.humidity_min.toFixed(0)}–${s.humidity_max.toFixed(0)} %`
                : "—"
            }
            · ${modelTxt}${scenarioTxt}
          </p>
        </article>
      `);
    }

    if (!cards.length) {
      clearProjections();
      return;
    }
    projectionsEl.innerHTML = cards.join("");
    if (foldProjectionsEl) foldProjectionsEl.hidden = false;
    if (foldProjectionsMetaEl) {
      const bits = [];
      if (loc && (forecast.outdoor || []).length) bits.push("weather");
      if (projCount) bits.push(`${projCount} sensor${projCount === 1 ? "" : "s"}`);
      foldProjectionsMetaEl.textContent = bits.length ? `· ${bits.join(" · ")}` : "";
    }
  }

  async function fetchForecast(addresses) {
    if (!showForecast && !showWindowBands && !windowNotify) {
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
        '<tr><td colspan="10" class="overview-empty">No devices detected</td></tr>';
      overviewStatus.textContent = "Waiting for BLE devices…";
      return;
    }
    if (!visible.length) {
      overviewBody.innerHTML =
        '<tr><td colspan="10" class="overview-empty">No sensors for these filters</td></tr>';
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

      const rssiTd = document.createElement("td");
      rssiTd.className = "num rssi-cell";
      rssiTd.innerHTML = rssiHtml(device.rssi);

      const sourceTd = document.createElement("td");
      sourceTd.className = "overview-source";
      sourceTd.innerHTML = sourceHtml(source);

      const timeTd = document.createElement("td");
      timeTd.textContent = fmtTime(device.last_reading_ts || device.last_seen);

      tr.append(
        nameTd,
        zoneTd,
        heightTd,
        roomTd,
        tempTd,
        humTd,
        battTd,
        rssiTd,
        sourceTd,
        timeTd
      );
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
    if (foldCurrentMetaEl) {
      foldCurrentMetaEl.textContent = picked.length
        ? `· ${picked.length} sensor${picked.length === 1 ? "" : "s"}`
        : "· none selected";
    }
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
            <span class="metric-label">Signal</span>
            <span class="metric-value metric-rssi">${rssiHtml(device.rssi)}</span>
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
    await loadDoors();
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
      setTempWindowBands([]);
      setTempHvacBands([]);
      setTempPowerScale(false);
      renderHvacStatus(null);
      tempChart.update();
      humChart.update();
      dewChart.update();
      clearProjections();
      statusEl.textContent = "Select at least one device…";
      historyLoaded = true;
      return;
    }

    const hvacPromise = showHvac
      ? Promise.all([
          fetch(`/api/hvac`).then(async (res) =>
            res.ok ? res.json() : { climate: null, power: null, active: false }
          ),
          fetch(`/api/hvac/history?hours=${hours}`).then(async (res) =>
            res.ok ? res.json() : { events: [], bands: [] }
          ),
          fetch(`/api/power/history?hours=${hours}`).then(async (res) =>
            res.ok ? res.json() : { points: [] }
          ),
        ]).catch((err) => {
          console.warn(err);
          return [
            { climate: null, power: null, active: false },
            { events: [], bands: [] },
            { points: [] },
          ];
        })
      : Promise.resolve(null);

    const [results, forecast, hvacBundle] = await Promise.all([
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
      hvacPromise,
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
      if (outdoor.length && (showForecast || showWindowBands)) {
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
        if (showForecast) {
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
      }

      if (showForecast) {
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
                .map((p) => ({
                  x: p.ts * 1000,
                  y: dewPoint(p.temperature_c, p.humidity),
                })),
              false,
              { borderDash: [2, 4], borderWidth: 1.5 }
            )
          );

          const scenarios = proj.window_scenarios || {};
          const closedPts = (scenarios.windows_closed && scenarios.windows_closed.points) || [];
          const openPts = (scenarios.windows_open && scenarios.windows_open.points) || [];
          if (closedPts.length) {
            tempDatasets.push(
              makeDataset(
                `${deviceLabel(device)} (windows closed)`,
                color,
                closedPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [8, 4], borderWidth: 1.35 }
              )
            );
          }
          if (openPts.length) {
            tempDatasets.push(
              makeDataset(
                `${deviceLabel(device)} (windows open)`,
                color,
                openPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [1, 3], borderWidth: 1.85 }
              )
            );
          }
        }
      }
    }

    let hvacExtra = "";
    if (showHvac && hvacBundle) {
      const [snapshot, hvacHist, powerHist] = hvacBundle;
      renderHvacStatus(snapshot);
      const bands = (hvacHist && hvacHist.bands) || [];
      setTempHvacBands(bands);
      const powerPoints = (powerHist && powerHist.points) || [];
      if (powerPoints.length) {
        setTempPowerScale(true);
        tempDatasets.push(
          makeDataset(
            "Power (Ecojoko)",
            "#8aa8d8",
            powerPoints.map((p) => ({ x: p.ts * 1000, y: p.watts })),
            false,
            {
              yAxisID: "yPower",
              borderWidth: 1.5,
              borderDash: [4, 3],
            }
          )
        );
      } else {
        setTempPowerScale(false);
      }
      if (bands.length || powerPoints.length) {
        hvacExtra =
          ` · AC bands×${bands.length}` +
          (powerPoints.length ? `, power ${powerPoints.length} pt` : "");
      }
    } else {
      renderHvacStatus(null);
      setTempHvacBands([]);
      setTempPowerScale(false);
    }

    tempChart.data.datasets = withLegendState("temp", tempDatasets);
    humChart.data.datasets = withLegendState("hum", humDatasets);
    dewChart.data.datasets = withLegendState("dew", dewDatasets);
    const showLegend = tempDatasets.length > 1;
    tempChart.options.plugins.legend.display = showLegend;
    humChart.options.plugins.legend.display = showLegend;
    dewChart.options.plugins.legend.display = showLegend;
    bindChartLegend(tempChart);
    bindChartLegend(humChart);
    bindChartLegend(dewChart);

    let windowExtra = "";
    if (
      showWindowBands &&
      forecast &&
      forecast.enabled &&
      (forecast.outdoor || []).length
    ) {
      const room = results.find(
        (r) => (r.device.zone || "").toLowerCase() !== "exterior"
      );
      if (room) {
        const indoor = (room.points || []).map((p) => ({
          ts: p.ts,
          t: p.temperature_c,
          rh: p.humidity,
        }));
        const proj =
          forecast.projections && forecast.projections[room.device.address];
        if (proj && proj.points) {
          for (const p of proj.points) {
            indoor.push({
              ts: p.ts,
              t: p.temperature_c,
              rh: p.humidity,
            });
          }
        }
        const bands = buildWindowBands(
          indoor,
          forecast.outdoor,
          WINDOW_DELTA_C
        );
        setTempWindowBands(bands, deviceLabel(room.device));
        if (bands.length) {
          const openN = bands.filter((b) => b.kind === "open").length;
          const closeN = bands.filter((b) => b.kind === "close").length;
          const humidN = bands.filter((b) => b.kind === "humid").length;
          windowExtra =
            ` · windows ${deviceLabel(room.device)} ` +
            `(open×${openN}, close×${closeN}, humid×${humidN})`;
        }
      } else {
        setTempWindowBands([]);
      }
    } else {
      setTempWindowBands([]);
    }

    tempChart.update();
    humChart.update();
    dewChart.update();
    if (showForecast) {
      renderProjections(forecast);
    } else {
      clearProjections();
    }
    historyLoaded = true;
    evaluateWindowNotifications(forecast).catch((err) => console.warn(err));
    updateWindowBanner(forecast).catch((err) => console.warn(err));

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
      `${names} · ${totalPoints} point(s) · window ${hours} h${extra}${windowExtra}${hvacExtra} · updated ` +
      new Date().toLocaleTimeString("en-GB");
  }

  async function refresh() {
    try {
      await loadFederation();
      await loadDevices();
      if (currentView === "compare") {
        await loadHistory();
      } else if (currentView === "facades") {
        await loadFacades();
        await updateWindowBanner(null);
      } else {
        const bannerPromise = updateWindowBanner(null);
        if (windowNotify) {
          await evaluateWindowNotifications(null);
        }
        await bannerPromise;
        await loadBackfill();
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

  if (chartHeightEl) {
    chartHeightEl.value = String(chartHeight);
    const onHeightInput = () => {
      chartHeight = applyChartHeight(chartHeightEl.value);
    };
    chartHeightEl.addEventListener("input", onHeightInput);
    chartHeightEl.addEventListener("change", onHeightInput);
  }

  if (showWindowBandsEl) {
    showWindowBandsEl.checked = showWindowBands;
    showWindowBandsEl.addEventListener("change", () => {
      showWindowBands = showWindowBandsEl.checked;
      localStorage.setItem(WINDOW_BANDS_KEY, showWindowBands ? "1" : "0");
      if (currentView === "compare") {
        loadHistory().catch((err) => {
          statusEl.textContent = `Error: ${err.message}`;
        });
      }
    });
  }

  if (showHvacEl) {
    showHvacEl.checked = showHvac;
    showHvacEl.addEventListener("change", () => {
      showHvac = showHvacEl.checked;
      localStorage.setItem(HVAC_KEY, showHvac ? "1" : "0");
      if (!showHvac) {
        renderHvacStatus(null);
        setTempHvacBands([]);
        setTempPowerScale(false);
      }
      if (currentView === "compare") {
        loadHistory().catch((err) => {
          statusEl.textContent = `Error: ${err.message}`;
        });
      }
    });
  }

  if (windowNotifyEl) {
    windowNotifyEl.checked = windowNotify;
    windowNotifyEl.addEventListener("change", async () => {
      if (windowNotifyEl.checked) {
        const perm = await ensureNotifyPermission();
        if (perm === "granted") {
          windowNotify = true;
          localStorage.setItem(WINDOW_NOTIFY_KEY, "1");
          evaluateWindowNotifications(null).catch((err) => console.warn(err));
        } else {
          windowNotify = false;
          windowNotifyEl.checked = false;
          localStorage.setItem(WINDOW_NOTIFY_KEY, "0");
          let hint = "Notifications blocked by the browser.";
          if (perm === "unsupported") hint = "Notifications not supported.";
          if (perm === "insecure") {
            hint = "Notifications need HTTPS (or localhost).";
          }
          if (geoStatusEl) geoStatusEl.textContent = hint;
          else if (statusEl) statusEl.textContent = hint;
        }
      } else {
        windowNotify = false;
        localStorage.setItem(WINDOW_NOTIFY_KEY, "0");
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

  if (backfillPauseBtn) {
    backfillPauseBtn.addEventListener("click", async () => {
      const paused = Boolean(backfillSnapshot && backfillSnapshot.paused);
      backfillPauseBtn.disabled = true;
      try {
        const res = await fetch(
          paused ? "/api/backfill/resume" : "/api/backfill/pause",
          { method: "POST" }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        renderBackfill(await res.json());
        syncBackfillPolling();
      } catch (err) {
        console.warn(err);
      } finally {
        backfillPauseBtn.disabled = false;
      }
    });
  }
  if (backfillRefreshBtn) {
    backfillRefreshBtn.addEventListener("click", async () => {
      backfillRefreshBtn.disabled = true;
      try {
        const res = await fetch("/api/backfill/refresh", { method: "POST" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        renderBackfill(await res.json());
        syncBackfillPolling();
      } catch (err) {
        console.warn(err);
      } finally {
        backfillRefreshBtn.disabled = false;
      }
    });
  }

  // Collapsible panels — default collapsed; remember open state
  if (foldCurrentEl) {
    foldCurrentEl.open = localStorage.getItem(FOLD_CURRENT_KEY) === "1";
    foldCurrentEl.addEventListener("toggle", () => {
      localStorage.setItem(FOLD_CURRENT_KEY, foldCurrentEl.open ? "1" : "0");
    });
  }
  if (foldProjectionsEl) {
    foldProjectionsEl.open = localStorage.getItem(FOLD_PROJ_KEY) === "1";
    foldProjectionsEl.addEventListener("toggle", () => {
      localStorage.setItem(FOLD_PROJ_KEY, foldProjectionsEl.open ? "1" : "0");
    });
  }

  setView(currentView);
  refresh();
  setInterval(refresh, 30000);
})();
