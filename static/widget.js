/**
 * Standalone embeddable chart widget.
 *
 * Query params:
 *   metric=temp|hum|dew          (default: temp)
 *   addr=AA:BB:…,CC:DD:…         device addresses (required)
 *   past=24                      past hours (default: 24, max 26280)
 *   future=24                    forecast future hours (0 = off, max 384)
 *   forecast=0|1                 include outdoor forecast curve (default: 1 if future>0)
 *   lat=48.87&lon=2.23           optional GPS (else localStorage / server fallback)
 *   transparent=0|1              transparent page background (default: 0)
 *   legend=0|1                   show legend (default: 1)
 *   refresh=0                    auto-reload seconds (0 = off, max 3600)
 */
(function () {
  "use strict";

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

  const params = new URLSearchParams(window.location.search);
  const metric = (params.get("metric") || "temp").toLowerCase();
  const addresses = (params.get("addr") || "")
    .split(",")
    .map((a) => a.trim().toUpperCase())
    .filter(Boolean);
  const pastH = clamp(Number(params.get("past") || 24), 0.25, 26280);
  const futureH = clamp(Number(params.get("future") || 0), 0, 384);
  const showForecast =
    params.has("forecast")
      ? params.get("forecast") === "1"
      : futureH > 0;
  const transparent = params.get("transparent") === "1";
  const showLegend = params.get("legend") !== "0";
  const refreshSec = clamp(Number(params.get("refresh") || 0), 0, 3600);
  const GEO_KEY = "govee-charts.geo";

  /** @type {{latitude:number, longitude:number}|null} */
  let geoCoords = readGeoFromParams() || readStoredGeo();

  const metaEl = document.getElementById("meta");
  const canvas = document.getElementById("chart");
  let chart = null;

  if (transparent) {
    document.body.classList.add("is-transparent");
  }

  function clamp(n, lo, hi) {
    if (!Number.isFinite(n)) return lo;
    return Math.min(hi, Math.max(lo, n));
  }

  function readGeoFromParams() {
    const lat = Number(params.get("lat") || params.get("latitude"));
    const lon = Number(params.get("lon") || params.get("longitude"));
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
    return { latitude: lat, longitude: lon };
  }

  function readStoredGeo() {
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
      return {
        latitude: parsed.latitude,
        longitude: parsed.longitude,
      };
    } catch (_) {
      return null;
    }
  }

  function dewPoint(tempC, rh) {
    const a = 17.625;
    const b = 243.04;
    const alpha = (a * tempC) / (b + tempC) + Math.log(rh / 100.0);
    return (b * alpha) / (a - alpha);
  }

  function colorFor(index) {
    return PALETTE[index % PALETTE.length];
  }

  function metricLabel() {
    if (metric === "hum") return "Humidity (%)";
    if (metric === "dew") return "Dew point (°C)";
    return "Temperature (°C)";
  }

  function yValue(point) {
    if (metric === "hum") {
      return point.humidity != null && Number.isFinite(Number(point.humidity))
        ? Number(point.humidity)
        : null;
    }
    if (metric === "dew") {
      if (
        point.temperature_c == null ||
        point.humidity == null ||
        !(Number(point.humidity) > 0)
      ) {
        return null;
      }
      return dewPoint(Number(point.temperature_c), Number(point.humidity));
    }
    return point.temperature_c != null &&
      Number.isFinite(Number(point.temperature_c))
      ? Number(point.temperature_c)
      : null;
  }

  function chartOptions(xMin, xMax) {
    const tick = transparent ? "rgba(40,40,40,0.85)" : "#8a9a88";
    const grid = transparent
      ? "rgba(0,0,0,0.12)"
      : "rgba(42,53,44,0.7)";
    const tipBg = transparent ? "rgba(255,255,255,0.92)" : "#1a221c";
    const tipFg = transparent ? "#1a1a1a" : "#e8efe6";
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "time",
          min: xMin,
          max: xMax,
          time: { tooltipFormat: "dd/MM HH:mm" },
          ticks: { color: tick, maxRotation: 0, autoSkipPadding: 12 },
          grid: { color: grid },
        },
        y: {
          ticks: { color: tick },
          grid: { color: grid },
          title: {
            display: true,
            text: metricLabel(),
            color: tick,
            font: { size: 11 },
          },
        },
      },
      plugins: {
        legend: {
          display: showLegend,
          position: "top",
          align: "start",
          labels: {
            color: tick,
            boxWidth: 10,
            boxHeight: 10,
            padding: 8,
            usePointStyle: true,
            pointStyle: "line",
            font: { size: 11 },
          },
        },
        tooltip: {
          backgroundColor: tipBg,
          titleColor: tipFg,
          bodyColor: tipFg,
          borderColor: transparent ? "rgba(0,0,0,0.15)" : "#2a352c",
          borderWidth: 1,
        },
      },
    };
  }

  function makeDataset(label, color, data, extra) {
    return Object.assign(
      {
        label,
        data,
        borderColor: color,
        backgroundColor: "transparent",
        fill: false,
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
        spanGaps: true,
      },
      extra || {}
    );
  }

  async function fetchHistory(address) {
    const q = new URLSearchParams({
      address,
      hours: String(pastH),
      max_points: "2000",
    });
    const res = await fetch(`/api/history?${q}`);
    if (!res.ok) throw new Error(`history ${address}: HTTP ${res.status}`);
    return res.json();
  }

  async function fetchDevices() {
    const res = await fetch("/api/devices");
    if (!res.ok) throw new Error(`devices HTTP ${res.status}`);
    return res.json();
  }

  async function fetchForecast(addrs) {
    if (!showForecast || futureH <= 0) {
      return { enabled: false, outdoor: [] };
    }
    const q = new URLSearchParams({
      hours: String(Math.min(pastH, 384)),
      future_hours: String(futureH),
    });
    for (const a of addrs) q.append("address", a);
    if (geoCoords) {
      q.set("latitude", String(geoCoords.latitude));
      q.set("longitude", String(geoCoords.longitude));
    }
    const res = await fetch(`/api/forecast?${q}`);
    if (!res.ok) throw new Error(`forecast HTTP ${res.status}`);
    return res.json();
  }

  function showError(msg) {
    const wrap = document.getElementById("wrap");
    wrap.innerHTML = `<p id="error">${escapeHtml(msg)}</p>`;
  }

  function escapeHtml(text) {
    return String(text)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  async function render() {
    if (!addresses.length) {
      showError("Missing addr=… query parameter (comma-separated MAC addresses).");
      return;
    }

    const [devices, histories, forecast] = await Promise.all([
      fetchDevices(),
      Promise.all(addresses.map((a) => fetchHistory(a))),
      fetchForecast(addresses),
    ]);

    const byAddr = new Map(
      (devices || []).map((d) => [String(d.address || "").toUpperCase(), d])
    );

    const now = Date.now();
    const xMin = now - pastH * 3600 * 1000;
    const xMax = now + (showForecast && futureH > 0 ? futureH : 0) * 3600 * 1000;

    const datasets = [];
    addresses.forEach((addr, idx) => {
      const device = byAddr.get(addr);
      const label =
        (device && (device.label || device.name)) || addr;
      const points = (histories[idx] && histories[idx].points) || [];
      const data = points
        .map((p) => {
          const y = yValue(p);
          return y == null ? null : { x: p.ts * 1000, y };
        })
        .filter(Boolean);
      datasets.push(makeDataset(label, colorFor(idx), data));
    });

    if (showForecast && forecast && forecast.enabled) {
      const outdoor = forecast.outdoor || [];
      if (outdoor.length) {
        const loc =
          (forecast.location && forecast.location.name) || "Forecast";
        const data = outdoor
          .map((p) => {
            const y = yValue(p);
            return y == null ? null : { x: p.ts * 1000, y };
          })
          .filter(Boolean);
        if (data.length) {
          datasets.push(
            makeDataset(`${loc} (forecast)`, "#c5c9c4", data, {
              borderDash: [6, 4],
              borderWidth: 1.75,
            })
          );
        }
      }
      // Optional per-sensor projections (temperature only for clarity).
      if (metric === "temp" && forecast.projections) {
        addresses.forEach((addr, idx) => {
          const proj =
            forecast.projections[addr] ||
            forecast.projections[String(addr).toUpperCase()];
          const pts = (proj && proj.points) || [];
          if (!pts.length) return;
          const device = byAddr.get(addr);
          const label =
            ((device && (device.label || device.name)) || addr) + " (proj.)";
          datasets.push(
            makeDataset(
              label,
              colorFor(idx),
              pts
                .map((p) =>
                  p.temperature_c == null
                    ? null
                    : { x: p.ts * 1000, y: Number(p.temperature_c) }
                )
                .filter(Boolean),
              { borderDash: [2, 4], borderWidth: 1.5 }
            )
          );
        });
      }
    }

    if (chart) {
      chart.destroy();
      chart = null;
    }
    chart = new Chart(canvas, {
      type: "line",
      data: { datasets },
      options: chartOptions(xMin, xMax),
    });

    const pastLabel =
      pastH >= 24 && pastH % 24 === 0
        ? `${pastH / 24} d`
        : `${pastH} h`;
    const futureBits =
      showForecast && futureH > 0
        ? ` · +${futureH >= 24 && futureH % 24 === 0 ? `${futureH / 24} d` : `${futureH} h`}`
        : "";
    let forecastNote = "";
    if (showForecast && futureH > 0) {
      if (forecast && forecast.enabled) {
        const nOut = (forecast.outdoor || []).length;
        const nProj = forecast.projections
          ? addresses.filter(
              (a) =>
                ((forecast.projections[a] ||
                  forecast.projections[String(a).toUpperCase()] ||
                  {}).points || []).length
            ).length
          : 0;
        forecastNote = ` · forecast ${nOut} pts · proj ${nProj}/${addresses.length}`;
      } else if (forecast && forecast.error) {
        forecastNote = ` · forecast off (${forecast.error})`;
      } else {
        forecastNote = " · forecast off";
      }
    }
    if (metaEl) {
      metaEl.textContent = `${metricLabel()} · −${pastLabel}${futureBits}${forecastNote} · ${addresses.length} sensor${
        addresses.length === 1 ? "" : "s"
      } · ${new Date().toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
      })}`;
    }
  }

  render().catch((err) => {
    console.error(err);
    showError(err.message || String(err));
  });

  if (refreshSec > 0) {
    setInterval(() => {
      render().catch((err) => console.warn(err));
    }, refreshSec * 1000);
  }
})();
