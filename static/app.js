(() => {
  const deviceList = document.getElementById("device-list");
  const currentEl = document.getElementById("current");
  const statusEl = document.getElementById("status");
  const overviewBody = document.getElementById("overview-body");
  const overviewStatus = document.getElementById("overview-status");
  const viewOverview = document.getElementById("view-overview");
  const viewCompare = document.getElementById("view-compare");
  const selectAllBtn = document.getElementById("select-all");
  const selectNoneBtn = document.getElementById("select-none");
  const rangeButtons = [...document.querySelectorAll(".ranges button")];
  const viewButtons = [...document.querySelectorAll(".views [data-view]")];

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

  let hours = 24;
  let devices = [];
  let selected = new Set();
  let currentView = localStorage.getItem(VIEW_KEY) === "compare" ? "compare" : "overview";
  let tempChart = null;
  let humChart = null;
  let historyLoaded = false;

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
    return devices.filter((d) => selected.has(d.address));
  }

  function sortedByTemperature(list) {
    return [...list].sort((a, b) => {
      const ta = a.temperature_c;
      const tb = b.temperature_c;
      if (ta == null && tb == null) return a.name.localeCompare(b.name, "fr");
      if (ta == null) return 1;
      if (tb == null) return -1;
      if (tb !== ta) return tb - ta;
      return a.name.localeCompare(b.name, "fr");
    });
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
    }
  }

  function ensureCharts() {
    if (tempChart && humChart) return;
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
  }

  function makeDataset(label, color, data, fill) {
    return {
      label,
      data,
      borderColor: color,
      backgroundColor: fill ? hexToRgba(color, 0.12) : "transparent",
      fill,
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2,
    };
  }

  function updateOverview() {
    overviewBody.innerHTML = "";
    if (!devices.length) {
      overviewBody.innerHTML =
        '<tr><td colspan="6" class="overview-empty">No devices detected</td></tr>';
      overviewStatus.textContent = "Waiting for BLE devices…";
      return;
    }

    const ranked = sortedByTemperature(devices);
    for (const device of ranked) {
      const tr = document.createElement("tr");
      tr.style.setProperty("--device-color", colorFor(device.address));
      const source = device.last_source || "—";
      tr.innerHTML = `
        <td>
          <span class="overview-name">
            <span class="device-swatch" aria-hidden="true"></span>
            ${escapeHtml(deviceLabel(device))}
          </span>
          <span class="overview-meta">${escapeHtml(device.model)} · ${escapeHtml(device.address)}</span>
        </td>
        <td class="num temp">${fmtNum(device.temperature_c, 1, " °C")}</td>
        <td class="num">${fmtNum(device.humidity, 1, " %")}</td>
        <td class="num">${device.battery != null ? `${device.battery} %` : "—"}</td>
        <td class="overview-source">${escapeHtml(source)}</td>
        <td>${fmtTime(device.last_reading_ts || device.last_seen)}</td>
      `;
      tr.addEventListener("click", () => {
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
    overviewStatus.textContent =
      `${ranked.length} sensor(s)${span} · updated ${new Date().toLocaleTimeString("en-GB")}`;
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

    if (!devices.length) {
      deviceList.innerHTML = '<p class="device-empty">No devices detected</p>';
      selected = new Set();
      return;
    }

    const known = new Set(devices.map((d) => d.address));
    if (previous.size) {
      selected = new Set([...previous].filter((a) => known.has(a)));
    } else if (persisted && persisted.length) {
      selected = new Set(persisted.filter((a) => known.has(a)));
    }
    if (!selected.size) {
      selected = new Set([devices[0].address]);
    }

    for (const d of devices) {
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
      text.textContent = `${d.name} (${d.model})`;

      label.append(input, swatch, text);
      deviceList.appendChild(label);
    }

    persistSelection();
  }

  async function loadDevices() {
    const res = await fetch("/api/devices");
    if (!res.ok) throw new Error(`devices HTTP ${res.status}`);
    devices = await res.json();
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
      tempChart.update();
      humChart.update();
      statusEl.textContent = "Select at least one device…";
      historyLoaded = true;
      return;
    }

    const results = await Promise.all(
      picked.map(async (device) => {
        const payload = await fetchHistory(device.address);
        return { device, points: payload.points || [] };
      })
    );

    const multi = results.length > 1;
    tempChart.data.datasets = results.map(({ device, points }) => {
      const color = colorFor(device.address);
      return makeDataset(
        deviceLabel(device),
        color,
        points.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
        !multi
      );
    });
    humChart.data.datasets = results.map(({ device, points }) => {
      const color = colorFor(device.address);
      return makeDataset(
        deviceLabel(device),
        color,
        points.map((p) => ({ x: p.ts * 1000, y: p.humidity })),
        !multi
      );
    });
    tempChart.options.plugins.legend.display = multi;
    humChart.options.plugins.legend.display = multi;
    tempChart.update();
    humChart.update();
    historyLoaded = true;

    const totalPoints = results.reduce((n, r) => n + r.points.length, 0);
    const names = results.map((r) => deviceLabel(r.device)).join(", ");
    statusEl.textContent =
      `${names} · ${totalPoints} point(s) · window ${hours} h · updated ` +
      new Date().toLocaleTimeString("en-GB");
  }

  async function refresh() {
    try {
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
    selected = new Set(devices.map((d) => d.address));
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

  setView(currentView);
  refresh();
  setInterval(refresh, 30000);
})();
