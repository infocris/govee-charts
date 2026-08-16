(() => {
  const I18n = window.I18n || {
    t: (k) => k,
    getLocale: () => "en",
    setLocale: () => {},
    localeTag: () => "en-GB",
    speechLang: () => "en-US",
    applyDom: () => {},
    onLocaleChange: () => () => {},
  };
  const t = (key, vars) => I18n.t(key, vars);

  const deviceList = document.getElementById("device-list");
  const currentEl = document.getElementById("current");
  const statusEl = document.getElementById("status");
  const overviewBody = document.getElementById("overview-body");
  const overviewStatus = document.getElementById("overview-status");
  const overviewDeviceFilterEl = document.getElementById("overview-device-filter");
  const OVERVIEW_TEXT_FILTER_KEY = "govee-charts.overviewTextFilter";
  let overviewTextFilter = localStorage.getItem(OVERVIEW_TEXT_FILTER_KEY) || "";
  if (overviewDeviceFilterEl && overviewTextFilter) {
    overviewDeviceFilterEl.value = overviewTextFilter;
  }
  const doorsBody = document.getElementById("doors-body");
  const doorsStatus = document.getElementById("doors-status");
  const doorLogEl = document.getElementById("door-log");
  const doorLogTitleEl = document.getElementById("door-log-title");
  const doorLogHintEl = document.getElementById("door-log-hint");
  const doorLogBodyEl = document.getElementById("door-log-body");
  const doorLogCloseBtn = document.getElementById("door-log-close");
  let selectedDoorId = null;
  const modelFiltersEl = document.getElementById("model-filters");
  const compareModelFiltersEl = document.getElementById("compare-model-filters");
  const nodeLineEl = document.getElementById("node-line");
  const peerLinksEl = document.getElementById("peer-links");
  const viewOverview = document.getElementById("view-overview");
  const viewCompare = document.getElementById("view-compare");
  const viewFacades = document.getElementById("view-facades");
  const viewNetwork = document.getElementById("view-network");
  const viewBackfill = document.getElementById("view-backfill");
  const viewCoverage = document.getElementById("view-coverage");
  const viewSystem = document.getElementById("view-system");
  const viewSettings = document.getElementById("view-settings");
  const settingsLocaleEl = document.getElementById("settings-locale");
  const settingsStationsEl = document.getElementById("settings-stations");
  const settingsStationsEmptyEl = document.getElementById(
    "settings-stations-empty"
  );
  const systemStorageSummaryEl = document.getElementById("system-storage-summary");
  const systemStorageHintEl = document.getElementById("system-storage-hint");
  const systemSourceSummaryEl = document.getElementById("system-source-summary");
  const systemInventoryHintEl = document.getElementById("system-inventory-hint");
  const systemInventoryBody = document.getElementById("system-inventory-body");
  const systemSensorStorageHintEl = document.getElementById(
    "system-sensor-storage-hint"
  );
  const systemSensorStorageBody = document.getElementById(
    "system-sensor-storage-body"
  );
  const systemCompactionPreviewEl = document.getElementById(
    "system-compaction-preview"
  );
  const systemDeviceEl = document.getElementById("system-device");
  const systemDeviceFilterEl = document.getElementById("system-device-filter");
  const systemDeviceStatusEl = document.getElementById("system-device-status");
  const systemStorageCanvas = document.getElementById("system-storage-chart");
  const systemSourceChartsEl = document.getElementById("system-source-charts");
  const systemRangeButtons = [
    ...document.querySelectorAll("#system-range-buttons > button[data-sys-days]"),
  ];
  const systemGrainButtons = [
    ...document.querySelectorAll(".system-ranges > button[data-sys-grain]"),
  ];
  const systemSelectAllBtn = document.getElementById("system-select-all");
  const systemClearAllBtn = document.getElementById("system-clear-all");
  let systemStorageChart = null;
  /** @type {Chart[]} */
  let systemSourceCharts = [];
  let systemDays = 30;
  let systemGrain = "day";
  let systemBusy = false;
  /** @type {{address:string,name?:string,sample_count?:number}[]} */
  let systemDeviceList = [];
  /** @type {Set<string>} */
  let systemSelectedAddresses = new Set();
  let systemDeviceFilter = "";
  const networkSvgEl = document.getElementById("network-svg");
  const networkCanvasWrapEl = document.getElementById("network-canvas-wrap");
  const networkMetaEl = document.getElementById("network-meta");
  const networkStatusEl = document.getElementById("network-status");
  const networkAirflowEl = document.getElementById("network-airflow");
  const networkTempScaleEl = document.getElementById("network-temp-scale");
  const networkTempScaleLoEl = document.getElementById("network-temp-scale-lo");
  const networkTempScaleHiEl = document.getElementById("network-temp-scale-hi");
  const sectionSvgEl = document.getElementById("section-svg");
  const sectionMetaEl = document.getElementById("section-meta");
  const sectionTempScaleEl = document.getElementById("section-temp-scale");
  const sectionTempScaleLoEl = document.getElementById("section-temp-scale-lo");
  const sectionTempScaleHiEl = document.getElementById("section-temp-scale-hi");
  const networkZoomInBtn = document.getElementById("network-zoom-in");
  const networkZoomOutBtn = document.getElementById("network-zoom-out");
  const networkZoomResetBtn = document.getElementById("network-zoom-reset");
  const mapRoomChartsEl = document.getElementById("map-room-charts");
  const mapRoomChartsTitleEl = document.getElementById("map-room-charts-title");
  const mapRoomChartsMetaEl = document.getElementById("map-room-charts-meta");
  const mapRoomChartsStatusEl = document.getElementById("map-room-charts-status");
  const mapRoomChartsCloseBtn = document.getElementById("map-room-charts-close");
  const mapRoomTempCanvas = document.getElementById("map-room-temp-chart");
  const mapRoomChartCaptionEl = document.getElementById("map-room-chart-caption");
  const mapRoomRangeButtons = [
    ...document.querySelectorAll(".map-room-ranges > button[data-map-hours]"),
  ];
  const networkMetricButtons = [
    ...document.querySelectorAll(".network-metric-ranges > button[data-map-metric]"),
  ];
  const foldMapChatEl = document.getElementById("fold-map-chat");
  const mapChatMetaEl = document.getElementById("map-chat-meta");
  const mapChatStatusEl = document.getElementById("map-chat-status");
  const mapChatLogEl = document.getElementById("map-chat-log");
  const mapChatFormEl = document.getElementById("map-chat-form");
  const mapChatInputEl = document.getElementById("map-chat-input");
  const mapChatSendBtn = document.getElementById("map-chat-send");
  const mapChatClearBtn = document.getElementById("map-chat-clear");
  const mapChatSessionEl = document.getElementById("map-chat-session");
  let mapChatReady = false;
  let mapChatBusy = false;
  let mapChatStatusLoaded = false;
  let mapChatModel = "auto";
  let mapChatSessionsLoaded = false;
  const sectionShowSmallEl = document.getElementById("section-show-small");
  const sectionPathClearBtn = document.getElementById("section-path-clear");
  const NETWORK_VB_W = 920;
  const NETWORK_VB_H = 640;
  const SECTION_VB_W = 960;
  const NETWORK_ZOOM_MIN = 0.6;
  const NETWORK_ZOOM_MAX = 4;
  /** @type {number} */
  // Same viewBox on every screen size means text shrinks a lot more on a
  // narrow phone than the rest of the UI — start pre-zoomed there so
  // room names/temperatures are legible without an extra manual zoom step.
  let networkZoom = window.innerWidth <= 640 ? 2.2 : 1.1;
  /** @type {{x:number,y:number}} viewBox top-left offset at current zoom */
  let networkPan = { x: 0, y: 0 };
  /** @type {{x:number,y:number}|null} */
  let networkPanDrag = null;
  /** @type {"temp"|"humidity"|"both"} */
  let networkMapMetric = "temp";
  /** Include bathroom / WC (area < 3.5 m²) in the cross-section. */
  let sectionShowSmall = false;
  /** Ordered room ids clicked on the topology graph (section waypoints). */
  let sectionWaypoints = [];
  /** Room id selected on the map for temperature charts. */
  let selectedMapRoomId = null;
  let mapRoomHours = 24;
  /** @type {import('chart.js').Chart | null} */
  let mapRoomTempChart = null;
  /** Chart.js instance embedded in the cross-section room volume. */
  let sectionRoomChart = null;
  /** @type {HTMLCanvasElement | null} */
  let sectionRoomChartCanvas = null;
  /** Cached series so section re-renders can repaint without refetch. */
  let mapRoomChartSeriesCache = null;
  let mapRoomChartsBusy = false;
  /** @type {any} */
  let networkLastData = null;
  /** Cached rooms from /api/apartment — used to filter window notifications. */
  let apartmentLastRooms = null;
  const selectAllBtn = document.getElementById("select-all");
  const selectNoneBtn = document.getElementById("select-none");
  const rangeButtons = [
    ...document.querySelectorAll(".ranges > button[data-hours]"),
  ];
  const coverageRangeButtons = [
    ...document.querySelectorAll(".coverage-ranges > button[data-cov-hours]"),
  ];
  const coverageDeviceEl = document.getElementById("coverage-device");
  const coverageSummaryEl = document.getElementById("coverage-summary");
  const coverageBarEl = document.getElementById("coverage-bar");
  const coverageSegmentsEl = document.getElementById("coverage-segments");
  const coverageStatusEl = document.getElementById("coverage-status");
  const coverageAllListEl = document.getElementById("coverage-all-list");
  const coverageAllSummaryEl = document.getElementById("coverage-all-summary");
  const coverageAggEl = document.getElementById("coverage-agg");
  const coverageAggBodyEl = document.getElementById("coverage-agg-body");
  const coverageAggHintEl = document.getElementById("coverage-agg-hint");
  const coverageRecentEl = document.getElementById("coverage-recent");
  const coverageRecentBody = document.getElementById("coverage-recent-body");
  const coverageRecentJobsBody = document.getElementById("coverage-recent-jobs-body");
  const coverageAggButtons = [
    ...document.querySelectorAll(".coverage-agg-ranges > button[data-agg-bucket]"),
  ];
  const coverageFileBarEl = document.getElementById("coverage-file-bar");
  const coverageDbBarEl = document.getElementById("coverage-db-bar");
  const coverageImportBarsEl = document.getElementById("coverage-import-bars");
  const rangeSelectEl = document.getElementById("range-select");
  const rangeCustomEl = document.getElementById("range-custom");
  const rangeSinceEl = document.getElementById("range-since");
  const rangeUntilEl = document.getElementById("range-until");
  const rangeApplyBtn = document.getElementById("range-apply");
  const rangeResetZoomBtn = document.getElementById("range-reset-zoom");
  const viewButtons = [...document.querySelectorAll(".views [data-view]")];
  const viewsNavEl = document.querySelector(".views");
  const dataMegaEl = document.querySelector('.nav-mega[data-mega="data"]');
  const dataMegaToggle = document.getElementById("nav-mega-data-toggle");
  const dataMegaPanel = document.getElementById("nav-mega-data-panel");
  const DATA_VIEWS = new Set(["coverage", "backfill", "system"]);
  const topHeaderEl = document.querySelector(".top");
  const sortButtons = [...document.querySelectorAll(".sort-btn")];
  const gitPullBtn = document.getElementById("git-pull-btn");
  const restartUiBtn = document.getElementById("restart-ui-btn");
  const restartWorkersBtn = document.getElementById("restart-workers-btn");
  const restartStatusEl = document.getElementById("restart-status");
  const widgetMetricEl = document.getElementById("widget-metric");
  const widgetPastEl = document.getElementById("widget-past");
  const widgetFutureEl = document.getElementById("widget-future");
  const widgetForecastEl = document.getElementById("widget-forecast");
  const widgetTransparentEl = document.getElementById("widget-transparent");
  const widgetLegendEl = document.getElementById("widget-legend");
  const widgetRefreshEl = document.getElementById("widget-refresh");
  const widgetCurveListEl = document.getElementById("widget-curve-list");
  const widgetUrlEl = document.getElementById("widget-url");
  const widgetCopyBtn = document.getElementById("widget-copy-btn");
  const widgetOpenBtn = document.getElementById("widget-open-btn");
  const widgetPreviewEl = document.getElementById("widget-preview");
  const widgetExportStatusEl = document.getElementById("widget-export-status");
  const foldWidgetExportEl = document.getElementById("fold-widget-export");
  const widgetCurvesSelectionBtn = document.getElementById(
    "widget-curves-selection"
  );
  const widgetCurvesAllBtn = document.getElementById("widget-curves-all");
  const widgetCurvesNoneBtn = document.getElementById("widget-curves-none");
  /** @type {Set<string>} */
  let widgetSelected = new Set();
  let widgetPreviewTimer = null;
  const facadeBody = document.getElementById("facade-body");
  const facadeMetaEl = document.getElementById("facade-meta");
  const facadeOutdoorEl = document.getElementById("facade-outdoor");
  const facadeChartsEl = document.getElementById("facade-charts");
  const facadeStatusEl = document.getElementById("facade-status");
  const windowBannerEl = document.getElementById("window-banner");
  const topBarEl = document.getElementById("top-bar");
  const windowBannerTitleEl = document.getElementById("window-banner-title");
  const windowBannerDetailEl = document.getElementById("window-banner-detail");
  const systemBannerEl = document.getElementById("system-banner");
  const systemBannerTitleEl = document.getElementById("system-banner-title");
  const systemBannerDetailEl = document.getElementById("system-banner-detail");
  const backfillPanelEl = document.getElementById("backfill-panel");
  const backfillCurrentEl = document.getElementById("backfill-current");
  const backfillQueueEl = document.getElementById("backfill-queue");
  const backfillStatusEl = document.getElementById("backfill-status");
  const backfillPauseBtn = document.getElementById("backfill-pause");
  const backfillRefreshBtn = document.getElementById("backfill-refresh");
  const backfillJobsBody = document.getElementById("backfill-jobs-body");
  const backfillRecentBody = document.getElementById("backfill-recent-body");
  const backfillSensorListEl = document.getElementById("backfill-sensor-list");
  const backfillSensorsHintEl = document.getElementById("backfill-sensors-hint");
  const backfillSelectAllBtn = document.getElementById("backfill-select-all");
  const backfillClearAllBtn = document.getElementById("backfill-clear-all");
  const coverageImportDeviceEl = document.getElementById("coverage-import-device");
  const coverageImportFileEl = document.getElementById("coverage-import-file");
  const coverageDropzoneEl = document.getElementById("coverage-dropzone");
  const coverageBatchEl = document.getElementById("coverage-batch");
  const coverageBatchBodyEl = document.getElementById("coverage-batch-body");
  const coverageBatchSelectAllEl = document.getElementById("coverage-batch-select-all");
  const coverageImportAnalyzeBtn = document.getElementById("coverage-import-analyze");
  const coverageImportConfirmBtn = document.getElementById("coverage-import-confirm");
  const coverageImportClearBtn = document.getElementById("coverage-import-clear");
  const coverageImportStatusEl = document.getElementById("coverage-import-status");
  const coverageImportRecapEl = document.getElementById("coverage-import-recap");
  const coverageImportFileStatsEl = document.getElementById("coverage-import-file-stats");
  const coverageImportExistingStatsEl = document.getElementById(
    "coverage-import-existing-stats"
  );
  const coverageImportCompareStatsEl = document.getElementById(
    "coverage-import-compare-stats"
  );
  const coverageImportMembersWrapEl = document.getElementById(
    "coverage-import-members-wrap"
  );
  const coverageImportMembersEl = document.getElementById("coverage-import-members");
  const coverageImportOverwriteEl = document.getElementById("coverage-import-overwrite");
  const coverageImportOverwriteWrapEl = document.getElementById(
    "coverage-import-overwrite-wrap"
  );
  const coverageImportOverwriteBodyEl = document.getElementById(
    "coverage-import-overwrite-body"
  );
  const coverageImportZigzagWrapEl = document.getElementById(
    "coverage-import-zigzag-wrap"
  );
  const coverageImportZigzagHintEl = document.getElementById(
    "coverage-import-zigzag-hint"
  );
  const coverageImportZigzagBodyEl = document.getElementById(
    "coverage-import-zigzag-body"
  );
  const mailInboxAddressEl = document.getElementById("mail-inbox-address");
  const mailInboxCopyBtn = document.getElementById("mail-inbox-copy");
  const mailInboxNewBtn = document.getElementById("mail-inbox-new");
  const mailInboxFetchBtn = document.getElementById("mail-inbox-fetch");
  const mailInboxClearBtn = document.getElementById("mail-inbox-clear");
  const mailInboxExistingEl = document.getElementById("mail-inbox-existing");
  const mailInboxUseBtn = document.getElementById("mail-inbox-use");
  const mailInboxStatusEl = document.getElementById("mail-inbox-status");
  const mailInboxMessagesEl = document.getElementById("mail-inbox-messages");
  /** @type {{address?:string, configured?:boolean}|null} */
  let mailInboxState = null;
  let mailInboxBusy = false;
  const coverageChartsEl = document.getElementById("coverage-charts");
  let backfillTimer = null;
  let backfillSnapshot = null;
  let backfillDeviceBusyAddrs = new Set();
  let backfillBulkBusy = false;
  let backfillLoadInFlight = false;
  /** @type {{id:string,file:File,included:boolean,address:string,match:string,preview:any,error:string|null,status:string,result:any}[]} */
  let coverageBatch = [];
  let coverageBatchActiveId = "";
  let coverageBatchBusy = false;
  /** @type {import('chart.js').Chart | null} */
  let coverageTempChart = null;
  /** @type {import('chart.js').Chart | null} */
  let coverageHumChart = null;
  /** @type {string} */
  let coverageHours = "1";
  /** @type {string} */
  let coverageAddress = localStorage.getItem("govee-charts.coverageAddress") || "";
  /** @type {string} */
  let coverageAggBucket = localStorage.getItem("govee-charts.coverageAggBucket") || "day";
  if (!["day", "week", "month"].includes(coverageAggBucket)) {
    coverageAggBucket = "day";
  }
  let coverageLoaded = false;

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
  const FORECAST_FUTURE_KEY = "govee-charts.forecastFutureHours";
  const PROJECTION_SCENARIO_KEY = "govee-charts.projectionScenario";
  const WINDOW_BANDS_KEY = "govee-charts.windowBands";
  const HVAC_KEY = "govee-charts.hvac";
  const WINDOW_NOTIFY_KEY = "govee-charts.windowNotify";
  const WINDOW_NOTIFY_STATE_KEY = "govee-charts.windowNotifyState";
  /** "wait" = user wants alerts; "reloaded" = already did one soft reload for Safari. */
  const WINDOW_NOTIFY_PENDING_KEY = "govee-charts.windowNotifyPending";
  const TTS_KEY = "govee-charts.tts";
  const TTS_VOICE_KEY = "govee-charts.ttsVoice";
  const DOOR_BEEP_KEY = "govee-charts.doorBeep";
  const VISIBLE_STATIONS_KEY = "govee-charts.visibleStations";
  const FOLD_CURRENT_KEY = "govee-charts.foldCurrent";
  const FOLD_PROJ_KEY = "govee-charts.foldProjections";
  const FOLD_MAP_CHAT_KEY = "govee-charts.foldMapChat";
  const MAP_CHAT_SESSION_KEY = "govee-charts.mapChatSession";
  const GEO_KEY = "govee-charts.geo";
  const CAT_FILTER_KEY = "govee-charts.catFilters";
  const CHART_HEIGHT_KEY = "govee-charts.chartHeight";
  const RANGE_KEY = "govee-charts.range";
  const CHART_HEIGHT_DEFAULT = 260;
  const CHART_HEIGHT_MIN = 160;
  const CHART_HEIGHT_MAX = 520;
  const RANGE_MAX_HOURS = 26280;
  const QUICK_RANGE_HOURS = new Set([1, 6, 12, 24, 72, 168, 336]);
  const SELECT_RANGE_HOURS = new Set([720, 2160, 4320, 8760, 17520, 26280]);
  /** Same presets as past quick ranges (API future_hours max 384). */
  const FORECAST_FUTURE_HOURS = new Set([1, 6, 12, 24, 72, 168, 336]);
  const COVERAGE_RANGE_HOURS = new Set([
    "1", "6", "12", "24", "72", "168", "336", "720", "2160", "8760", "all",
  ]);

  /** @type {number} relative window in hours (ignored when customSince/Until set) */
  let hours = 24;
  /** Last non-custom quick/select range — restored by reset zoom / double-click. */
  let lastRelativeHours = 24;
  let suppressChartRangeSync = false;
  let chartRangeSyncTimer = null;
  /** @type {number|null} */
  let customSince = null;
  /** @type {number|null} */
  let customUntil = null;
  let devices = [];
  let taxonomyData = { zones: [], heights: [], rooms: [], contact_kinds: [] };
  /** @type {Array<{sensor_id:string,name:string,state:string,ts:number,room?:string,kind?:string}>} */
  let doorSensors = [];
  let doorBeepEnabled = localStorage.getItem(DOOR_BEEP_KEY) === "1";
  /** @type {Map<string, string>} sensor_id → last seen state, to detect transitions */
  const doorBeepSeenStates = new Map();
  let selected = new Set();
  /** @type {string[]} empty = all models */
  let activeModels = loadActiveModels();
  /** @type {{zone:string[], height:string[], room:string[]}} empty array = all */
  let catFilters = loadCatFilters();
  let sortState = loadSortState();
  const VALID_VIEWS = new Set([
    "overview",
    "compare",
    "facades",
    "network",
    "coverage",
    "backfill",
    "system",
    "settings",
  ]);
  const VIEW_PATHS = {
    overview: "/overview",
    compare: "/compare",
    facades: "/facades",
    network: "/map",
    coverage: "/coverage",
    backfill: "/backfill",
    system: "/system",
    settings: "/settings",
  };

  function normalizeView(raw) {
    const v = String(raw || "").trim().toLowerCase();
    return VALID_VIEWS.has(v) ? v : "overview";
  }

  function pathToView(pathname) {
    const p = String(pathname || "/").replace(/\/+$/, "") || "/";
    if (p === "/" || p === "/index.html") return null;
    if (p === "/overview") return "overview";
    if (p === "/compare") return "compare";
    if (p === "/facades") return "facades";
    if (p === "/map" || p === "/network") return "network";
    if (p === "/coverage") return "coverage";
    if (p === "/backfill") return "backfill";
    if (p === "/system") return "system";
    if (p === "/settings") return "settings";
    return null;
  }

  function viewToPath(view) {
    return VIEW_PATHS[normalizeView(view)] || "/overview";
  }

  function detectInitialView() {
    const fromPath = pathToView(window.location.pathname);
    if (fromPath) return fromPath;
    const saved = normalizeView(localStorage.getItem(VIEW_KEY));
    return saved || "overview";
  }

  let currentView = detectInitialView();
  let showForecast = localStorage.getItem(FORECAST_KEY) !== "0";
  /** Future horizon for forecast / projection charts (hours from now). */
  let forecastFutureHours = loadForecastFutureHours();
  let projectionScenario = loadProjectionScenario();
  let showWindowBands = localStorage.getItem(WINDOW_BANDS_KEY) !== "0";
  let showHvac = localStorage.getItem(HVAC_KEY) !== "0";
  let windowNotify = localStorage.getItem(WINDOW_NOTIFY_KEY) === "1";
  let ttsEnabled = localStorage.getItem(TTS_KEY) === "1";
  let ttsVoiceURI = localStorage.getItem(TTS_VOICE_KEY) || "";
  /** @type {{visible:Set<string>, known:Set<string>}|null} null = show all */
  let stationVisibilityPref = loadStationVisibilityPref();
  /** @type {object[]} */
  let availableStationsCache = [];
  let lastSpokenSystemBannerTitle = null;
  /** @type {{hidden?: boolean, tone?: string, title?: string, detail?: string} | null} */
  let windowBannerModel = null;
  /** @type {{hidden?: boolean, tone?: string, title?: string, detail?: string} | null} */
  let systemBannerModel = null;
  /** @type {{latitude:number, longitude:number, accuracy?:number, at?:number}|null} */
  let browserGeo = loadStoredGeo();
  let geoStatus = browserGeo ? "cached" : "idle";
  let tempChart = null;
  let humChart = null;
  let dewChart = null;
  let spreadChart = null;
  /** @type {import('chart.js').Chart[]} */
  let facadeChartInstances = [];
  let historyLoaded = false;
  let localNodeId = "";
  /** @type {Map<string, string>} node_id → url */
  let peerByNodeId = new Map();
  /** @type {Array<{url?: string, node_id?: string, online?: boolean}>} */
  let federationPeers = [];
  const showForecastEl = document.getElementById("show-forecast");
  const projectionScenarioEl = document.getElementById("projection-scenario");
  const showWindowBandsEl = document.getElementById("show-window-bands");
  const facadeShowForecastEl = document.getElementById("facade-show-forecast");
  const facadeProjectionScenarioEl = document.getElementById(
    "facade-projection-scenario"
  );
  const facadeShowWindowBandsEl = document.getElementById(
    "facade-show-window-bands"
  );
  const facadeRangeSelectEl = document.getElementById("facade-range-select");
  const facadeRangeCustomEl = document.getElementById("facade-range-custom");
  const facadeRangeSinceEl = document.getElementById("facade-range-since");
  const facadeRangeUntilEl = document.getElementById("facade-range-until");
  const facadeRangeApplyBtn = document.getElementById("facade-range-apply");
  const facadeLocateBtn = document.getElementById("facade-locate-btn");
  const facadeGeoStatusEl = document.getElementById("facade-geo-status");
  const showHvacEl = document.getElementById("show-hvac");
  const windowNotifyEl = document.getElementById("window-notify-btn");
  const ttsEl = document.getElementById("tts-btn");
  const ttsVoiceSelectEl = document.getElementById("tts-voice-select");
  const ttsVoiceTestBtn = document.getElementById("tts-voice-test-btn");
  const doorBeepEl = document.getElementById("door-beep-btn");
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

  function compareChartZoomOptions() {
    return {
      limits: {
        x: { minRange: 60 * 1000 },
      },
      pan: {
        enabled: true,
        mode: "x",
        modifierKey: "shift",
        onPanComplete: ({ chart }) => scheduleSyncRangeFromChart(chart),
      },
      zoom: {
        mode: "x",
        drag: {
          enabled: true,
          backgroundColor: "rgba(120, 180, 140, 0.18)",
          borderColor: "rgba(140, 200, 160, 0.85)",
          borderWidth: 1,
          threshold: 12,
        },
        wheel: {
          enabled: true,
          modifierKey: "ctrl",
        },
        pinch: { enabled: true },
        onZoomComplete: ({ chart }) => scheduleSyncRangeFromChart(chart),
      },
    };
  }

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

  function scheduleSyncRangeFromChart(chart) {
    if (suppressChartRangeSync || !chart) return;
    if (chartRangeSyncTimer) clearTimeout(chartRangeSyncTimer);
    chartRangeSyncTimer = setTimeout(() => {
      chartRangeSyncTimer = null;
      syncRangeFromChart(chart);
    }, 80);
  }

  function syncRangeFromChart(chart) {
    if (suppressChartRangeSync || !chart || !chart.scales || !chart.scales.x) {
      return;
    }
    const scale = chart.scales.x;
    const minMs = Number(scale.min);
    const maxMs = Number(scale.max);
    if (!Number.isFinite(minMs) || !Number.isFinite(maxMs) || maxMs <= minMs) {
      return;
    }
    const t0 = minMs / 1000;
    const t1 = maxMs / 1000;
    if (!setCustomRange(t0, t1)) return;

    suppressChartRangeSync = true;
    try {
      for (const other of [tempChart, humChart, dewChart]) {
        if (!other || other === chart || !other.options.scales?.x) continue;
        other.options.scales.x.min = minMs;
        other.options.scales.x.max = maxMs;
        other.update("none");
      }
    } finally {
      suppressChartRangeSync = false;
    }

    loadHistory().catch((err) => {
      statusEl.textContent = `Error: ${err.message}`;
    });
  }

  function resetCompareZoom() {
    if (chartRangeSyncTimer) {
      clearTimeout(chartRangeSyncTimer);
      chartRangeSyncTimer = null;
    }
    for (const chart of [tempChart, humChart, dewChart]) {
      if (chart && typeof chart.resetZoom === "function") {
        suppressChartRangeSync = true;
        try {
          chart.resetZoom();
        } finally {
          suppressChartRangeSync = false;
        }
      }
    }
    setRelativeRange(lastRelativeHours);
    loadHistory().catch((err) => {
      statusEl.textContent = `Error: ${err.message}`;
    });
  }

  function bindCompareChartZoom(chart) {
    if (!chart || !chart.canvas) return;
    chart.canvas.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      resetCompareZoom();
    });
  }

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
    const text = (() => {
      if (!showForecast) return "";
      if (geoStatus === "pending") return "Locating…";
      if (geoStatus === "denied") {
        return "Location denied — using config fallback";
      }
      if (geoStatus === "unavailable") {
        return "Geolocation unavailable (needs HTTPS or localhost)";
      }
      if (geoStatus === "error") {
        return "Location failed — using config fallback";
      }
      if (browserGeo) {
        return `GPS ${browserGeo.latitude.toFixed(3)}, ${browserGeo.longitude.toFixed(3)}`;
      }
      return "No GPS — config fallback";
    })();
    if (geoStatusEl) geoStatusEl.textContent = text;
    if (facadeGeoStatusEl) facadeGeoStatusEl.textContent = text;
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

  function normalizeFilterList(value) {
    if (Array.isArray(value)) {
      return [...new Set(value.map((v) => String(v || "").trim()).filter(Boolean))];
    }
    if (value == null || value === "" || value === "all") return [];
    return [String(value)];
  }

  function loadProjectionScenario() {
    const raw = localStorage.getItem(PROJECTION_SCENARIO_KEY) || "closed";
    if (
      ["auto", "closed", "open", "both", "coolest", "warmest"].includes(raw)
    ) {
      return raw;
    }
    return "closed";
  }

  function loadForecastFutureHours() {
    const n = Number(localStorage.getItem(FORECAST_FUTURE_KEY));
    if (FORECAST_FUTURE_HOURS.has(n)) return n;
    // Migrate former +16 d (384 h) preset to +14 d.
    if (n === 384) return 336;
    return 24;
  }

  function loadStationVisibilityPref() {
    try {
      const raw = localStorage.getItem(VISIBLE_STATIONS_KEY);
      if (raw == null || raw === "") return null;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const visible = new Set(
          parsed.map((x) => String(x || "").trim()).filter(Boolean)
        );
        return { visible, known: new Set(visible) };
      }
      if (parsed && typeof parsed === "object") {
        const visible = new Set(
          (Array.isArray(parsed.visible) ? parsed.visible : [])
            .map((x) => String(x || "").trim())
            .filter(Boolean)
        );
        const known = new Set(
          (Array.isArray(parsed.known) ? parsed.known : [...visible])
            .map((x) => String(x || "").trim())
            .filter(Boolean)
        );
        return { visible, known };
      }
    } catch (_) {
      /* ignore */
    }
    return null;
  }

  function saveStationVisibilityPref(visibleIds, knownIds) {
    const visible = [...new Set(visibleIds.map((x) => String(x).trim()).filter(Boolean))];
    const known = [...new Set(knownIds.map((x) => String(x).trim()).filter(Boolean))];
    stationVisibilityPref = {
      visible: new Set(visible),
      known: new Set(known),
    };
    try {
      localStorage.setItem(
        VISIBLE_STATIONS_KEY,
        JSON.stringify({ visible, known })
      );
    } catch (_) {
      /* ignore */
    }
  }

  function isStationVisible(stationId) {
    const id = String(stationId || "").trim();
    if (!id) return false;
    if (!stationVisibilityPref) return true;
    if (!stationVisibilityPref.known.has(id)) return true;
    return stationVisibilityPref.visible.has(id);
  }

  function stationsFromBlock(stationBlock) {
    const block = stationBlock || {};
    if (Array.isArray(block.stations) && block.stations.length) {
      return block.stations.filter((s) => s && s.station_id);
    }
    if (block.enabled && block.station_id) return [block];
    return [];
  }

  function filterStationList(stations) {
    return (stations || []).filter((s) => isStationVisible(s.station_id));
  }

  function rememberAvailableStations(stationBlock) {
    const list = stationsFromBlock(stationBlock);
    if (!list.length) return;
    const byId = new Map(
      availableStationsCache.map((s) => [String(s.station_id), s])
    );
    for (const s of list) {
      byId.set(String(s.station_id), s);
    }
    availableStationsCache = [...byId.values()];
    renderSettingsStations();
  }

  function stationCoordsHint(station) {
    const latest =
      (station && station.latest) ||
      ((station && station.points) || []).slice().sort((a, b) => a.ts - b.ts).pop();
    if (!latest) return "";
    const lat = latest.lat;
    const lon = latest.lon;
    if (lat == null || lon == null) return "";
    const latN = Number(lat);
    const lonN = Number(lon);
    if (!Number.isFinite(latN) || !Number.isFinite(lonN)) return "";
    return t("settings.stationsCoords", {
      lat: latN.toFixed(4),
      lon: lonN.toFixed(4),
    });
  }

  function renderSettingsStations() {
    if (!settingsStationsEl) return;
    const stations = availableStationsCache.slice().sort((a, b) =>
      String(a.station_name || a.station_id).localeCompare(
        String(b.station_name || b.station_id),
        I18n.getLocale()
      )
    );
    settingsStationsEl.innerHTML = "";
    if (settingsStationsEmptyEl) {
      settingsStationsEmptyEl.hidden = stations.length > 0;
    }
    for (const station of stations) {
      const id = String(station.station_id || "").trim();
      if (!id) continue;
      const name = station.station_name || id;
      const label = document.createElement("label");
      label.className = "settings-station-option";
      const main = document.createElement("span");
      main.className = "settings-station-option-main";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = id;
      input.checked = isStationVisible(id);
      input.addEventListener("change", onSettingsStationsChange);
      const text = document.createElement("span");
      text.textContent = `${name} (${id})`;
      main.append(input, text);
      label.appendChild(main);
      const coords = stationCoordsHint(station);
      if (coords) {
        const meta = document.createElement("span");
        meta.className = "settings-station-meta";
        meta.textContent = coords;
        label.appendChild(meta);
      }
      settingsStationsEl.appendChild(label);
    }
  }

  function onSettingsStationsChange() {
    if (!settingsStationsEl) return;
    const inputs = [
      ...settingsStationsEl.querySelectorAll('input[type="checkbox"]'),
    ];
    const known = inputs.map((el) => el.value);
    const visible = inputs.filter((el) => el.checked).map((el) => el.value);
    saveStationVisibilityPref(visible, known);
    if (currentView === "compare" && historyLoaded) {
      loadHistory().catch((err) => {
        if (statusEl) {
          statusEl.textContent = t("compare.error", { error: err.message });
        }
      });
    }
  }

  async function ensureStationsForSettings() {
    renderSettingsStations();
    if (availableStationsCache.length) return;
    try {
      const params = new URLSearchParams({
        hours: "24",
        future_hours: "24",
      });
      if (browserGeo) {
        params.set("latitude", String(browserGeo.latitude));
        params.set("longitude", String(browserGeo.longitude));
      }
      const res = await fetch(`/api/forecast?${params}`);
      if (!res.ok) throw new Error(`forecast HTTP ${res.status}`);
      const data = await res.json();
      rememberAvailableStations(data.station || {});
    } catch (err) {
      console.warn("Could not load stations for settings", err);
      renderSettingsStations();
    }
  }

  function syncForecastFutureButtons() {
    const btns = document.querySelectorAll(
      ".forecast-future-ranges > button[data-forecast-future]"
    );
    btns.forEach((btn) => {
      const h = Number(btn.dataset.forecastFuture);
      btn.classList.toggle("active", h === forecastFutureHours);
    });
  }

  function setForecastFutureHours(h) {
    const next = Number(h);
    if (!FORECAST_FUTURE_HOURS.has(next)) return;
    if (next === forecastFutureHours) return;
    forecastFutureHours = next;
    try {
      localStorage.setItem(FORECAST_FUTURE_KEY, String(forecastFutureHours));
    } catch (_) {
      /* ignore */
    }
    syncForecastFutureButtons();
    if (currentView === "compare") {
      loadHistory().catch((err) => {
        if (statusEl) statusEl.textContent = `Error: ${err.message}`;
      });
    } else if (currentView === "facades") {
      loadFacades().catch((err) => {
        if (facadeStatusEl) {
          facadeStatusEl.textContent = `Error: ${err.message}`;
        }
      });
    }
  }

  function syncProjectionScenarioControl() {
    for (const el of [projectionScenarioEl, facadeProjectionScenarioEl]) {
      if (!el) continue;
      el.value = projectionScenario;
      el.disabled = !showForecast;
    }
  }

  function syncForecastToggleControls() {
    if (showForecastEl) showForecastEl.checked = showForecast;
    if (facadeShowForecastEl) facadeShowForecastEl.checked = showForecast;
    if (showWindowBandsEl) showWindowBandsEl.checked = showWindowBands;
    if (facadeShowWindowBandsEl) {
      facadeShowWindowBandsEl.checked = showWindowBands;
    }
    syncProjectionScenarioControl();
    syncForecastFutureButtons();
  }

  function reloadRangeDependentViews() {
    if (currentView === "compare") {
      loadHistory().catch((err) => {
        statusEl.textContent = `Error: ${err.message}`;
      });
    } else if (currentView === "facades") {
      loadFacades().catch((err) => {
        if (facadeStatusEl) {
          facadeStatusEl.textContent = `Error: ${err.message}`;
        }
      });
    }
  }

  function loadActiveModels() {
    try {
      const raw = localStorage.getItem(MODEL_KEY);
      if (!raw || raw === "all") return [];
      if (raw.startsWith("[")) {
        return normalizeFilterList(JSON.parse(raw));
      }
      return normalizeFilterList(raw);
    } catch {
      return [];
    }
  }

  function loadCatFilters() {
    try {
      const raw = localStorage.getItem(CAT_FILTER_KEY);
      if (!raw) return { zone: [], height: [], room: [] };
      const parsed = JSON.parse(raw);
      return {
        zone: normalizeFilterList(parsed.zone),
        height: normalizeFilterList(parsed.height),
        room: normalizeFilterList(parsed.room),
      };
    } catch {
      return { zone: [], height: [], room: [] };
    }
  }

  function persistCatFilters() {
    localStorage.setItem(CAT_FILTER_KEY, JSON.stringify(catFilters));
  }

  function filterListAllows(selected, value) {
    if (!selected || selected.length === 0) return true;
    return selected.includes(String(value || ""));
  }

  function toggleFilterValue(selected, id) {
    if (id === "all") return [];
    const next = selected.slice();
    const idx = next.indexOf(id);
    if (idx >= 0) next.splice(idx, 1);
    else next.push(id);
    return next;
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
    if (typeof resizeCoverageCharts === "function") resizeCoverageCharts();
  }

  function applyChartHeight(px, { persist = true } = {}) {
    const height = Math.min(
      CHART_HEIGHT_MAX,
      Math.max(CHART_HEIGHT_MIN, Math.round(Number(px) || CHART_HEIGHT_DEFAULT))
    );
    document.documentElement.style.setProperty("--chart-height", `${height}px`);
    if (chartHeightEl) chartHeightEl.value = String(height);
    if (chartHeightValueEl) {
      chartHeightValueEl.textContent = t("compare.chartHeightPx", { n: height });
    }
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
    localStorage.setItem(MODEL_KEY, JSON.stringify(activeModels));
  }

  function isCustomRange() {
    return customSince != null && customUntil != null;
  }

  /** Hours spanning the active chart window (for overlays / forecast clamp). */
  function rangeSpanHours() {
    if (isCustomRange()) {
      return Math.max(1 / 60, (customUntil - customSince) / 3600);
    }
    return Number(hours) || 24;
  }

  /**
   * Hours-from-now query param for APIs that only accept relative `hours`
   * (covers absolute windows that start in the past).
   */
  function rangeOverlayHours() {
    let h;
    if (isCustomRange()) {
      h = (Date.now() / 1000 - customSince) / 3600;
    } else {
      h = Number(hours) || 24;
    }
    return Math.min(RANGE_MAX_HOURS, Math.max(1 / 60, h));
  }

  function rangeAxisBounds() {
    if (isCustomRange()) {
      return {
        xMin: customSince * 1000,
        xMax: customUntil * 1000,
      };
    }
    const now = Date.now();
    const xMin = now - Number(hours) * 3600 * 1000;
    let xMax = now;
    if (showForecast || showWindowBands) {
      xMax = now + Number(forecastFutureHours) * 3600 * 1000;
    }
    return { xMin, xMax };
  }

  function formatRangeLabel() {
    if (isCustomRange()) {
      const fmt = (sec) =>
        new Date(sec * 1000).toLocaleString("en-GB", {
          day: "numeric",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
      return `${fmt(customSince)} → ${fmt(customUntil)}`;
    }
    const h = Number(hours);
    if (h < 24) return `${h} h`;
    if (h % 8760 === 0) {
      const y = h / 8760;
      return y === 1 ? "1 y" : `${y} y`;
    }
    if (h % 24 === 0) {
      const d = h / 24;
      return d === 1 ? "1 d" : `${d} d`;
    }
    return `${h} h`;
  }

  function toDatetimeLocalValue(sec) {
    const d = new Date(sec * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}`
    );
  }

  function fromDatetimeLocalValue(value) {
    if (!value) return null;
    const ms = Date.parse(value);
    if (!Number.isFinite(ms)) return null;
    return ms / 1000;
  }

  function persistRange() {
    if (isCustomRange()) {
      localStorage.setItem(
        RANGE_KEY,
        JSON.stringify({ since: customSince, until: customUntil })
      );
      return;
    }
    localStorage.setItem(RANGE_KEY, JSON.stringify({ hours: Number(hours) }));
  }

  function loadPersistedRange() {
    try {
      const raw = localStorage.getItem(RANGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (
        parsed &&
        typeof parsed.since === "number" &&
        typeof parsed.until === "number" &&
        Number.isFinite(parsed.since) &&
        Number.isFinite(parsed.until)
      ) {
        customSince = Math.min(parsed.since, parsed.until);
        customUntil = Math.max(parsed.since, parsed.until);
        hours = Math.max(1 / 60, (customUntil - customSince) / 3600);
        return;
      }
      if (parsed && typeof parsed.hours === "number" && parsed.hours > 0) {
        hours = Math.min(RANGE_MAX_HOURS, parsed.hours);
        lastRelativeHours = hours;
        customSince = null;
        customUntil = null;
      }
    } catch {
      /* ignore */
    }
  }

  function syncRangeControls() {
    const custom = isCustomRange();
    const h = Number(hours);
    const quickMatch = !custom && QUICK_RANGE_HOURS.has(h);
    const selectMatch = !custom && SELECT_RANGE_HOURS.has(h);

    rangeButtons.forEach((b) => {
      b.classList.toggle(
        "active",
        quickMatch && Number(b.dataset.hours) === h
      );
    });

    for (const sel of [rangeSelectEl, facadeRangeSelectEl]) {
      if (!sel) continue;
      sel.classList.remove("active");
      if (custom) {
        sel.value = "custom";
        sel.classList.add("active");
      } else if (quickMatch) {
        sel.value = "";
      } else if (selectMatch) {
        sel.value = String(h);
        sel.classList.add("active");
      } else {
        sel.value = "custom";
        sel.classList.add("active");
      }
    }

    for (const box of [rangeCustomEl, facadeRangeCustomEl]) {
      if (box) box.hidden = !custom;
    }
    if (custom) {
      if (rangeSinceEl) rangeSinceEl.value = toDatetimeLocalValue(customSince);
      if (rangeUntilEl) rangeUntilEl.value = toDatetimeLocalValue(customUntil);
      if (facadeRangeSinceEl) {
        facadeRangeSinceEl.value = toDatetimeLocalValue(customSince);
      }
      if (facadeRangeUntilEl) {
        facadeRangeUntilEl.value = toDatetimeLocalValue(customUntil);
      }
    }
  }

  function setRelativeRange(h, { fromSelect = false } = {}) {
    hours = Math.min(RANGE_MAX_HOURS, Math.max(1 / 60, Number(h) || 24));
    lastRelativeHours = hours;
    customSince = null;
    customUntil = null;
    void fromSelect;
    syncRangeControls();
    persistRange();
  }

  function setCustomRange(sinceSec, untilSec) {
    let t0 = Number(sinceSec);
    let t1 = Number(untilSec);
    if (!Number.isFinite(t0) || !Number.isFinite(t1)) return false;
    if (t1 < t0) [t0, t1] = [t1, t0];
    const spanH = (t1 - t0) / 3600;
    if (spanH <= 0 || spanH > RANGE_MAX_HOURS) return false;
    customSince = t0;
    customUntil = t1;
    hours = spanH;
    syncRangeControls();
    persistRange();
    return true;
  }

  const CUSTOM_RANGE_MIN_SPAN_SEC = 60;

  /**
   * Keep From ≤ To by moving the bound that was not edited.
   * @param {"since"|"until"} edited
   * @returns {{ since: number, until: number } | null}
   */
  function coerceCustomBoundInputs(sinceEl, untilEl, edited) {
    if (!sinceEl || !untilEl) return null;
    let since = fromDatetimeLocalValue(sinceEl.value);
    let until = fromDatetimeLocalValue(untilEl.value);
    if (since == null || until == null) return null;
    if (since > until) {
      if (edited === "since") {
        until = since + CUSTOM_RANGE_MIN_SPAN_SEC;
        untilEl.value = toDatetimeLocalValue(until);
      } else {
        since = until - CUSTOM_RANGE_MIN_SPAN_SEC;
        sinceEl.value = toDatetimeLocalValue(since);
      }
    } else if (until - since < CUSTOM_RANGE_MIN_SPAN_SEC) {
      if (edited === "since") {
        until = since + CUSTOM_RANGE_MIN_SPAN_SEC;
        untilEl.value = toDatetimeLocalValue(until);
      } else {
        since = until - CUSTOM_RANGE_MIN_SPAN_SEC;
        sinceEl.value = toDatetimeLocalValue(since);
      }
    }
    // Mirror the other view's custom inputs so Compare / Facades stay aligned.
    const pairs = [
      [rangeSinceEl, rangeUntilEl],
      [facadeRangeSinceEl, facadeRangeUntilEl],
    ];
    for (const [sEl, uEl] of pairs) {
      if (!sEl || !uEl || (sEl === sinceEl && uEl === untilEl)) continue;
      sEl.value = toDatetimeLocalValue(since);
      uEl.value = toDatetimeLocalValue(until);
    }
    return { since, until };
  }

  function peerHostLabel(url) {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  async function probePeer(url) {
    // Kept as fallback; prefer server-side probes from /api/federation.
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

  function peerLinkUrl(peer) {
    if (peer.browse_url) return peer.browse_url;
    if (location.protocol === "https:" && peer.url) {
      try {
        const u = new URL(peer.url);
        u.protocol = "https:";
        // Only remap default HTTP UI port; keep explicit HTTPS ports (e.g. 8082).
        if (!u.port || u.port === "8080") u.port = "8081";
        return u.toString().replace(/\/$/, "");
      } catch {
        /* ignore */
      }
    }
    return peer.url;
  }

  function renderPeers(peers) {
    federationPeers = Array.isArray(peers) ? peers : [];
    peerByNodeId = new Map();
    for (const peer of federationPeers) {
      if (peer.node_id) {
        peerByNodeId.set(peer.node_id, peerLinkUrl(peer));
      }
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
      const href = peerLinkUrl(peer);
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = peer.node_id;
      a.title = href + (peer.online ? "" : " (offline)");
      if (!peer.online) a.classList.add("offline");
      peerLinksEl.appendChild(a);
    }
  }

  async function loadFederation() {
    const res = await fetch("/api/federation");
    if (!res.ok) throw new Error(`federation HTTP ${res.status}`);
    const data = await res.json();
    localNodeId = data.node_id || "";
    const peers = Array.isArray(data.peers) ? data.peers : [];
    // Server already probed health (same-origin → no mixed-content errors).
    // Fall back to client probe only if peers are plain URL strings.
    const normalized = await Promise.all(
      peers.map(async (p) => {
        if (p && typeof p === "object" && p.url) {
          return {
            url: p.url,
            browse_url: p.browse_url || null,
            node_id: p.node_id || peerHostLabel(p.url),
            online: Boolean(p.online),
          };
        }
        const url = String(p || "");
        return probePeer(url);
      })
    );
    renderPeers(normalized);
  }

  function sourceHtml(source) {
    if (!source || source === "—") return "—";
    const raw = String(source);
    const isGatt = raw.endsWith("/gatt");
    const isCsv = raw.endsWith("/csv");
    const nodeId = isGatt
      ? raw.slice(0, -"/gatt".length)
      : isCsv
        ? raw.slice(0, -"/csv".length)
        : raw;
    const url = peerByNodeId.get(nodeId);
    const suffix = isGatt ? "/gatt" : isCsv ? "/csv" : "";
    const label = suffix ? `${nodeId}${suffix}` : nodeId;
    if (!url) return escapeHtml(label);
    const linkText = suffix ? nodeId : label;
    return (
      `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">` +
      `${escapeHtml(linkText)}</a>${escapeHtml(suffix)}`
    );
  }

  function availableModels() {
    return [...new Set(devices.map((d) => (d.model || "").toLowerCase()).filter(Boolean))].sort();
  }

  function filteredDevices() {
    return devices.filter((d) => {
      if (!filterListAllows(activeModels, (d.model || "").toLowerCase())) {
        return false;
      }
      if (!filterListAllows(catFilters.zone, d.zone || "")) {
        return false;
      }
      if (!filterListAllows(catFilters.height, d.height || "")) {
        return false;
      }
      if (!filterListAllows(catFilters.room, d.room || "")) {
        return false;
      }
      return true;
    });
  }

  function overviewVisibleDevices() {
    return filteredDevices().filter((d) =>
      deviceMatchesSystemFilter(d, overviewTextFilter)
    );
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
    return new Date(ts * 1000).toLocaleString(I18n.localeTag(), {
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

  function formatBackfillTs(ts) {
    if (ts == null || !Number.isFinite(Number(ts))) return "—";
    return new Date(Number(ts) * 1000).toLocaleString("en-GB", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function deviceNameForAddress(address) {
    const addr = String(address || "").toUpperCase();
    const d = devices.find((x) => String(x.address || "").toUpperCase() === addr);
    if (d) return deviceLabel(d);
    return addr || "—";
  }

  function renderBackfillJobs(jobs) {
    if (!backfillJobsBody) return;
    const rows = jobs || [];
    if (!rows.length) {
      backfillJobsBody.innerHTML =
        '<tr><td colspan="6" class="overview-empty">No jobs yet</td></tr>';
      return;
    }
    backfillJobsBody.innerHTML = rows
      .map((job) => {
        const st = String(job.status || "").replace(/[^a-z0-9_-]/gi, "");
        const samples =
          `${Number(job.samples_done) || 0}` +
          (job.samples_expected != null ? ` / ${Number(job.samples_expected) || 0}` : "");
        const detail = job.error
          ? escapeHtml(String(job.error))
          : `${formatBackfillTs(job.window_start)} → ${formatBackfillTs(job.window_end)}`;
        return `<tr>
          <td>${escapeHtml(formatBackfillTs(job.updated_at))}</td>
          <td>${escapeHtml(deviceNameForAddress(job.address))}</td>
          <td>${escapeHtml(phaseLabel(job.phase))}</td>
          <td><span class="backfill-job-status backfill-job-status-${st}">${escapeHtml(job.status || "—")}</span></td>
          <td class="num">${escapeHtml(samples)}</td>
          <td class="backfill-job-detail">${detail}</td>
        </tr>`;
      })
      .join("");
  }

  function renderBackfillRecent(recent) {
    if (!backfillRecentBody) return;
    const rows = recent || [];
    if (!rows.length) {
      backfillRecentBody.innerHTML =
        '<tr><td colspan="7" class="overview-empty">No GATT readings recovered yet</td></tr>';
      return;
    }
    backfillRecentBody.innerHTML = rows
      .map((row) => {
        const name = row.name || deviceNameForAddress(row.address);
        const temp =
          row.temperature_c != null && Number.isFinite(Number(row.temperature_c))
            ? `${Number(row.temperature_c).toFixed(1)} °C`
            : "—";
        const hum =
          row.humidity != null && Number.isFinite(Number(row.humidity))
            ? `${Number(row.humidity).toFixed(1)} %`
            : "—";
        const batt =
          row.battery != null && Number.isFinite(Number(row.battery))
            ? `${Number(row.battery)} %`
            : "—";
        return `<tr>
          <td>${escapeHtml(formatBackfillTs(row.ts))}</td>
          <td title="${escapeHtml(row.address || "")}">${escapeHtml(name)}</td>
          <td class="num temp">${escapeHtml(temp)}</td>
          <td class="num">${escapeHtml(hum)}</td>
          <td class="num">${escapeHtml(batt)}</td>
          <td class="num">${rssiHtml(row.rssi)}</td>
          <td class="overview-source">${sourceHtml(row.source || "—")}</td>
        </tr>`;
      })
      .join("");
  }

  function coverageReadingTemp(row) {
    return row.temperature_c != null && Number.isFinite(Number(row.temperature_c))
      ? `${Number(row.temperature_c).toFixed(1)} °C`
      : "—";
  }

  function coverageReadingHum(row) {
    return row.humidity != null && Number.isFinite(Number(row.humidity))
      ? `${Number(row.humidity).toFixed(1)} %`
      : "—";
  }

  function coverageReadingBatt(row) {
    return row.battery != null && Number.isFinite(Number(row.battery))
      ? `${Number(row.battery)} %`
      : "—";
  }

  function coverageRecentRowsHtml(rows, emptyMsg) {
    const list = Array.isArray(rows) ? rows : [];
    if (!list.length) {
      return `<tr><td colspan="6" class="overview-empty">${escapeHtml(
        emptyMsg || "No readings yet"
      )}</td></tr>`;
    }
    return list
      .map((row) => {
        return `<tr>
          <td>${escapeHtml(formatBackfillTs(row.ts))}</td>
          <td class="num temp">${escapeHtml(coverageReadingTemp(row))}</td>
          <td class="num">${escapeHtml(coverageReadingHum(row))}</td>
          <td class="num">${escapeHtml(coverageReadingBatt(row))}</td>
          <td class="num">${rssiHtml(row.rssi)}</td>
          <td class="overview-source">${sourceHtml(row.source || "—")}</td>
        </tr>`;
      })
      .join("");
  }

  function renderCoverageRecent(recent) {
    if (coverageRecentEl) coverageRecentEl.hidden = !coverageAddress;
    if (!coverageRecentBody) return;
    coverageRecentBody.innerHTML = coverageRecentRowsHtml(recent, "No readings yet");
  }

  function renderCoverageRecentJobs(jobs) {
    if (!coverageRecentJobsBody) return;
    const rows = jobs || [];
    if (!rows.length) {
      coverageRecentJobsBody.innerHTML =
        '<tr><td colspan="5" class="overview-empty">No backfill jobs yet</td></tr>';
      return;
    }
    coverageRecentJobsBody.innerHTML = rows
      .map((job) => {
        const st = String(job.status || "").replace(/[^a-z0-9_-]/gi, "");
        const samples =
          `${Number(job.samples_done) || 0}` +
          (job.samples_expected != null
            ? ` / ${Number(job.samples_expected) || 0}`
            : "");
        const detail = job.error
          ? escapeHtml(String(job.error))
          : `${formatBackfillTs(job.window_start)} → ${formatBackfillTs(job.window_end)}`;
        return `<tr>
          <td>${escapeHtml(formatBackfillTs(job.updated_at))}</td>
          <td>${escapeHtml(phaseLabel(job.phase))}</td>
          <td><span class="backfill-job-status backfill-job-status-${st}">${escapeHtml(job.status || "—")}</span></td>
          <td class="num">${escapeHtml(samples)}</td>
          <td class="backfill-job-detail">${detail}</td>
        </tr>`;
      })
      .join("");
  }

  function patchBackfillDeviceLocal(address, patch) {
    if (!backfillSnapshot || !Array.isArray(backfillSnapshot.devices)) return;
    const key = String(address || "").toUpperCase();
    backfillSnapshot.devices = backfillSnapshot.devices.map((d) => {
      if (String(d.address || "").toUpperCase() !== key) return d;
      return Object.assign({}, d, patch);
    });
  }

  function renderBackfillSensors(devices) {
    if (!backfillSensorListEl) return;
    const rows = Array.isArray(devices) ? devices : [];
    const anyOn = rows.some((d) => d.enabled);
    if (backfillSensorsHintEl) {
      if (!rows.length) {
        backfillSensorsHintEl.hidden = false;
        backfillSensorsHintEl.textContent = "No eligible Govee sensors found.";
      } else if (!anyOn) {
        backfillSensorsHintEl.hidden = false;
        backfillSensorsHintEl.textContent =
          "No sensors selected — enable at least one to enqueue recovery. Uncheck GATT for peers only.";
      } else {
        backfillSensorsHintEl.hidden = false;
        backfillSensorsHintEl.textContent =
          "Uncheck GATT to fill gaps from federation peers only (no local BLE download).";
      }
    }
    if (backfillSelectAllBtn) {
      backfillSelectAllBtn.disabled =
        !rows.length || backfillBulkBusy || backfillDeviceBusyAddrs.size > 0;
    }
    if (backfillClearAllBtn) {
      backfillClearAllBtn.disabled =
        !rows.length || backfillBulkBusy || backfillDeviceBusyAddrs.size > 0;
    }
    if (!rows.length) {
      backfillSensorListEl.innerHTML =
        `<li class="overview-empty">No eligible sensors</li>`;
      return;
    }
    backfillSensorListEl.innerHTML = rows
      .map((d) => {
        const safe = String(d.address || "").replace(/:/g, "");
        const id = `bf-dev-${escapeHtml(safe)}`;
        const gattId = `bf-gatt-${escapeHtml(safe)}`;
        const rowBusy = backfillDeviceBusyAddrs.has(
          String(d.address || "").toUpperCase()
        );
        const meta = [
          d.local_best ? "★" : null,
          d.rssi != null ? `${Number(d.rssi)} dBm` : null,
          d.queued_jobs ? `${Number(d.queued_jobs)} job(s)` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        // Do not use label[for] wrapping the same input — it double-toggles in browsers.
        return (
          `<li class="backfill-sensor-row">` +
          `<span class="backfill-sensor-flags">` +
          `<label class="backfill-sensor-opt" title="Opt in to backfill">` +
          `<input type="checkbox" id="${id}" data-address="${escapeHtml(d.address)}" ` +
          `data-flag="enabled" ` +
          (d.enabled ? "checked " : "") +
          (rowBusy ? "disabled " : "") +
          `/></label>` +
          `<label class="backfill-sensor-gatt" title="Allow GATT after peer fill">` +
          `<input type="checkbox" id="${gattId}" data-address="${escapeHtml(d.address)}" ` +
          `data-flag="gatt_enabled" ` +
          (d.gatt_enabled !== false ? "checked " : "") +
          (rowBusy ? "disabled " : "") +
          `/><span>GATT</span></label>` +
          `</span>` +
          `<span class="backfill-sensor-name">${escapeHtml(d.name || d.address)}</span>` +
          (meta
            ? ` <span class="backfill-sensor-meta">${escapeHtml(meta)}</span>`
            : "") +
          `</li>`
        );
      })
      .join("");
  }

  async function setBackfillDeviceFlags(address, patch) {
    const key = String(address || "").toUpperCase();
    if (backfillDeviceBusyAddrs.has(key)) return;
    patchBackfillDeviceLocal(address, patch);
    backfillDeviceBusyAddrs.add(key);
    if (backfillSnapshot) {
      renderBackfillSensors(backfillSnapshot.devices);
    }
    try {
      const res = await fetch("/api/backfill/devices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, ...patch }),
      });
      if (!res.ok) {
        let detail = res.statusText;
        try {
          const body = await res.json();
          if (body && body.detail) detail = body.detail;
        } catch (_) {
          /* ignore */
        }
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      // Keep in-flight optimistic flags for other busy rows (incl. bulk).
      if (
        backfillDeviceBusyAddrs.size > 0 &&
        backfillSnapshot &&
        Array.isArray(backfillSnapshot.devices) &&
        Array.isArray(data.devices)
      ) {
        const local = new Map(
          backfillSnapshot.devices.map((d) => [
            String(d.address || "").toUpperCase(),
            d,
          ])
        );
        data.devices = data.devices.map((d) => {
          const addr = String(d.address || "").toUpperCase();
          if (addr === key || !backfillDeviceBusyAddrs.has(addr)) return d;
          const prev = local.get(addr);
          if (!prev) return d;
          return Object.assign({}, d, {
            enabled: prev.enabled,
            gatt_enabled: prev.gatt_enabled,
          });
        });
      }
      renderBackfill(data);
      syncBackfillPolling();
    } catch (err) {
      const revert = {};
      if (Object.prototype.hasOwnProperty.call(patch, "enabled")) {
        revert.enabled = !patch.enabled;
      }
      if (Object.prototype.hasOwnProperty.call(patch, "gatt_enabled")) {
        revert.gatt_enabled = !patch.gatt_enabled;
      }
      patchBackfillDeviceLocal(address, revert);
      throw err;
    } finally {
      backfillDeviceBusyAddrs.delete(key);
      if (backfillSnapshot) {
        renderBackfillSensors(backfillSnapshot.devices);
      }
    }
  }

  async function setBackfillDevice(address, enabled) {
    return setBackfillDeviceFlags(address, { enabled: Boolean(enabled) });
  }

  async function setBackfillDevicesBulk(enabled) {
    if (backfillBulkBusy || backfillDeviceBusyAddrs.size) return;
    const devices = (backfillSnapshot && backfillSnapshot.devices) || [];
    const targets = devices.filter((d) => Boolean(d.enabled) !== Boolean(enabled));
    if (!targets.length) return;

    const flag = Boolean(enabled);
    backfillBulkBusy = true;
    for (const d of targets) {
      const key = String(d.address || "").toUpperCase();
      patchBackfillDeviceLocal(d.address, { enabled: flag });
      backfillDeviceBusyAddrs.add(key);
    }
    if (backfillSnapshot) {
      renderBackfillSensors(backfillSnapshot.devices);
    }
    if (backfillSelectAllBtn) backfillSelectAllBtn.disabled = true;
    if (backfillClearAllBtn) backfillClearAllBtn.disabled = true;

    try {
      let last = null;
      for (const d of targets) {
        const key = String(d.address || "").toUpperCase();
        const res = await fetch("/api/backfill/devices", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: d.address, enabled: flag }),
        });
        if (!res.ok) {
          let detail = res.statusText;
          try {
            const body = await res.json();
            if (body && body.detail) detail = body.detail;
          } catch (_) {
            /* ignore */
          }
          throw new Error(detail || `HTTP ${res.status}`);
        }
        last = await res.json();
        backfillDeviceBusyAddrs.delete(key);
        if (last && Array.isArray(last.devices) && backfillSnapshot) {
          const local = new Map(
            backfillSnapshot.devices.map((row) => [
              String(row.address || "").toUpperCase(),
              row,
            ])
          );
          last.devices = last.devices.map((row) => {
            const addr = String(row.address || "").toUpperCase();
            if (!backfillDeviceBusyAddrs.has(addr)) return row;
            const prev = local.get(addr);
            if (!prev) return row;
            return Object.assign({}, row, {
              enabled: prev.enabled,
              gatt_enabled: prev.gatt_enabled,
            });
          });
          backfillSnapshot = last;
          renderBackfillSensors(last.devices);
        }
      }
      if (last) {
        renderBackfill(last);
        syncBackfillPolling();
      }
    } catch (err) {
      backfillDeviceBusyAddrs.clear();
      try {
        await loadBackfill();
      } catch (_) {
        /* ignore */
      }
      throw err;
    } finally {
      backfillBulkBusy = false;
      backfillDeviceBusyAddrs.clear();
      if (backfillSnapshot) {
        renderBackfillSensors(backfillSnapshot.devices);
      }
    }
  }

  function renderBackfill(data) {
    backfillSnapshot = data;
    if (!backfillPanelEl || !backfillCurrentEl) return;

    const workerOffline =
      !data || data.worker === "disabled" || data.enabled === false;
    if (backfillPauseBtn) {
      backfillPauseBtn.disabled = workerOffline;
      backfillPauseBtn.textContent =
        data && data.paused ? "Resume" : "Pause";
    }
    if (backfillRefreshBtn) {
      backfillRefreshBtn.disabled = workerOffline;
    }

    renderBackfillSensors(data && data.devices);

    const current = data && data.current;
    const queue = (data && data.queue) || [];
    const totals = (data && data.totals) || {};
    const anyOn = ((data && data.devices) || []).some((d) => d.enabled);

    if (workerOffline) {
      backfillCurrentEl.innerHTML =
        `<p class="backfill-idle">Worker offline — waiting for scanner or federation peers</p>`;
    } else if (!current) {
      backfillCurrentEl.innerHTML =
        `<p class="backfill-idle">` +
        (data.paused
          ? "Paused"
          : !anyOn
            ? "Idle — no sensors selected"
            : data.worker === "idle" && !(totals.pending > 0)
              ? "Queue empty — waiting for gaps"
              : `Worker ${escapeHtml(data.worker || "idle")} · ${Number(totals.pending) || 0} job(s) pending`) +
        `</p>`;
    } else {
      const done = Number(current.samples_done) || 0;
      const expected = Math.max(Number(current.samples_expected) || 0, done);
      const pct = expected > 0 ? Math.min(100, Math.round((100 * done) / expected)) : 0;
      const lastTs = current.last_sample_ts
        ? formatBackfillTs(current.last_sample_ts)
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
          .slice(0, 20)
          .map(
            (q) =>
              `<li><span class="q-name">${escapeHtml(q.name || q.address)}` +
              (q.local_best
                ? ' <span class="backfill-local-best" title="Best local signal">★</span>'
                : "") +
              (q.rssi != null ? ` <span class="overview-meta">${Number(q.rssi)} dBm</span>` : "") +
              `</span>` +
              `<span>${escapeHtml(phaseLabel(q.phase))} · ~${Number(q.samples_expected) || 0} missing · ${Number(q.jobs) || 0} job(s)</span></li>`
          )
          .join("");
      }
    }

    if (backfillStatusEl) {
      backfillStatusEl.textContent =
        `pending ${totals.pending || 0} · done ${totals.done || 0}` +
        (totals.failed ? ` · failed ${totals.failed}` : "") +
        (data && data.config && data.config.min_rssi != null
          ? ` · min RSSI ${data.config.min_rssi} dBm`
          : "");
    }

    renderBackfillJobs(data && data.recent_jobs);
    renderBackfillRecent(data && data.recent);
  }

  function populateCoverageDevices() {
    const rows = Array.isArray(devices) ? devices.slice() : [];
    rows.sort((a, b) =>
      String(a.name || a.address).localeCompare(String(b.name || b.address), "en")
    );
    const opts = ['<option value="">Select a sensor…</option>'].concat(
      rows.map(
        (d) =>
          `<option value="${escapeHtml(d.address)}">${escapeHtml(
            d.name || d.address
          )}</option>`
      )
    );
    const html = opts.join("");
    if (coverageDeviceEl) {
      const prev = coverageAddress || coverageDeviceEl.value;
      coverageDeviceEl.innerHTML = html;
      if (prev && rows.some((d) => d.address === prev)) {
        coverageDeviceEl.value = prev;
        coverageAddress = prev;
      }
    }
    if (coverageImportDeviceEl) {
      const prev = coverageImportDeviceEl.value || coverageAddress;
      coverageImportDeviceEl.innerHTML = html;
      if (prev && rows.some((d) => d.address === prev)) {
        coverageImportDeviceEl.value = prev;
      }
    }
  }

  function formatImportTs(ts) {
    if (ts == null || !Number.isFinite(Number(ts))) return "—";
    return new Date(Number(ts) * 1000).toLocaleString("en-GB", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function formatImportRange(range) {
    if (!range || range.start == null || range.end == null) return "—";
    return `${formatImportTs(range.start)} → ${formatImportTs(range.end)}`;
  }

  function formatImportMinMax(obj, digits, unit) {
    if (!obj || obj.min == null || obj.max == null) return "—";
    const a = Number(obj.min).toFixed(digits);
    const b = Number(obj.max).toFixed(digits);
    return `${a} – ${b}${unit || ""}`;
  }

  function dlRows(pairs) {
    return pairs
      .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`)
      .join("");
  }

  function clearCoverageImportRecap() {
    if (coverageImportRecapEl) coverageImportRecapEl.hidden = true;
    if (coverageImportBarsEl) coverageImportBarsEl.hidden = true;
    if (coverageFileBarEl) coverageFileBarEl.innerHTML = "";
    if (coverageDbBarEl) coverageDbBarEl.innerHTML = "";
    if (coverageImportOverwriteWrapEl) coverageImportOverwriteWrapEl.hidden = true;
    if (coverageImportOverwriteBodyEl) coverageImportOverwriteBodyEl.innerHTML = "";
    if (coverageImportZigzagWrapEl) coverageImportZigzagWrapEl.hidden = true;
    if (coverageImportZigzagBodyEl) coverageImportZigzagBodyEl.innerHTML = "";
    if (coverageImportZigzagHintEl) coverageImportZigzagHintEl.textContent = "";
  }

  function newBatchItemId() {
    return `b-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function isImportableFilename(name) {
    const lower = String(name || "").toLowerCase();
    return lower.endsWith(".csv") || lower.endsWith(".zip");
  }

  function matchScoreForFilename(filename, sensorName) {
    const nameFold = foldImportLabel(sensorName);
    const fileFold = foldImportLabel(filename);
    if (!nameFold || nameFold.length < 2 || !fileFold) return 0;
    if (fileFold.includes(nameFold)) return nameFold.length * 100;
    const tokens = String(sensorName || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .map((t) => t.trim())
      .filter((t) => t.length >= 3);
    if (!tokens.length) return 0;
    const hit = tokens.filter((t) => fileFold.includes(t));
    if (hit.length === tokens.length && tokens.length >= 2) {
      return hit.join("").length * 40;
    }
    if (hit.length >= 2) return hit.join("").length * 15;
    if (hit.length === 1 && hit[0].length >= 5) return hit[0].length * 8;
    return 0;
  }

  function matchDeviceForFilename(filename) {
    let best = null;
    let bestScore = 0;
    for (const d of devices || []) {
      const score = matchScoreForFilename(filename, d.name || "");
      if (score > bestScore) {
        bestScore = score;
        best = d;
      }
    }
    if (!best || bestScore <= 0) {
      return { address: "", match: "none", score: 0 };
    }
    const exact = filenameMentionsSensor(filename, best.name || "");
    return {
      address: best.address,
      match: exact ? "exact" : "partial",
      score: bestScore,
    };
  }

  function deviceOptionsHtml(selectedAddress) {
    const opts = ['<option value="">— select —</option>'];
    for (const d of devices || []) {
      const sel = d.address === selectedAddress ? " selected" : "";
      opts.push(
        `<option value="${escapeHtml(d.address)}"${sel}>${escapeHtml(d.name)}</option>`
      );
    }
    return opts.join("");
  }

  function batchItemById(id) {
    return coverageBatch.find((it) => it.id === id) || null;
  }

  function syncBatchSelectAll() {
    if (!coverageBatchSelectAllEl) return;
    const rows = coverageBatch.filter((it) => it.status !== "done");
    if (!rows.length) {
      coverageBatchSelectAllEl.checked = false;
      coverageBatchSelectAllEl.indeterminate = false;
      return;
    }
    const n = rows.filter((it) => it.included).length;
    coverageBatchSelectAllEl.checked = n === rows.length;
    coverageBatchSelectAllEl.indeterminate = n > 0 && n < rows.length;
  }

  function coverageOverwriteEnabled() {
    return Boolean(coverageImportOverwriteEl && coverageImportOverwriteEl.checked);
  }

  function batchItemImportable(it) {
    if (!it.included || !it.address || !it.preview) return false;
    if (it.status === "done" || it.status === "importing") return false;
    const compare = it.preview.compare || {};
    const zigzagLeft = Number(compare.zigzag_remaining) || 0;
    // Block insert-only when nearby BLE/other points would sawtooth the chart.
    if (zigzagLeft > 0 && !coverageOverwriteEnabled()) return false;
    const wouldInsert = Number(compare.would_insert) || 0;
    const wouldOverwrite = Number(compare.would_overwrite) || 0;
    if (wouldInsert > 0) return true;
    return coverageOverwriteEnabled() && wouldOverwrite > 0;
  }

  function updateBatchImportButton() {
    if (!coverageImportConfirmBtn) return;
    const ready = coverageBatch.filter(batchItemImportable);
    const zigzagBlocked = coverageBatch.some(
      (it) =>
        it.included &&
        it.preview &&
        (Number((it.preview.compare || {}).zigzag_remaining) || 0) > 0 &&
        !coverageOverwriteEnabled()
    );
    coverageImportConfirmBtn.disabled = coverageBatchBusy || ready.length === 0;
    if (zigzagBlocked && ready.length === 0) {
      coverageImportConfirmBtn.textContent = "Enable overwrite (zigzag)";
    } else {
      coverageImportConfirmBtn.textContent =
        ready.length > 1
          ? `Import selected (${ready.length})`
          : "Import selected";
    }
  }

  function updateBatchStatusLine() {
    if (!coverageImportStatusEl) return;
    if (!coverageBatch.length) {
      coverageImportStatusEl.textContent = "";
      coverageImportStatusEl.classList.remove("import-name-warn");
      return;
    }
    if (coverageBatchBusy) return;
    const matched = coverageBatch.filter((it) => it.address).length;
    const unmatched = coverageBatch.length - matched;
    const would = coverageBatch
      .filter((it) => it.included && it.preview)
      .reduce(
        (n, it) => n + (Number((it.preview.compare || {}).would_insert) || 0),
        0
      );
    const wouldOw = coverageBatch
      .filter((it) => it.included && it.preview)
      .reduce(
        (n, it) => n + (Number((it.preview.compare || {}).would_overwrite) || 0),
        0
      );
    const zigzag = coverageBatch
      .filter((it) => it.included && it.preview)
      .reduce(
        (n, it) => n + (Number((it.preview.compare || {}).zigzag_count) || 0),
        0
      );
    const zigzagLeft = coverageBatch
      .filter((it) => it.included && it.preview)
      .reduce(
        (n, it) => n + (Number((it.preview.compare || {}).zigzag_remaining) || 0),
        0
      );
    const errs = coverageBatch.filter((it) => it.error).length;
    const owOn = coverageOverwriteEnabled();
    let msg =
      `${coverageBatch.length} file(s)` +
      ` · ${matched} matched` +
      (unmatched ? ` · ${unmatched} unmatched` : "") +
      ` · ${would} new minute(s)`;
    if (owOn) msg += ` · ${wouldOw} overwrite`;
    else if (wouldOw) msg += ` · ${wouldOw} differing (enable overwrite)`;
    if (zigzag) {
      msg += owOn
        ? ` · ${zigzag} zigzag (resolved by overwrite)`
        : ` · ${zigzagLeft} zigzag — enable overwrite`;
    }
    if (errs) msg += ` · ${errs} error(s)`;
    coverageImportStatusEl.textContent = msg;
    coverageImportStatusEl.classList.toggle(
      "import-name-warn",
      unmatched > 0 || errs > 0 || (owOn && wouldOw > 0) || zigzagLeft > 0
    );
  }

  function showBatchItemRecap(item) {
    if (!item || !item.preview) {
      clearCoverageImportRecap();
      return;
    }
    renderBackfillImportPreview(item.preview);
  }

  function renderCoverageBatch() {
    if (!coverageBatchEl || !coverageBatchBodyEl) return;
    coverageBatchEl.hidden = coverageBatch.length === 0;
    if (!coverageBatch.length) {
      coverageBatchBodyEl.innerHTML = "";
      clearCoverageImportRecap();
      updateBatchImportButton();
      updateBatchStatusLine();
      return;
    }
    const owOn = coverageOverwriteEnabled();
    coverageBatchBodyEl.innerHTML = coverageBatch
      .map((it) => {
        const compare = (it.preview && it.preview.compare) || {};
        const would =
          it.preview ? Number(compare.would_insert) || 0 : "—";
        const wouldOw =
          it.preview ? Number(compare.would_overwrite) || 0 : "—";
        const samples =
          it.preview && it.preview.file
            ? Number(it.preview.file.parsed) || 0
            : "—";
        let statusTxt = it.status;
        let statusCls = "cov-batch-status";
        if (it.error) {
          statusTxt = it.error;
          statusCls += " is-error";
        } else if (it.status === "ready") {
          const parts = [];
          if (Number(would) > 0) parts.push(`${would} new`);
          if (Number(wouldOw) > 0) {
            parts.push(owOn ? `${wouldOw} overwrite` : `${wouldOw} differ`);
          }
          const zz = Number(compare.zigzag_count) || 0;
          const zzLeft = Number(compare.zigzag_remaining) || 0;
          if (zzLeft > 0) parts.push(`${zzLeft} zigzag`);
          else if (zz > 0 && owOn) parts.push(`${zz} zigzag ok`);
          statusTxt = parts.length ? parts.join(" · ") : "Nothing new";
          statusCls +=
            Number(would) > 0 || (owOn && Number(wouldOw) > 0) ? " is-ok" : "";
          if (zzLeft > 0) statusCls += " is-error";
        } else if (it.status === "done" && it.result) {
          statusTxt =
            `Imported ${it.result.inserted || 0}` +
            (it.result.overwritten
              ? ` · ow ${it.result.overwritten}`
              : "");
          statusCls += " is-ok";
        } else if (it.status === "analyzing") {
          statusTxt = "Analyzing…";
        } else if (it.status === "importing") {
          statusTxt = "Importing…";
        } else if (it.match === "none" && !it.address) {
          statusTxt = "No sensor match";
          statusCls += " is-error";
        }
        const active = it.id === coverageBatchActiveId ? " is-active" : "";
        const unmatched = !it.address ? " is-unmatched" : "";
        return (
          `<tr class="${active}${unmatched}" data-batch-id="${escapeHtml(it.id)}">` +
          `<td class="cov-batch-check"><input type="checkbox" data-batch-include` +
          `${it.included ? " checked" : ""}` +
          `${it.status === "done" ? " disabled" : ""} /></td>` +
          `<td class="cov-batch-file" title="${escapeHtml(it.file.name)}">${escapeHtml(
            it.file.name
          )}</td>` +
          `<td class="cov-batch-sensor"><select data-batch-sensor>${deviceOptionsHtml(
            it.address
          )}</select></td>` +
          `<td class="num">${samples}</td>` +
          `<td class="num">${would}</td>` +
          `<td class="num">${wouldOw}</td>` +
          `<td class="${statusCls}">${escapeHtml(String(statusTxt))}</td>` +
          `</tr>`
        );
      })
      .join("");
    syncBatchSelectAll();
    updateBatchImportButton();
    updateBatchStatusLine();
    const active = batchItemById(coverageBatchActiveId);
    if (active && active.preview) showBatchItemRecap(active);
    else if (coverageBatch.length === 1 && coverageBatch[0].preview) {
      coverageBatchActiveId = coverageBatch[0].id;
      showBatchItemRecap(coverageBatch[0]);
    }
  }

  function addFilesToBatch(fileList) {
    const incoming = [...(fileList || [])].filter((f) => isImportableFilename(f.name));
    if (!incoming.length) {
      if (coverageImportStatusEl) {
        coverageImportStatusEl.textContent = "No CSV or ZIP files found.";
      }
      return;
    }
    for (const file of incoming) {
      const dup = coverageBatch.some(
        (it) => it.file.name === file.name && it.file.size === file.size
      );
      if (dup) continue;
      const matched = matchDeviceForFilename(file.name);
      coverageBatch.push({
        id: newBatchItemId(),
        file,
        included: Boolean(matched.address),
        address: matched.address || "",
        match: matched.match,
        preview: null,
        error: null,
        status: matched.address ? "pending" : "pending",
        result: null,
      });
    }
    if (!coverageBatchActiveId && coverageBatch.length) {
      coverageBatchActiveId = coverageBatch[0].id;
    }
    renderCoverageBatch();
    analyzeCoverageBatch().catch((err) => console.warn(err));
  }

  function base64ToFile(filename, contentBase64, contentType) {
    const bin = atob(contentBase64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], filename, {
      type: contentType || "application/octet-stream",
    });
  }

  function renderMailInboxState() {
    const address = mailInboxState && mailInboxState.address;
    const configured = Boolean(address);
    if (mailInboxAddressEl) {
      mailInboxAddressEl.textContent = address || "—";
    }
    if (mailInboxCopyBtn) mailInboxCopyBtn.disabled = !configured || mailInboxBusy;
    if (mailInboxFetchBtn) mailInboxFetchBtn.disabled = !configured || mailInboxBusy;
    if (mailInboxClearBtn) mailInboxClearBtn.disabled = !configured || mailInboxBusy;
    if (mailInboxNewBtn) mailInboxNewBtn.disabled = mailInboxBusy;
    if (mailInboxUseBtn) mailInboxUseBtn.disabled = mailInboxBusy;
    if (mailInboxExistingEl) mailInboxExistingEl.disabled = mailInboxBusy;
  }

  function renderMailMessages(messages) {
    if (!mailInboxMessagesEl) return;
    const rows = Array.isArray(messages) ? messages : [];
    if (!rows.length) {
      mailInboxMessagesEl.hidden = true;
      mailInboxMessagesEl.innerHTML = "";
      return;
    }
    mailInboxMessagesEl.hidden = false;
    mailInboxMessagesEl.innerHTML = rows
      .map((msg) => {
        const files = (msg.attachments || [])
          .map((a) => a.filename)
          .filter(Boolean)
          .join(", ");
        const from = escapeHtml(msg.from || "—");
        const subject = escapeHtml(msg.subject || "(no subject)");
        const body = String(msg.text || msg.preview || "").trim();
        const bodyHtml = body
          ? `<span class="mail-msg-body">${escapeHtml(body.slice(0, 800))}</span>`
          : "";
        const codes = Array.isArray(msg.verification_codes)
          ? msg.verification_codes
          : [];
        const codesHtml = codes.length
          ? `<div class="mail-msg-code-row">${codes
              .map(
                (code) =>
                  `<code class="mail-msg-code">${escapeHtml(code)}</code>` +
                  `<button type="button" class="backfill-btn mail-copy-code" data-code="${escapeHtml(
                    code
                  )}">Copy code</button>`
              )
              .join("")}</div>`
          : "";
        const filesHtml = files
          ? `<span class="mail-msg-files">Attachment: ${escapeHtml(files)}</span>`
          : codes.length
            ? `<span class="mail-msg-files">Verification email (no CSV yet)</span>`
            : `<span class="mail-msg-files">No CSV/ZIP attachment</span>`;
        return `<li><span class="mail-msg-subject">${subject}</span> · from ${from}${codesHtml}${bodyHtml}${filesHtml}</li>`;
      })
      .join("");
  }

  async function loadMailInbox() {
    try {
      const res = await fetch("/api/mail/inbox");
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      mailInboxState = data;
      renderMailInboxState();
    } catch (err) {
      if (mailInboxStatusEl) {
        mailInboxStatusEl.textContent = `Inbox status failed: ${err.message}`;
      }
    }
  }

  async function setMailInbox(address) {
    mailInboxBusy = true;
    renderMailInboxState();
    if (mailInboxStatusEl) {
      mailInboxStatusEl.textContent = address
        ? "Saving address…"
        : "Creating disposable inbox…";
    }
    try {
      const res = await fetch("/api/mail/inbox", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(address ? { address } : {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`
        );
      }
      mailInboxState = data;
      renderMailInboxState();
      renderMailMessages([]);
      if (mailInboxStatusEl) {
        mailInboxStatusEl.textContent = address
          ? `Using ${data.address}`
          : `Created ${data.address} (expires ${data.expires_in || "24h"})`;
      }
      if (mailInboxExistingEl && data.address) {
        mailInboxExistingEl.value = data.address;
      }
    } catch (err) {
      if (mailInboxStatusEl) {
        mailInboxStatusEl.textContent = `Inbox failed: ${err.message}`;
      }
    } finally {
      mailInboxBusy = false;
      renderMailInboxState();
    }
  }

  async function clearMailInbox() {
    mailInboxBusy = true;
    renderMailInboxState();
    try {
      const res = await fetch("/api/mail/inbox", { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      mailInboxState = { address: null, configured: false };
      renderMailInboxState();
      renderMailMessages([]);
      if (mailInboxExistingEl) mailInboxExistingEl.value = "";
      if (mailInboxStatusEl) mailInboxStatusEl.textContent = "Inbox cleared.";
    } catch (err) {
      if (mailInboxStatusEl) {
        mailInboxStatusEl.textContent = `Clear failed: ${err.message}`;
      }
    } finally {
      mailInboxBusy = false;
      renderMailInboxState();
    }
  }

  async function fetchMailInbox() {
    if (!mailInboxState || !mailInboxState.address) return;
    mailInboxBusy = true;
    renderMailInboxState();
    if (mailInboxStatusEl) mailInboxStatusEl.textContent = "Checking mail…";
    try {
      const res = await fetch("/api/mail/fetch", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`
        );
      }
      const messages = data.messages || [];
      renderMailMessages(messages);
      const codes = Array.isArray(data.verification_codes)
        ? data.verification_codes
        : [];
      const files = [];
      for (const msg of messages) {
        for (const att of msg.attachments || []) {
          if (!att.content_base64 || !att.filename) continue;
          files.push(
            base64ToFile(att.filename, att.content_base64, att.content_type)
          );
        }
      }
      const count = Number(data.attachment_count) || files.length;
      if (mailInboxStatusEl) {
        if (codes.length && !count) {
          mailInboxStatusEl.textContent =
            `Verification code: ${codes.join(", ")} — copy it into Govee, then Check mail again for the CSV.`;
        } else if (count) {
          mailInboxStatusEl.textContent = codes.length
            ? `Found ${count} CSV/ZIP + code ${codes.join(", ")} — analyzing…`
            : `Found ${count} CSV/ZIP attachment(s) — analyzing…`;
        } else if (messages.length) {
          mailInboxStatusEl.textContent =
            `Found ${messages.length} message(s), no CSV/ZIP yet — open a message above for the code.`;
        } else {
          mailInboxStatusEl.textContent =
            "Inbox empty — start the Govee export to this address, then check again.";
        }
      }
      if (files.length) {
        addFilesToBatch(files);
      }
    } catch (err) {
      if (mailInboxStatusEl) {
        mailInboxStatusEl.textContent = `Check mail failed: ${err.message}`;
      }
    } finally {
      mailInboxBusy = false;
      renderMailInboxState();
    }
  }

  function clearCoverageBatch() {
    coverageBatch = [];
    coverageBatchActiveId = "";
    coverageBatchBusy = false;
    if (coverageImportFileEl) coverageImportFileEl.value = "";
    clearCoverageImportRecap();
    renderCoverageBatch();
    if (coverageImportAnalyzeBtn) coverageImportAnalyzeBtn.disabled = false;
    if (coverageImportStatusEl) {
      coverageImportStatusEl.textContent = "";
      coverageImportStatusEl.classList.remove("import-name-warn");
    }
  }

  async function previewImportFile(file, address) {
    const body = new FormData();
    body.append("address", address);
    body.append("file", file, file.name);
    body.append("overwrite", coverageOverwriteEnabled() ? "true" : "false");
    const res = await fetch("/api/backfill/import/preview", { method: "POST", body });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const err = await res.json();
        if (err && err.detail) detail = err.detail;
      } catch (_) {
        /* ignore */
      }
      throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    return res.json();
  }

  async function importOneFile(file, address) {
    const body = new FormData();
    body.append("address", address);
    body.append("file", file, file.name);
    body.append("overwrite", coverageOverwriteEnabled() ? "true" : "false");
    const res = await fetch("/api/backfill/import", { method: "POST", body });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const err = await res.json();
        if (err && err.detail) detail = err.detail;
      } catch (_) {
        /* ignore */
      }
      throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    return res.json();
  }

  async function analyzeCoverageBatchItem(item) {
    item.error = null;
    if (!item.address) {
      item.preview = null;
      item.status = "pending";
      return;
    }
    item.status = "analyzing";
    renderCoverageBatch();
    try {
      const preview = await previewImportFile(item.file, item.address);
      item.preview = preview;
      item.status = "ready";
      item.error = null;
    } catch (err) {
      item.preview = null;
      item.status = "error";
      item.error = err.message || String(err);
    }
  }

  async function analyzeCoverageBatch() {
    if (coverageBatchBusy) return;
    coverageBatchBusy = true;
    if (coverageImportAnalyzeBtn) coverageImportAnalyzeBtn.disabled = true;
    if (coverageImportConfirmBtn) coverageImportConfirmBtn.disabled = true;
    if (coverageImportStatusEl) {
      coverageImportStatusEl.textContent = "Analyzing…";
      coverageImportStatusEl.classList.remove("import-name-warn");
    }
    try {
      for (const item of coverageBatch) {
        if (item.status === "done") continue;
        await analyzeCoverageBatchItem(item);
        renderCoverageBatch();
      }
    } finally {
      coverageBatchBusy = false;
      if (coverageImportAnalyzeBtn) coverageImportAnalyzeBtn.disabled = false;
      renderCoverageBatch();
    }
  }

  async function confirmCoverageBatch() {
    const todo = coverageBatch.filter(batchItemImportable);
    if (!todo.length || coverageBatchBusy) return;
    coverageBatchBusy = true;
    if (coverageImportAnalyzeBtn) coverageImportAnalyzeBtn.disabled = true;
    if (coverageImportConfirmBtn) coverageImportConfirmBtn.disabled = true;
    let insertedTotal = 0;
    let overwrittenTotal = 0;
    let skippedTotal = 0;
    let badTotal = 0;
    let okCount = 0;
    let failCount = 0;
    try {
      for (const item of todo) {
        item.status = "importing";
        item.error = null;
        renderCoverageBatch();
        if (coverageImportStatusEl) {
          coverageImportStatusEl.textContent = `Importing ${item.file.name}…`;
        }
        try {
          const result = await importOneFile(item.file, item.address);
          item.result = result;
          item.status = "done";
          item.included = false;
          insertedTotal += Number(result.inserted) || 0;
          overwrittenTotal += Number(result.overwritten) || 0;
          skippedTotal += Number(result.skipped) || 0;
          badTotal += Number(result.bad_rows) || 0;
          okCount += 1;
        } catch (err) {
          item.status = "error";
          item.error = err.message || String(err);
          failCount += 1;
        }
        renderCoverageBatch();
      }
      await loadDevices();
      if (currentView === "coverage") {
        await loadCoverage();
      }
      if (coverageImportStatusEl) {
        coverageImportStatusEl.textContent =
          `Imported ${okCount} file(s)` +
          ` · ${insertedTotal} sample(s)` +
          (overwrittenTotal ? ` · overwritten ${overwrittenTotal}` : "") +
          (skippedTotal ? ` · skipped ${skippedTotal}` : "") +
          (badTotal ? ` · ${badTotal} bad row(s)` : "") +
          (failCount ? ` · ${failCount} failed` : "") +
          `.`;
        coverageImportStatusEl.classList.toggle("import-name-warn", failCount > 0);
      }
    } finally {
      coverageBatchBusy = false;
      if (coverageImportAnalyzeBtn) coverageImportAnalyzeBtn.disabled = false;
      renderCoverageBatch();
    }
  }

  function renderBackfillImportPreview(preview) {
    if (!coverageImportRecapEl) return;
    const file = preview.file || {};
    const existing = preview.existing || {};
    const compare = preview.compare || {};
    const fileNames = (preview.files || []).join(", ") || "—";
    const fileCount = Number((file && file.file_count) || (preview.files || []).length || 0);
    if (coverageImportFileStatsEl) {
      coverageImportFileStatsEl.innerHTML = dlRows([
        ["Sensor", preview.name || preview.address || "—"],
        ["CSV files", String(fileCount || 1)],
        ["Files", fileNames],
        ["Samples (merged)", String(file.parsed ?? 0)],
        ["Bad rows", String(file.bad_rows ?? 0)],
        ["Time span", formatImportRange(file.range)],
        ["Temperature", formatImportMinMax(file.temp, 1, " °C")],
        ["Humidity", formatImportMinMax(file.humidity, 1, " %")],
      ]);
    }
    const sources = existing.sources || {};
    const sourceText = Object.keys(sources).length
      ? Object.entries(sources)
          .map(([k, n]) => `${k}: ${n}`)
          .join(", ")
      : "—";
    if (coverageImportExistingStatsEl) {
      coverageImportExistingStatsEl.innerHTML = dlRows([
        ["Samples in range", String(existing.samples_in_range ?? 0)],
        ["Time span", formatImportRange(existing.range)],
        ["Temperature", formatImportMinMax(existing.temp, 1, " °C")],
        ["Humidity", formatImportMinMax(existing.humidity, 1, " %")],
        ["Sources", sourceText],
      ]);
    }
    if (coverageImportCompareStatsEl) {
      coverageImportCompareStatsEl.innerHTML = dlRows([
        ["Already present", String(compare.already_present ?? 0)],
        ["Would insert", String(compare.would_insert ?? 0)],
        ["Would overwrite", String(compare.would_overwrite ?? 0)],
        ["Zigzag nearby", String(compare.zigzag_count ?? 0)],
        ["Zigzag remaining", String(compare.zigzag_remaining ?? 0)],
        ["Max |ΔT| overwrite", `${Number(compare.overwrite_temp_max ?? 0).toFixed(2)} °C`],
        ["Max |ΔT| zigzag", `${Number(compare.zigzag_temp_max ?? 0).toFixed(2)} °C`],
        ["DB-only minutes", String(compare.db_only_minutes ?? 0)],
        ["Overlap", `${Number(compare.overlap_pct ?? 0)} %`],
      ]);
    }
    const owSamples = Array.isArray(compare.overwrite_samples)
      ? compare.overwrite_samples
      : [];
    if (coverageImportOverwriteWrapEl && coverageImportOverwriteBodyEl) {
      if (owSamples.length) {
        coverageImportOverwriteWrapEl.hidden = false;
        coverageImportOverwriteBodyEl.innerHTML = owSamples
          .map(
            (row) =>
              `<tr>` +
              `<td>${escapeHtml(formatImportTs(row.ts))}</td>` +
              `<td class="num">${Number(row.old_temp).toFixed(1)}</td>` +
              `<td class="num">${Number(row.new_temp).toFixed(1)}</td>` +
              `<td class="num">${Number(row.old_hum).toFixed(1)}</td>` +
              `<td class="num">${Number(row.new_hum).toFixed(1)}</td>` +
              `</tr>`
          )
          .join("");
      } else {
        coverageImportOverwriteWrapEl.hidden = true;
        coverageImportOverwriteBodyEl.innerHTML = "";
      }
    }
    const zzSamples = Array.isArray(compare.zigzag_samples)
      ? compare.zigzag_samples
      : [];
    if (coverageImportZigzagWrapEl && coverageImportZigzagBodyEl) {
      const zzCount = Number(compare.zigzag_count) || 0;
      if (zzCount > 0) {
        coverageImportZigzagWrapEl.hidden = false;
        const rem = Number(compare.zigzag_remaining) || 0;
        const epsT = Number(compare.zigzag_eps_temp) || 1;
        const win = Number(compare.zigzag_window_s) || 60;
        if (coverageImportZigzagHintEl) {
          coverageImportZigzagHintEl.textContent = rem
            ? `${zzCount} CSV minute(s) disagree with nearby DB readings within ±${win}s (|ΔT|≥${epsT}°C). Insert-only would zigzag — enable Overwrite existing minutes.`
            : `${zzCount} nearby conflict(s) detected; overwrite will replace the DB minute in place (no zigzag).`;
        }
        coverageImportZigzagBodyEl.innerHTML = zzSamples
          .map(
            (row) =>
              `<tr>` +
              `<td>${escapeHtml(formatImportTs(row.ts))}</td>` +
              `<td>${escapeHtml(formatImportTs(row.db_ts))}</td>` +
              `<td>${escapeHtml(row.source || "—")}</td>` +
              `<td class="num">${Number(row.csv_temp).toFixed(1)}</td>` +
              `<td class="num">${Number(row.db_temp).toFixed(1)}</td>` +
              `<td class="num">${Number(row.csv_hum).toFixed(1)}</td>` +
              `<td class="num">${Number(row.db_hum).toFixed(1)}</td>` +
              `</tr>`
          )
          .join("");
      } else {
        coverageImportZigzagWrapEl.hidden = true;
        coverageImportZigzagBodyEl.innerHTML = "";
        if (coverageImportZigzagHintEl) coverageImportZigzagHintEl.textContent = "";
      }
    }
    const memberStats = Array.isArray(preview.file_stats) ? preview.file_stats : [];
    if (coverageImportMembersWrapEl && coverageImportMembersEl) {
      if (memberStats.length > 1) {
        coverageImportMembersWrapEl.hidden = false;
        coverageImportMembersEl.innerHTML = memberStats
          .map((m) => {
            const err = m.error ? ` · error: ${m.error}` : "";
            const span =
              m.range && m.range.start != null
                ? ` · ${formatImportRange(m.range)}`
                : "";
            return (
              `<li><span class="m-name">${escapeHtml(m.name || "—")}</span>` +
              `<span>${Number(m.parsed) || 0} samples` +
              (m.bad_rows ? ` · ${Number(m.bad_rows)} bad` : "") +
              `${escapeHtml(span)}${escapeHtml(err)}</span></li>`
            );
          })
          .join("");
      } else {
        coverageImportMembersWrapEl.hidden = true;
        coverageImportMembersEl.innerHTML = "";
      }
    }

    const fileSegs = preview.file_segments || [];
    const dbSegs = preview.db_segments || [];
    const fileRange = (preview.file && preview.file.range) || {};
    const covRange =
      fileRange.start != null
        ? { start: fileRange.start, end: Number(fileRange.end) + 60 }
        : null;
    if (coverageImportBarsEl && covRange) {
      coverageImportBarsEl.hidden = false;
      renderCoverageBar(coverageFileBarEl, fileSegs, covRange);
      renderCoverageBar(coverageDbBarEl, dbSegs, covRange);
      const covMeta = preview.coverage || {};
      const filePct = (covMeta.file && covMeta.file.coverage_pct) || 0;
      const dbPct = (covMeta.db && covMeta.db.coverage_pct) || 0;
      if (coverageImportCompareStatsEl) {
        coverageImportCompareStatsEl.innerHTML += dlRows([
          ["File coverage", `${filePct} %`],
          ["DB coverage (exact)", `${dbPct} %`],
        ]);
      }
    } else if (coverageImportBarsEl) {
      coverageImportBarsEl.hidden = true;
    }

    coverageImportRecapEl.hidden = false;
  }

  function foldImportLabel(text) {
    return String(text || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "");
  }

  /** True if filename / ZIP member seems to refer to the sensor label. */
  function filenameMentionsSensor(filename, sensorName) {
    const nameFold = foldImportLabel(sensorName);
    if (!nameFold || nameFold.length < 3) return true;
    const fileFold = foldImportLabel(filename);
    if (!fileFold) return true;
    if (fileFold.includes(nameFold)) return true;
    const tokens = String(sensorName || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .map((t) => t.trim())
      .filter((t) => t.length >= 3);
    if (tokens.length >= 2) {
      return tokens.every((t) => fileFold.includes(t));
    }
    return false;
  }

  function renderCoverageBar(container, segments, range) {
    if (!container) return;
    container.innerHTML = "";
    const list = Array.isArray(segments) ? segments : [];
    const t0 = range && range.start != null ? Number(range.start) : null;
    const t1 = range && range.end != null ? Number(range.end) : null;
    const span =
      t0 != null && t1 != null && t1 > t0
        ? t1 - t0
        : list.reduce((s, seg) => s + Math.max(0, Number(seg.end) - Number(seg.start)), 0);
    if (!list.length || !(span > 0)) {
      const empty = document.createElement("div");
      empty.className = "coverage-seg coverage-seg-empty";
      empty.style.flex = "1";
      empty.title = "No data";
      container.appendChild(empty);
      return;
    }
    for (const seg of list) {
      const w = Math.max(0, Number(seg.end) - Number(seg.start));
      const el = document.createElement("div");
      el.className = `coverage-seg coverage-seg-${seg.status || "missing"}`;
      el.style.flex = String(Math.max(w / span, 0.0001));
      const dens = Math.round(Number(seg.density || 0) * 100);
      el.title =
        `${seg.status || "?"} · ${dens}% · ` +
        `${formatImportTs(seg.start)} → ${formatImportTs(seg.end)}`;
      container.appendChild(el);
    }
  }

  function formatCoverageSegmentLabel(seg) {
    const status = String(seg.status || "?");
    const label = status.charAt(0).toUpperCase() + status.slice(1);
    const dens = Math.round(Number(seg.density || 0) * 100);
    return `${label} · ${dens}% · ${formatImportTs(seg.start)} → ${formatImportTs(seg.end)}`;
  }

  function renderCoverageSegmentsList(segments) {
    if (!coverageSegmentsEl) return;
    const list = Array.isArray(segments) ? segments : [];
    if (!list.length) {
      coverageSegmentsEl.innerHTML = "";
      return;
    }
    // Prefer listing gaps and partials; include full only if few segments.
    const interesting = list.filter((s) => s.status !== "full");
    const show = interesting.length ? interesting : list;
    const capped = show.slice(0, 40);
    coverageSegmentsEl.innerHTML = capped
      .map(
        (s) =>
          `<li class="coverage-seg-item coverage-seg-item-${escapeHtml(
            s.status || "missing"
          )}">${escapeHtml(formatCoverageSegmentLabel(s))}</li>`
      )
      .join("");
    if (show.length > capped.length) {
      coverageSegmentsEl.innerHTML +=
        `<li class="coverage-seg-item">… ${show.length - capped.length} more</li>`;
    }
  }

  function deviceStoredInfo(address) {
    const key = String(address || "").toUpperCase();
    const device = (devices || []).find(
      (d) => String(d.address || "").toUpperCase() === key
    );
    if (!device) {
      return { samples: 0, bytes: 0, label: "—", title: "" };
    }
    const samples = Number(device.sample_count) || 0;
    const bytes =
      device.storage_bytes_est != null
        ? Number(device.storage_bytes_est)
        : samples * 120;
    if (samples <= 0) {
      return { samples: 0, bytes: 0, label: "—", title: "" };
    }
    return {
      samples,
      bytes,
      label: `${formatSampleCount(samples)} · ${formatBytes(bytes)}`,
      title: `${samples.toLocaleString("en-GB")} samples · ~${formatBytes(bytes)} (est.)`,
    };
  }

  function renderCoverageAllList(sensors, range) {
    if (!coverageAllListEl) return;
    const rows = Array.isArray(sensors) ? sensors : [];
    if (!rows.length) {
      coverageAllListEl.innerHTML =
        '<li class="coverage-all-empty">No sensors</li>';
      return;
    }
    coverageAllListEl.innerHTML = "";
    for (const s of rows) {
      const li = document.createElement("li");
      li.className = "coverage-all-row";
      if (s.address === coverageAddress) li.classList.add("active");
      li.dataset.address = s.address;

      const meta = document.createElement("div");
      meta.className = "coverage-all-meta";
      const name = document.createElement("span");
      name.className = "coverage-all-name";
      name.textContent = s.name || s.address;
      const pct = document.createElement("span");
      pct.className = "coverage-all-pct";
      const stored = deviceStoredInfo(s.address);
      pct.textContent = `${Number(s.coverage_pct || 0).toFixed(0)}%`;
      if (stored.samples > 0) {
        const storeEl = document.createElement("span");
        storeEl.className = "coverage-all-stored";
        storeEl.textContent = stored.label;
        storeEl.title = stored.title;
        pct.append(" · ", storeEl);
      }
      meta.append(name, pct);

      const bar = document.createElement("div");
      bar.className = "coverage-bar coverage-bar-thin coverage-all-bar";
      bar.setAttribute("role", "img");
      bar.setAttribute(
        "aria-label",
        `${s.name || s.address} ${Number(s.coverage_pct || 0)}% covered`
      );
      renderCoverageBar(bar, s.segments, range || s.range);

      li.append(meta, bar);
      li.addEventListener("click", () => {
        coverageAddress = s.address;
        persistCoverageState();
        if (coverageDeviceEl) coverageDeviceEl.value = s.address;
        if (coverageImportDeviceEl) coverageImportDeviceEl.value = s.address;
        loadCoverageDetail().catch((err) => console.warn(err));
        coverageAllListEl
          .querySelectorAll(".coverage-all-row")
          .forEach((el) => {
            el.classList.toggle("active", el.dataset.address === coverageAddress);
          });
      });
      coverageAllListEl.appendChild(li);
    }
  }

  async function loadCoverageOverview() {
    syncCoverageRangeButtons();
    const hasList =
      coverageAllListEl &&
      coverageAllListEl.querySelector(".coverage-all-row") != null;
    if (coverageAllSummaryEl) {
      coverageAllSummaryEl.textContent = hasList
        ? "Refreshing…"
        : "Loading…";
    }
    // Keep the previous list visible while refreshing so the view does not flash empty.
    if (coverageAllListEl && !hasList) {
      coverageAllListEl.innerHTML =
        '<li class="coverage-all-empty">Loading…</li>';
    }
    if (coverageAllListEl && hasList) {
      coverageAllListEl.classList.add("is-refreshing");
    }
    try {
      const params = new URLSearchParams();
      if (coverageHours === "all") {
        params.set("since_first", "true");
      } else {
        params.set("hours", String(coverageHours));
      }
      const res = await fetch(`/api/coverage/overview?${params}`);
      if (!res.ok) throw new Error(`coverage overview HTTP ${res.status}`);
      const data = await res.json();
      const sensors = data.sensors || [];
      const avg =
        sensors.length > 0
          ? sensors.reduce((n, s) => n + Number(s.coverage_pct || 0), 0) /
            sensors.length
          : 0;
      let totalSamples = 0;
      let totalBytes = 0;
      for (const s of sensors) {
        const stored = deviceStoredInfo(s.address);
        totalSamples += stored.samples;
        totalBytes += stored.bytes;
      }
      const storeNote =
        totalSamples > 0
          ? ` · ~${formatSampleCount(totalSamples)} samples / ${formatBytes(totalBytes)}`
          : "";
      if (coverageAllSummaryEl) {
        coverageAllSummaryEl.textContent =
          `${sensors.length} sensor(s) · avg ${avg.toFixed(0)}% covered` +
          storeNote +
          ` · window ${formatImportRange(data.range)}` +
          ` · buckets: ${data.bucket || "day"}`;
      }
      renderCoverageAllList(sensors, data.range);
      return data;
    } finally {
      if (coverageAllListEl) {
        coverageAllListEl.classList.remove("is-refreshing");
      }
    }
  }

  async function loadCoverageDetail() {
    populateCoverageDevices();
    if (!coverageAddress) {
      if (coverageSummaryEl) coverageSummaryEl.textContent = "Select a sensor…";
      if (coverageBarEl) coverageBarEl.innerHTML = "";
      if (coverageSegmentsEl) coverageSegmentsEl.innerHTML = "";
      if (coverageStatusEl) coverageStatusEl.textContent = "";
      if (coverageAggEl) coverageAggEl.hidden = true;
      renderCoverageRecent([]);
      renderCoverageRecentJobs([]);
      clearCoverageCharts();
      return;
    }
    if (coverageStatusEl) coverageStatusEl.textContent = "Loading coverage…";
    if (coverageSummaryEl) coverageSummaryEl.textContent = "Loading…";
    if (coverageAggEl) coverageAggEl.hidden = false;
    const params = new URLSearchParams({ address: coverageAddress });
    if (coverageHours === "all") {
      params.set("since_first", "true");
    } else {
      params.set("hours", String(coverageHours));
    }
    const res = await fetch(`/api/coverage?${params}`);
    if (!res.ok) throw new Error(`coverage HTTP ${res.status}`);
    const data = await res.json();
    const counts = data.counts || {};
    const unit = data.bucket === "hour" ? "hours" : "days";
    if (coverageSummaryEl) {
      coverageSummaryEl.textContent =
        `${data.name || data.address} · ${Number(data.coverage_pct || 0)}% covered` +
        ` · ${counts.full || 0} full / ${counts.partial || 0} partial / ${counts.missing || 0} missing` +
        ` segment(s) (${unit})` +
        ` · ${Number(data.samples || 0)} soft-covered minute(s)`;
    }
    renderCoverageBar(coverageBarEl, data.segments, data.range);
    renderCoverageSegmentsList(data.segments);
    if (coverageStatusEl) {
      const src = data.sources || {};
      const srcTxt = Object.keys(src).length
        ? Object.entries(src)
            .map(([k, n]) => `${k}: ${n}`)
            .join(", ")
        : "—";
      coverageStatusEl.textContent = `Sources · ${srcTxt}`;
    }
    renderCoverageRecent(data.recent);
    renderCoverageRecentJobs(data.recent_jobs);
    await Promise.all([
      loadCoverageAggregates(),
      loadCoverageCharts(data.range || null),
    ]);
  }

  function ensureCoverageCharts() {
    if (coverageTempChart && coverageHumChart) return;
    const tempCanvas = document.getElementById("coverage-temp-chart");
    const humCanvas = document.getElementById("coverage-hum-chart");
    if (!tempCanvas || !humCanvas || typeof Chart === "undefined") return;
    const opts = structuredClone(chartDefaults);
    if (opts.plugins && opts.plugins.legend) {
      opts.plugins.legend.display = false;
    }
    // Avoid Compare zoom plugins on coverage canvases.
    if (opts.plugins && opts.plugins.zoom) delete opts.plugins.zoom;
    if (opts.plugins && opts.plugins.windowBands) delete opts.plugins.windowBands;
    if (opts.plugins && opts.plugins.hvacBands) delete opts.plugins.hvacBands;
    coverageTempChart = new Chart(tempCanvas, {
      type: "line",
      data: { datasets: [] },
      options: structuredClone(opts),
    });
    coverageHumChart = new Chart(humCanvas, {
      type: "line",
      data: { datasets: [] },
      options: structuredClone(opts),
    });
  }

  function resizeCoverageCharts() {
    if (coverageTempChart) coverageTempChart.resize();
    if (coverageHumChart) coverageHumChart.resize();
  }

  function clearCoverageCharts() {
    if (coverageChartsEl) coverageChartsEl.hidden = true;
    if (coverageTempChart) {
      coverageTempChart.data.datasets = [];
      coverageTempChart.update("none");
    }
    if (coverageHumChart) {
      coverageHumChart.data.datasets = [];
      coverageHumChart.update("none");
    }
  }

  async function loadCoverageCharts(range) {
    if (!coverageAddress) {
      clearCoverageCharts();
      return;
    }
    // Unhide before Chart.js measures the canvas (hidden → 0×0 layout).
    if (coverageChartsEl) coverageChartsEl.hidden = false;
    ensureCoverageCharts();
    if (!coverageTempChart || !coverageHumChart) return;
    resizeCoverageCharts();
    const histParams = new URLSearchParams({
      address: coverageAddress,
      max_points: "2000",
    });
    if (
      coverageHours === "all" &&
      range &&
      range.start != null &&
      range.end != null
    ) {
      histParams.set("since", String(range.start));
      histParams.set("until", String(range.end));
    } else if (coverageHours === "all") {
      histParams.set("hours", "8760");
    } else {
      histParams.set("hours", String(coverageHours));
    }
    try {
      const res = await fetch(`/api/history?${histParams}`);
      if (!res.ok) throw new Error(`history HTTP ${res.status}`);
      const payload = await res.json();
      const points = payload.points || [];
      const color = colorFor(coverageAddress);
      const tempData = points
        .filter((p) => p && p.ts != null && p.temperature_c != null)
        .map((p) => ({
          x: Number(p.ts) * 1000,
          y: Number(p.temperature_c),
        }));
      const humData = points
        .filter((p) => p && p.ts != null && p.humidity != null)
        .map((p) => ({
          x: Number(p.ts) * 1000,
          y: Number(p.humidity),
        }));
      coverageTempChart.data.datasets = [
        makeDataset("Temperature", color, tempData, true),
      ];
      coverageHumChart.data.datasets = [
        makeDataset("Humidity", color, humData, true),
      ];
      coverageTempChart.update();
      coverageHumChart.update();
      // Second resize after data+layout settle (tab/column may still be settling).
      requestAnimationFrame(() => resizeCoverageCharts());
    } catch (err) {
      console.warn("coverage charts:", err);
      if (coverageTempChart) {
        coverageTempChart.data.datasets = [];
        coverageTempChart.update("none");
      }
      if (coverageHumChart) {
        coverageHumChart.data.datasets = [];
        coverageHumChart.update("none");
      }
    }
  }

  function syncCoverageAggButtons() {
    coverageAggButtons.forEach((btn) => {
      btn.classList.toggle(
        "active",
        btn.dataset.aggBucket === String(coverageAggBucket)
      );
    });
  }

  function fmtAggNum(v, digits) {
    if (v == null || Number.isNaN(Number(v))) return "—";
    return Number(v).toFixed(digits);
  }

  async function loadCoverageAggregates() {
    syncCoverageAggButtons();
    if (!coverageAggBodyEl) return;
    if (!coverageAddress) {
      if (coverageAggEl) coverageAggEl.hidden = true;
      return;
    }
    if (coverageAggEl) coverageAggEl.hidden = false;
    if (coverageAggHintEl) coverageAggHintEl.textContent = "Loading aggregates…";
    coverageAggBodyEl.innerHTML =
      '<tr><td colspan="8" class="overview-empty">Loading…</td></tr>';
    try {
      const params = new URLSearchParams({
        address: coverageAddress,
        bucket: coverageAggBucket,
      });
      if (coverageHours === "all") {
        params.set("since_first", "true");
      } else {
        params.set("hours", String(coverageHours));
      }
      const res = await fetch(`/api/history/aggregate?${params}`);
      if (!res.ok) throw new Error(`aggregate HTTP ${res.status}`);
      const data = await res.json();
      const rows = data.rows || [];
      if (coverageAggHintEl) {
        coverageAggHintEl.textContent =
          `${data.name || data.address} · ${rows.length} ${coverageAggBucket} row(s)` +
          ` · ${formatImportRange(data.range)}`;
      }
      if (!rows.length) {
        coverageAggBodyEl.innerHTML =
          '<tr><td colspan="8" class="overview-empty">No samples in this window</td></tr>';
        return;
      }
      // Newest first for scanning recent stats.
      const ordered = rows.slice().reverse();
      coverageAggBodyEl.innerHTML = ordered
        .map((r) => {
          const t = r.temperature_c || {};
          const h = r.humidity || {};
          return (
            `<tr>` +
            `<td>${escapeHtml(r.period || "—")}</td>` +
            `<td class="num">${fmtAggNum(t.avg, 1)}</td>` +
            `<td class="num">${fmtAggNum(t.min, 1)}</td>` +
            `<td class="num">${fmtAggNum(t.max, 1)}</td>` +
            `<td class="num">${fmtAggNum(h.avg, 0)}</td>` +
            `<td class="num">${fmtAggNum(h.min, 0)}</td>` +
            `<td class="num">${fmtAggNum(h.max, 0)}</td>` +
            `<td class="num">${Number(r.count) || 0}</td>` +
            `</tr>`
          );
        })
        .join("");
    } catch (err) {
      console.warn(err);
      if (coverageAggHintEl) {
        coverageAggHintEl.textContent = `Error: ${err.message}`;
      }
      coverageAggBodyEl.innerHTML =
        `<tr><td colspan="8" class="overview-empty">${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function loadCoverage() {
    populateCoverageDevices();
    syncCoverageRangeButtons();
    try {
      await loadCoverageOverview();
      await loadCoverageDetail();
      coverageLoaded = true;
    } catch (err) {
      console.warn(err);
      if (coverageAllSummaryEl) {
        coverageAllSummaryEl.textContent = `Error: ${err.message}`;
      }
      if (coverageSummaryEl) coverageSummaryEl.textContent = `Error: ${err.message}`;
      if (coverageStatusEl) coverageStatusEl.textContent = "";
    }
  }

  function syncCoverageRangeButtons() {
    coverageRangeButtons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.covHours === String(coverageHours));
    });
  }

  function persistCoverageState() {
    localStorage.setItem("govee-charts.coverageAddress", coverageAddress || "");
    localStorage.setItem("govee-charts.coverageHours", String(coverageHours));
    localStorage.setItem("govee-charts.coverageAggBucket", String(coverageAggBucket));
  }

  async function loadBackfill() {
    if (backfillLoadInFlight) return;
    backfillLoadInFlight = true;
    try {
      const res = await fetch("/api/backfill?recent_limit=10&job_limit=10");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // Avoid overwriting checkboxes mid-PATCH (poll races).
      if (
        backfillDeviceBusyAddrs.size &&
        backfillSnapshot &&
        Array.isArray(backfillSnapshot.devices)
      ) {
        data.devices = backfillSnapshot.devices;
      }
      renderBackfill(data);
    } catch (err) {
      console.warn("backfill status:", err);
      if (backfillCurrentEl) {
        backfillCurrentEl.innerHTML =
          `<p class="backfill-idle">Backfill status unavailable: ${escapeHtml(err.message)}</p>`;
      }
    } finally {
      backfillLoadInFlight = false;
      if (currentView === "backfill" && !backfillTimer) {
        scheduleBackfillPoll();
      }
    }
  }

  function stopBackfillPolling() {
    if (backfillTimer) {
      clearTimeout(backfillTimer);
      backfillTimer = null;
    }
  }

  function scheduleBackfillPoll() {
    stopBackfillPolling();
    if (currentView !== "backfill") return;
    backfillTimer = setTimeout(() => {
      backfillTimer = null;
      loadBackfill().catch((err) => console.warn(err));
    }, 2500);
  }

  function syncBackfillPolling() {
    if (currentView !== "backfill") {
      stopBackfillPolling();
      return;
    }
    // Keep a single chain: next poll is scheduled after each load finishes.
    if (!backfillLoadInFlight && !backfillTimer) {
      scheduleBackfillPoll();
    }
  }

  function formatCount(n) {
    const v = Number(n) || 0;
    return v.toLocaleString();
  }

  function ensureSystemCharts() {
    if (typeof Chart === "undefined") return;
    if (systemStorageCanvas && !systemStorageChart) {
      systemStorageChart = new Chart(systemStorageCanvas.getContext("2d"), {
        type: "line",
        data: { datasets: [] },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: { position: "bottom" },
            tooltip: {
              callbacks: {
                label(ctx) {
                  const y = ctx.parsed.y;
                  return `${ctx.dataset.label}: ${formatBytes(y)}`;
                },
              },
            },
          },
          scales: {
            x: {
              type: "time",
              time: { unit: "day", tooltipFormat: "yyyy-MM-dd" },
              title: { display: false },
            },
            y: {
              beginAtZero: true,
              ticks: {
                callback(v) {
                  return formatBytes(v);
                },
              },
            },
          },
        },
      });
    }
  }

  function destroySystemSourceCharts() {
    systemSourceCharts.forEach((c) => {
      try {
        c.destroy();
      } catch (_) {
        /* ignore */
      }
    });
    systemSourceCharts = [];
    if (systemSourceChartsEl) systemSourceChartsEl.innerHTML = "";
  }

  function makeSystemSourceChart(canvas, grain) {
    const xUnit = grain === "hour" ? "hour" : "day";
    return new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: { datasets: [] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom" },
        },
        scales: {
          x: {
            type: "time",
            stacked: true,
            time: {
              unit: xUnit,
              tooltipFormat: "yyyy-MM-dd HH:mm",
            },
          },
          y: {
            stacked: true,
            beginAtZero: true,
            title: {
              display: true,
              text: grain === "hour" ? "Samples / hour" : "Samples / day",
            },
          },
        },
      },
    });
  }

  function syncSystemRangeButtons() {
    const hourMode = systemGrain === "hour";
    systemRangeButtons.forEach((btn) => {
      const d = Number(btn.dataset.sysDays);
      const hourOnly = d <= 2;
      btn.hidden = hourMode ? false : hourOnly;
      if (hourMode && d > 14) btn.hidden = true;
      btn.classList.toggle("active", !btn.hidden && d === systemDays);
    });
    systemGrainButtons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.sysGrain === systemGrain);
    });
  }

  function selectedSystemAddressesFromDom() {
    if (!systemDeviceEl) return [];
    return [...systemDeviceEl.selectedOptions]
      .map((o) => o.value)
      .filter(Boolean);
  }

  function syncSystemSelectionFromDom() {
    if (!systemDeviceEl) return;
    const visible = new Set(
      [...systemDeviceEl.options].map((o) => String(o.value || "").toUpperCase())
    );
    for (const addr of [...systemSelectedAddresses]) {
      if (!visible.has(addr)) continue;
      const opt = [...systemDeviceEl.options].find(
        (o) => String(o.value || "").toUpperCase() === addr
      );
      if (opt && !opt.selected) systemSelectedAddresses.delete(addr);
    }
    selectedSystemAddressesFromDom().forEach((a) => {
      systemSelectedAddresses.add(String(a).toUpperCase());
    });
  }

  function selectedSystemAddresses() {
    syncSystemSelectionFromDom();
    return [...systemSelectedAddresses];
  }

  function deviceMatchesSystemFilter(device, rawFilter) {
    const q = String(rawFilter || "").trim().toLowerCase();
    if (!q) return true;
    const qMac = q.replace(/[:\s-]/g, "");
    const name = String(device.name || "").toLowerCase();
    const addr = String(device.address || "").toLowerCase();
    const addrMac = addr.replace(/[:\s-]/g, "");
    if (name.includes(q) || addr.includes(q)) return true;
    return Boolean(qMac) && addrMac.includes(qMac);
  }

  function renderSystemDeviceOptions() {
    if (!systemDeviceEl) return;
    syncSystemSelectionFromDom();
    const filtered = systemDeviceList.filter((d) =>
      deviceMatchesSystemFilter(d, systemDeviceFilter)
    );
    systemDeviceEl.innerHTML = filtered
      .map((d) => {
        const addr = String(d.address || "").toUpperCase();
        const name = String(d.name || addr);
        const n = Number(d.sample_count) || 0;
        const label = n ? `${name} (${formatSampleCount(n)})` : name;
        return `<option value="${escapeHtml(addr)}">${escapeHtml(label)}</option>`;
      })
      .join("");
    [...systemDeviceEl.options].forEach((opt) => {
      opt.selected = systemSelectedAddresses.has(
        String(opt.value || "").toUpperCase()
      );
    });
  }

  function seriesPointTime(row, grain) {
    const t = row.t || row.day || "";
    if (!t) return null;
    if (grain === "hour") {
      return t.endsWith("Z") ? t : `${t}Z`;
    }
    // Day bucket → midnight UTC
    if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return `${t}T00:00:00.000Z`;
    return t;
  }

  function renderSystemStorage(data) {
    ensureSystemCharts();
    const current = (data.storage && data.storage.current) || {};
    const daily = Array.isArray(data.storage && data.storage.daily)
      ? data.storage.daily
      : [];
    if (systemStorageSummaryEl) {
      const bits = [
        `Now: ${formatBytes(current.total_bytes)}`,
        `DB ${formatBytes(current.db_bytes)}`,
        `WAL ${formatBytes(current.wal_bytes)}`,
      ];
      if (current.readings_count != null) {
        bits.push(`${formatCount(current.readings_count)} readings`);
      }
      systemStorageSummaryEl.textContent = bits.join(" · ");
    }
    if (systemStorageHintEl) {
      systemStorageHintEl.textContent = daily.length
        ? `${daily.length} daily snapshot${daily.length === 1 ? "" : "s"} (UTC)`
        : "No daily snapshots yet — recorded by workers once per UTC day";
    }
    if (!systemStorageChart) return;
    const toPoints = (key) =>
      daily.map((row) => ({
        x: `${row.day}T00:00:00.000Z`,
        y: Number(row[key]) || 0,
      }));
    // Include live point if newer than last snapshot day.
    const seriesKeys = [
      { key: "total_bytes", label: "Total", color: "#1f6feb" },
      { key: "db_bytes", label: "DB file", color: "#2da44e" },
      { key: "wal_bytes", label: "WAL", color: "#bf8700" },
    ];
    const lastDay = daily.length ? daily[daily.length - 1].day : null;
    const curDay = current.day || null;
    systemStorageChart.data.datasets = seriesKeys.map((s) => {
      const pts = toPoints(s.key);
      if (
        curDay &&
        current[s.key] != null &&
        (!lastDay || curDay > lastDay || curDay === lastDay)
      ) {
        const live = {
          x: `${curDay}T00:00:00.000Z`,
          y: Number(current[s.key]) || 0,
        };
        if (!pts.length || pts[pts.length - 1].x !== live.x) {
          pts.push(live);
        } else {
          pts[pts.length - 1] = live;
        }
      }
      return {
        label: s.label,
        data: pts,
        borderColor: s.color,
        backgroundColor: s.color,
        tension: 0.15,
        pointRadius: pts.length <= 2 ? 3 : 0,
        borderWidth: 2,
      };
    });
    systemStorageChart.update();
  }

  function formatInventoryPct(pct) {
    const v = Number(pct);
    if (!Number.isFinite(v)) return "—";
    if (v > 0 && v < 0.01) return "<0.01%";
    if (v < 10) return `${v.toFixed(2)}%`;
    return `${v.toFixed(1)}%`;
  }

  function renderSystemInventory(data) {
    const inv = data.inventory || {};
    const bySrc = inv.readings_by_source || {};
    const dbFile = inv.db_file || {};
    if (systemSourceSummaryEl) {
      const pills = [
        ["direct", "Direct BLE"],
        ["backfill", "GATT backfill"],
        ["federation", "Federation"],
        ["other", "Other"],
      ];
      systemSourceSummaryEl.innerHTML = pills
        .map(
          ([k, label]) =>
            `<span class="sys-pill"><span>${escapeHtml(label)}</span>` +
            `<strong>${escapeHtml(formatCount(bySrc[k] || 0))}</strong></span>`
        )
        .join("");
    }
    if (systemInventoryHintEl) {
      if (inv.size_source === "dbstat") {
        const logical = Number(dbFile.logical_bytes) || 0;
        const attributed = Number(dbFile.attributed_bytes);
        const bits = [
          "Sizes from SQLite dbstat (table pages + indexes)",
          `% of ${formatBytes(logical)} logical DB`,
        ];
        if (Number.isFinite(attributed) && logical > 0) {
          const other = Math.max(0, logical - attributed);
          if (other > 0) {
            bits.push(
              `${formatBytes(other)} schema / free / other (${formatInventoryPct(
                (100 * other) / logical
              )})`
            );
          }
        }
        systemInventoryHintEl.textContent = bits.join(" · ");
      } else {
        systemInventoryHintEl.textContent =
          "What is stored in this node’s database — per-table size unavailable on this SQLite build";
      }
    }
    if (!systemInventoryBody) return;
    const tables = Array.isArray(inv.tables) ? inv.tables : [];
    if (!tables.length) {
      systemInventoryBody.innerHTML =
        `<tr><td colspan="5" class="overview-empty">No tables</td></tr>`;
      return;
    }
    systemInventoryBody.innerHTML = tables
      .map((t) => {
        const size =
          t.bytes != null
            ? formatBytes(t.bytes)
            : "—";
        const pct = formatInventoryPct(t.pct);
        return (
          `<tr>` +
          `<td>${escapeHtml(t.name)}</td>` +
          `<td class="num">${escapeHtml(formatCount(t.rows))}</td>` +
          `<td class="num">${escapeHtml(size)}</td>` +
          `<td class="num">${escapeHtml(pct)}</td>` +
          `<td>${escapeHtml(t.note || "")}</td>` +
          `</tr>`
        );
      })
      .join("");
  }

  function ageMixHtml(buckets) {
    const list = Array.isArray(buckets) ? buckets : [];
    const parts = list
      .filter((b) => Number(b.samples) > 0)
      .map((b) => {
        const pct = formatInventoryPct(b.pct);
        return `<span class="sys-age-chip" title="${escapeHtml(
          String(b.key)
        )}: ${escapeHtml(formatCount(b.samples))} (${escapeHtml(pct)})">${escapeHtml(
          String(b.key)
        )} ${escapeHtml(pct)}</span>`;
      });
    if (!parts.length) return '<span class="overview-meta">—</span>';
    return `<div class="sys-age-mix">${parts.join("")}</div>`;
  }

  function renderSystemSensorStorage(data) {
    const store = data.sensor_storage || {};
    const policies = Array.isArray(store.policies) ? store.policies : [];
    const sensors = Array.isArray(store.sensors) ? store.sensors : [];
    if (systemSensorStorageHintEl) {
      const bits = [
        "Per-sensor readings footprint (dbstat share) and compaction policy",
        "Policies roll up old raw samples to min/max/avg buckets on the workers schedule",
      ];
      if (store.readings_store_bytes != null) {
        bits.push(
          `Readings store ${formatBytes(store.readings_store_bytes)}` +
            (store.rollup_bytes
              ? ` (rollup ${formatBytes(store.rollup_bytes)})`
              : "")
        );
      }
      systemSensorStorageHintEl.textContent = bits.join(" · ");
    }
    if (!systemSensorStorageBody) return;
    if (!sensors.length) {
      systemSensorStorageBody.innerHTML =
        `<tr><td colspan="8" class="overview-empty">No sensors</td></tr>`;
      return;
    }
    const policyOptions = (selected) =>
      policies
        .map((p) => {
          const id = String(p.id || "");
          const label = String(p.label || id);
          const sel = id === selected ? " selected" : "";
          return `<option value="${escapeHtml(id)}"${sel}>${escapeHtml(
            label
          )}</option>`;
        })
        .join("");

    systemSensorStorageBody.innerHTML = "";
    for (const s of sensors) {
      const tr = document.createElement("tr");
      const addr = String(s.address || "");
      const policy = String(s.policy || "none");
      tr.innerHTML =
        `<td>` +
        `<span class="overview-name">${escapeHtml(s.name || addr)}</span>` +
        `<span class="overview-meta">${escapeHtml(addr)}</span>` +
        `</td>` +
        `<td class="num">${escapeHtml(formatCount(s.samples))}</td>` +
        `<td class="num">${escapeHtml(formatBytes(s.bytes_est))}</td>` +
        `<td class="num">${escapeHtml(formatInventoryPct(s.pct))}</td>` +
        `<td>${ageMixHtml(s.age_buckets)}</td>` +
        `<td class="sys-policy-cell"></td>` +
        `<td class="num">${escapeHtml(formatBytes(s.bytes_after_est))}</td>` +
        `<td class="sys-preview-cell"></td>`;
      const cell = tr.querySelector(".sys-policy-cell");
      const select = document.createElement("select");
      select.className = "cat-select sys-compaction-select";
      select.setAttribute("aria-label", `Compaction policy for ${s.name || addr}`);
      select.innerHTML = policyOptions(policy);
      select.addEventListener("click", (ev) => ev.stopPropagation());
      select.addEventListener("change", async () => {
        const next = select.value;
        select.disabled = true;
        try {
          const res = await fetch(
            `/api/devices/${encodeURIComponent(addr)}/compaction`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ policy: next }),
            }
          );
          const body = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(
              typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`
            );
          }
          s.policy = next;
          // Refresh estimates from server.
          loadSystem().catch((err) => console.warn(err));
        } catch (err) {
          console.warn(err);
          select.value = policy;
          if (systemSensorStorageHintEl) {
            systemSensorStorageHintEl.textContent = `Policy update failed: ${err.message}`;
          }
        } finally {
          select.disabled = false;
        }
      });
      cell.appendChild(select);

      const previewCell = tr.querySelector(".sys-preview-cell");
      const previewBtn = document.createElement("button");
      previewBtn.type = "button";
      previewBtn.className = "backfill-btn sys-preview-btn";
      previewBtn.textContent = "Preview";
      previewBtn.title = "Dry-run report for every policy (no changes)";
      previewBtn.addEventListener("click", () => {
        loadCompactionPreview(addr, s.name || addr, previewBtn).catch((err) =>
          console.warn(err)
        );
      });
      previewCell.appendChild(previewBtn);
      systemSensorStorageBody.appendChild(tr);
    }
  }

  function formatBucketLabel(secs) {
    const s = Number(secs) || 0;
    if (s >= 86400) return `${Math.round(s / 86400)}d`;
    if (s >= 3600) return `${Math.round(s / 3600)}h`;
    if (s >= 60) return `${Math.round(s / 60)}m`;
    return `${s}s`;
  }

  function renderCompactionPreview(report) {
    if (!systemCompactionPreviewEl) return;
    const cur = report.current || {};
    const policies = Array.isArray(report.policies) ? report.policies : [];
    const rows = policies
      .map((p) => {
        const d = p.details || {};
        let detailHtml = "";
        if (d.kind === "none") {
          detailHtml = `<span class="overview-meta">${escapeHtml(
            d.note || "No changes"
          )}</span>`;
        } else if (d.kind === "tiers") {
          const tiers = Array.isArray(d.tiers) ? d.tiers : [];
          detailHtml =
            `<ul class="sys-preview-tiers">` +
            tiers
              .map((t) => {
                const age =
                  t.younger_than_days == null
                    ? `≥${t.older_than_days}d`
                    : `${t.older_than_days}–${t.younger_than_days}d`;
                return (
                  `<li>` +
                  `<strong>${escapeHtml(age)}</strong> @ ${escapeHtml(
                    formatBucketLabel(t.bucket_secs)
                  )}: ` +
                  `${escapeHtml(formatCount(t.raw_compacted))} → ` +
                  `${escapeHtml(formatCount(t.rollups))} rollup(s)` +
                  (t.raw_kept_incomplete_bucket
                    ? ` · ${escapeHtml(
                        formatCount(t.raw_kept_incomplete_bucket)
                      )} kept (open bucket)`
                    : "") +
                  `</li>`
                );
              })
              .join("") +
            `</ul>`;
        } else if (d.kind === "adaptive") {
          detailHtml =
            `<ul class="sys-preview-tiers">` +
            `<li>Hot window (&lt;${escapeHtml(
              String(d.raw_days)
            )}d): ${escapeHtml(formatCount(d.samples_hot_raw))} raw kept</li>` +
            `<li>Old window: ${escapeHtml(
              formatCount(d.samples_old_window)
            )} samples · ΔT≤${escapeHtml(
              String(d.temp_epsilon_c)
            )} °C</li>` +
            `<li>Stable segments: ${escapeHtml(
              formatCount(d.stable_segments)
            )} ` +
            `(avg ${escapeHtml(String(d.avg_segment_samples))} samples / ` +
            `${escapeHtml(formatBucketLabel(d.avg_segment_span_secs))}, ` +
            `ΔT̄ ${escapeHtml(String(d.avg_segment_delta_t))} °C)</li>` +
            `<li>Rolled: ${escapeHtml(
              formatCount(d.samples_rolled)
            )} · kept volatile: ${escapeHtml(
              formatCount(d.samples_kept_volatile)
            )}</li>` +
            `</ul>`;
        }
        return (
          `<tr>` +
          `<td>${escapeHtml(p.label || p.policy)}</td>` +
          `<td class="num">${escapeHtml(formatCount(p.raw_deleted))}</td>` +
          `<td class="num">${escapeHtml(formatCount(p.rollups))}</td>` +
          `<td class="num">${escapeHtml(formatCount(p.raw_kept))}</td>` +
          `<td class="num">${escapeHtml(formatBytes(p.bytes_after_est))}</td>` +
          `<td class="num">${escapeHtml(formatBytes(p.bytes_saved_est))} ` +
          `(${escapeHtml(formatInventoryPct(p.pct_saved))})</td>` +
          `<td>${detailHtml}</td>` +
          `</tr>`
        );
      })
      .join("");

    systemCompactionPreviewEl.hidden = false;
    systemCompactionPreviewEl.innerHTML =
      `<div class="overview-head overview-head-secondary">` +
      `<h3>Compaction preview — ${escapeHtml(report.name || report.address)}</h3>` +
      `<p class="overview-hint">Dry-run only · current ` +
      `${escapeHtml(formatCount(cur.raw_samples))} raw · ` +
      `${escapeHtml(formatBytes(cur.bytes_est))} · no data written</p>` +
      `<button type="button" class="backfill-btn" id="system-compaction-preview-close">Close</button>` +
      `</div>` +
      `<div class="overview-table-wrap">` +
      `<table class="overview-table system-compaction-preview-table">` +
      `<thead><tr>` +
      `<th>Policy</th>` +
      `<th class="num">Would delete</th>` +
      `<th class="num">Rollups</th>` +
      `<th class="num">Raw kept</th>` +
      `<th class="num">Size after</th>` +
      `<th class="num">Saved</th>` +
      `<th>Details</th>` +
      `</tr></thead>` +
      `<tbody>${rows}</tbody>` +
      `</table></div>`;

    const closeBtn = document.getElementById("system-compaction-preview-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        systemCompactionPreviewEl.hidden = true;
        systemCompactionPreviewEl.innerHTML = "";
      });
    }
  }

  async function loadCompactionPreview(address, name, btn) {
    if (!systemCompactionPreviewEl) return;
    const prev = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "…";
    }
    systemCompactionPreviewEl.hidden = false;
    systemCompactionPreviewEl.innerHTML =
      `<p class="overview-hint">Analyzing policies for ${escapeHtml(
        name || address
      )}… (adaptive may take a few seconds)</p>`;
    try {
      const res = await fetch(
        `/api/devices/${encodeURIComponent(address)}/compaction/preview`
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`
        );
      }
      renderCompactionPreview(body);
    } catch (err) {
      systemCompactionPreviewEl.innerHTML =
        `<p class="overview-hint">Preview failed: ${escapeHtml(err.message)}</p>`;
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = prev || "Preview";
      }
    }
  }

  function populateSystemDevices(devices) {
    if (!systemDeviceEl) return;
    syncSystemSelectionFromDom();
    systemDeviceList = Array.isArray(devices) ? devices : [];
    if (!systemSelectedAddresses.size) {
      let saved = [];
      try {
        saved = JSON.parse(
          localStorage.getItem("govee-charts.systemAddresses") || "[]"
        );
      } catch (_) {
        saved = [];
      }
      if (Array.isArray(saved)) {
        saved.forEach((a) => {
          if (a) systemSelectedAddresses.add(String(a).toUpperCase());
        });
      }
      const legacy = localStorage.getItem("govee-charts.systemAddress") || "";
      if (legacy) systemSelectedAddresses.add(String(legacy).toUpperCase());
    }
    const known = new Set(
      systemDeviceList.map((d) => String(d.address || "").toUpperCase())
    );
    for (const addr of [...systemSelectedAddresses]) {
      if (!known.has(addr)) systemSelectedAddresses.delete(addr);
    }
    if (systemDeviceFilterEl && systemDeviceFilter) {
      systemDeviceFilterEl.value = systemDeviceFilter;
    }
    renderSystemDeviceOptions();
  }

  async function loadSystemDeviceSources() {
    const addresses = selectedSystemAddresses();
    localStorage.setItem(
      "govee-charts.systemAddresses",
      JSON.stringify(addresses)
    );
    if (!addresses.length) {
      destroySystemSourceCharts();
      if (systemDeviceStatusEl) {
        systemDeviceStatusEl.textContent =
          "Select one or more sensors (Ctrl/Cmd-click) — one chart each.";
      }
      return;
    }
    if (systemDeviceStatusEl) systemDeviceStatusEl.textContent = "Loading…";
    const params = new URLSearchParams({
      days: String(systemDays),
      grain: systemGrain,
    });
    addresses.forEach((a) => params.append("address", a));
    const res = await fetch(`/api/system/device-sources?${params}`);
    if (!res.ok) throw new Error(`device-sources HTTP ${res.status}`);
    const data = await res.json();
    if (typeof Chart === "undefined" || !systemSourceChartsEl) {
      if (systemDeviceStatusEl) {
        systemDeviceStatusEl.textContent = "Chart.js unavailable.";
      }
      return;
    }
    const grain = data.grain || systemGrain;
    const buckets = [
      { key: "direct", label: "Direct BLE", color: "#2da44e" },
      { key: "backfill", label: "GATT backfill", color: "#bf8700" },
      { key: "federation", label: "Federation", color: "#1f6feb" },
      { key: "other", label: "Other", color: "#8c959f" },
    ];
    const devices = Array.isArray(data.devices) ? data.devices : [];
    destroySystemSourceCharts();
    let grandTotal = 0;
    devices.forEach((dev) => {
      const series = Array.isArray(dev.series) ? dev.series : [];
      const total = series.reduce(
        (acc, row) =>
          acc +
          (Number(row.direct) || 0) +
          (Number(row.backfill) || 0) +
          (Number(row.federation) || 0) +
          (Number(row.other) || 0),
        0
      );
      grandTotal += total;
      const block = document.createElement("div");
      block.className = "system-source-chart-block";
      const title = document.createElement("h3");
      title.textContent = dev.name || dev.address || "Sensor";
      const meta = document.createElement("p");
      meta.className = "system-chart-meta";
      meta.textContent = `${formatCount(total)} samples · ${dev.address || ""}`;
      const wrap = document.createElement("div");
      wrap.className = "system-chart-wrap system-chart-wrap-tall";
      const canvas = document.createElement("canvas");
      canvas.setAttribute(
        "aria-label",
        `Provenance for ${dev.name || dev.address || "sensor"}`
      );
      wrap.appendChild(canvas);
      block.appendChild(title);
      block.appendChild(meta);
      block.appendChild(wrap);
      systemSourceChartsEl.appendChild(block);

      const chart = makeSystemSourceChart(canvas, grain);
      chart.data.datasets = buckets.map((b) => ({
        label: b.label,
        data: series
          .map((row) => {
            const x = seriesPointTime(row, grain);
            if (!x) return null;
            return { x, y: Number(row[b.key]) || 0 };
          })
          .filter(Boolean),
        backgroundColor: b.color,
        borderColor: b.color,
        stack: "src",
        borderWidth: 0,
      }));
      chart.update();
      systemSourceCharts.push(chart);
    });
    const rangeBit =
      systemDays < 1
        ? `${Math.round(systemDays * 24)}h`
        : systemDays === 1
          ? "24h"
          : `${systemDays}d`;
    if (systemDeviceStatusEl) {
      systemDeviceStatusEl.textContent = `${devices.length} chart${
        devices.length === 1 ? "" : "s"
      } · ${formatCount(grandTotal)} samples total · ${grain} buckets · ${rangeBit}`;
    }
  }

  async function loadSystem() {
    if (systemBusy) return;
    systemBusy = true;
    try {
      if (systemStorageSummaryEl) systemStorageSummaryEl.textContent = "Loading…";
      const res = await fetch("/api/system");
      if (!res.ok) throw new Error(`system HTTP ${res.status}`);
      const data = await res.json();
      renderSystemStorage(data);
      renderSystemInventory(data);
      renderSystemSensorStorage(data);
      populateSystemDevices(data.devices || []);
      syncSystemRangeButtons();
      await loadSystemDeviceSources();
      requestAnimationFrame(() => {
        if (systemStorageChart) systemStorageChart.resize();
        systemSourceCharts.forEach((c) => c.resize());
      });
    } catch (err) {
      console.warn("system:", err);
      if (systemStorageSummaryEl) {
        systemStorageSummaryEl.textContent = `Error: ${err.message}`;
      }
    } finally {
      systemBusy = false;
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
    const loc = I18n.getLocale();
    return [...list].sort((a, b) => {
      const va = sortValue(a, key);
      const vb = sortValue(b, key);
      if (va == null && vb == null) {
        return a.name.localeCompare(b.name, loc);
      }
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "string" && typeof vb === "string") {
        const cmp = va.localeCompare(vb, loc);
        return cmp !== 0 ? cmp * factor : a.name.localeCompare(b.name, loc);
      }
      if (va !== vb) return (va < vb ? -1 : 1) * factor;
      return a.name.localeCompare(b.name, loc);
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
    const before = activeModels.length;
    activeModels = activeModels.filter((m) => models.includes(m));
    if (activeModels.length !== before) persistModelFilter();
    container.innerHTML = "";
    const options = [{ id: "all", label: t("overview.allModels") }].concat(
      models.map((m) => ({ id: m, label: m.toUpperCase() }))
    );
    for (const opt of options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.model = opt.id;
      btn.textContent = opt.label;
      const on =
        opt.id === "all" ? activeModels.length === 0 : activeModels.includes(opt.id);
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.addEventListener("click", () => {
        activeModels = toggleFilterValue(activeModels, opt.id);
        persistModelFilter();
        syncModelFilterButtons();
        fillDeviceList();
        updateOverview();
        updateCurrent();
        if (currentView === "compare") {
          loadHistory().catch((err) => {
            statusEl.textContent = t("compare.error", { error: err.message });
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
      kind === "zone"
        ? t("overview.zone")
        : kind === "height"
          ? t("overview.height")
          : t("overview.room");
    container.innerHTML = "";
    const allowed = new Set((options || []).map((o) => o.id));
    const before = catFilters[kind].length;
    catFilters[kind] = catFilters[kind].filter((id) => allowed.has(id));
    if (catFilters[kind].length !== before) persistCatFilters();
    const items = [{ id: "all", label: t("overview.all") }].concat(options || []);
    for (const opt of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.value = opt.id;
      btn.textContent = opt.label;
      const on =
        opt.id === "all"
          ? catFilters[kind].length === 0
          : catFilters[kind].includes(opt.id);
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.addEventListener("click", () => {
        catFilters[kind] = toggleFilterValue(catFilters[kind], opt.id);
        persistCatFilters();
        renderAllCategoryFilters();
        fillDeviceList();
        updateOverview();
        updateCurrent();
        if (currentView === "compare") {
          loadHistory().catch((err) => {
            statusEl.textContent = t("compare.error", { error: err.message });
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

  async function applyDoorSensorUpdate(sensor, updated) {
    const idx = doorSensors.findIndex((d) => d.sensor_id === sensor.sensor_id);
    if (idx >= 0) {
      doorSensors[idx] = { ...doorSensors[idx], ...updated };
    }
    evaluateDoorBeeps(doorSensors);
    updateDoorsTable();
    if (selectedDoorId === sensor.sensor_id) {
      const next = idx >= 0 ? doorSensors[idx] : { ...sensor, ...updated };
      loadDoorLog(next).catch((err) => console.warn(err));
    }
    updateWindowBanner(null).catch((err) => console.warn(err));
  }

  async function forceDoorState(sensor, state) {
    if (doorsStatus) {
      doorsStatus.hidden = true;
      doorsStatus.textContent = "";
    }
    try {
      const res = await fetch(
        `/api/doors/${encodeURIComponent(sensor.sensor_id)}/force`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ state }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      await applyDoorSensorUpdate(sensor, await res.json());
    } catch (err) {
      if (doorsStatus) {
        doorsStatus.hidden = false;
        doorsStatus.textContent = t("overview.doorLockFailed", {
          error: err.message,
        });
      }
    }
  }

  async function unlockDoorState(sensor) {
    if (doorsStatus) {
      doorsStatus.hidden = true;
      doorsStatus.textContent = "";
    }
    try {
      const res = await fetch(
        `/api/doors/${encodeURIComponent(sensor.sensor_id)}/unlock`,
        { method: "POST" }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      await applyDoorSensorUpdate(sensor, await res.json());
    } catch (err) {
      if (doorsStatus) {
        doorsStatus.hidden = false;
        doorsStatus.textContent = t("overview.doorLockFailed", {
          error: err.message,
        });
      }
    }
  }

  function makeDoorStateCell(sensor) {
    const wrap = document.createElement("div");
    wrap.className = "door-state-cell";
    const st = sensor.state || "—";
    const label = document.createElement("span");
    label.className = `door-state door-state-${st}`;
    label.textContent = st;
    wrap.appendChild(label);

    if (sensor.forced) {
      const badge = document.createElement("span");
      badge.className = "door-forced-badge";
      badge.textContent = t("overview.doorLocked");
      label.appendChild(document.createTextNode(" "));
      label.appendChild(badge);

      const live = String(sensor.reported_state || "").toLowerCase();
      if (live === "open" || live === "closed") {
        const liveEl = document.createElement("span");
        if (live !== st) {
          liveEl.className = "door-mqtt-mismatch";
          liveEl.textContent = t("overview.doorMqttMismatch", { state: live });
          liveEl.title = t("overview.doorMqttMismatchTitle");
          wrap.classList.add("has-mqtt-mismatch");
        } else {
          liveEl.className = "door-live-hint";
          liveEl.textContent = t("overview.doorLiveState", { state: live });
        }
        wrap.appendChild(liveEl);
      }
    }

    const actions = document.createElement("div");
    actions.className = "door-force-actions";
    actions.title = t("overview.doorLockTitle");

    const lockBtn = document.createElement("button");
    lockBtn.type = "button";
    lockBtn.className = "door-force-btn door-lock-btn";
    if (sensor.forced) {
      lockBtn.classList.add("is-active");
      lockBtn.textContent = t("overview.doorUnlock");
      lockBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        unlockDoorState(sensor).catch((err) => console.warn(err));
      });
    } else {
      lockBtn.textContent = t("overview.doorLock");
      lockBtn.disabled = st !== "open" && st !== "closed";
      lockBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (st !== "open" && st !== "closed") return;
        forceDoorState(sensor, st).catch((err) => console.warn(err));
      });
    }
    actions.appendChild(lockBtn);

    for (const [value, key] of [
      ["open", "overview.doorForceOpen"],
      ["closed", "overview.doorForceClosed"],
    ]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "door-force-btn";
      if (sensor.forced && sensor.state === value) {
        btn.classList.add("is-active");
      }
      btn.textContent = t(key);
      btn.title = t("overview.doorForceSetTitle");
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        forceDoorState(sensor, value).catch((err) => console.warn(err));
      });
      actions.appendChild(btn);
    }
    wrap.appendChild(actions);
    return wrap;
  }

  function updateDoorsTable() {
    if (!doorsBody) return;
    doorsBody.innerHTML = "";
    if (!doorSensors.length) {
      doorsBody.innerHTML = `<tr><td colspan="5" class="overview-empty">${escapeHtml(
        t("overview.noDoorsYet")
      )}</td></tr>`;
      if (doorsStatus) {
        doorsStatus.hidden = false;
        doorsStatus.textContent = t("overview.waitingDoors");
      }
      if (doorLogEl) doorLogEl.hidden = true;
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
      if (selectedDoorId && sensor.sensor_id === selectedDoorId) {
        tr.classList.add("is-selected");
      }
      const nameTd = document.createElement("td");
      const nameBtn = document.createElement("button");
      nameBtn.type = "button";
      nameBtn.className = "door-sensor-link";
      if (selectedDoorId && sensor.sensor_id === selectedDoorId) {
        nameBtn.classList.add("is-active");
      }
      nameBtn.innerHTML = `
        <span class="overview-name">${escapeHtml(sensor.name || sensor.sensor_id)}</span>
        <span class="overview-meta">${escapeHtml(sensor.sensor_id)}</span>
      `;
      nameBtn.addEventListener("click", () => {
        loadDoorLog(sensor).catch((err) => console.warn(err));
      });
      nameTd.appendChild(nameBtn);

      const stateTd = document.createElement("td");
      stateTd.appendChild(makeDoorStateCell(sensor));

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

  function hideDoorLog() {
    selectedDoorId = null;
    if (doorLogEl) doorLogEl.hidden = true;
    if (doorLogBodyEl) {
      doorLogBodyEl.innerHTML =
        `<tr><td colspan="3" class="overview-empty">${escapeHtml(
          t("overview.selectContact")
        )}</td></tr>`;
    }
    updateDoorsTable();
  }

  async function loadDoorLog(sensor, hours = 168) {
    if (!doorLogEl || !doorLogBodyEl) return;
    selectedDoorId = sensor.sensor_id;
    updateDoorsTable();
    doorLogEl.hidden = false;
    if (doorLogTitleEl) {
      doorLogTitleEl.textContent = t("overview.doorLogNamed", {
        name: sensor.name || sensor.sensor_id,
      });
    }
    if (doorLogHintEl) {
      doorLogHintEl.textContent =
        hours >= 24
          ? t("overview.doorLogLastDays", { n: hours / 24 })
          : t("overview.doorLogLastHours", { n: hours });
    }
    doorLogBodyEl.innerHTML =
      `<tr><td colspan="3" class="overview-empty">${escapeHtml(
        t("overview.loading")
      )}</td></tr>`;
    try {
      const res = await fetch(
        `/api/doors/history?hours=${encodeURIComponent(hours)}` +
          `&sensor_id=${encodeURIComponent(sensor.sensor_id)}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const events = Array.isArray(data.events) ? data.events.slice() : [];
      // Newest first for a log view.
      events.reverse();
      if (!events.length) {
        doorLogBodyEl.innerHTML =
          `<tr><td colspan="3" class="overview-empty">${escapeHtml(
            t("overview.doorLogEmpty")
          )}</td></tr>`;
        return;
      }
      doorLogBodyEl.innerHTML = events
        .map((ev) => {
          const st = String(ev.state || "—");
          return (
            `<tr>` +
            `<td>${escapeHtml(fmtTime(ev.ts))}</td>` +
            `<td><span class="door-state door-state-${escapeHtml(st)}">${escapeHtml(st)}</span></td>` +
            `<td class="overview-meta">${escapeHtml(ev.source || "—")}</td>` +
            `</tr>`
          );
        })
        .join("");
    } catch (err) {
      doorLogBodyEl.innerHTML =
        `<tr><td colspan="3" class="overview-empty">${escapeHtml(
          t("overview.doorLogUnavailable", { error: err.message })
        )}</td></tr>`;
    }
  }

  async function loadDoors() {
    try {
      const res = await fetch("/api/doors");
      if (!res.ok) throw new Error(`doors HTTP ${res.status}`);
      const data = await res.json();
      doorSensors = data.sensors || [];
      evaluateDoorBeeps(doorSensors);
      updateDoorsTable();
    } catch (err) {
      if (doorsBody) {
        doorsBody.innerHTML = `<tr><td colspan="5" class="overview-empty">${escapeHtml(
          t("overview.doorsUnavailable")
        )}</td></tr>`;
      }
      if (doorsStatus) {
        doorsStatus.hidden = false;
        doorsStatus.textContent = t("common.error", { error: err.message });
      }
    }
  }

  function suppressScrollValueChange(el) {
    // Focused <select>/<input type=number> change value on wheel — easy to
    // edit a category by accident while scrolling the overview.
    el.addEventListener(
      "wheel",
      (ev) => {
        if (document.activeElement === el) {
          ev.preventDefault();
          el.blur();
        }
      },
      { passive: false }
    );
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
    suppressScrollValueChange(select);
    select.addEventListener("click", (ev) => ev.stopPropagation());
    select.addEventListener("mousedown", (ev) => ev.stopPropagation());
    select.addEventListener("change", async (ev) => {
      ev.stopPropagation();
      const previous = device[field] || "";
      const value = select.value === "" ? null : select.value;
      if ((value || "") === previous) return;
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
        select.value = previous;
        overviewStatus.textContent = t("overview.catFailed", {
          error: err.message,
        });
      } finally {
        select.disabled = false;
      }
    });
    return select;
  }

  function syncViewUrl(view, mode = "push") {
    const nextPath = viewToPath(view);
    const nowPath = window.location.pathname.replace(/\/+$/, "") || "/";
    const normNext = nextPath.replace(/\/+$/, "") || "/";
    if (nowPath === normNext) return;
    const nextUrl = `${nextPath}${window.location.search || ""}${window.location.hash || ""}`;
    if (mode === "replace") {
      window.history.replaceState({ view }, "", nextUrl);
    } else {
      window.history.pushState({ view }, "", nextUrl);
    }
  }

  function refreshViewsStickyState() {
    if (!viewsNavEl || !topBarEl) return;
    const vh = window.innerHeight || document.documentElement.clientHeight || 0;
    // Fixed alert bar (.top-bar) — sticky nav must stop exactly below it.
    const topBarH = Math.max(0, Math.ceil(topBarEl.getBoundingClientRect().height));
    document.body.style.setProperty("--topbar-offset", `${topBarH}px`);
    const shouldStick = vh >= 760;
    document.body.classList.toggle("sticky-views-enabled", shouldStick);
  }

  if (topBarEl && typeof ResizeObserver !== "undefined") {
    const topBarResizeObs = new ResizeObserver(() => refreshViewsStickyState());
    topBarResizeObs.observe(topBarEl);
  }

  function isDataMegaOpen() {
    return !!(dataMegaEl && dataMegaEl.classList.contains("open"));
  }

  function setDataMegaOpen(open) {
    if (!dataMegaEl || !dataMegaToggle || !dataMegaPanel) return;
    const next = !!open;
    dataMegaEl.classList.toggle("open", next);
    dataMegaToggle.setAttribute("aria-expanded", next ? "true" : "false");
    dataMegaPanel.hidden = !next;
  }

  function syncDataMega(view) {
    if (!dataMegaEl) return;
    const inData = DATA_VIEWS.has(view);
    dataMegaEl.classList.toggle("active", inData);
    setDataMegaOpen(inData);
  }

  function setView(view, opts = {}) {
    const mode = opts.url || "none";
    view = normalizeView(view);
    currentView = view;
    localStorage.setItem(VIEW_KEY, view);
    if (mode === "push" || mode === "replace") {
      syncViewUrl(view, mode);
    }
    if (viewOverview) viewOverview.hidden = view !== "overview";
    if (viewCompare) viewCompare.hidden = view !== "compare";
    if (viewFacades) viewFacades.hidden = view !== "facades";
    if (viewNetwork) viewNetwork.hidden = view !== "network";
    if (viewCoverage) viewCoverage.hidden = view !== "coverage";
    if (viewBackfill) viewBackfill.hidden = view !== "backfill";
    if (viewSystem) viewSystem.hidden = view !== "system";
    if (viewSettings) viewSettings.hidden = view !== "settings";
    viewButtons.forEach((btn) => {
      const active = btn.dataset.view === view;
      btn.classList.toggle("active", active);
      if (active) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
    syncDataMega(view);
    if (view === "compare" && !historyLoaded) {
      loadHistory().catch((err) => {
        statusEl.textContent = t("compare.error", { error: err.message });
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
    } else if (view === "network") {
      loadNetwork().catch((err) => {
        if (networkStatusEl) {
          networkStatusEl.textContent = `Error: ${err.message}`;
        }
      });
      ensureMapChatStatus().catch((err) => console.warn(err));
    } else if (view === "coverage") {
      loadCoverage()
        .then(() => {
          requestAnimationFrame(() => resizeCoverageCharts());
        })
        .catch((err) => console.warn(err));
    } else if (view === "backfill") {
      loadBackfill().catch((err) => console.warn(err));
    } else if (view === "system") {
      loadSystem().catch((err) => console.warn(err));
    } else if (view === "settings") {
      ensureStationsForSettings().catch((err) => console.warn(err));
    }
    syncBackfillPolling();
  }

  async function loadFacades() {
    if (!facadeBody) return;
    if (facadeStatusEl) facadeStatusEl.textContent = "Loading…";
    await requestBrowserGeo(false);
    const pastH = Math.min(rangeOverlayHours(), 26280);
    const futH = Math.min(Number(forecastFutureHours) || 24, 384);
    const params = new URLSearchParams({
      hours: String(pastH),
      future_hours: String(futH),
    });
    if (browserGeo) {
      params.set("latitude", String(browserGeo.latitude));
      params.set("longitude", String(browserGeo.longitude));
    }
    const res = await fetch(`/api/apartment?${params}`);
    if (!res.ok) throw new Error(`apartment HTTP ${res.status}`);
    const data = await res.json();
    if (data.rooms) apartmentLastRooms = data.rooms;
    renderFacades(data);
  }

  async function loadNetwork() {
    if (!networkSvgEl) return;
    if (networkStatusEl) networkStatusEl.textContent = "Loading…";
    await requestBrowserGeo(false);
    // 24 h window so ΔTmax coupling is meaningful without door contacts.
    const params = new URLSearchParams({ hours: "24" });
    if (browserGeo) {
      params.set("latitude", String(browserGeo.latitude));
      params.set("longitude", String(browserGeo.longitude));
    }
    const res = await fetch(`/api/apartment?${params}`);
    if (!res.ok) throw new Error(`apartment HTTP ${res.status}`);
    const data = await res.json();
    networkLastData = data;
    if (data.rooms) apartmentLastRooms = data.rooms;
    renderNetwork(data);
  }

  function networkMetricField() {
    // Color scale + primary metric: temperature wins in "both".
    return networkMapMetric === "humidity" ? "humidity" : "temperature_c";
  }

  /** Seconds after last reading before a sensor is ignored on the plan / section. */
  const NETWORK_SENSOR_STALE_AFTER_S = 900;

  function networkSensorIsStale(sensor) {
    if (!sensor) return true;
    if (sensor.stale === true) return true;
    if (sensor.stale === false) return false;
    const ts = Number(sensor.last_reading_ts || sensor.last_seen);
    if (!Number.isFinite(ts)) return false;
    const limit = Number(sensor.stale_after_s);
    const after =
      Number.isFinite(limit) && limit > 0 ? limit : NETWORK_SENSOR_STALE_AFTER_S;
    return Date.now() / 1000 - ts > after;
  }

  function networkSensorAgeLabel(sensor) {
    const ts = Number(sensor && (sensor.last_reading_ts || sensor.last_seen));
    if (!Number.isFinite(ts)) return "no update time";
    const age = Math.max(0, Date.now() / 1000 - ts);
    if (age < 90) return `${Math.round(age)}s ago`;
    if (age < 3600) return `${Math.round(age / 60)} min ago`;
    if (age < 86400) return `${(age / 3600).toFixed(1)} h ago`;
    return `${(age / 86400).toFixed(1)} d ago`;
  }

  function networkShowsBothMetrics() {
    return networkMapMetric === "both";
  }

  function networkSensorFieldValue(sensor, field) {
    if (networkSensorIsStale(sensor)) return NaN;
    const v = Number(sensor && sensor[field]);
    return Number.isFinite(v) ? v : NaN;
  }

  function networkSensorMetric(sensor) {
    return networkSensorFieldValue(sensor, networkMetricField());
  }

  function networkMetricUnit() {
    return networkMapMetric === "humidity" ? "%" : "°C";
  }

  function networkMetricUnitShort() {
    return networkMapMetric === "humidity" ? "%" : "°";
  }

  function networkMetricLabel() {
    if (networkMapMetric === "humidity") return "humidity";
    if (networkMapMetric === "both") return "temp + humidity";
    return "temperature";
  }

  function syncNetworkMetricButtons() {
    networkMetricButtons.forEach((btn) => {
      btn.classList.toggle(
        "active",
        btn.dataset.mapMetric === networkMapMetric
      );
    });
  }

  function setNetworkMapMetric(metric) {
    const next =
      metric === "humidity" ? "humidity" : metric === "both" ? "both" : "temp";
    if (next === networkMapMetric) return;
    networkMapMetric = next;
    try {
      localStorage.setItem("govee-charts.mapMetric", networkMapMetric);
    } catch (_) {
      /* ignore */
    }
    syncNetworkMetricButtons();
    // Axis layout changes in "both" — rebuild panel chart on next paint.
    if (mapRoomTempChart) {
      try {
        mapRoomTempChart.destroy();
      } catch {
        /* ignore */
      }
      mapRoomTempChart = null;
    }
    if (networkLastData) renderNetwork(networkLastData);
    if (selectedMapRoomId && mapRoomChartSeriesCache) {
      paintMapRoomChartDatasets(mapRoomChartSeriesCache.series || []);
      const series = mapRoomChartSeriesCache.series || [];
      const totalPts = countMapRoomChartPoints(series);
      if (mapRoomChartsStatusEl) {
        mapRoomChartsStatusEl.textContent = totalPts
          ? `${series.length} series · ${totalPts} point(s) · ${networkMetricLabel()}`
          : `No ${networkMetricLabel()} samples in this range.`;
      }
    }
  }

  function networkExteriorOffset(room, p) {
    const exteriors = room.exterior || [];
    const len = Math.hypot(p.x, p.y) || 1;
    let dx = p.x / len;
    let dy = p.y / len;
    if (exteriors.includes("ne") || exteriors.includes("n") || exteriors.includes("e")) {
      dx = Math.max(0.35, dx);
      dy = Math.min(-0.35, dy);
    } else if (
      exteriors.includes("sw") ||
      exteriors.includes("s") ||
      exteriors.includes("w")
    ) {
      dx = Math.min(-0.35, dx);
      dy = Math.max(0.35, dy);
    }
    // Keep façade nodes close enough to stay inside the padded viewBox.
    return { x: p.x + dx * 0.38, y: p.y + dy * 0.38 };
  }

  /** Stable key for rooms that share the same exterior orientation(s). */
  function networkFacadeKey(room) {
    const orients = [...new Set((room.exterior || []).map((o) => String(o).toLowerCase()))]
      .filter(Boolean)
      .sort();
    return orients.join("+") || "";
  }

  /** High / low exterior sensors for a façade group (all rooms on that face). */
  function networkFacadeTempBands(groupRooms) {
    return networkFacadeFieldBands(groupRooms, networkMetricField());
  }

  /**
   * Append a vertical linearGradient (top=ceiling, bottom=floor) and return its url(#id).
   * ``levels`` is [{offset: "0%"|"50%"|..., temp}] or continuous stop list.
   */
  function appendHeightGradient(defs, NS, gradId, stopsOrLevels, tMin, tMax) {
    const grad = document.createElementNS(NS, "linearGradient");
    grad.setAttribute("id", gradId);
    grad.setAttribute("x1", "0");
    grad.setAttribute("y1", "0");
    grad.setAttribute("x2", "0");
    grad.setAttribute("y2", "1");
    let levels;
    if (Array.isArray(stopsOrLevels)) {
      levels = stopsOrLevels;
    } else {
      const stops = stopsOrLevels;
      levels = [
        { offset: "0%", temp: stops.high },
        { offset: "50%", temp: stops.mid },
        { offset: "100%", temp: stops.low },
      ];
    }
    for (const level of levels) {
      const stop = document.createElementNS(NS, "stop");
      stop.setAttribute("offset", level.offset);
      stop.setAttribute(
        "stop-color",
        networkTempColor(level.temp, tMin, tMax)
      );
      grad.appendChild(stop);
    }
    defs.appendChild(grad);
    return `url(#${gradId})`;
  }

  /** Prefer exact height_cm; else map high/mid/low onto ceiling fractions. */
  function sensorHeightCm(sensor, ceilingCm) {
    const cm = Number(sensor && sensor.height_cm);
    if (Number.isFinite(cm) && cm >= 0) return cm;
    const h = String((sensor && sensor.height) || "").toLowerCase();
    if (h === "high") return ceilingCm * 0.85;
    if (h === "mid") return ceilingCm * 0.5;
    if (h === "low") return ceilingCm * 0.15;
    return null;
  }

  /**
   * Build SVG gradient stops from sensors (offset 0% = ceiling / top).
   * Returns null when no usable heights+temps.
   */
  function networkSensorGradientLevels(sensors, ceilingCm, { exterior = false } = {}) {
    const ceil = Math.max(Number(ceilingCm) || 250, 1);
    /** @type {Map<number, number[]>} */
    const byCm = new Map();
    for (const s of sensors || []) {
      const zone = String(s.zone || "").toLowerCase();
      if (exterior) {
        if (zone !== "exterior") continue;
      } else if (zone === "exterior") {
        continue;
      }
      const cm = sensorHeightCm(s, ceil);
      const t = networkSensorMetric(s);
      if (cm == null || !Number.isFinite(t)) continue;
      const key = Math.round(cm);
      if (!byCm.has(key)) byCm.set(key, []);
      byCm.get(key).push(t);
    }
    if (!byCm.size) return null;
    const points = [...byCm.entries()]
      .map(([cm, temps]) => ({
        cm,
        temp: temps.reduce((a, b) => a + b, 0) / temps.length,
      }))
      .sort((a, b) => b.cm - a.cm); // high first
    // Ensure top (ceiling) and bottom (floor) ends exist for a full band fill.
    const top = points[0];
    const bot = points[points.length - 1];
    if (top.cm < ceil * 0.95) {
      points.unshift({ cm: ceil, temp: top.temp });
    }
    if (bot.cm > ceil * 0.05) {
      points.push({ cm: 0, temp: bot.temp });
    }
    return points.map((p) => {
      const fromTop = Math.min(1, Math.max(0, (ceil - p.cm) / ceil));
      return {
        offset: `${(fromTop * 100).toFixed(1)}%`,
        temp: p.temp,
      };
    });
  }

  /** Preferred relative positions for the default T3 layout (unit circle). */
  const NETWORK_PREF = {
    corridor: [0, 0],
    bedroom: [0.12, -0.68],
    bathroom: [0.68, -0.38],
    living: [-0.5, 0.48],
    kitchen: [-0.72, -0.02],
    wc: [0.05, 0.72],
  };

  function networkLayout(rooms, edges) {
    const ids = rooms.map((r) => r.id);
    const degree = Object.fromEntries(ids.map((id) => [id, 0]));
    for (const e of edges) {
      if (degree[e.a] != null) degree[e.a] += 1;
      if (degree[e.b] != null) degree[e.b] += 1;
    }
    const hub =
      ids.find((id) => id === "corridor") ||
      ids.slice().sort((a, b) => degree[b] - degree[a])[0];
    const pos = {};
    const known = ids.filter((id) => NETWORK_PREF[id]);
    const unknown = ids.filter((id) => !NETWORK_PREF[id]);
    if (known.length >= Math.min(3, ids.length)) {
      for (const id of known) {
        const [x, y] = NETWORK_PREF[id];
        pos[id] = { x, y };
      }
      unknown.forEach((id, i) => {
        const ang = (-Math.PI / 2) + ((i + 1) * (2 * Math.PI)) / (unknown.length + 1);
        pos[id] = { x: Math.cos(ang) * 0.9, y: Math.sin(ang) * 0.9 };
      });
    } else {
      if (hub) pos[hub] = { x: 0, y: 0 };
      const others = ids.filter((id) => id !== hub);
      others.forEach((id, i) => {
        const ang = (-Math.PI / 2) + (i * 2 * Math.PI) / Math.max(others.length, 1);
        pos[id] = { x: Math.cos(ang) * 0.85, y: Math.sin(ang) * 0.85 };
      });
    }
    return { pos, hub };
  }

  function formatNetworkTemp(temp) {
    if (temp == null || !Number.isFinite(Number(temp))) return "—";
    return `${Number(temp).toFixed(1)}${networkMetricUnit()}`;
  }

  function formatNetworkBandWithUnit(temps, unit) {
    const vals = (temps || [])
      .map((t) => Number(t))
      .filter((t) => Number.isFinite(t));
    if (!vals.length) return null;
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    if (Math.abs(hi - lo) < 0.05) return `${lo.toFixed(1)}${unit}`;
    return `${lo.toFixed(1)}–${hi.toFixed(1)}${unit}`;
  }

  function formatNetworkTempBand(temps) {
    return formatNetworkBandWithUnit(temps, networkMetricUnit());
  }

  function formatNetworkBothBand(tempVals, humVals) {
    const t = formatNetworkBandWithUnit(tempVals, "°C");
    const h = formatNetworkBandWithUnit(humVals, "%");
    if (t && h) return `${t} · ${h}`;
    return t || h;
  }

  function formatNetworkSensorReading(sensor) {
    if (networkSensorIsStale(sensor)) {
      return `stale (${networkSensorAgeLabel(sensor)})`;
    }
    const t = networkSensorFieldValue(sensor, "temperature_c");
    const h = networkSensorFieldValue(sensor, "humidity");
    if (networkShowsBothMetrics()) {
      const parts = [];
      if (Number.isFinite(t)) parts.push(`${t.toFixed(1)}°`);
      if (Number.isFinite(h)) parts.push(`${Math.round(h)}%`);
      return parts.join(" · ") || "—";
    }
    if (networkMapMetric === "humidity") {
      return Number.isFinite(h) ? `${h.toFixed(1)}%` : "—";
    }
    return Number.isFinite(t) ? `${t.toFixed(1)}°C` : "—";
  }

  /** Warning triangle for stale sensors on the open-room cross-section. */
  function appendSectionStaleSensorIcon(parent, NS, cx, cy, sensor) {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "section-sensor-stale");
    g.setAttribute("pointer-events", "none");
    const tri = document.createElementNS(NS, "path");
    tri.setAttribute(
      "d",
      `M ${cx} ${cy - 8} L ${cx + 8} ${cy + 7} L ${cx - 8} ${cy + 7} Z`
    );
    tri.setAttribute("fill", "#c4782a");
    tri.setAttribute("stroke", "#fff");
    tri.setAttribute("stroke-width", "1.25");
    tri.setAttribute("stroke-linejoin", "round");
    g.appendChild(tri);
    const bang = document.createElementNS(NS, "text");
    bang.setAttribute("x", String(cx));
    bang.setAttribute("y", String(cy + 5));
    bang.setAttribute("text-anchor", "middle");
    bang.setAttribute("class", "section-sensor-stale-mark");
    bang.textContent = "!";
    g.appendChild(bang);
    const tip = document.createElementNS(NS, "title");
    const cm =
      sensor &&
      sensor.height_cm != null &&
      Number.isFinite(Number(sensor.height_cm))
        ? ` @ ${Math.round(Number(sensor.height_cm))} cm`
        : "";
    tip.textContent = `${(sensor && sensor.name) || "Sensor"}${cm}: ${formatNetworkSensorReading(
      sensor
    )}`;
    g.appendChild(tip);
    parent.appendChild(g);

    const lab = document.createElementNS(NS, "text");
    lab.setAttribute("x", String(cx + 10));
    lab.setAttribute("y", String(cy + 4));
    lab.setAttribute("class", "section-sensor-label section-sensor-stale-label");
    lab.textContent = "stale";
    parent.appendChild(lab);
  }

  /** Split sensors by height for a given metric field. */
  function networkInteriorFieldBands(room, field) {
    const high = [];
    const low = [];
    const mid = [];
    const other = [];
    for (const s of room.sensors || []) {
      if (String(s.zone || "").toLowerCase() === "exterior") continue;
      const t = networkSensorFieldValue(s, field);
      if (!Number.isFinite(t)) continue;
      const h = String(s.height || "").toLowerCase();
      if (h === "high") high.push(t);
      else if (h === "low") low.push(t);
      else if (h === "mid") mid.push(t);
      else other.push(t);
    }
    return { high, mid, low, other };
  }

  /** Split interior sensors by height for map pill layout (active metric). */
  function networkInteriorTempBands(room) {
    return networkInteriorFieldBands(room, networkMetricField());
  }

  function networkFacadeFieldBands(groupRooms, field) {
    const high = [];
    const low = [];
    const mid = [];
    const other = [];
    for (const room of groupRooms) {
      for (const s of room.sensors || []) {
        if (String(s.zone || "").toLowerCase() !== "exterior") continue;
        const t = networkSensorFieldValue(s, field);
        if (!Number.isFinite(t)) continue;
        const h = String(s.height || "").toLowerCase();
        if (h === "high") high.push(t);
        else if (h === "low") low.push(t);
        else if (h === "mid") mid.push(t);
        else other.push(t);
      }
    }
    return { high, mid, low, other };
  }

  function networkAvgTemp(temps) {
    const vals = (temps || [])
      .map((t) => Number(t))
      .filter((t) => Number.isFinite(t));
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }

  /** Global min/max across sensors for the shared color scale. */
  function networkTempScale(rooms) {
    let tMin = Infinity;
    let tMax = -Infinity;
    for (const room of rooms) {
      for (const s of room.sensors || []) {
        const t = networkSensorMetric(s);
        if (!Number.isFinite(t)) continue;
        if (t < tMin) tMin = t;
        if (t > tMax) tMax = t;
      }
    }
    if (!Number.isFinite(tMin) || !Number.isFinite(tMax)) {
      return networkMapMetric === "humidity"
        ? { tMin: 30, tMax: 70 }
        : { tMin: 18, tMax: 28 };
    }
    const minSpan = networkMapMetric === "humidity" ? 5.0 : 1.0;
    if (tMax - tMin < minSpan) {
      const mid = (tMin + tMax) / 2;
      tMin = mid - minSpan / 2;
      tMax = mid + minSpan / 2;
    }
    return { tMin, tMax };
  }

  /** Map temperature onto cool→warm palette (#2b7bbf → #c4782a → #c45c4a). */
  function networkTempColor(temp, tMin, tMax) {
    const t = Number(temp);
    if (!Number.isFinite(t)) return "#6a756e";
    const span = Math.max(tMax - tMin, 0.01);
    const u = Math.min(1, Math.max(0, (t - tMin) / span));
    const stops = [
      { u: 0, r: 0x2b, g: 0x7b, b: 0xbf },
      { u: 0.5, r: 0xc4, g: 0x78, b: 0x2a },
      { u: 1, r: 0xc4, g: 0x5c, b: 0x4a },
    ];
    let a = stops[0];
    let b = stops[stops.length - 1];
    for (let i = 0; i < stops.length - 1; i += 1) {
      if (u >= stops[i].u && u <= stops[i + 1].u) {
        a = stops[i];
        b = stops[i + 1];
        break;
      }
    }
    const local = (u - a.u) / Math.max(b.u - a.u, 1e-6);
    const r = Math.round(a.r + (b.r - a.r) * local);
    const g = Math.round(a.g + (b.g - a.g) * local);
    const bl = Math.round(a.b + (b.b - a.b) * local);
    return `#${[r, g, bl]
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("")}`;
  }

  /**
   * Resolve high / mid / low representative temps for a vertical gradient.
   * Missing mid is interpolated from high+low when both exist.
   */
  function networkHeightStops(bands) {
    const high = networkAvgTemp(bands.high);
    const low = networkAvgTemp(bands.low);
    let mid = networkAvgTemp(bands.mid);
    const other = networkAvgTemp(bands.other);
    if (mid == null && high != null && low != null) {
      mid = (high + low) / 2;
    }
    if (high == null && low == null && mid == null && other != null) {
      return { high: other, mid: other, low: other };
    }
    if (high == null && mid == null && low != null) {
      return { high: low, mid: low, low };
    }
    if (low == null && mid == null && high != null) {
      return { high, mid: high, low: high };
    }
    if (high == null && low == null && mid != null) {
      return { high: mid, mid, low: mid };
    }
    return {
      high: high != null ? high : mid != null ? mid : low,
      mid: mid != null ? mid : high != null && low != null ? (high + low) / 2 : high ?? low,
      low: low != null ? low : mid != null ? mid : high,
    };
  }

  function networkHottestRoomIds(rooms) {
    if (networkMapMetric === "humidity") {
      let best = -Infinity;
      /** @type {Map<string, number>} */
      const avgs = new Map();
      for (const room of rooms) {
        const vals = [];
        for (const s of room.sensors || []) {
          if (String(s.zone || "").toLowerCase() === "exterior") continue;
          const v = networkSensorMetric(s);
          if (Number.isFinite(v)) vals.push(v);
        }
        if (!vals.length) continue;
        const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
        avgs.set(room.id, avg);
        if (avg > best) best = avg;
      }
      if (!Number.isFinite(best)) return new Set();
      const ids = new Set();
      for (const [id, avg] of avgs) {
        if (Math.abs(avg - best) < 0.05) ids.add(id);
      }
      return ids;
    }
    let best = -Infinity;
    for (const room of rooms) {
      const t =
        room.temp_c != null
          ? Number(room.temp_c)
          : room.temp_max != null
            ? Number(room.temp_max)
            : NaN;
      if (Number.isFinite(t) && t > best) best = t;
    }
    if (!Number.isFinite(best)) return new Set();
    const ids = new Set();
    for (const room of rooms) {
      const t =
        room.temp_c != null
          ? Number(room.temp_c)
          : room.temp_max != null
            ? Number(room.temp_max)
            : NaN;
      if (Number.isFinite(t) && Math.abs(t - best) < 0.05) {
        ids.add(room.id);
      }
    }
    return ids;
  }

  function clampNetworkPan() {
    const vw = NETWORK_VB_W / networkZoom;
    const vh = NETWORK_VB_H / networkZoom;
    const maxX = Math.max(0, NETWORK_VB_W - vw);
    const maxY = Math.max(0, NETWORK_VB_H - vh);
    networkPan.x = Math.min(maxX, Math.max(0, networkPan.x));
    networkPan.y = Math.min(maxY, Math.max(0, networkPan.y));
  }

  function centerNetworkPan() {
    const vw = NETWORK_VB_W / networkZoom;
    const vh = NETWORK_VB_H / networkZoom;
    networkPan.x = Math.max(0, (NETWORK_VB_W - vw) / 2);
    networkPan.y = Math.max(0, (NETWORK_VB_H - vh) / 2);
    clampNetworkPan();
  }

  function applyNetworkViewBox() {
    if (!networkSvgEl) return;
    clampNetworkPan();
    const vw = NETWORK_VB_W / networkZoom;
    const vh = NETWORK_VB_H / networkZoom;
    networkSvgEl.setAttribute(
      "viewBox",
      `${networkPan.x} ${networkPan.y} ${vw} ${vh}`
    );
    networkSvgEl.setAttribute("preserveAspectRatio", "xMidYMid meet");
    if (networkZoomResetBtn) {
      networkZoomResetBtn.textContent = `${Math.round(networkZoom * 100)}%`;
    }
  }

  function setNetworkZoom(next, anchorClientX, anchorClientY) {
    const prev = networkZoom;
    networkZoom = Math.min(
      NETWORK_ZOOM_MAX,
      Math.max(NETWORK_ZOOM_MIN, next)
    );
    if (networkZoom === prev) {
      applyNetworkViewBox();
      return;
    }
    // Keep the point under the cursor (or canvas center) stable.
    const rect = networkCanvasWrapEl
      ? networkCanvasWrapEl.getBoundingClientRect()
      : null;
    const ax =
      anchorClientX != null && rect
        ? (anchorClientX - rect.left) / Math.max(rect.width, 1)
        : 0.5;
    const ay =
      anchorClientY != null && rect
        ? (anchorClientY - rect.top) / Math.max(rect.height, 1)
        : 0.5;
    const prevW = NETWORK_VB_W / prev;
    const prevH = NETWORK_VB_H / prev;
    const focusX = networkPan.x + ax * prevW;
    const focusY = networkPan.y + ay * prevH;
    const nextW = NETWORK_VB_W / networkZoom;
    const nextH = NETWORK_VB_H / networkZoom;
    networkPan.x = focusX - ax * nextW;
    networkPan.y = focusY - ay * nextH;
    applyNetworkViewBox();
  }

  /** Walkable links for section path finding (doors + partial walls). */
  function buildNetworkAdj(edges) {
    /** @type {Map<string, Set<string>>} */
    const adj = new Map();
    const link = (a, b) => {
      if (!a || !b || a === b) return;
      if (!adj.has(a)) adj.set(a, new Set());
      if (!adj.has(b)) adj.set(b, new Set());
      adj.get(a).add(b);
      adj.get(b).add(a);
    };
    for (const e of edges || []) {
      const kind = String(e.kind || "door");
      if (kind === "wall") continue;
      link(String(e.a || ""), String(e.b || ""));
    }
    return adj;
  }

  function bfsRoomPath(adj, start, end) {
    const s = String(start || "");
    const t = String(end || "");
    if (!s || !t) return null;
    if (s === t) return [s];
    if (!adj.has(s) || !adj.has(t)) return null;
    const q = [s];
    /** @type {Map<string, string|null>} */
    const prev = new Map([[s, null]]);
    while (q.length) {
      const u = q.shift();
      for (const v of adj.get(u) || []) {
        if (prev.has(v)) continue;
        prev.set(v, u);
        if (v === t) {
          const path = [v];
          let cur = u;
          while (cur != null) {
            path.push(cur);
            cur = prev.get(cur);
          }
          return path.reverse();
        }
        q.push(v);
      }
    }
    return null;
  }

  function stitchRoomPaths(adj, stops) {
    const ids = (stops || []).filter(Boolean);
    if (ids.length < 2) return ids.length ? [ids[0]] : [];
    const out = [];
    for (let i = 0; i < ids.length - 1; i += 1) {
      const seg = bfsRoomPath(adj, ids[i], ids[i + 1]);
      if (!seg || !seg.length) return null;
      if (out.length) out.pop();
      out.push(...seg);
    }
    return out;
  }

  /** Compass score: SW/W/S left (−), NE/E/N right (+). */
  function facadeSideScore(key) {
    const k = String(key || "").toLowerCase();
    let score = 0;
    for (const o of k.split("+")) {
      if (o === "sw" || o === "w" || o === "s" || o === "nw") score -= 1;
      if (o === "ne" || o === "e" || o === "n" || o === "se") score += 1;
    }
    return score;
  }

  function pickFacadeEndpoints(rooms, waypoints) {
    /** @type {Map<string, any[]>} */
    const byKey = new Map();
    for (const room of rooms || []) {
      const key = networkFacadeKey(room);
      if (!key) continue;
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key).push(room);
    }
    const keys = [...byKey.keys()].sort(
      (a, b) => facadeSideScore(a) - facadeSideScore(b) || a.localeCompare(b)
    );
    if (keys.length < 2) return null;
    const leftKey = keys[0];
    const rightKey = keys[keys.length - 1];
    if (leftKey === rightKey) return null;

    const preferLeft = [...waypoints, "kitchen", "living"];
    const preferRight = [...waypoints, "bedroom"];

    const pick = (key, prefers) => {
      const list = byKey.get(key) || [];
      for (const id of prefers) {
        const hit = list.find((r) => r.id === id);
        if (hit) return String(hit.id);
      }
      return list.length ? String(list[0].id) : "";
    };

    const left = pick(leftKey, preferLeft);
    const right = pick(rightKey, preferRight);
    if (!left || !right || left === right) return null;
    return { left, right, leftKey, rightKey };
  }

  function orderWaypointsGreedy(adj, start, end, waypoints) {
    const remaining = new Set(
      (waypoints || []).filter((id) => id && id !== start && id !== end)
    );
    const ordered = [];
    let cur = start;
    while (remaining.size) {
      let best = null;
      let bestLen = Infinity;
      for (const id of remaining) {
        const p = bfsRoomPath(adj, cur, id);
        const len = p ? p.length : Infinity;
        if (len < bestLen) {
          bestLen = len;
          best = id;
        }
      }
      if (!best || !Number.isFinite(bestLen)) break;
      ordered.push(best);
      remaining.delete(best);
      cur = best;
    }
    return ordered;
  }

  /** Rooms smaller than this (m²) are hidden unless "Small rooms" is checked. */
  const SECTION_SMALL_AREA_M2 = 3.5;

  function isSectionSmallRoom(room) {
    const area = Number(room && room.area_m2);
    return Number.isFinite(area) && area > 0 && area < SECTION_SMALL_AREA_M2;
  }

  /**
   * Default façade→façade cut. Preferred order keeps SW rooms, hub, then NE;
   * small rooms (bathroom, WC) slot in when enabled.
   */
  function defaultSectionPathIds(data) {
    const rooms = (data && data.rooms) || [];
    const byId = Object.fromEntries(rooms.map((r) => [r.id, r]));
    const preferred = [
      "kitchen",
      "living",
      "wc",
      "corridor",
      "bathroom",
      "bedroom",
    ];
    const path = preferred.filter((id) => {
      const room = byId[id];
      if (!room) return false;
      if (!sectionShowSmall && isSectionSmallRoom(room)) return false;
      return true;
    });
    // Any other non-small (or all, if enabled) rooms not in the preferred list.
    for (const room of rooms) {
      if (path.includes(room.id)) continue;
      if (!sectionShowSmall && isSectionSmallRoom(room)) continue;
      // Keep extras before the last façade room when possible.
      const last = path[path.length - 1];
      const lastRoom = last ? byId[last] : null;
      const lastIsFacade = !!(lastRoom && (lastRoom.exterior || []).length);
      if (lastIsFacade && path.length >= 2) {
        path.splice(path.length - 1, 0, room.id);
      } else {
        path.push(room.id);
      }
    }
    return path;
  }

  function persistSectionPathState() {
    try {
      localStorage.setItem(
        "govee-charts.sectionShowSmall",
        sectionShowSmall ? "1" : "0"
      );
      localStorage.setItem(
        "govee-charts.sectionWaypoints",
        JSON.stringify(sectionWaypoints)
      );
    } catch (_) {
      /* ignore */
    }
  }

  function syncSectionPathControls() {
    if (sectionShowSmallEl) {
      sectionShowSmallEl.checked = !!sectionShowSmall;
    }
    const custom = sectionWaypoints.length > 0;
    if (sectionPathClearBtn) {
      sectionPathClearBtn.disabled = !custom;
      sectionPathClearBtn.classList.toggle("active", custom);
    }
  }

  /**
   * Room sequence for the open-room cross-section.
   * Default: all façade→façade rooms (small rooms optional).
   * Shift-click waypoints override via graph stitching.
   */
  function sectionPathIds(data) {
    const preset = defaultSectionPathIds(data);
    if (!data || !data.enabled) return preset;
    const rooms = data.rooms || [];
    const byId = Object.fromEntries(rooms.map((r) => [r.id, r]));
    const adj = buildNetworkAdj(data.edges || []);
    if (!sectionWaypoints.length) {
      return preset.filter((id) => byId[id]);
    }
    const waypoints = sectionWaypoints.filter((id) => byId[id]);
    const ends = pickFacadeEndpoints(rooms, waypoints);
    let stops;
    if (ends) {
      const mid = orderWaypointsGreedy(adj, ends.left, ends.right, waypoints);
      stops = [ends.left, ...mid, ends.right];
    } else if (waypoints.length >= 2) {
      stops = [...waypoints];
    } else {
      return preset.filter((id) => byId[id]);
    }
    // Drop consecutive duplicates in stop list.
    stops = stops.filter((id, i) => i === 0 || id !== stops[i - 1]);
    const path = stitchRoomPaths(adj, stops);
    if (!path || path.length < 2) {
      return preset.filter((id) => byId[id]);
    }
    const waypointSet = new Set(waypoints);
    return path.filter((id, i) => {
      if (i > 0 && id === path[i - 1]) return false;
      const room = byId[id];
      if (
        !sectionShowSmall &&
        room &&
        isSectionSmallRoom(room) &&
        !waypointSet.has(id)
      ) {
        return false;
      }
      return true;
    });
  }

  function setSectionShowSmall(on) {
    sectionShowSmall = !!on;
    persistSectionPathState();
    syncSectionPathControls();
    if (networkLastData) renderNetwork(networkLastData);
  }

  function clearSectionWaypoints() {
    if (!sectionWaypoints.length) return;
    sectionWaypoints = [];
    persistSectionPathState();
    syncSectionPathControls();
    if (networkLastData) renderNetwork(networkLastData);
  }

  function destroySectionRoomChart() {
    if (sectionRoomChart) {
      try {
        sectionRoomChart.destroy();
      } catch {
        /* ignore */
      }
      sectionRoomChart = null;
    }
    sectionRoomChartCanvas = null;
  }

  function clearMapRoomSelection() {
    selectedMapRoomId = null;
    mapRoomChartSeriesCache = null;
    if (mapRoomChartsEl) mapRoomChartsEl.hidden = true;
    if (mapRoomChartsStatusEl) mapRoomChartsStatusEl.textContent = "";
    if (mapRoomChartsMetaEl) mapRoomChartsMetaEl.textContent = "";
    if (mapRoomTempChart) {
      try {
        mapRoomTempChart.destroy();
      } catch {
        /* ignore */
      }
      mapRoomTempChart = null;
    }
    destroySectionRoomChart();
    if (networkLastData) renderNetwork(networkLastData);
  }

  function selectMapRoom(roomId) {
    const id = String(roomId || "");
    if (!id) return;
    if (selectedMapRoomId === id) {
      clearMapRoomSelection();
      return;
    }
    selectedMapRoomId = id;
    mapRoomChartSeriesCache = null;
    if (networkLastData) renderNetwork(networkLastData);
    loadMapRoomCharts().catch((err) => {
      if (mapRoomChartsStatusEl) {
        mapRoomChartsStatusEl.textContent = `Error: ${err.message}`;
      }
    });
  }

  function mapRoomChartOptions(compact) {
    const opts = structuredClone(chartDefaults);
    if (opts.plugins && opts.plugins.zoom) delete opts.plugins.zoom;
    if (opts.plugins && opts.plugins.legend) {
      opts.plugins.legend.display = true;
      opts.plugins.legend.position = "bottom";
      if (compact) {
        opts.plugins.legend.labels = {
          boxWidth: 8,
          boxHeight: 8,
          font: { size: 9 },
          color: "rgba(255,255,255,0.92)",
          padding: 4,
        };
      }
    }
    if (compact) {
      opts.maintainAspectRatio = false;
      opts.layout = { padding: { top: 4, right: 4, bottom: 0, left: 2 } };
      if (opts.scales) {
        for (const axis of Object.values(opts.scales)) {
          if (!axis || typeof axis !== "object") continue;
          if (!axis.ticks) axis.ticks = {};
          axis.ticks.maxTicksLimit = 4;
          axis.ticks.font = { size: 9 };
          axis.ticks.color = "rgba(255,255,255,0.75)";
          if (axis.grid) {
            axis.grid.color = "rgba(255,255,255,0.12)";
          }
        }
      }
    }
    return opts;
  }

  function ensureMapRoomTempChart() {
    if (mapRoomTempChart || !mapRoomTempCanvas || typeof Chart === "undefined") {
      return mapRoomTempChart;
    }
    mapRoomTempChart = new Chart(mapRoomTempCanvas.getContext("2d"), {
      type: "line",
      data: { datasets: [] },
      options: mapRoomChartOptions(false),
    });
    return mapRoomTempChart;
  }

  function ensureSectionRoomChart() {
    if (sectionRoomChart || !sectionRoomChartCanvas || typeof Chart === "undefined") {
      return sectionRoomChart;
    }
    sectionRoomChart = new Chart(sectionRoomChartCanvas.getContext("2d"), {
      type: "line",
      data: { datasets: [] },
      options: mapRoomChartOptions(true),
    });
    return sectionRoomChart;
  }

  function syncMapRoomChartLabels() {
    if (mapRoomChartCaptionEl) {
      if (networkMapMetric === "humidity") {
        mapRoomChartCaptionEl.textContent = "Humidity (detail)";
      } else if (networkMapMetric === "both") {
        mapRoomChartCaptionEl.textContent = "Temperature + humidity (detail)";
      } else {
        mapRoomChartCaptionEl.textContent = "Temperature (detail)";
      }
    }
    if (mapRoomChartsCloseBtn) {
      mapRoomChartsCloseBtn.title =
        networkMapMetric === "humidity"
          ? "Close humidity charts"
          : networkMapMetric === "both"
            ? "Close temperature and humidity charts"
            : "Close temperature charts";
    }
  }

  function mapRoomPointSeries(points, field) {
    return (points || [])
      .filter(
        (p) =>
          p &&
          p.ts != null &&
          p[field] != null &&
          Number.isFinite(Number(p[field]))
      )
      .map((p) => ({ x: p.ts * 1000, y: Number(p[field]) }));
  }

  function countMapRoomChartPoints(series) {
    if (networkShowsBothMetrics()) {
      return series.reduce((n, s) => {
        const pts = s.points || [];
        return (
          n +
          pts.filter(
            (p) => p.temperature_c != null && Number.isFinite(Number(p.temperature_c))
          ).length +
          pts.filter(
            (p) => p.humidity != null && Number.isFinite(Number(p.humidity))
          ).length
        );
      }, 0);
    }
    const field = networkMetricField();
    return series.reduce(
      (n, s) =>
        n +
        (s.points || []).filter(
          (p) => p[field] != null && Number.isFinite(Number(p[field]))
        ).length,
      0
    );
  }

  function configureMapRoomChartAxes(chart, compact) {
    if (!chart || !chart.options) return;
    if (!chart.options.scales) chart.options.scales = {};
    const tickBase = compact
      ? {
          maxTicksLimit: 4,
          font: { size: 9 },
          color: "rgba(255,255,255,0.75)",
        }
      : { color: "#8a9a88" };
    const gridColor = compact
      ? "rgba(255,255,255,0.12)"
      : "rgba(42,53,44,0.7)";
    if (networkShowsBothMetrics()) {
      chart.options.scales.y = {
        type: "linear",
        position: "left",
        title: compact
          ? undefined
          : { display: true, text: "°C", color: "#c4782a" },
        ticks: { ...tickBase, color: compact ? tickBase.color : "#c4782a" },
        grid: { color: gridColor },
      };
      chart.options.scales.y1 = {
        type: "linear",
        position: "right",
        title: compact
          ? undefined
          : { display: true, text: "% RH", color: "#5b8fd9" },
        ticks: { ...tickBase, color: compact ? "rgba(180,210,255,0.85)" : "#5b8fd9" },
        grid: { drawOnChartArea: false },
      };
    } else {
      delete chart.options.scales.y1;
      chart.options.scales.y = {
        ticks: tickBase,
        grid: { color: gridColor },
      };
    }
  }

  function paintMapRoomChartDatasets(series) {
    const multi = series.length > 1;
    const build = () => {
      if (!networkShowsBothMetrics()) {
        const field = networkMetricField();
        return series.map((s) =>
          makeDataset(
            s.label,
            s.color,
            mapRoomPointSeries(s.points, field),
            !multi
          )
        );
      }
      const out = [];
      for (const s of series) {
        out.push(
          makeDataset(
            `${s.label} °C`,
            s.color,
            mapRoomPointSeries(s.points, "temperature_c"),
            false,
            { yAxisID: "y" }
          )
        );
        out.push(
          makeDataset(
            `${s.label} RH`,
            s.color,
            mapRoomPointSeries(s.points, "humidity"),
            false,
            {
              yAxisID: "y1",
              borderDash: [5, 3],
              borderWidth: 1.5,
            }
          )
        );
      }
      return out;
    };
    syncMapRoomChartLabels();
    const panelChart = ensureMapRoomTempChart();
    if (panelChart) {
      configureMapRoomChartAxes(panelChart, false);
      panelChart.data.datasets = build();
      panelChart.update();
    }
    const sectionChart = ensureSectionRoomChart();
    if (sectionChart) {
      configureMapRoomChartAxes(sectionChart, true);
      sectionChart.data.datasets = build();
      sectionChart.update();
    }
  }

  function resolveMapChartTarget() {
    const id = String(selectedMapRoomId || "");
    if (!id || !networkLastData) return null;
    const rooms = networkLastData.rooms || [];
    const room = rooms.find((r) => String(r.id) === id);
    if (room) {
      return {
        kind: "room",
        id: String(room.id),
        label: room.label || room.id,
        sensors: (room.sensors || []).filter(
          (s) => String(s.zone || "").toLowerCase() !== "exterior"
        ),
        sensorKind: "indoor",
      };
    }
    const byId = Object.fromEntries(rooms.map((r) => [r.id, r]));
    const path = sectionPathIds(networkLastData).filter((rid) => byId[rid]);
    if (path.length < 2) return null;
    const columns = buildSectionColumns(path, rooms, byId);
    const col = columns.find(
      (c) => c.kind === "facade" && String(c.id) === id
    );
    if (!col) return null;
    // Deduplicate exterior sensors shared across rooms on the same face.
    const seen = new Set();
    const sensors = [];
    for (const s of col.sensors || []) {
      const address = String(s.address || "").toUpperCase();
      const key = address || `${s.name || ""}|${s.height_cm || s.height || ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      sensors.push(s);
    }
    const orient = col.label || "EXT";
    return {
      kind: "facade",
      id: String(col.id),
      label: col.sublabel
        ? `Façade ${orient} · ${col.sublabel}`
        : `Façade ${orient}`,
      sensors,
      sensorKind: "exterior",
    };
  }

  async function loadMapRoomCharts() {
    if (!selectedMapRoomId || !mapRoomChartsEl) return;
    const target = resolveMapChartTarget();
    if (!target) {
      clearMapRoomSelection();
      return;
    }
    mapRoomChartsEl.hidden = false;
    if (mapRoomChartsTitleEl) {
      mapRoomChartsTitleEl.textContent = target.label;
    }
    const sensors = target.sensors || [];
    const kindLabel =
      target.sensorKind === "exterior" ? "exterior" : "indoor";
    if (mapRoomChartsMetaEl) {
      mapRoomChartsMetaEl.textContent = sensors.length
        ? `${sensors.length} ${kindLabel} sensor(s) · last ${mapRoomHours} h`
        : `No ${kindLabel} sensors on this ${target.kind === "facade" ? "façade" : "room"}`;
    }
    if (!sensors.length) {
      mapRoomChartSeriesCache = { roomId: target.id, series: [] };
      paintMapRoomChartDatasets([]);
      if (mapRoomChartsStatusEl) {
        mapRoomChartsStatusEl.textContent = `No ${kindLabel} sensors to chart.`;
      }
      return;
    }
    if (mapRoomChartsStatusEl) mapRoomChartsStatusEl.textContent = "Loading…";
    mapRoomChartsBusy = true;
    try {
      const results = await Promise.all(
        sensors.map(async (sensor, idx) => {
          const address = String(sensor.address || "").toUpperCase();
          if (!address) return null;
          const params = new URLSearchParams({
            address,
            hours: String(mapRoomHours),
          });
          const res = await fetch(`/api/history?${params}`);
          if (!res.ok) throw new Error(`history HTTP ${res.status}`);
          const payload = await res.json();
          const height = String(sensor.height || "").trim();
          const cm =
            sensor.height_cm != null && Number.isFinite(Number(sensor.height_cm))
              ? `${Math.round(Number(sensor.height_cm))} cm`
              : "";
          const heightBit = [height, cm].filter(Boolean).join(" · ");
          const name = sensor.name || address;
          return {
            label: heightBit ? `${name} (${heightBit})` : name,
            color: roomColor(`${target.id}-${address}`, idx),
            points: payload.points || [],
          };
        })
      );
      if (String(selectedMapRoomId) !== String(target.id)) return;
      const series = results.filter(Boolean);
      mapRoomChartSeriesCache = { roomId: target.id, series };
      if (typeof Chart === "undefined") {
        if (mapRoomChartsStatusEl) {
          mapRoomChartsStatusEl.textContent = "Chart.js unavailable.";
        }
        return;
      }
      paintMapRoomChartDatasets(series);
      const totalPts = countMapRoomChartPoints(series);
      if (mapRoomChartsStatusEl) {
        mapRoomChartsStatusEl.textContent = totalPts
          ? `${series.length} series · ${totalPts} point(s) · updated ${new Date().toLocaleTimeString("en-GB")}`
          : `No ${networkMetricLabel()} samples in this range.`;
      }
    } finally {
      mapRoomChartsBusy = false;
    }
  }

  function toggleSectionWaypoint(roomId) {
    const id = String(roomId || "");
    if (!id) return;
    const idx = sectionWaypoints.indexOf(id);
    if (idx >= 0) {
      sectionWaypoints = sectionWaypoints.filter((x) => x !== id);
    } else {
      sectionWaypoints = [...sectionWaypoints, id];
    }
    persistSectionPathState();
    syncSectionPathControls();
    if (networkLastData) renderNetwork(networkLastData);
  }

  function edgeOpeningBetween(edges, a, b) {
    for (const e of edges || []) {
      if (
        (e.a === a && e.b === b) ||
        (e.a === b && e.b === a)
      ) {
        return {
          opening: e.opening || "unknown",
          kind: e.kind || "door",
          source: e.opening_source || "",
        };
      }
    }
    return { opening: "unknown", kind: "door", source: "" };
  }

  /**
   * Build cross-section columns: optional left façade · rooms · optional right façade.
   * Shared orientations (e.g. kitchen+living SW) merge exterior sensors into one band.
   */
  function buildSectionColumns(pathIds, rooms, byId) {
    const cols = [];
    const first = byId[pathIds[0]];
    const last = byId[pathIds[pathIds.length - 1]];
    const leftKey = first ? networkFacadeKey(first) : "";
    const rightKey = last ? networkFacadeKey(last) : "";

    function facadeColumn(key, side) {
      const facadeRooms = rooms.filter((r) => networkFacadeKey(r) === key);
      const sensors = facadeRooms.flatMap((r) =>
        (r.sensors || []).filter(
          (s) => String(s.zone || "").toLowerCase() === "exterior"
        )
      );
      const orients = key.split("+").map((o) => o.toUpperCase());
      const roomLabels = facadeRooms
        .map((r) => r.label || r.id)
        .join(" + ");
      // Window state for legend on this façade band (open wins; else closed
      // only if every known contact is closed — null contacts ignored).
      let windowState = "unknown";
      const known = facadeRooms
        .map((r) => r.window_state)
        .filter((s) => s === "open" || s === "closed" || s === "unknown");
      if (known.some((s) => s === "open")) {
        windowState = "open";
      } else if (known.length && known.every((s) => s === "closed")) {
        windowState = "closed";
      } else if (known.some((s) => s === "unknown")) {
        windowState = "unknown";
      }
      return {
        kind: "facade",
        id: `facade-${side}-${key}`,
        label: orients[0] || "EXT",
        sublabel: roomLabels,
        orients,
        sensors,
        weight: 2.5,
        windowState,
        exterior: true,
      };
    }

    if (leftKey) {
      cols.push(facadeColumn(leftKey, "left"));
    }
    for (const id of pathIds) {
      const room = byId[id];
      if (!room) continue;
      cols.push({
        kind: "room",
        id: room.id,
        label: room.label || room.id,
        sublabel: "",
        sensors: (room.sensors || []).filter(
          (s) => String(s.zone || "").toLowerCase() !== "exterior"
        ),
        weight: Math.max(1, Number(room.area_m2) || 1),
        room,
        exterior: false,
      });
    }
    if (rightKey && rightKey !== leftKey) {
      cols.push(facadeColumn(rightKey, "right"));
    }
    return cols;
  }

  /**
   * The map SVGs use a fixed-size viewBox that gets shrunk to fit the
   * container width. On a narrow phone that shrink is much larger than
   * anywhere else in the UI, so in-map text becomes unreadable. Measure
   * the actual rendered-vs-viewBox ratio and expose it as a CSS variable
   * so label font-size rules (see style.css) can compensate and keep a
   * legible on-screen size regardless of device width.
   */
  function applyMapFontScale(svgEl, viewBoxWidth) {
    if (!svgEl || !viewBoxWidth) return;
    const rendered = svgEl.getBoundingClientRect().width;
    if (!rendered) return;
    const rawScale = rendered / viewBoxWidth;
    const compensation = rawScale > 0 ? Math.min(3, Math.max(1, 1 / rawScale)) : 1;
    svgEl.style.setProperty("--map-font-scale", compensation.toFixed(2));
  }

  function renderOpenRoomSection(data) {
    if (!sectionSvgEl) return;
    const NS = "http://www.w3.org/2000/svg";
    destroySectionRoomChart();
    sectionSvgEl.replaceChildren();
    if (!data || !data.enabled) {
      if (sectionTempScaleEl) sectionTempScaleEl.hidden = true;
      if (sectionMetaEl) {
        sectionMetaEl.textContent =
          "Enable [apartment] in config.toml to show the cross-section.";
      }
      return;
    }
    const rooms = data.rooms || [];
    const edges = data.edges || [];
    const byId = Object.fromEntries(rooms.map((r) => [r.id, r]));
    const path = sectionPathIds(data).filter((id) => byId[id]);
    if (path.length < 2) {
      if (sectionTempScaleEl) sectionTempScaleEl.hidden = true;
      if (sectionMetaEl) {
        sectionMetaEl.textContent =
          "Need at least two connected rooms between façades for a cross-section.";
      }
      return;
    }

    const ceilingCm = Math.max(
      50,
      Math.round(Number(data.ceiling_m || 2.5) * 100)
    );
    const columns = buildSectionColumns(path, rooms, byId);
    // Scale across interiors + façades in this cut.
    const scaleRooms = [
      ...path.map((id) => byId[id]),
      ...columns
        .filter((c) => c.kind === "facade")
        .map((c) => ({ sensors: c.sensors })),
    ];
    const { tMin, tMax } = networkTempScale(scaleRooms);
    if (sectionTempScaleEl) {
      sectionTempScaleEl.hidden = false;
      const u = networkMetricUnitShort();
      if (sectionTempScaleLoEl) {
        sectionTempScaleLoEl.textContent = `${tMin.toFixed(1)}${u}`;
      }
      if (sectionTempScaleHiEl) {
        sectionTempScaleHiEl.textContent = `${tMax.toFixed(1)}${u}`;
      }
    }

    const padL = 52;
    const padR = 18;
    const padT = 28;
    const padB = 48;
    const W = 960;
    const H = 420;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const gap = 12;
    const weightSum = columns.reduce((a, c) => a + c.weight, 0);
    const usable = plotW - gap * Math.max(0, columns.length - 1);
    const widths = columns.map((c) => (c.weight / weightSum) * usable);

    sectionSvgEl.setAttribute("viewBox", `0 0 ${W} ${H}`);
    sectionSvgEl.setAttribute("preserveAspectRatio", "xMidYMid meet");

    const defs = document.createElementNS(NS, "defs");
    sectionSvgEl.appendChild(defs);

    // Height axis
    const axisG = document.createElementNS(NS, "g");
    axisG.setAttribute("class", "section-axis");
    const axisLine = document.createElementNS(NS, "line");
    axisLine.setAttribute("x1", String(padL - 8));
    axisLine.setAttribute("x2", String(padL - 8));
    axisLine.setAttribute("y1", String(padT));
    axisLine.setAttribute("y2", String(padT + plotH));
    axisLine.setAttribute("stroke", "var(--line)");
    axisLine.setAttribute("stroke-width", "1.5");
    axisG.appendChild(axisLine);
    const ticks = [0, 0.25, 0.5, 0.75, 1];
    for (const u of ticks) {
      const cm = Math.round(ceilingCm * (1 - u));
      const y = padT + u * plotH;
      const tick = document.createElementNS(NS, "line");
      tick.setAttribute("x1", String(padL - 12));
      tick.setAttribute("x2", String(padL - 4));
      tick.setAttribute("y1", String(y));
      tick.setAttribute("y2", String(y));
      tick.setAttribute("stroke", "var(--line)");
      axisG.appendChild(tick);
      const lab = document.createElementNS(NS, "text");
      lab.setAttribute("x", String(padL - 16));
      lab.setAttribute("y", String(y + 4));
      lab.setAttribute("class", "section-axis-label");
      lab.textContent = `${cm}`;
      axisG.appendChild(lab);
    }
    const axisTitle = document.createElementNS(NS, "text");
    axisTitle.setAttribute("x", String(padL - 16));
    axisTitle.setAttribute("y", String(padT - 10));
    axisTitle.setAttribute("class", "section-axis-label");
    axisTitle.textContent = "cm";
    axisG.appendChild(axisTitle);
    sectionSvgEl.appendChild(axisG);

    // Floor / ceiling guides
    const guides = document.createElementNS(NS, "g");
    for (const u of [0, 1]) {
      const y = padT + u * plotH;
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", String(padL));
      line.setAttribute("x2", String(W - padR));
      line.setAttribute("y1", String(y));
      line.setAttribute("y2", String(y));
      line.setAttribute("stroke", "var(--line)");
      line.setAttribute("stroke-width", u === 1 ? "2" : "1.25");
      line.setAttribute("opacity", "0.55");
      guides.appendChild(line);
    }
    sectionSvgEl.appendChild(guides);

    let x = padL;
    const linkBits = [];
    for (let i = 0; i < columns.length; i += 1) {
      const col = columns[i];
      const w = widths[i];
      const contLevels = networkSensorGradientLevels(col.sensors, ceilingCm, {
        exterior: !!col.exterior,
      });
      // Fallback categorical bands for rooms without height_cm.
      let fallbackStops = null;
      if (!contLevels && col.kind === "room" && col.room) {
        fallbackStops = networkHeightStops(networkInteriorTempBands(col.room));
      } else if (!contLevels && col.kind === "facade") {
        fallbackStops = networkHeightStops(
          networkFacadeTempBands([{ sensors: col.sensors }])
        );
      }
      const hasTemp = !!(
        contLevels ||
        (fallbackStops &&
          (fallbackStops.high != null ||
            fallbackStops.mid != null ||
            fallbackStops.low != null))
      );
      const gradId = `section-grad-${String(col.id).replace(/[^a-z0-9_-]/gi, "_")}`;
      const fill = hasTemp
        ? appendHeightGradient(
            defs,
            NS,
            gradId,
            contLevels || fallbackStops,
            tMin,
            tMax
          )
        : col.kind === "facade"
          ? "#354860"
          : "#2a3230";

      const isMapSelected =
        String(selectedMapRoomId || "") === String(col.id);
      const roomGroup = document.createElementNS(NS, "g");
      if (col.kind === "room" || col.kind === "facade") {
        roomGroup.setAttribute(
          "class",
          col.kind === "facade" ? "section-room-hit section-facade-hit" : "section-room-hit"
        );
        roomGroup.style.cursor = "pointer";
        roomGroup.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (col.kind === "room" && ev.shiftKey) {
            toggleSectionWaypoint(col.id);
          } else {
            selectMapRoom(col.id);
          }
        });
      }

      const rect = document.createElementNS(NS, "rect");
      rect.setAttribute("x", String(x));
      rect.setAttribute("y", String(padT));
      rect.setAttribute("width", String(w));
      rect.setAttribute("height", String(plotH));
      rect.setAttribute("rx", "8");
      rect.setAttribute("ry", "8");
      let roomClass =
        col.kind === "facade" ? "section-facade" : "section-room";
      if (isMapSelected) roomClass += " is-map-selected";
      rect.setAttribute("class", roomClass);
      rect.setAttribute("fill", fill);
      rect.setAttribute(
        "stroke",
        isMapSelected
          ? "#6fbf73"
          : col.kind === "facade"
            ? "#5b8fd9"
            : "var(--line)"
      );
      rect.setAttribute(
        "stroke-width",
        isMapSelected ? "3" : col.kind === "facade" ? "1.75" : "1.5"
      );
      if (col.kind === "facade" && !isMapSelected) {
        rect.setAttribute("stroke-dasharray", "5 3");
      }
      if (isMapSelected) {
        rect.setAttribute("opacity", "0.42");
      }
      const title = document.createElementNS(NS, "title");
      const sensorBits = (col.sensors || [])
        .map((s) => {
          const cm =
            s.height_cm != null && Number.isFinite(Number(s.height_cm))
              ? `${Math.round(Number(s.height_cm))} cm`
              : String(s.height || "?");
          return `${s.name} @ ${cm}: ${formatNetworkSensorReading(s)}`;
        })
        .join("; ");
      title.textContent =
        (col.kind === "facade"
          ? `Façade ${col.label}${col.sublabel ? ` · ${col.sublabel}` : ""} — click for temperature charts`
          : `${col.label} — click for temperature charts`) +
        (sensorBits
          ? `\n${sensorBits}`
          : col.kind === "facade"
            ? "\nNo exterior sensors"
            : "\nNo interior sensors");
      rect.appendChild(title);
      roomGroup.appendChild(rect);

      if (!isMapSelected) {
        for (const s of col.sensors || []) {
          const cm = sensorHeightCm(s, ceilingCm);
          if (cm == null) continue;
          const y = padT + ((ceilingCm - cm) / ceilingCm) * plotH;
          const cx = x + w * 0.5;
          if (networkSensorIsStale(s)) {
            appendSectionStaleSensorIcon(roomGroup, NS, cx, y, s);
            continue;
          }
          const t = networkSensorMetric(s);
          if (!Number.isFinite(t)) continue;
          const dot = document.createElementNS(NS, "circle");
          dot.setAttribute("cx", String(cx));
          dot.setAttribute("cy", String(y));
          dot.setAttribute("r", "5");
          dot.setAttribute("fill", networkTempColor(t, tMin, tMax));
          dot.setAttribute("stroke", "#fff");
          dot.setAttribute("stroke-width", "1.5");
          dot.setAttribute("pointer-events", "none");
          const tip = document.createElementNS(NS, "title");
          tip.textContent = `${s.name}: ${formatNetworkSensorReading(s)} @ ${Math.round(cm)} cm`;
          dot.appendChild(tip);
          roomGroup.appendChild(dot);

          const lab = document.createElementNS(NS, "text");
          lab.setAttribute("x", String(cx + 8));
          lab.setAttribute("y", String(y + 4));
          lab.setAttribute("class", "section-sensor-label");
          lab.setAttribute(
            "fill",
            t >= (tMin + tMax) / 2 ? "var(--temp)" : "var(--hum)"
          );
          lab.textContent = networkShowsBothMetrics()
            ? `${formatNetworkSensorReading(s)} · ${Math.round(cm)}`
            : `${t.toFixed(1)}${networkMetricUnitShort()} · ${Math.round(cm)}`;
          roomGroup.appendChild(lab);
        }
      } else if (w >= 72) {
        const fo = document.createElementNS(NS, "foreignObject");
        fo.setAttribute("x", String(x + 5));
        fo.setAttribute("y", String(padT + 6));
        fo.setAttribute("width", String(Math.max(40, w - 10)));
        fo.setAttribute("height", String(Math.max(40, plotH - 12)));
        fo.setAttribute("class", "section-room-chart-fo");
        const host = document.createElementNS(
          "http://www.w3.org/1999/xhtml",
          "div"
        );
        host.className = "section-room-chart-host";
        const toolbar = document.createElementNS(
          "http://www.w3.org/1999/xhtml",
          "div"
        );
        toolbar.className = "section-room-chart-toolbar";
        const closeBtn = document.createElementNS(
          "http://www.w3.org/1999/xhtml",
          "button"
        );
        closeBtn.type = "button";
        closeBtn.className = "section-room-chart-close";
        closeBtn.title = "Close temperature charts";
        closeBtn.setAttribute("aria-label", "Close temperature charts");
        closeBtn.textContent = "Close";
        closeBtn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          clearMapRoomSelection();
        });
        toolbar.appendChild(closeBtn);
        const canvas = document.createElementNS(
          "http://www.w3.org/1999/xhtml",
          "canvas"
        );
        canvas.className = "section-room-temp-chart";
        host.appendChild(toolbar);
        host.appendChild(canvas);
        fo.appendChild(host);
        // Chart clicks should not toggle selection; use Close.
        fo.addEventListener("click", (ev) => ev.stopPropagation());
        roomGroup.appendChild(fo);
        sectionRoomChartCanvas = canvas;
      }

      const nameLab = document.createElementNS(NS, "text");
      nameLab.setAttribute("x", String(x + w / 2));
      nameLab.setAttribute("y", String(H - 18));
      nameLab.setAttribute(
        "class",
        col.kind === "facade"
          ? "section-room-label section-facade-label"
          : "section-room-label"
      );
      nameLab.textContent = col.label;
      roomGroup.appendChild(nameLab);
      if (col.kind === "facade" && col.sublabel) {
        const sub = document.createElementNS(NS, "text");
        sub.setAttribute("x", String(x + w / 2));
        sub.setAttribute("y", String(H - 6));
        sub.setAttribute("class", "section-facade-sublabel");
        sub.textContent = col.sublabel;
        roomGroup.appendChild(sub);
      }
      sectionSvgEl.appendChild(roomGroup);

      if (i < columns.length - 1) {
        const next = columns[i + 1];
        const doorX = x + w + gap / 2;
        let opening = "unknown";
        let linkKind = "door";
        let linkTitle = "";
        if (col.kind === "room" && next.kind === "room") {
          const link = edgeOpeningBetween(edges, col.id, next.id);
          opening = link.opening || "unknown";
          linkKind = link.kind || "door";
          linkTitle =
            `${col.id} ↔ ${next.id}: ${linkKind} ${opening}` +
            (link.source ? ` (${link.source})` : "");
          linkBits.push(`${col.label}↔${next.label}: ${linkKind} ${opening}`);
        } else {
          // Façade ↔ room: use that room's window/door state, not the merged
          // façade aggregate (kitchen+living share SW — living unknown must not
          // dash the kitchen link when kitchen is closed).
          const roomCol = col.kind === "room" ? col : next;
          const facadeCol = col.kind === "facade" ? col : next;
          const room = roomCol.room || null;
          const wState = room ? room.window_state : null;
          if (wState === "open" || wState === "closed" || wState === "unknown") {
            opening = wState;
          } else {
            opening = "unknown";
          }
          linkKind = "exterior";
          linkTitle =
            `Window ${facadeCol.label} ↔ ${roomCol.label}: ${opening}` +
            (wState == null ? " (no contact)" : "");
          linkBits.push(
            `win ${roomCol.label}: ${opening}${wState == null ? "?" : ""}`
          );
        }
        const kindClass = `section-link-${String(linkKind).replace(/[^a-z0-9_-]/gi, "_")}`;
        const door = document.createElementNS(NS, "line");
        door.setAttribute("x1", String(doorX));
        door.setAttribute("x2", String(doorX));
        door.setAttribute("y1", String(padT + plotH * 0.18));
        door.setAttribute("y2", String(padT + plotH * 0.82));
        door.setAttribute("class", `section-door ${kindClass} ${opening}`);
        const dTitle = document.createElementNS(NS, "title");
        dTitle.textContent = linkTitle;
        door.appendChild(dTitle);
        sectionSvgEl.appendChild(door);
        x += w + gap;
      } else {
        x += w;
      }
    }

    if (sectionMetaEl) {
      const labels = columns.map((c) =>
        c.kind === "facade" ? `ext ${c.label}` : c.label
      );
      sectionMetaEl.textContent =
        `Ceiling ${ceilingCm} cm · ${labels.join(" → ")}` +
        (linkBits.length ? ` · ${linkBits.join(", ")}` : "") +
        ` · scale ${tMin.toFixed(1)}–${tMax.toFixed(1)} ${networkMetricUnit()}`;
    }

    if (
      sectionRoomChartCanvas &&
      mapRoomChartSeriesCache &&
      selectedMapRoomId &&
      String(mapRoomChartSeriesCache.roomId) === String(selectedMapRoomId)
    ) {
      const series = mapRoomChartSeriesCache.series || [];
      requestAnimationFrame(() => {
        if (
          sectionRoomChartCanvas &&
          mapRoomChartSeriesCache &&
          String(mapRoomChartSeriesCache.roomId) === String(selectedMapRoomId)
        ) {
          paintMapRoomChartDatasets(series);
        }
      });
    }
    requestAnimationFrame(() => applyMapFontScale(sectionSvgEl, W));
  }

  function renderNetwork(data) {
    if (!networkSvgEl) return;
    const NS = "http://www.w3.org/2000/svg";
    networkSvgEl.replaceChildren();
    renderOpenRoomSection(data);
    if (!data || !data.enabled) {
      if (networkTempScaleEl) networkTempScaleEl.hidden = true;
      if (networkMetaEl) {
        networkMetaEl.textContent =
          "Apartment map disabled — enable [apartment] in config.toml.";
      }
      if (networkStatusEl) networkStatusEl.textContent = "Disabled";
      return;
    }
    const rooms = data.rooms || [];
    const edges = data.edges || [];
    if (!rooms.length) {
      if (networkTempScaleEl) networkTempScaleEl.hidden = true;
      if (networkMetaEl) networkMetaEl.textContent = "No apartment rooms in config.";
      if (networkStatusEl) networkStatusEl.textContent = "Empty";
      return;
    }

    const { pos } = networkLayout(rooms, edges);
    const sectionPath = sectionPathIds(data).filter((id) =>
      rooms.some((r) => r.id === id)
    );
    const sectionPathSet = new Set(sectionPath);
    /** @type {Set<string>} */
    const sectionEdgeKeys = new Set();
    for (let i = 0; i < sectionPath.length - 1; i += 1) {
      const a = sectionPath[i];
      const b = sectionPath[i + 1];
      sectionEdgeKeys.add(`${a}|${b}`);
      sectionEdgeKeys.add(`${b}|${a}`);
    }
    const waypointSet = new Set(sectionWaypoints);
    const W = NETWORK_VB_W;
    const H = NETWORK_VB_H;
    // Leave room for node radii (~44) + labels so top/bottom façade nodes are not clipped.
    const pad = 78;
    const usable = Math.min(W - 2 * pad, H - 2 * pad);
    const cx = W / 2;
    const cy = H / 2;
    const scale = usable * 0.42;
    const toXY = (p) => ({ x: cx + p.x * scale, y: cy + p.y * scale });

    centerNetworkPan();
    applyNetworkViewBox();

    const defs = document.createElementNS(NS, "defs");
    for (const [id, color] of [
      ["network-arrow", "#1f8a70"],
      ["network-arrow-in", "#2b7bbf"],
      ["network-arrow-out", "#c45c4a"],
      ["network-arrow-need", "#c4782a"],
    ]) {
      const marker = document.createElementNS(NS, "marker");
      marker.setAttribute("id", id);
      marker.setAttribute("viewBox", "0 0 10 10");
      marker.setAttribute("refX", "9");
      marker.setAttribute("refY", "5");
      marker.setAttribute("markerWidth", "7");
      marker.setAttribute("markerHeight", "7");
      marker.setAttribute("orient", "auto-start-reverse");
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
      path.setAttribute("fill", color);
      marker.appendChild(path);
      defs.appendChild(marker);
    }
    networkSvgEl.appendChild(defs);

    const { tMin, tMax } = networkTempScale(rooms);
    const ceilingCm = Math.max(
      50,
      Math.round(Number(data.ceiling_m || 2.5) * 100)
    );
    if (networkTempScaleEl) {
      networkTempScaleEl.hidden = false;
      const u = networkMetricUnitShort();
      if (networkTempScaleLoEl) {
        networkTempScaleLoEl.textContent = `${tMin.toFixed(1)}${u}`;
      }
      if (networkTempScaleHiEl) {
        networkTempScaleHiEl.textContent = `${tMax.toFixed(1)}${u}`;
      }
    }

    const gEdges = document.createElementNS(NS, "g");
    gEdges.setAttribute("class", "network-edges");
    const gFlows = document.createElementNS(NS, "g");
    gFlows.setAttribute("class", "network-flows");
    const gNodes = document.createElementNS(NS, "g");
    gNodes.setAttribute("class", "network-nodes");
    const gLabels = document.createElementNS(NS, "g");
    gLabels.setAttribute("class", "network-labels");

    /** @type {Record<string, {x:number,y:number}>} */
    const roomXY = {};
    /** @type {Record<string, {x:number,y:number}>} */
    const extXY = {};

    for (const edge of edges) {
      const pa = pos[edge.a];
      const pb = pos[edge.b];
      if (!pa || !pb) continue;
      const a = toXY(pa);
      const b = toXY(pb);
      const line = document.createElementNS(NS, "line");
      const kind = edge.kind || "door";
      const opening = edge.opening || "unknown";
      line.setAttribute("x1", String(a.x));
      line.setAttribute("y1", String(a.y));
      line.setAttribute("x2", String(b.x));
      line.setAttribute("y2", String(b.y));
      line.setAttribute(
        "class",
        `network-edge network-edge-${kind}${
          kind === "door" || kind === "wall_partial" ? ` ${opening}` : ""
        }${
          sectionEdgeKeys.has(`${edge.a}|${edge.b}`)
            ? " is-section-path"
            : ""
        }`
      );
      const title = document.createElementNS(NS, "title");
      const contactNames = (edge.contacts || [])
        .map((c) => `${c.name || c.sensor_id}: ${c.state || "?"}`)
        .join(", ");
      const src = edge.opening_source || "";
      const delta =
        edge.temp_delta_max_c != null ? `ΔTmax ${edge.temp_delta_max_c}°C` : "";
      title.textContent =
        `${edge.a} ↔ ${edge.b} (${kind}` +
        (kind === "wall" ? "" : `, ${opening}`) +
        `)` +
        (src ? ` · ${src}` : "") +
        (delta ? ` · ${delta}` : "") +
        (contactNames ? ` — ${contactNames}` : "");
      line.appendChild(title);
      gEdges.appendChild(line);

      if (kind === "door" || kind === "wall_partial") {
        const midX = (a.x + b.x) / 2;
        const midY = (a.y + b.y) / 2;
        const lab = document.createElementNS(NS, "text");
        lab.setAttribute("x", String(midX));
        lab.setAttribute("y", String(midY - 6));
        lab.setAttribute("class", "network-edge-label");
        let text;
        if (src === "temp_coupling" && edge.temp_delta_max_c != null) {
          const tag =
            opening === "open"
              ? "coupled"
              : opening === "closed"
                ? "isolated"
                : "ΔT?";
          text = `${tag} ${edge.temp_delta_max_c}°`;
        } else if (kind === "wall_partial") {
          text =
            opening === "unknown" ? "partial" : `partial · ${opening}`;
        } else {
          text = opening;
        }
        lab.textContent = text;
        gLabels.appendChild(lab);
      }
    }

    // Exterior links for façade rooms
    let openWindows = 0;
    let openDoors = 0;
    let coupledLinks = 0;
    for (const edge of edges) {
      if (edge.kind !== "door" && edge.kind !== "wall_partial") continue;
      if (edge.opening !== "open") continue;
      if (edge.opening_source === "temp_coupling") coupledLinks += 1;
      else openDoors += 1;
    }

    const hottestIds = networkHottestRoomIds(rooms);
    const hvac = data.hvac || null;
    const hvacRoomId =
      hvac && hvac.active && hvac.room ? String(hvac.room).toLowerCase() : "";
    const hvacClimate = (hvac && hvac.climate) || null;
    const hvacSetpoint =
      hvacClimate && hvacClimate.target_temp_c != null
        ? Number(hvacClimate.target_temp_c)
        : null;
    const hvacAcWatts =
      hvac && hvac.ac_watts != null ? Number(hvac.ac_watts) : null;

    // Group rooms that share the same exterior orientation (e.g. living+kitchen → SW).
    const facadeGroups = new Map();
    for (const room of rooms) {
      const p = pos[room.id];
      if (!p) continue;
      const key = networkFacadeKey(room);
      if (!key) continue;
      if (!facadeGroups.has(key)) {
        facadeGroups.set(key, { key, orients: key.split("+"), rooms: [] });
      }
      facadeGroups.get(key).rooms.push(room);
    }

    for (const group of facadeGroups.values()) {
      let sx = 0;
      let sy = 0;
      let n = 0;
      for (const room of group.rooms) {
        const p = pos[room.id];
        if (!p) continue;
        const off = networkExteriorOffset(room, p);
        sx += off.x;
        sy += off.y;
        n += 1;
      }
      if (!n) continue;
      const exy = toXY({ x: sx / n, y: sy / n });
      group.exy = exy;

      for (const room of group.rooms) {
        extXY[room.id] = exy;
        const xy = toXY(pos[room.id]);
        const wState = room.window_state;
        if (wState === "open") openWindows += 1;
        const line = document.createElementNS(NS, "line");
        line.setAttribute("x1", String(xy.x));
        line.setAttribute("y1", String(xy.y));
        line.setAttribute("x2", String(exy.x));
        line.setAttribute("y2", String(exy.y));
        line.setAttribute(
          "class",
          `network-edge network-edge-exterior ${wState || "unknown"}`
        );
        const title = document.createElementNS(NS, "title");
        title.textContent =
          `${room.label || room.id} → façade ${group.orients.join(", ").toUpperCase()}` +
          (wState ? ` — window ${wState}` : "");
        line.appendChild(title);
        gEdges.appendChild(line);
      }

      const bands = networkFacadeTempBands(group.rooms);
      const humBands = networkShowsBothMetrics()
        ? networkFacadeFieldBands(group.rooms, "humidity")
        : null;
      const highTxt = networkShowsBothMetrics()
        ? formatNetworkBothBand(bands.high, humBands.high)
        : formatNetworkTempBand(bands.high);
      const lowTxt = networkShowsBothMetrics()
        ? formatNetworkBothBand(bands.low, humBands.low)
        : formatNetworkTempBand(bands.low);
      const otherTxt = networkShowsBothMetrics()
        ? formatNetworkBothBand(bands.other, humBands.other)
        : formatNetworkTempBand(bands.other);
      const roomLabels = group.rooms
        .map((r) => r.label || r.id)
        .join(" + ");
      const facadeNames = [
        ...new Set(
          group.rooms.flatMap((r) => r.facade_sensor_names || [])
        ),
      ];
      let facadeLo = null;
      let facadeHi = null;
      for (const r of group.rooms) {
        if (r.facade_temp_min != null) {
          facadeLo =
            facadeLo == null
              ? Number(r.facade_temp_min)
              : Math.min(facadeLo, Number(r.facade_temp_min));
        }
        if (r.facade_temp_max != null) {
          facadeHi =
            facadeHi == null
              ? Number(r.facade_temp_max)
              : Math.max(facadeHi, Number(r.facade_temp_max));
        }
      }

      const facadeSensors = group.rooms.flatMap((r) => r.sensors || []);
      const contLevels = networkSensorGradientLevels(facadeSensors, ceilingCm, {
        exterior: true,
      });
      const heightStops = networkHeightStops(bands);
      const hasTemp = !!(
        contLevels ||
        heightStops.high != null ||
        heightStops.mid != null ||
        heightStops.low != null
      );
      const extW = 52;
      const extH = 80;
      const gradId = `ext-grad-${group.key.replace(/[^a-z0-9+_-]/gi, "_")}`;
      const fill = hasTemp
        ? appendHeightGradient(
            defs,
            NS,
            gradId,
            contLevels || heightStops,
            tMin,
            tMax
          )
        : "#354860";
      const extNode = document.createElementNS(NS, "rect");
      extNode.setAttribute("x", String(exy.x - extW / 2));
      extNode.setAttribute("y", String(exy.y - extH / 2));
      extNode.setAttribute("width", String(extW));
      extNode.setAttribute("height", String(extH));
      extNode.setAttribute("rx", "14");
      extNode.setAttribute("ry", "14");
      extNode.setAttribute("class", "network-node-exterior");
      extNode.setAttribute("fill", fill);
      const extTitle = document.createElementNS(NS, "title");
      const sensorBits = group.rooms
        .flatMap((r) => r.sensors || [])
        .filter((s) => String(s.zone || "").toLowerCase() === "exterior")
        .map((s) => {
          const h = String(s.height || "").trim();
          const cm =
            s.height_cm != null && Number.isFinite(Number(s.height_cm))
              ? `${Math.round(Number(s.height_cm))} cm`
              : "";
          const hBit = [h, cm].filter(Boolean).join(" · ");
          return `${s.name}${hBit ? ` [${hBit}]` : ""}: ${formatNetworkSensorReading(
            s
          )}`;
        })
        .join("; ");
      extTitle.textContent =
        `Façade ${group.orients.join(", ").toUpperCase()} · ${roomLabels}` +
        (networkMapMetric === "temp" &&
        facadeLo != null &&
        facadeHi != null
          ? ` · ${facadeLo.toFixed(1)}–${facadeHi.toFixed(1)}°C`
          : "") +
        (facadeNames.length ? ` · ${facadeNames.join(", ")}` : "") +
        (highTxt ? `\nHigh: ${highTxt}` : "") +
        (lowTxt ? `\nLow: ${lowTxt}` : "") +
        (otherTxt && !highTxt && !lowTxt ? `\n${otherTxt}` : "") +
        (sensorBits ? `\n${sensorBits}` : "");
      extNode.appendChild(extTitle);
      gNodes.appendChild(extNode);

      if (highTxt) {
        const highLab = document.createElementNS(NS, "text");
        highLab.setAttribute("x", String(exy.x));
        highLab.setAttribute("y", String(exy.y - extH / 2 + 16));
        highLab.setAttribute("class", "network-sublabel network-temp-high");
        highLab.textContent = highTxt;
        gLabels.appendChild(highLab);
      }

      const extLab = document.createElementNS(NS, "text");
      extLab.setAttribute("x", String(exy.x));
      extLab.setAttribute("y", String(exy.y + 4));
      extLab.setAttribute("class", "network-label");
      extLab.textContent = (group.orients[0] || "out").toUpperCase();
      gLabels.appendChild(extLab);

      const bottomTxt =
        lowTxt ||
        (!highTxt
          ? otherTxt ||
            (networkMapMetric === "temp" &&
            facadeLo != null &&
            facadeHi != null
              ? facadeLo === facadeHi
                ? `${facadeLo.toFixed(1)}°C`
                : `${facadeLo.toFixed(1)}–${facadeHi.toFixed(1)}°C`
              : null)
          : null);
      if (bottomTxt) {
        const lowLab = document.createElementNS(NS, "text");
        lowLab.setAttribute("x", String(exy.x));
        lowLab.setAttribute("y", String(exy.y + extH / 2 - 10));
        lowLab.setAttribute("class", "network-sublabel network-temp-low");
        lowLab.textContent = bottomTxt;
        gLabels.appendChild(lowLab);
      }
    }

    const ROOM_W = 64;
    const ROOM_H = 100;

    for (const room of rooms) {
      const p = pos[room.id];
      if (!p) continue;
      const xy = toXY(p);
      roomXY[room.id] = xy;

      const hasOpen =
        room.window_state === "open" ||
        (room.contacts || []).some((c) => String(c.state || "").toLowerCase() === "open");
      const isHottest = hottestIds.has(room.id);
      const hasAc = hvacRoomId && room.id === hvacRoomId;
      const bands = networkInteriorTempBands(room);
      const humBands = networkShowsBothMetrics()
        ? networkInteriorFieldBands(room, "humidity")
        : null;
      const contLevels = networkSensorGradientLevels(
        room.sensors || [],
        ceilingCm,
        { exterior: false }
      );
      const heightStops = networkHeightStops(bands);
      const hasTemp = !!(
        contLevels ||
        heightStops.high != null ||
        heightStops.mid != null ||
        heightStops.low != null
      );
      const gradId = `room-grad-${String(room.id).replace(/[^a-z0-9_-]/gi, "_")}`;
      const fill = hasTemp
        ? appendHeightGradient(
            defs,
            NS,
            gradId,
            contLevels || heightStops,
            tMin,
            tMax
          )
        : roomColor(room.id, 0) + "44";
      const isOnPath = sectionPathSet.has(room.id);
      const isWaypoint = waypointSet.has(room.id);
      const isMapSelected = String(selectedMapRoomId || "") === String(room.id);
      const waypointIdx = sectionWaypoints.indexOf(room.id);
      const node = document.createElementNS(NS, "rect");
      node.setAttribute("x", String(xy.x - ROOM_W / 2));
      node.setAttribute("y", String(xy.y - ROOM_H / 2));
      node.setAttribute("width", String(ROOM_W));
      node.setAttribute("height", String(ROOM_H));
      node.setAttribute("rx", "16");
      node.setAttribute("ry", "16");
      node.setAttribute(
        "class",
        `network-node-room${hasOpen ? " has-open" : ""}${
          isHottest ? " is-hottest" : ""
        }${hasAc ? " has-ac" : ""}${isOnPath ? " is-section-path" : ""}${
          isWaypoint ? " is-section-waypoint" : ""
        }${isMapSelected ? " is-map-selected" : ""}`
      );
      node.style.cursor = "pointer";
      node.addEventListener("pointerdown", (ev) => {
        ev.stopPropagation();
      });
      node.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (ev.shiftKey) {
          toggleSectionWaypoint(room.id);
        } else {
          selectMapRoom(room.id);
        }
      });
      node.setAttribute("fill", fill);
      if (isMapSelected) {
        node.setAttribute("stroke", "#6fbf73");
        node.setAttribute("stroke-width", "3.5");
      } else if (isWaypoint) {
        node.setAttribute("stroke", "#1f8a70");
        node.setAttribute("stroke-width", "3");
      } else if (isOnPath) {
        node.setAttribute("stroke", "#5b8fd9");
        node.setAttribute("stroke-width", "2.5");
      } else if (isHottest) {
        node.setAttribute("stroke", "#c45c4a");
      } else if (hasAc) {
        node.setAttribute("stroke", "#2b7bbf");
      }
      const highTxt = networkShowsBothMetrics()
        ? formatNetworkBothBand(bands.high, humBands.high)
        : formatNetworkTempBand(bands.high);
      const lowTxt = networkShowsBothMetrics()
        ? formatNetworkBothBand(bands.low, humBands.low)
        : formatNetworkTempBand(bands.low);
      const otherTxt = networkShowsBothMetrics()
        ? formatNetworkBothBand(
            [...(bands.mid || []), ...(bands.other || [])],
            [...(humBands.mid || []), ...(humBands.other || [])]
          )
        : formatNetworkTempBand(
            [...(bands.mid || []), ...(bands.other || [])]
          );
      const title = document.createElementNS(NS, "title");
      const sensorBits = (room.sensors || [])
        .map((s) => {
          const h = String(s.height || "").trim();
          const cm =
            s.height_cm != null && Number.isFinite(Number(s.height_cm))
              ? `${Math.round(Number(s.height_cm))} cm`
              : "";
          const hBit = [h, cm].filter(Boolean).join(" · ");
          return `${s.name}${hBit ? ` [${hBit}]` : ""}: ${formatNetworkSensorReading(
            s
          )}`;
        })
        .join("; ");
      let acTitle = "";
      if (hasAc) {
        const setBit =
          hvacSetpoint != null && Number.isFinite(hvacSetpoint)
            ? `setpoint ${hvacSetpoint.toFixed(1)}°C`
            : "setpoint —";
        const powBit =
          hvacAcWatts != null && Number.isFinite(hvacAcWatts)
            ? `≈ ${Math.round(hvacAcWatts)} W`
            : "power —";
        const mode = (hvacClimate && (hvacClimate.hvac_mode || hvacClimate.state)) || "";
        acTitle =
          `\nAC on` +
          (mode ? ` (${mode})` : "") +
          ` · ${setBit} · ${powBit}`;
      }
      const peakLabel =
        networkMapMetric === "humidity" ? "most humid" : "hottest";
      const pathBit = isWaypoint
        ? `\nSection waypoint #${waypointIdx + 1} (click to remove)`
        : isOnPath
          ? "\nOn cross-section path (click to pin as waypoint)"
          : "\nClick to add to cross-section path";
      title.textContent =
        `${room.label || room.id}` +
        (isHottest ? ` · ${peakLabel}` : "") +
        pathBit +
        acTitle +
        (highTxt ? `\nHigh: ${highTxt}` : "") +
        (lowTxt ? `\nLow: ${lowTxt}` : "") +
        (otherTxt && !highTxt && !lowTxt ? `\n${otherTxt}` : "") +
        (sensorBits ? `\n${sensorBits}` : "");
      node.appendChild(title);
      gNodes.appendChild(node);

      if (isWaypoint) {
        const badge = document.createElementNS(NS, "text");
        badge.setAttribute("x", String(xy.x + ROOM_W / 2 - 10));
        badge.setAttribute("y", String(xy.y - ROOM_H / 2 + 14));
        badge.setAttribute("class", "network-waypoint-badge");
        badge.textContent = String(waypointIdx + 1);
        gLabels.appendChild(badge);
      }

      // High sensors → top of band; low sensors → bottom; name in the middle.
      if (highTxt) {
        const highLab = document.createElementNS(NS, "text");
        highLab.setAttribute("x", String(xy.x));
        highLab.setAttribute("y", String(xy.y - ROOM_H / 2 + 16));
        highLab.setAttribute(
          "class",
          `network-sublabel network-temp-high${isHottest ? " is-hottest" : ""}`
        );
        highLab.textContent = highTxt;
        gLabels.appendChild(highLab);
      }

      const lab = document.createElementNS(NS, "text");
      lab.setAttribute("x", String(xy.x));
      lab.setAttribute("y", String(xy.y + 4));
      lab.setAttribute(
        "class",
        `network-label${isHottest ? " is-hottest" : ""}`
      );
      lab.textContent = room.label || room.id;
      gLabels.appendChild(lab);

      const indoorSensors = (room.sensors || []).filter(
        (s) => String(s.zone || "").toLowerCase() !== "exterior"
      );
      const roomFallback = networkShowsBothMetrics()
        ? formatNetworkBothBand(
            indoorSensors.map((s) =>
              networkSensorFieldValue(s, "temperature_c")
            ),
            indoorSensors.map((s) => networkSensorFieldValue(s, "humidity"))
          )
        : networkMapMetric === "temp"
          ? formatNetworkTemp(room.temp_c)
          : formatNetworkTemp(
              networkAvgTemp(
                indoorSensors.map((s) => networkSensorMetric(s))
              )
            );
      const bottomTxt =
        lowTxt || (!highTxt ? otherTxt || roomFallback : null);
      if (bottomTxt) {
        const lowLab = document.createElementNS(NS, "text");
        lowLab.setAttribute("x", String(xy.x));
        lowLab.setAttribute("y", String(xy.y + ROOM_H / 2 - 10));
        lowLab.setAttribute(
          "class",
          `network-sublabel network-temp-low${isHottest ? " is-hottest" : ""}`
        );
        lowLab.textContent = bottomTxt;
        gLabels.appendChild(lowLab);
      }

      if (hasAc) {
        const bits = [];
        if (hvacSetpoint != null && Number.isFinite(hvacSetpoint)) {
          bits.push(`${hvacSetpoint.toFixed(1)}°`);
        }
        if (hvacAcWatts != null && Number.isFinite(hvacAcWatts)) {
          bits.push(`≈${Math.round(hvacAcWatts)} W`);
        }
        const acLab = document.createElementNS(NS, "text");
        acLab.setAttribute("x", String(xy.x));
        acLab.setAttribute("y", String(xy.y + ROOM_H / 2 + 14));
        acLab.setAttribute("class", "network-sublabel network-ac-label");
        acLab.textContent = bits.length ? `AC ${bits.join(" · ")}` : "AC on";
        gLabels.appendChild(acLab);
      }
    }

    function resolveFlowPoint(id) {
      if (!id) return null;
      if (String(id).startsWith("ext:")) {
        const rid = String(id).slice(4);
        return extXY[rid] || roomXY[rid] || null;
      }
      return roomXY[id] || null;
    }

    function shortenSegment(a, b, pad) {
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const len = Math.hypot(dx, dy) || 1;
      const t0 = Math.min(pad / len, 0.4);
      const t1 = 1 - t0;
      return {
        x1: a.x + dx * t0,
        y1: a.y + dy * t0,
        x2: a.x + dx * t1,
        y2: a.y + dy * t1,
      };
    }

    const airflow = data.airflow || null;
    if (airflow && Array.isArray(airflow.flows)) {
      for (const flow of airflow.flows) {
        const from = resolveFlowPoint(flow.from);
        const to = resolveFlowPoint(flow.to);
        if (!from || !to) continue;
        const seg = shortenSegment(from, to, 40);
        const line = document.createElementNS(NS, "line");
        line.setAttribute("x1", String(seg.x1));
        line.setAttribute("y1", String(seg.y1));
        line.setAttribute("x2", String(seg.x2));
        line.setAttribute("y2", String(seg.y2));
        const role = flow.role || "path";
        const needs = !!flow.needs_open;
        line.setAttribute(
          "class",
          `network-flow network-flow-${role}${needs ? " needs-open" : ""}`
        );
        const marker =
          needs
            ? "network-arrow-need"
            : role === "inlet"
              ? "network-arrow-in"
              : role === "outlet"
                ? "network-arrow-out"
                : "network-arrow";
        line.setAttribute("marker-end", `url(#${marker})`);
        line.setAttribute(
          "stroke-width",
          String(2.5 + 2.5 * Number(flow.strength || 1))
        );
        const title = document.createElementNS(NS, "title");
        title.textContent =
          `${flow.from} → ${flow.to}` +
          (role ? ` (${role})` : "") +
          (needs ? " — open door to enable" : "");
        line.appendChild(title);
        gFlows.appendChild(line);
      }
      if (airflow.inlet && airflow.outlet && airflow.inlet.room !== airflow.outlet.room) {
        const midRoom =
          (airflow.path || [])[Math.floor((airflow.path || []).length / 2)];
        const mid = roomXY[midRoom];
        if (mid) {
          const lab = document.createElementNS(NS, "text");
          lab.setAttribute("x", String(mid.x));
          lab.setAttribute("y", String(mid.y + 28));
          lab.setAttribute("class", "network-flow-label");
          lab.textContent = "draft →";
          gLabels.appendChild(lab);
        }
      }
    }

    networkSvgEl.appendChild(gEdges);
    networkSvgEl.appendChild(gFlows);
    networkSvgEl.appendChild(gNodes);
    networkSvgEl.appendChild(gLabels);

    const outdoor = data.outdoor || {};
    const outTemp =
      outdoor.available && outdoor.temp_now != null
        ? Number(outdoor.temp_now)
        : outdoor.available && outdoor.temp_c != null
          ? Number(outdoor.temp_c)
          : NaN;
    const outBit = Number.isFinite(outTemp)
      ? ` · outdoor ${outTemp.toFixed(1)}°C`
      : "";
    const couple = data.temp_couple || {};
    const coupleBit =
      couple.open_threshold_c != null
        ? ` · coupled if ΔTmax ≤ ${couple.open_threshold_c}°C` +
          (couple.closed_threshold_c != null
            ? `, isolated if ≥ ${couple.closed_threshold_c}°C`
            : "")
        : "";
    let acBit = "";
    if (hvacRoomId) {
      const roomLabel =
        (rooms.find((r) => r.id === hvacRoomId) || {}).label || hvacRoomId;
      const setBit =
        hvacSetpoint != null && Number.isFinite(hvacSetpoint)
          ? `${hvacSetpoint.toFixed(1)}°C`
          : "—";
      const powBit =
        hvacAcWatts != null && Number.isFinite(hvacAcWatts)
          ? `≈${Math.round(hvacAcWatts)} W`
          : "—";
      acBit = ` · AC on in ${roomLabel} · set ${setBit} · ${powBit}`;
    }
    if (networkMetaEl) {
      const pathLabels = sectionPath
        .map((id) => {
          const r = rooms.find((x) => x.id === id);
          return (r && (r.label || r.id)) || id;
        })
        .join(" → ");
      const pathBit = pathLabels ? ` · cut ${pathLabels}` : "";
      networkMetaEl.textContent =
        `${rooms.length} rooms · ${edges.length} links` +
        (openDoors ? ` · ${openDoors} contact open` : "") +
        (coupledLinks ? ` · ${coupledLinks} thermally coupled` : "") +
        (openWindows ? ` · ${openWindows} window(s) open` : "") +
        outBit +
        coupleBit +
        acBit +
        pathBit;
    }
    if (networkAirflowEl) {
      if (!airflow || !airflow.mode) {
        networkAirflowEl.textContent = "";
      } else if (airflow.mode === "hold") {
        networkAirflowEl.innerHTML = `<strong>Hold heat out</strong> — ${(
          airflow.actions || []
        )
          .map((a) => escapeHtml(a))
          .join(" ")}`;
      } else {
        const inlet = airflow.inlet || {};
        const outlet = airflow.outlet || {};
        const pathLabels = (airflow.path || [])
          .map((id) => {
            const r = rooms.find((x) => x.id === id);
            return escapeHtml((r && r.label) || id);
          })
          .join(" → ");
        const delta =
          airflow.delta_c != null
            ? ` · Δ outdoor ${Number(airflow.delta_c).toFixed(1)}°C`
            : airflow.mode === "cooling_est"
              ? " · outdoor unknown — estimate from façades / room heat"
              : "";
        const wind =
          airflow.wind_compass != null
            ? ` · wind ${escapeHtml(String(airflow.wind_compass))}` +
              (airflow.wind_speed_ms != null
                ? ` ${Number(airflow.wind_speed_ms).toFixed(1)} m/s`
                : "")
            : "";
        const actions = (airflow.actions || [])
          .map((a) => `<li>${escapeHtml(a)}</li>`)
          .join("");
        networkAirflowEl.innerHTML =
          `<strong>Cooling draft</strong>: ${escapeHtml(
            inlet.label || inlet.room || "?"
          )} (in) → ${escapeHtml(outlet.label || outlet.room || "?")} (out)` +
          (pathLabels ? ` · ${pathLabels}` : "") +
          `${delta}${wind}` +
          (actions ? `<ol>${actions}</ol>` : "");
      }
    }
    if (networkStatusEl) {
      networkStatusEl.textContent = `Updated ${new Date().toLocaleTimeString("en-GB")}`;
    }
    requestAnimationFrame(() =>
      applyMapFontScale(networkSvgEl, NETWORK_VB_W / networkZoom)
    );
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
    const count = { open: 0, close: 0, humid: 0, natural: 0, mechanical: 0 };
    const hours = { open: 0, close: 0, humid: 0, natural: 0, mechanical: 0 };
    for (const b of bands) {
      const durH = Math.max(0, (Number(b.x2) - Number(b.x1)) / 3600000);
      if (count[b.kind] != null) {
        count[b.kind] += 1;
        hours[b.kind] += durH;
      }
      if (b.vent && count[b.vent] != null) {
        count[b.vent] += 1;
        hours[b.vent] += durH;
      }
    }
    const fmtH = (h) => {
      if (h < 1) return `${Math.round(h * 60)} min`;
      return `${h.toFixed(h >= 10 ? 0 : 1)} h`;
    };
    const parts = [];
    if (count.open) parts.push(`Open ×${count.open} (${fmtH(hours.open)})`);
    if (count.close) parts.push(`Close ×${count.close} (${fmtH(hours.close)})`);
    if (count.humid) parts.push(`Too humid ×${count.humid} (${fmtH(hours.humid)})`);
    if (count.natural) {
      parts.push(`Natural OK ×${count.natural} (${fmtH(hours.natural)})`);
    }
    if (count.mechanical) {
      parts.push(
        `Mechanical preferred ×${count.mechanical} (${fmtH(hours.mechanical)})`
      );
    }
    return parts.join(" · ") || "No clear open/close windows in this period.";
  }

  /** Detailed ranges for tooltip (hover), not shown inline. */
  function formatWindowScheduleDetail(bands) {
    if (!bands || !bands.length) return "";
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
    return parts.join(" · ");
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

    if (!groups.length || !outdoor.available || !outdoorPoints.length) {
      facadeChartsEl.hidden = true;
      return;
    }

    facadeChartsEl.hidden = false;
    const axis = rangeAxisBounds();
    groups.forEach((group, gIdx) => {
      const figure = document.createElement("figure");
      figure.className = "chart-block facade-chart-block";

      const caption = document.createElement("figcaption");
      const roomNames = group.rooms.map((r) => r.label || r.id).join(", ");
      caption.innerHTML = `${escapeHtml(group.label)} façade
        <span class="overview-meta">${escapeHtml(roomNames)} · ${escapeHtml(
        formatRangeLabel()
      )} · +${forecastFutureHours} h</span>`;

      const canvas = document.createElement("canvas");
      canvas.id = `facade-chart-${gIdx}`;

      const scheduleEl = document.createElement("p");
      scheduleEl.className = "facade-window-schedule";

      const legendHint = document.createElement("p");
      legendHint.className = "facade-window-legend";
      legendHint.hidden = !showWindowBands;
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
      if (showForecast && fp && fp.points.length) {
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

      // Comparative façade temp: exterior high sensors (fallback any exterior).
      const seenFacadeAddr = new Set();
      group.rooms.forEach((room, idx) => {
        const fh = room.facade_history;
        if (!fh || !(fh.points || []).length) return;
        const addr = String(fh.address || "").toUpperCase();
        if (addr && seenFacadeAddr.has(addr)) return;
        if (addr) seenFacadeAddr.add(addr);
        const label =
          (fh.name || room.label || room.id) +
          (fh.height === "high" ? " (high)" : " (ext)");
        datasets.push(
          makeDataset(
            label,
            roomColor(`${room.id}-facade`, gIdx * 3 + idx + 8),
            fh.points.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
            false,
            { borderWidth: 2, borderDash: [8, 3] }
          )
        );
      });

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
        if (showForecast && rp) {
          const scenarios = rp.window_scenarios || {};
          const closedPts =
            (scenarios.windows_closed && scenarios.windows_closed.points) || [];
          const openPts =
            (scenarios.windows_open && scenarios.windows_open.points) || [];
          const coolPts =
            (scenarios.strategy_coolest &&
              scenarios.strategy_coolest.points) ||
            [];
          const warmPts =
            (scenarios.strategy_warmest &&
              scenarios.strategy_warmest.points) ||
            [];
          const showAuto = projectionScenario === "auto";
          const showClosed =
            projectionScenario === "closed" || projectionScenario === "both";
          const showOpen =
            projectionScenario === "open" || projectionScenario === "both";
          const showCoolest = projectionScenario === "coolest";
          const showWarmest = projectionScenario === "warmest";
          if (showAuto && (rp.points || []).length) {
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
          if (showClosed && closedPts.length) {
            datasets.push(
              makeDataset(
                `${labelBase} (windows closed)`,
                color,
                closedPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [8, 4], borderWidth: 1.35 }
              )
            );
          }
          if (showOpen && openPts.length) {
            datasets.push(
              makeDataset(
                `${labelBase} (windows open)`,
                color,
                openPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [2, 3], borderWidth: 1.35 }
              )
            );
          }
          if (showCoolest && coolPts.length) {
            datasets.push(
              makeDataset(
                `${labelBase} (coolest open/close)`,
                color,
                coolPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [6, 2], borderWidth: 1.75 }
              )
            );
          }
          if (showWarmest && warmPts.length) {
            datasets.push(
              makeDataset(
                `${labelBase} (warmest open/close)`,
                color,
                warmPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [4, 2, 1, 2], borderWidth: 1.75 }
              )
            );
          }
        }
      });

      const indoor = indoorSeriesForFacade(group.rooms);
      const allExterior = rooms.flatMap((r) => r.exterior || []);
      let bands = [];
      if (showWindowBands && indoor && indoor.series.length) {
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
        const detail = formatWindowScheduleDetail(bands);
        const basedOn = indoor.room
          ? `Based on ${indoor.room.label || indoor.room.id} vs outdoor air + wind (past + forecast)`
          : "";
        scheduleEl.title = [basedOn, detail].filter(Boolean).join("\n\n");
      } else if (!showWindowBands) {
        scheduleEl.textContent = "";
      } else {
        scheduleEl.textContent =
          "Window schedule unavailable (no interior sensor / history for this façade).";
      }

      const opts = structuredClone(chartDefaults);
      opts.plugins.windowBands = { bands: showWindowBands ? bands : [] };
      opts.plugins.legend.display = datasets.length > 1;
      // Compare-only: no drag-zoom on façade overview charts.
      if (opts.plugins.zoom) delete opts.plugins.zoom;
      if (!opts.scales) opts.scales = {};
      if (!opts.scales.x) opts.scales.x = {};
      opts.scales.x.min = axis.xMin;
      opts.scales.x.max = axis.xMax;

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
              · −${data.hours || hours} h / +${data.future_hours != null ? data.future_hours : hours} h
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
        title: t("notify.openTitle", { label }),
        body: t("notify.openBody", { out: dOut, in: dIn }),
      };
    }
    if (kind === "close") {
      return {
        title: t("notify.closeTitle", { label }),
        body: t("notify.closeBody", { out: dOut, in: dIn }),
      };
    }
    if (kind === "humid") {
      return {
        title: t("notify.humidTitle", { label }),
        body: t("notify.humidBody", { out: dOut }),
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
          ? t("banner.noRoomsContacts")
          : t("banner.noContacts"),
        detail: hasContacts
          ? t("banner.assignRooms")
          : t("banner.enableDoors"),
      };
    }

    const outT = Number(outdoorNow.temperature_c).toFixed(1);
    let climateBit = t("banner.outdoor", { temp: outT });
    if (outdoorNow.humidity != null && outdoorNow.humidity > 0) {
      const dew = dewPoint(outdoorNow.temperature_c, outdoorNow.humidity);
      climateBit += t("banner.dewRh", {
        dew: dew.toFixed(1),
        rh: Number(outdoorNow.humidity).toFixed(0),
      });
    }
    const openBit = openContactNames.length
      ? t("banner.openNow", { names: openContactNames.join(", ") })
      : t("banner.allClosed");

    const join = (arr) => arr.join(", ");

    let tone = "idle";
    let title = t("banner.noAction");
    let detail = t("banner.tempsClose", { climate: climateBit, open: openBit });

    if (closeNow.length) {
      tone = humidBias ? "humid" : "close";
      title = t("banner.closeTitle", { rooms: join(closeNow) });
      detail = humidBias
        ? t("banner.closeHumid", { climate: climateBit, open: openBit })
        : t("banner.closeWarm", { climate: climateBit, open: openBit });
      if (openNow.length) {
        detail = `${detail}${t("banner.alsoOpen", { rooms: join(openNow) })}`;
      }
    } else if (openNow.length) {
      tone = "open";
      title = t("banner.openTitle", { rooms: join(openNow) });
      detail = t("banner.openDetail", { climate: climateBit, open: openBit });
    } else if (okOpen.length) {
      tone = "ok";
      title = t("banner.okOpenTitle", { rooms: join(okOpen) });
      detail = t("banner.okOpenDetail", { climate: climateBit, open: openBit });
      if (okClosed.length) {
        detail = `${detail}${t("banner.closedOk", { rooms: join(okClosed) })}`;
      }
    } else if (okClosed.length) {
      tone = "ok";
      title = t("banner.okClosedTitle", { rooms: join(okClosed) });
      detail = t("banner.okClosedDetail", {
        climate: climateBit,
        open: openBit,
      });
    }

    return { hidden: false, tone, title, detail };
  }

  /** @type {string} Last visible alert-bar banner / notification text for TTS test. */
  let lastDisplayedAlertText = "";

  function rememberDisplayedAlert(title, detail) {
    const head = String(title || "").trim();
    const body = String(detail || "").trim();
    if (!head && !body) return;
    lastDisplayedAlertText = body ? `${head}. ${body}` : head;
  }

  function renderWindowBanner(model) {
    if (!windowBannerEl) return;
    if (!model || model.hidden) {
      windowBannerEl.hidden = true;
      windowBannerEl.className = "window-banner";
      windowBannerModel = null;
      syncTopBarTones();
      requestAnimationFrame(refreshViewsStickyState);
      return;
    }
    windowBannerEl.hidden = false;
    windowBannerEl.className = "window-banner";
    windowBannerModel = model;
    if (windowBannerTitleEl) windowBannerTitleEl.textContent = model.title || "";
    if (windowBannerDetailEl) windowBannerDetailEl.textContent = model.detail || "";
    rememberDisplayedAlert(model.title, model.detail);
    syncTopBarTones();
    // Banner height changes with content — refresh sticky offset under fixed top-bar.
    requestAnimationFrame(refreshViewsStickyState);
  }

  function formatDuration(seconds) {
    const s = Math.max(0, Math.round(Number(seconds) || 0));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    const rem = m % 60;
    return rem ? `${h}h ${rem}m` : `${h}h`;
  }

  function buildSystemBannerModel(health) {
    if (!health) return { hidden: true };
    if (!health.workers_available) {
      const age = health.workers_age_s;
      const ageBit =
        age == null
          ? t("banner.noHeartbeat")
          : t("banner.lastSeen", { age: formatDuration(age) });
      return {
        hidden: false,
        tone: "crit",
        title: t("banner.workersOffline"),
        detail: t("banner.workersDetail", { age: ageBit }),
      };
    }
    const ble = health.ble || {};
    if (ble.enabled === false || ble.ok !== false) {
      return { hidden: true };
    }
    if (ble.paused_for_gatt) {
      return { hidden: true };
    }
    const ageBit =
      ble.age_s == null
        ? t("banner.bleNoAdsStart")
        : t("banner.bleNoAdsFor", { age: formatDuration(ble.age_s) });
    return {
      hidden: false,
      tone: "warn",
      title: t("banner.bleStalled"),
      detail: t("banner.bleDetail", { age: ageBit }),
    };
  }

  function renderSystemBanner(model) {
    if (!systemBannerEl) return;
    if (!model || model.hidden) {
      systemBannerEl.hidden = true;
      systemBannerEl.className = "window-banner system-banner";
      systemBannerModel = null;
      lastSpokenSystemBannerTitle = null;
      syncTopBarTones();
      requestAnimationFrame(refreshViewsStickyState);
      return;
    }
    systemBannerEl.hidden = false;
    systemBannerEl.className = "window-banner system-banner";
    systemBannerModel = model;
    if (systemBannerTitleEl) systemBannerTitleEl.textContent = model.title || "";
    if (systemBannerDetailEl) systemBannerDetailEl.textContent = model.detail || "";
    rememberDisplayedAlert(model.title, model.detail);
    // Speak only on a fresh alert (not on every 30s poll while it stays active).
    if (model.title && model.title !== lastSpokenSystemBannerTitle) {
      speak(model.detail ? `${model.title}. ${model.detail}` : model.title);
      bumpBadge();
      lastSpokenSystemBannerTitle = model.title;
    }
    syncTopBarTones();
    requestAnimationFrame(refreshViewsStickyState);
  }

  function syncTopBarTones() {
    if (!topBarEl) return;
    const toneClasses = [
      "system-banner-tone-crit",
      "system-banner-tone-warn",
      "window-banner-tone-close",
      "window-banner-tone-open",
      "window-banner-tone-humid",
      "window-banner-tone-ok",
      "window-banner-tone-idle",
    ];
    topBarEl.classList.remove(...toneClasses);
    if (systemBannerModel && !systemBannerModel.hidden) {
      topBarEl.classList.add(
        `system-banner-tone-${systemBannerModel.tone || "warn"}`
      );
      return;
    }
    if (windowBannerModel && !windowBannerModel.hidden) {
      topBarEl.classList.add(
        `window-banner-tone-${windowBannerModel.tone || "idle"}`
      );
    }
  }

  async function updateSystemHealth() {
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      if (!res.ok) {
        renderSystemBanner({
          hidden: false,
          tone: "crit",
          title: "UI unreachable",
          detail: `Health check failed (HTTP ${res.status}).`,
        });
        return;
      }
      const data = await res.json();
      renderSystemBanner(buildSystemBannerModel(data));
    } catch (err) {
      renderSystemBanner({
        hidden: false,
        tone: "crit",
        title: "UI unreachable",
        detail: err.message || "Could not reach /api/health.",
      });
    }
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

  const BADGE_COUNT_KEY = "govee-charts.badgeCount";
  let badgeCount = parseInt(localStorage.getItem(BADGE_COUNT_KEY) || "0", 10) || 0;

  function applyBadge() {
    if (!("setAppBadge" in navigator)) return;
    try {
      if (badgeCount > 0) {
        navigator.setAppBadge(badgeCount).catch(() => {});
      } else if ("clearAppBadge" in navigator) {
        navigator.clearAppBadge().catch(() => {});
      }
    } catch (err) {
      console.warn("App badge failed", err);
    }
  }

  function bumpBadge() {
    // Only bump while the app/tab is in the background — no need to badge
    // something the user is already looking at.
    if (document.visibilityState === "visible" && document.hasFocus()) return;
    badgeCount += 1;
    localStorage.setItem(BADGE_COUNT_KEY, String(badgeCount));
    applyBadge();
  }

  function clearBadge() {
    if (badgeCount === 0) return;
    badgeCount = 0;
    localStorage.setItem(BADGE_COUNT_KEY, "0");
    applyBadge();
  }

  applyBadge();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") clearBadge();
  });
  window.addEventListener("focus", clearBadge);

  /** Promise-based permission request; call only from a user gesture on Safari. */
  function requestNotifyPermission() {
    const TIMEOUT_MS = 2500;
    return new Promise((resolve) => {
      let done = false;
      const finish = (perm) => {
        if (done) return;
        done = true;
        const out = perm || Notification.permission || "denied";
        console.info("[notify] permission result", out);
        resolve(out);
      };
      try {
        // Prefer promise API; always race a timeout (Safari can hang after OS Settings).
        const ret = Notification.requestPermission(finish);
        if (ret && typeof ret.then === "function") {
          ret.then(finish, () => finish(Notification.permission));
        }
      } catch (err) {
        console.warn("[notify] requestPermission failed", err);
        finish(Notification.permission || "denied");
        return;
      }
      setTimeout(() => {
        console.warn("[notify] requestPermission timed out", Notification.permission);
        finish(Notification.permission || "denied");
      }, TIMEOUT_MS);
    });
  }

  /** @type {ServiceWorkerRegistration|null} */
  let notifySwReg = null;

  async function ensureNotifyServiceWorker() {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) {
      return null;
    }
    try {
      if (notifySwReg && notifySwReg.active) return notifySwReg;
      const existing = await navigator.serviceWorker.getRegistration("/");
      if (existing) {
        notifySwReg = existing;
        return existing;
      }
      const ver = document.querySelector('script[src*="app.js"]')?.src.match(/[?&]v=([^&]+)/)?.[1];
      const url = ver ? `/sw.js?v=${encodeURIComponent(ver)}` : "/sw.js";
      notifySwReg = await navigator.serviceWorker.register(url, { scope: "/" });
      await navigator.serviceWorker.ready;
      return notifySwReg;
    } catch (err) {
      console.warn("Service worker registration failed", err);
      return null;
    }
  }

  // Register early so Safari standalone can show notifications via SW.
  if ("serviceWorker" in navigator && window.isSecureContext) {
    ensureNotifyServiceWorker().catch(() => {});
  }

  // browser-tts skill: Chromium lists Mac voices but often "ghost speaks"
  // (speaking=true, no onstart, silence). Prefer edge-tts there.
  const _ua = navigator.userAgent || "";
  const isChromium = /\bChrome\/|\bChromium\/|\bEdg\//.test(_ua);
  const isSafari = /\bSafari\//.test(_ua) && !isChromium;
  const useMacVoices = !isChromium && !!window.speechSynthesis;
  const EDGE_DEFAULT = { fr: "fr-FR-DeniseNeural", en: "en-US-JennyNeural" };

  /** @type {HTMLAudioElement|null} */
  let ttsAudioEl = null;
  /** @type {string|null} */
  let ttsObjectUrl = null;
  let ttsSpeakGen = 0;
  /** @type {Array<{id:string,locale:string,gender:string,name:string}>} */
  let edgeVoicesCache = [];
  let edgeVoicesLang = "";
  let homeTtsEnabled = false;
  const HOME_TTS_VOICE_ID = "home-tts";

  function ttsLog(...args) {
    console.info("[tts]", ...args);
  }

  function defaultEdgeVoice() {
    const lang = I18n.getLocale() === "en" ? "en" : "fr";
    return EDGE_DEFAULT[lang] || EDGE_DEFAULT.fr;
  }

  function isHomeTtsVoice(id) {
    return String(id || "") === HOME_TTS_VOICE_ID;
  }

  function browserVoiceId(voice) {
    return `browser:${encodeURIComponent(`${voice.name}||${voice.lang}`)}`;
  }

  function parseBrowserVoiceId(id) {
    if (!String(id || "").startsWith("browser:")) return null;
    try {
      const raw = decodeURIComponent(String(id).slice("browser:".length));
      const sep = raw.lastIndexOf("||");
      if (sep < 0) return null;
      return { name: raw.slice(0, sep), lang: raw.slice(sep + 2) };
    } catch (_) {
      return null;
    }
  }

  function migrateStoredTtsVoice() {
    // Old storage used raw voiceURI; Chromium Mac URIs must migrate to edge.
    const raw = ttsVoiceURI || "";
    if (!raw) {
      ttsVoiceURI = defaultEdgeVoice();
      try {
        localStorage.setItem(TTS_VOICE_KEY, ttsVoiceURI);
      } catch (_) {}
      return;
    }
    if (isHomeTtsVoice(raw)) return;
    if (raw.startsWith("browser:")) {
      if (!useMacVoices) {
        ttsLog("migrate browser voice → edge (Chromium)");
        ttsVoiceURI = defaultEdgeVoice();
        try {
          localStorage.setItem(TTS_VOICE_KEY, ttsVoiceURI);
        } catch (_) {}
      }
      return;
    }
    // Legacy voiceURI (not browser:/edge/home-tts id) → edge default on Chromium.
    if (!raw.includes("-") || raw.includes(" ") || raw.startsWith("com.")) {
      ttsLog("migrate legacy voiceURI → edge");
      ttsVoiceURI = defaultEdgeVoice();
      try {
        localStorage.setItem(TTS_VOICE_KEY, ttsVoiceURI);
      } catch (_) {}
    }
  }

  function stopTtsAudio() {
    if (ttsAudioEl) {
      try {
        ttsAudioEl.pause();
        ttsAudioEl.removeAttribute("src");
        ttsAudioEl.load();
      } catch (_) {}
    }
    if (ttsObjectUrl) {
      try {
        URL.revokeObjectURL(ttsObjectUrl);
      } catch (_) {}
      ttsObjectUrl = null;
    }
  }

  function cancelSpeechIfBusy() {
    const syn = window.speechSynthesis;
    // Skill: never cancel() when idle — breaks the next speak() on Chrome.
    if (syn && (syn.speaking || syn.pending)) {
      syn.cancel();
    }
  }

  function b64ToBlob(b64, mime) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: mime || "audio/mpeg" });
  }

  async function fetchEdgeVoices(lang) {
    const prefix = (lang || I18n.getLocale() || "fr").split("-")[0];
    if (edgeVoicesLang === prefix && edgeVoicesCache.length) {
      return edgeVoicesCache;
    }
    const res = await fetch(
      `/api/tts/voices?lang=${encodeURIComponent(prefix)}`
    );
    if (!res.ok) throw new Error(`tts voices HTTP ${res.status}`);
    const data = await res.json();
    edgeVoicesCache = Array.isArray(data.voices) ? data.voices : [];
    edgeVoicesLang = prefix;
    homeTtsEnabled = !!(data.home_tts && data.home_tts.enabled);
    if (data.default_voice && !ttsVoiceURI) {
      ttsVoiceURI = data.default_voice;
    }
    return edgeVoicesCache;
  }

  async function speakHomeTts(text, gen) {
    const lang = I18n.getLocale() === "en" ? "en" : "fr";
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        voice: HOME_TTS_VOICE_ID,
        lang,
      }),
    });
    if (gen !== ttsSpeakGen) return { spoken: false, reason: "interrupted" };
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (gen !== ttsSpeakGen) return { spoken: false, reason: "interrupted" };
    if (data.play_error) {
      ttsLog("home-tts play_error", data.play_error);
    }
    ttsLog("home-tts ok", {
      voice: data.voice,
      played: data.played,
      channel: data.channel,
      destinations: data.destinations,
      hasAudio: !!data.audio_base64,
    });
    // Emit-only: Bridge Outputs play the sound. Ignore debug audio_base64
    // so this tab never doubles Precision/Chrome listeners.
    return {
      spoken: true,
      reason: data.destinations
        ? "broadcast:" +
          (data.destinations || []).map((d) => d.id || d.label).join("+")
        : data.played
          ? ""
          : "emitted",
    };
  }

  async function speakEdge(text, voiceId, gen) {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        voice: voiceId || defaultEdgeVoice(),
      }),
    });
    if (gen !== ttsSpeakGen) return { spoken: false, reason: "interrupted" };
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (gen !== ttsSpeakGen) return { spoken: false, reason: "interrupted" };
    if (!data.audio_base64) throw new Error("empty audio");
    stopTtsAudio();
    const blob = b64ToBlob(data.audio_base64, data.mime || "audio/mpeg");
    ttsObjectUrl = URL.createObjectURL(blob);
    if (!ttsAudioEl) ttsAudioEl = new Audio();
    ttsAudioEl.src = ttsObjectUrl;
    ttsAudioEl.volume = 1;
    try {
      await ttsAudioEl.play();
    } catch (err) {
      if (err && err.name === "NotAllowedError") {
        ttsLog("audio blocked — need a user gesture");
        return { spoken: false, reason: "NotAllowedError" };
      }
      throw err;
    }
    return { spoken: true, reason: "" };
  }

  /**
   * Web Speech path (Safari / non-Chromium). Detects ghost speaking.
   * @returns {Promise<{spoken:boolean, ghost?:boolean, reason?:string}>}
   */
  function speakBrowser(text, voiceId) {
    return new Promise((resolve) => {
      if (!useMacVoices || !window.speechSynthesis) {
        resolve({ spoken: false, reason: "no mac voices" });
        return;
      }
      const syn = window.speechSynthesis;
      const utter = new SpeechSynthesisUtterance(text);
      const parsed = parseBrowserVoiceId(voiceId);
      let voice = null;
      if (parsed) {
        voice = syn
          .getVoices()
          .find(
            (v) =>
              v.name === parsed.name &&
              normalizeVoiceLang(v.lang) === normalizeVoiceLang(parsed.lang)
          );
      }
      utter.lang = voice ? voice.lang : I18n.speechLang();
      if (voice) utter.voice = voice;

      let started = false;
      let settled = false;
      const done = (result) => {
        if (settled) return;
        settled = true;
        resolve(result);
      };
      utter.onstart = () => {
        started = true;
        ttsLog("browser onstart");
      };
      utter.onend = () => done({ spoken: started, reason: started ? "" : "silent" });
      utter.onerror = (ev) => {
        const err = (ev && ev.error) || "error";
        if (err === "canceled" || err === "interrupted") {
          done({ spoken: false, reason: err });
          return;
        }
        done({ spoken: false, reason: err });
      };

      try {
        syn.speak(utter);
      } catch (err) {
        done({ spoken: false, reason: String(err) });
        return;
      }

      setTimeout(() => {
        if (started || settled) return;
        const ghost = syn.speaking || syn.pending;
        ttsLog("browser ghost/silent", { ghost, speaking: syn.speaking });
        if (ghost) cancelSpeechIfBusy();
        done({ spoken: false, ghost: !!ghost, reason: ghost ? "ghost" : "silent" });
      }, 700);
    });
  }

  async function speak(text, opts = {}) {
    const force = !!opts.force;
    if ((!ttsEnabled && !force) || !text) return;
    const cleaned = String(text).trim();
    if (!cleaned) return;

    ttsSpeakGen += 1;
    const gen = ttsSpeakGen;
    cancelSpeechIfBusy();
    stopTtsAudio();

    migrateStoredTtsVoice();
    let voiceId = ttsVoiceURI || defaultEdgeVoice();
    if (voiceId.startsWith("browser:") && !useMacVoices) {
      voiceId = defaultEdgeVoice();
    }
    if (isHomeTtsVoice(voiceId) && !homeTtsEnabled) {
      ttsLog("home-tts not configured — falling back to edge");
      voiceId = defaultEdgeVoice();
    }

    const engine = isHomeTtsVoice(voiceId)
      ? "home-tts"
      : voiceId.startsWith("browser:")
        ? "browser"
        : "edge";
    ttsLog("speak", {
      engine,
      voiceId,
      isChromium,
      useMacVoices,
    });

    try {
      if (isHomeTtsVoice(voiceId)) {
        await speakHomeTts(cleaned, gen);
        return;
      }
      if (voiceId.startsWith("browser:") && useMacVoices) {
        const result = await speakBrowser(cleaned, voiceId);
        if (gen !== ttsSpeakGen) return;
        if (result.spoken) return;
        if (result.ghost || result.reason === "silent") {
          ttsLog("fallback edge after ghost");
          await speakEdge(cleaned, defaultEdgeVoice(), gen);
        }
        return;
      }
      await speakEdge(cleaned, voiceId, gen);
    } catch (err) {
      console.warn("[tts] speak failed", err);
      // Chromium: never fall back to Web Speech if edge fails.
      // Home TTS: do not fall back to browser audio (user chose house speakers).
      if (
        useMacVoices &&
        !voiceId.startsWith("browser:") &&
        !isHomeTtsVoice(voiceId)
      ) {
        try {
          await speakBrowser(cleaned, null);
        } catch (err2) {
          console.warn("[tts] browser fallback failed", err2);
        }
      }
    }
  }

  /** @type {AudioContext|null} */
  let doorBeepAudioCtx = null;

  function beepDoor(opened) {
    if (!doorBeepEnabled) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      if (!doorBeepAudioCtx) doorBeepAudioCtx = new Ctx();
      const ctx = doorBeepAudioCtx;
      if (ctx.state === "suspended") ctx.resume().catch(() => {});
      const now = ctx.currentTime;
      // Two quick ascending notes for "open", one descending note for "close".
      const notes = opened ? [660, 880] : [660, 440];
      let t = now;
      for (const freq of notes) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        gain.gain.value = 0.0001;
        osc.connect(gain);
        gain.connect(ctx.destination);
        gain.gain.exponentialRampToValueAtTime(0.2, t + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.14);
        osc.start(t);
        osc.stop(t + 0.16);
        t += 0.15;
      }
    } catch (err) {
      console.warn("Door beep failed", err);
    }
  }

  function evaluateDoorBeeps(sensors) {
    for (const sensor of sensors) {
      const id = sensor.sensor_id;
      const state = sensor.state || "";
      const prev = doorBeepSeenStates.get(id);
      if (prev !== undefined && prev !== state && (state === "open" || state === "closed")) {
        beepDoor(state === "open");
        bumpBadge();
      }
      doorBeepSeenStates.set(id, state);
    }
  }

  let ttsVoicePollAttempts = 0;

  function normalizeVoiceLang(lang) {
    return String(lang || "")
      .toLowerCase()
      .replace(/_/g, "-");
  }

  function voiceMatchesLocale(voice, locale) {
    const lang = normalizeVoiceLang(voice.lang);
    return lang === locale || lang.startsWith(`${locale}-`);
  }

  function populateTtsVoiceOptions() {
    if (!ttsVoiceSelectEl) return;
    // Async fill (edge + optional Mac). Keep sync entry for voiceschanged.
    populateTtsVoiceOptionsAsync().catch((err) =>
      console.warn("[tts] populate voices failed", err)
    );
  }

  async function populateTtsVoiceOptionsAsync() {
    if (!ttsVoiceSelectEl) return;
    migrateStoredTtsVoice();
    const locale = I18n.getLocale();
    const previousValue = ttsVoiceSelectEl.value || ttsVoiceURI;

    let edgeVoices = [];
    try {
      edgeVoices = await fetchEdgeVoices(locale);
    } catch (err) {
      console.warn("[tts] edge voices unavailable", err);
    }

    /** @type {SpeechSynthesisVoice[]} */
    let macVoices = [];
    if (useMacVoices && window.speechSynthesis) {
      macVoices = window.speechSynthesis.getVoices();
      if (!macVoices.length && ttsVoicePollAttempts < 20) {
        ttsVoicePollAttempts += 1;
        setTimeout(populateTtsVoiceOptions, 250);
      } else {
        ttsVoicePollAttempts = 20;
      }
      macVoices = macVoices
        .filter((v) => voiceMatchesLocale(v, locale))
        .sort((a, b) =>
          `${a.lang} ${a.name}`.localeCompare(`${b.lang} ${b.name}`, locale)
        );
    }

    ttsVoiceSelectEl.innerHTML = "";

    if (homeTtsEnabled) {
      const homeGroup = document.createElement("optgroup");
      homeGroup.label = t("tts.groupHome");
      const homeOpt = document.createElement("option");
      homeOpt.value = HOME_TTS_VOICE_ID;
      homeOpt.textContent = t("tts.homeSpeakers");
      homeGroup.appendChild(homeOpt);
      ttsVoiceSelectEl.appendChild(homeGroup);
    }

    if (useMacVoices && macVoices.length) {
      const macGroup = document.createElement("optgroup");
      macGroup.label = t("tts.groupMac");
      for (const v of macVoices) {
        const opt = document.createElement("option");
        opt.value = browserVoiceId(v);
        opt.textContent = `${v.name} (${v.lang || "?"})`;
        macGroup.appendChild(opt);
      }
      ttsVoiceSelectEl.appendChild(macGroup);
    }

    const edgeGroup = document.createElement("optgroup");
    edgeGroup.label = t("tts.groupServer");
    if (!edgeVoices.length) {
      const opt = document.createElement("option");
      opt.value = defaultEdgeVoice();
      opt.textContent = defaultEdgeVoice();
      edgeGroup.appendChild(opt);
    } else {
      for (const v of edgeVoices) {
        const opt = document.createElement("option");
        opt.value = v.id;
        const short = v.id.replace(/^[a-z]{2}-[A-Z]{2}-/, "");
        const gender = v.gender ? ` · ${String(v.gender)[0]}` : "";
        opt.textContent = `${short} (${v.locale}${gender})`;
        edgeGroup.appendChild(opt);
      }
    }
    ttsVoiceSelectEl.appendChild(edgeGroup);

    const validIds = new Set(
      [...ttsVoiceSelectEl.querySelectorAll("option")].map((o) => o.value)
    );
    let wanted = previousValue || ttsVoiceURI || defaultEdgeVoice();
    if (wanted.startsWith("browser:") && !useMacVoices) {
      wanted = defaultEdgeVoice();
    }
    if (isHomeTtsVoice(wanted) && !homeTtsEnabled) {
      wanted = defaultEdgeVoice();
    }
    if (!validIds.has(wanted)) {
      wanted = defaultEdgeVoice();
      if (!validIds.has(wanted) && edgeVoices[0]) wanted = edgeVoices[0].id;
      if (!validIds.has(wanted) && homeTtsEnabled) wanted = HOME_TTS_VOICE_ID;
    }
    ttsVoiceURI = wanted;
    ttsVoiceSelectEl.value = wanted;
    try {
      localStorage.setItem(TTS_VOICE_KEY, ttsVoiceURI);
    } catch (_) {
      /* ignore */
    }
  }

  function sendWindowNotification(title, body, tag) {
    rememberDisplayedAlert(title, body);
    speak(body ? `${title}. ${body}` : title);
    bumpBadge();
    if (!("Notification" in window) || Notification.permission !== "granted") {
      return;
    }
    const opts = {
      body: body || "",
      tag: tag || "govee-window",
    };
    // Safari / WebKit PWA: prefer SW showNotification (new Notification is flaky).
    void (async () => {
      try {
        const reg = await ensureNotifyServiceWorker();
        if (reg && typeof reg.showNotification === "function") {
          await reg.showNotification(title, opts);
          return;
        }
      } catch (err) {
        console.warn("SW notification failed", err);
      }
      try {
        const n = new Notification(title, opts);
        n.onclick = () => {
          window.focus();
          n.close();
        };
      } catch (err) {
        console.warn("Notification failed", err);
      }
    })();
  }

  /**
   * Prefer one sensor per interior room (skip exterior / uncategorized).
   */
  function interiorRoomDevices() {
    // Build set of rooms that have at least one exterior façade orientation.
    // If apartment config isn't loaded yet, fall back to allowing all rooms
    // (conservative — avoids silently suppressing all notifications on first load).
    let windowedRooms = null;
    if (apartmentLastRooms && apartmentLastRooms.length) {
      windowedRooms = new Set(
        apartmentLastRooms
          .filter((r) => Array.isArray(r.exterior) && r.exterior.length > 0)
          .map((r) => String(r.id).toLowerCase())
      );
    }

    const byRoom = new Map();
    for (const d of devices) {
      const zone = (d.zone || "").toLowerCase();
      if (zone === "exterior") continue;
      const room = (d.room || "").toLowerCase();
      if (!room || room === "other") continue;
      if (d.temperature_c == null || d.humidity == null) continue;
      // Skip rooms that have no exterior windows configured.
      if (windowedRooms && !windowedRooms.has(room)) continue;
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
          t("notify.neutralTitle", { label }),
          t("notify.neutralBody", {
            in: tin.toFixed(1),
            out: text.toFixed(1),
          }),
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
        windowLegendEl.title = t("compare.windowLegendTitle", {
          label: deviceLabel,
          delta: WINDOW_DELTA_C,
        });
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
        // Heat-gain series can go negative while AC extracts heat.
        beginAtZero: false,
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
    const energy = snapshot && snapshot.energy;
    if (!climate && !power && !energy) {
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
    const acWatts =
      snapshot && snapshot.ac_watts != null
        ? `≈ ${Math.round(Number(snapshot.ac_watts))} W`
        : null;
    const watts =
      power && power.watts != null ? `${Math.round(Number(power.watts))} W` : "—";
    const roomBit =
      snapshot && snapshot.room
        ? ` <span class="muted">(${escapeHtml(String(snapshot.room))})</span>`
        : "";
    const when = climate && climate.ts
      ? new Date(climate.ts * 1000).toLocaleTimeString("en-GB")
      : power && power.ts
        ? new Date(power.ts * 1000).toLocaleTimeString("en-GB")
        : "";
    let energyHtml = "";
    if (energy && !energy.error) {
      const home =
        energy.home_kwh != null ? `${Number(energy.home_kwh).toFixed(2)} kWh` : "—";
      const wh =
        energy.water_heater_kwh != null
          ? `${Number(energy.water_heater_kwh).toFixed(2)} kWh`
          : "—";
      const ac =
        energy.ac_kwh != null ? `≈ ${Number(energy.ac_kwh).toFixed(2)} kWh` : "—";
      const heatMj =
        energy.heat_indoor_mj != null
          ? `${Number(energy.heat_indoor_mj).toFixed(1)} MJ`
          : "—";
      const heatKcal =
        energy.heat_indoor_kcal != null
          ? `≈ ${Math.round(Number(energy.heat_indoor_kcal))} kcal`
          : "";
      energyHtml = `
        <span class="hvac-energy">
          Today grid <strong>${escapeHtml(home)}</strong>
          · tank <strong>${escapeHtml(wh)}</strong>
          · AC <strong>${escapeHtml(ac)}</strong>
          · indoor heat <strong>${escapeHtml(heatMj)}</strong>${
            heatKcal ? ` <span class="muted">(${escapeHtml(heatKcal)})</span>` : ""
          }
        </span>`;
    }
    hvacStatusEl.innerHTML = `
      <span><span class="hvac-pill ${active ? "hvac-pill-on" : "hvac-pill-off"}">${
        active ? "AC on" : "AC off"
      }</span>${roomBit}</span>
      <span>Mode <strong>${escapeHtml(String(mode))}</strong></span>
      <span>Setpoint <strong>${escapeHtml(target)}</strong></span>
      <span>AC temp <strong>${escapeHtml(current)}</strong></span>
      ${
        acWatts
          ? `<span>AC power <strong title="Estimated from whole-home power minus baseline">${escapeHtml(
              acWatts
            )}</strong></span>`
          : ""
      }
      <span>Grid <strong>${escapeHtml(watts)}</strong></span>
      ${when ? `<span>Updated ${escapeHtml(when)}</span>` : ""}
      ${energyHtml}
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
    // Re-attach zoom callbacks (lost by structuredClone of function refs).
    for (const chart of [tempChart, humChart, dewChart]) {
      if (!chart.options.plugins) chart.options.plugins = {};
      chart.options.plugins.zoom = compareChartZoomOptions();
      bindCompareChartZoom(chart);
    }
    bindChartLegend(tempChart);
    bindChartLegend(humChart);
    bindChartLegend(dewChart);
  }

  /**
   * Build time-bucketed spread (max-min) series per room from loaded results.
   * @param {Array<{device: object, points: Array}>} results
   * @param {number} bucketMs  bucket width in milliseconds
   * @returns {Map<string, Array<{x:number, y:number}>>}  room → sorted points
   */
  /** room id → facade orientation key (e.g. "sw", "ne"), or "" if no exterior. */
  function facadeKeyForRoom(roomId) {
    const rid = String(roomId || "").toLowerCase();
    if (!rid || !apartmentLastRooms) return "";
    const room = apartmentLastRooms.find(
      (r) => String(r.id || "").toLowerCase() === rid
    );
    if (!room) return "";
    return networkFacadeKey(room);
  }

  function facadeDisplayLabel(key) {
    if (!key) return "";
    return key
      .split("+")
      .map((o) => o.toUpperCase())
      .join("+");
  }

  async function ensureApartmentRooms() {
    if (apartmentLastRooms && apartmentLastRooms.length) return;
    try {
      const res = await fetch("/api/apartment?hours=1");
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.rooms) apartmentLastRooms = data.rooms;
    } catch (_) {
      /* ignore */
    }
  }

  /**
   * Max−min temperature across all selected sensors that share a façade
   * (rooms with the same exterior orientation(s)).
   * Falls back to per-room max−min when apartment façades are unavailable.
   * Returns [{ key, label, pts }].
   */
  function computeFacadeSpread(results, bucketMs) {
    const avg = (arr) => arr.reduce((s, v) => s + v, 0) / arr.length;

    /** groupKey → bucket_ms → address → [temps] */
    const groups = new Map();
    const useFacades =
      apartmentLastRooms &&
      apartmentLastRooms.some(
        (r) => Array.isArray(r.exterior) && r.exterior.length > 0
      );

    for (const { device, points } of results) {
      const room = (device.room || "").trim().toLowerCase();
      if (!room) continue;
      let key;
      let label;
      if (useFacades) {
        key = facadeKeyForRoom(room);
        if (!key) continue; // rooms without windows are not façades
        label = facadeDisplayLabel(key);
      } else {
        key = `room:${room}`;
        label = room.charAt(0).toUpperCase() + room.slice(1);
      }
      if (!groups.has(key)) {
        groups.set(key, { label, buckets: new Map() });
      }
      const group = groups.get(key);
      const addr = device.address;
      for (const p of points) {
        if (p.temperature_c == null || !Number.isFinite(Number(p.temperature_c))) {
          continue;
        }
        const bucket = Math.floor((p.ts * 1000) / bucketMs) * bucketMs;
        if (!group.buckets.has(bucket)) group.buckets.set(bucket, new Map());
        const byAddr = group.buckets.get(bucket);
        if (!byAddr.has(addr)) byAddr.set(addr, []);
        byAddr.get(addr).push(Number(p.temperature_c));
      }
    }

    const series = [];
    for (const [key, group] of groups) {
      const pts = [];
      for (const [bucket, byAddr] of group.buckets) {
        if (byAddr.size < 2) continue;
        const sensorAvgs = [...byAddr.values()].map(avg);
        const spread = Math.max(...sensorAvgs) - Math.min(...sensorAvgs);
        pts.push({
          x: bucket + bucketMs / 2,
          y: Math.round(spread * 10) / 10,
        });
      }
      pts.sort((a, b) => a.x - b.x);
      if (pts.length) {
        series.push({ key, label: group.label, pts });
      }
    }
    series.sort((a, b) => a.label.localeCompare(b.label));
    return series;
  }

  const FACADE_SPREAD_COLORS = {
    sw: "#61afef",
    ne: "#98c379",
    nw: "#e5c07b",
    se: "#c678dd",
    n: "#56b6c2",
    s: "#e06c75",
    e: "#d19a66",
    w: "#abb2bf",
  };
  const FACADE_FALLBACK_COLORS = ["#e06c75", "#d19a66", "#be5046", "#5c6370"];

  function facadeSeriesColor(key, idx) {
    const primary = String(key || "").split("+")[0].toLowerCase();
    return (
      FACADE_SPREAD_COLORS[primary] ||
      FACADE_FALLBACK_COLORS[idx % FACADE_FALLBACK_COLORS.length]
    );
  }

  function ensureSpreadChart() {
    if (spreadChart) return;
    const canvas = document.getElementById("spread-chart");
    if (!canvas) return;
    const opts = structuredClone(chartDefaults);
    opts.scales.y = {
      ...opts.scales.y,
      min: 0,
      title: { display: true, text: "Δ°C", color: "#8a9a88" },
    };
    spreadChart = new Chart(canvas, {
      type: "line",
      data: { datasets: [] },
      options: opts,
    });
  }

  function renderSpread(results) {
    const section = document.getElementById("spread-section");
    if (!section) return;

    // Bucket width: ~120 pts → adapt to window span
    const span = isCustomRange()
      ? (customUntil - customSince) * 1000
      : hours * 3600 * 1000;
    const bucketMs = Math.max(
      5 * 60 * 1000,
      Math.round(span / 120 / (5 * 60 * 1000)) * 5 * 60 * 1000
    );

    const series = computeFacadeSpread(results, bucketMs);

    if (!series.length) {
      section.hidden = true;
      return;
    }

    ensureSpreadChart();
    if (!spreadChart) {
      section.hidden = true;
      return;
    }

    const titleEl = section.querySelector(".spread-title");
    const hintEl = section.querySelector(".spread-hint");
    const useFacades = series.some((s) => !String(s.key).startsWith("room:"));
    if (titleEl) {
      titleEl.setAttribute(
        "data-i18n",
        useFacades ? "compare.spread.titleFacade" : "compare.spread.title"
      );
      titleEl.textContent = t(
        useFacades ? "compare.spread.titleFacade" : "compare.spread.title"
      );
    }
    if (hintEl) {
      hintEl.setAttribute(
        "data-i18n",
        useFacades ? "compare.spread.hintFacade" : "compare.spread.hint"
      );
      hintEl.textContent = t(
        useFacades ? "compare.spread.hintFacade" : "compare.spread.hint"
      );
    }

    const datasets = series.map((s, idx) =>
      makeDataset(s.label, facadeSeriesColor(s.key, idx), s.pts, false, {
        borderWidth: 2.25,
        pointRadius: 0,
        spanGaps: true,
      })
    );

    spreadChart.data.datasets = datasets;
    spreadChart.options.plugins.legend.display = datasets.length > 1;

    const { xMin, xMax } = rangeAxisBounds();
    spreadChart.options.scales.x.min = xMin;
    spreadChart.options.scales.x.max = xMax;
    spreadChart.update();
    section.hidden = false;
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
    const stationBlock = (forecast && forecast.station) || {};
    rememberAvailableStations(stationBlock);
    const stationList = filterStationList(stationsFromBlock(stationBlock)).filter(
      (s) => s && s.enabled && (s.latest || (s.points || []).length)
    );
    const hasStation = stationList.length > 0;
    if ((!showForecast || !forecast || !forecast.enabled) && !hasStation) {
      clearProjections();
      return;
    }

    const cards = [];
    for (const station of stationList) {
      const latest =
        station.latest ||
        (station.points || []).slice().sort((a, b) => a.ts - b.ts).pop();
      const name = station.station_name || station.station_id || "Station";
      const t =
        latest && latest.temperature_c != null
          ? `${Number(latest.temperature_c).toFixed(1)} °C`
          : "—";
      const h =
        latest && latest.humidity != null
          ? `${Number(latest.humidity).toFixed(0)} %`
          : "—";
      const when =
        latest && latest.ts
          ? new Date(latest.ts * 1000).toLocaleTimeString("en-GB", {
              hour: "2-digit",
              minute: "2-digit",
            })
          : "";
      cards.push(`
        <article class="projection-card projection-weather">
          <h4>Station · ${escapeHtml(name)}</h4>
          <p class="projection-meta">
            Now <strong>${escapeHtml(t)}</strong>
            · RH <strong>${escapeHtml(h)}</strong>
            ${when ? ` · ${escapeHtml(when)}` : ""}
            · Météo-France
          </p>
        </article>
      `);
    }
    const loc = forecast && forecast.location;
    if (showForecast && forecast && forecast.enabled && loc && (forecast.outdoor || []).length) {
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

    const projections = (forecast && forecast.projections) || {};
    let projCount = 0;
    for (const device of showForecast ? selectedDevices() : []) {
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
      if (projectionScenario === "closed" && closed && closed.summary) {
        const cSrc =
          closed.source && closed.source !== "default" ? `/${closed.source}` : "";
        scenarioTxt =
          ` · closed${cSrc} ${Number(closed.summary.temp_min).toFixed(1)}–${Number(closed.summary.temp_max).toFixed(1)} °C`;
      } else if (projectionScenario === "open" && opened && opened.summary) {
        let oSrc = "";
        if (opened.source === "facade") oSrc = "/façade";
        else if (opened.source && opened.source !== "default") oSrc = `/${opened.source}`;
        scenarioTxt =
          ` · open${oSrc} ${Number(opened.summary.temp_min).toFixed(1)}–${Number(opened.summary.temp_max).toFixed(1)} °C`;
      } else if (
        projectionScenario === "both" &&
        closed &&
        closed.summary &&
        opened &&
        opened.summary
      ) {
        const cSrc =
          closed.source && closed.source !== "default" ? `/${closed.source}` : "";
        let oSrc = "";
        if (opened.source === "facade") oSrc = "/façade";
        else if (opened.source && opened.source !== "default") oSrc = `/${opened.source}`;
        scenarioTxt =
          ` · closed${cSrc} ${Number(closed.summary.temp_min).toFixed(1)}–${Number(closed.summary.temp_max).toFixed(1)} °C` +
          ` · open${oSrc} ${Number(opened.summary.temp_min).toFixed(1)}–${Number(opened.summary.temp_max).toFixed(1)} °C`;
      } else if (projectionScenario === "auto" && proj.opening_state) {
        scenarioTxt = ` · opening ${proj.opening_state}`;
      } else if (projectionScenario === "coolest") {
        const cool = scenarios.strategy_coolest;
        if (cool && cool.summary) {
          const openH =
            cool.summary.hours_open != null
              ? ` · ${cool.summary.hours_open}h open`
              : "";
          scenarioTxt =
            ` · coolest ${Number(cool.summary.temp_min).toFixed(1)}–${Number(cool.summary.temp_max).toFixed(1)} °C${openH}`;
        }
      } else if (projectionScenario === "warmest") {
        const warm = scenarios.strategy_warmest;
        if (warm && warm.summary) {
          const openH =
            warm.summary.hours_open != null
              ? ` · ${warm.summary.hours_open}h open`
              : "";
          scenarioTxt =
            ` · warmest ${Number(warm.summary.temp_min).toFixed(1)}–${Number(warm.summary.temp_max).toFixed(1)} °C${openH}`;
        }
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
      if (hasStation) {
        bits.push(
          stationList.length === 1
            ? stationList[0].station_name || "station"
            : `${stationList.length} stations`
        );
      }
      if (showForecast && loc && (forecast.outdoor || []).length) bits.push("weather");
      if (projCount) bits.push(`${projCount} sensor${projCount === 1 ? "" : "s"}`);
      foldProjectionsMetaEl.textContent = bits.length ? `· ${bits.join(" · ")}` : "";
    }
  }

  async function fetchForecast(addresses) {
    await requestBrowserGeo(false);
    const params = new URLSearchParams({
      // Past outdoor for bands / alignment; future horizon is independent.
      // Open-Meteo forecast max is 16 d (384 h).
      hours: String(Math.min(rangeSpanHours(), 384)),
      future_hours: String(forecastFutureHours),
    });
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

  function formatBytes(n) {
    const v = Number(n);
    if (!Number.isFinite(v) || v < 0) return "—";
    if (v < 1024) return `${Math.round(v)} B`;
    if (v < 1024 * 1024) return `${(v / 1024).toFixed(v < 10 * 1024 ? 1 : 0)} KB`;
    if (v < 1024 * 1024 * 1024) {
      return `${(v / (1024 * 1024)).toFixed(v < 10 * 1024 * 1024 ? 1 : 0)} MB`;
    }
    return `${(v / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function formatSampleCount(n) {
    const v = Number(n) || 0;
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 10_000) return `${Math.round(v / 1000)}k`;
    if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
    return String(v);
  }

  function makeFedPushMetaBtn(device) {
    if (!federationPeers.length) return null;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "restart-btn overview-fed-push";
    btn.textContent = t("overview.pushMeta");
    btn.title = t("overview.pushMetaTitle");
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      btn.disabled = true;
      const prev = btn.textContent;
      btn.textContent = t("overview.pushing");
      try {
        const res = await fetch(
          `/api/devices/${encodeURIComponent(device.address)}/push-meta`,
          { method: "POST" }
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(
            typeof data.detail === "string"
              ? data.detail
              : `HTTP ${res.status}`
          );
        }
        const peers = Array.isArray(data.peers) ? data.peers : [];
        const okN = peers.filter((p) => p.ok).length;
        const fail = peers.filter((p) => !p.ok);
        if (fail.length) {
          const bits = fail.map(
            (p) =>
              `${p.url || "peer"}: ${p.detail || p.status || "failed"}`
          );
          overviewStatus.textContent = t("overview.metaPushedFail", {
            ok: okN,
            total: peers.length,
            fail: bits.join("; "),
          });
        } else {
          overviewStatus.textContent = t("overview.metaPushedOk", {
            ok: okN,
            name: deviceLabel(device),
          });
        }
        btn.textContent =
          okN === peers.length ? t("overview.pushed") : t("overview.partial");
        setTimeout(() => {
          btn.textContent = prev;
          btn.disabled = false;
        }, 1500);
      } catch (err) {
        console.error(err);
        overviewStatus.textContent = t("overview.metaPushFailed", {
          error: err.message,
        });
        btn.textContent = prev;
        btn.disabled = false;
      }
    });
    return btn;
  }

  function labeledCategorySelect(device, field, options, label) {
    const wrap = document.createElement("label");
    wrap.className = "overview-cat-field";
    const caption = document.createElement("span");
    caption.textContent = label;
    wrap.append(caption, makeCategorySelect(device, field, options));
    return wrap;
  }

  function labeledDeviceNameInput(device) {
    const input = document.createElement("input");
    input.type = "text";
    input.className = "device-name-input";
    input.maxLength = 80;
    input.placeholder = device.ble_name || device.address || t("overview.namePlaceholder");
    input.title = t("overview.nameTitle");
    input.value = deviceLabel(device);
    input.dataset.address = device.address;
    input.addEventListener("click", (ev) => ev.stopPropagation());
    input.addEventListener("mousedown", (ev) => ev.stopPropagation());
    input.addEventListener("keydown", (ev) => {
      ev.stopPropagation();
      if (ev.key === "Enter") {
        ev.preventDefault();
        input.blur();
      }
      if (ev.key === "Escape") {
        ev.preventDefault();
        input.value = deviceLabel(device);
        input.blur();
      }
    });
    input.addEventListener("change", async (ev) => {
      ev.stopPropagation();
      const raw = String(input.value || "").trim();
      // Empty clears the override and falls back to BLE / config name.
      const value = raw === "" ? null : raw;
      input.disabled = true;
      try {
        const res = await fetch(
          `/api/devices/${encodeURIComponent(device.address)}/categories`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label: value }),
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
        input.value = deviceLabel(device);
        overviewStatus.textContent = t("overview.nameFailed", {
          error: err.message,
        });
      } finally {
        input.disabled = false;
      }
    });
    return input;
  }

  function labeledHeightCmInput(device) {
    const wrap = document.createElement("label");
    wrap.className = "overview-cat-field overview-cat-field-cm";
    const caption = document.createElement("span");
    caption.textContent = t("overview.heightCm");
    const input = document.createElement("input");
    input.type = "number";
    input.className = "cat-input cat-input-cm";
    input.min = "0";
    input.max = "600";
    input.step = "1";
    input.placeholder = "cm";
    input.title = t("overview.heightCmTitle");
    input.dataset.address = device.address;
    input.dataset.field = "height_cm";
    if (device.height_cm != null && Number.isFinite(Number(device.height_cm))) {
      input.value = String(Math.round(Number(device.height_cm)));
    } else {
      input.value = "";
    }
    suppressScrollValueChange(input);
    input.addEventListener("click", (ev) => ev.stopPropagation());
    input.addEventListener("mousedown", (ev) => ev.stopPropagation());
    input.addEventListener("keydown", (ev) => ev.stopPropagation());
    input.addEventListener("change", async (ev) => {
      ev.stopPropagation();
      const raw = String(input.value || "").trim();
      const value = raw === "" ? null : Number(raw);
      const previous =
        device.height_cm != null && Number.isFinite(Number(device.height_cm))
          ? Math.round(Number(device.height_cm))
          : null;
      if (value === previous || (value == null && previous == null)) return;
      if (value != null && (!Number.isFinite(value) || value < 0 || value > 600)) {
        overviewStatus.textContent = t("overview.heightCmInvalid");
        input.value = previous != null ? String(previous) : "";
        return;
      }
      input.disabled = true;
      try {
        const res = await fetch(
          `/api/devices/${encodeURIComponent(device.address)}/categories`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ height_cm: value }),
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
        input.value =
          device.height_cm != null && Number.isFinite(Number(device.height_cm))
            ? String(Math.round(Number(device.height_cm)))
            : "";
        overviewStatus.textContent = t("overview.catFailed", {
          error: err.message,
        });
      } finally {
        input.disabled = false;
      }
    });
    wrap.append(caption, input);
    return wrap;
  }

  function updateOverview() {
    overviewBody.innerHTML = "";
    updateSortButtons();
    const visible = overviewVisibleDevices();
    if (!devices.length) {
      overviewBody.innerHTML = `<p class="overview-empty">${escapeHtml(
        t("overview.noDevices")
      )}</p>`;
      overviewStatus.textContent = t("overview.waitingBle");
      return;
    }
    if (!visible.length) {
      overviewBody.innerHTML = `<p class="overview-empty">${escapeHtml(
        t("overview.noSensorsFilter")
      )}</p>`;
      overviewStatus.textContent = t("overview.statusFiltered", {
        shown: 0,
        total: devices.length,
      });
      return;
    }

    const ranked = sortedDevices(visible);
    for (const device of ranked) {
      const card = document.createElement("article");
      card.className = "overview-card";
      card.style.setProperty("--device-color", colorFor(device.address));
      const source = device.last_source || "—";

      const top = document.createElement("div");
      top.className = "overview-card-top";

      const identity = document.createElement("div");
      identity.className = "overview-card-identity";
      const nameRow = document.createElement("span");
      nameRow.className = "overview-name";
      const swatch = document.createElement("span");
      swatch.className = "device-swatch";
      swatch.setAttribute("aria-hidden", "true");
      nameRow.append(swatch, labeledDeviceNameInput(device));
      const meta = document.createElement("span");
      meta.className = "overview-meta";
      meta.textContent = `${device.model || "—"} · ${device.address}`;
      identity.append(nameRow, meta);

      const readings = document.createElement("div");
      readings.className = "overview-card-readings";
      readings.innerHTML =
        `<span class="overview-card-temp temp">${escapeHtml(
          fmtNum(device.temperature_c, 1, " °C")
        )}</span>` +
        `<span class="overview-card-hum">${escapeHtml(
          fmtNum(device.humidity, 1, " %")
        )}</span>`;

      const chartsBtn = document.createElement("button");
      chartsBtn.type = "button";
      chartsBtn.className = "restart-btn overview-charts-btn";
      chartsBtn.textContent = t("overview.charts");
      chartsBtn.title = t("overview.chartsTitle");
      chartsBtn.setAttribute(
        "aria-label",
        t("overview.chartsAria", {
          name: device.name || device.address,
        })
      );
      chartsBtn.addEventListener("click", () => {
        selected = new Set([device.address]);
        persistSelection();
        fillDeviceList();
        updateCurrent();
        setView("compare");
        loadHistory().catch((err) => {
          statusEl.textContent = t("compare.error", { error: err.message });
        });
      });
      readings.appendChild(chartsBtn);

      top.append(identity, readings);

      const place = document.createElement("div");
      place.className = "overview-card-place";
      place.append(
        labeledCategorySelect(
          device,
          "zone",
          taxonomyData.zones,
          t("overview.zone")
        ),
        labeledCategorySelect(
          device,
          "height",
          taxonomyData.heights,
          t("overview.height")
        ),
        labeledHeightCmInput(device),
        labeledCategorySelect(
          device,
          "room",
          taxonomyData.rooms,
          t("overview.room")
        )
      );
      const fedPush = makeFedPushMetaBtn(device);
      if (fedPush) {
        const pushWrap = document.createElement("div");
        pushWrap.className = "overview-cat-field overview-cat-field-push";
        const caption = document.createElement("span");
        caption.textContent = t("overview.federation");
        pushWrap.append(caption, fedPush);
        place.appendChild(pushWrap);
      }

      const foot = document.createElement("div");
      foot.className = "overview-card-foot";
      const footLeft = document.createElement("div");
      footLeft.className = "overview-card-foot-left rssi-cell";
      footLeft.innerHTML =
        `<span>${escapeHtml(
          t("overview.battery", {
            value:
              device.battery != null ? `${Number(device.battery)} %` : "—",
          })
        )}</span>` + `<span>${rssiHtml(device.rssi)}</span>`;
      const footRight = document.createElement("div");
      footRight.className = "overview-card-foot-right";
      footRight.innerHTML =
        `<span class="overview-source">${sourceHtml(source)}</span>` +
        `<span class="overview-meta">${escapeHtml(
          fmtTime(device.last_reading_ts || device.last_seen)
        )}</span>`;
      foot.append(footLeft, footRight);

      card.append(top, place, foot);
      overviewBody.appendChild(card);
    }

    const temps = ranked
      .map((d) => d.temperature_c)
      .filter((t) => t != null && !Number.isNaN(t));
    const span =
      temps.length >= 2
        ? ` · Δ ${(Math.max(...temps) - Math.min(...temps)).toFixed(1)} °C`
        : "";
    const activeCats = ["zone", "height", "room"].flatMap((k) => catFilters[k]);
    const textQ = String(overviewTextFilter || "").trim();
    const filterNote = [
      ...activeModels.map((m) => m.toUpperCase()),
      ...activeCats,
      textQ ? `“${textQ}”` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    overviewStatus.textContent =
      (ranked.length === devices.length
        ? t("overview.statusCountSame", { n: ranked.length })
        : t("overview.statusCount", {
            shown: ranked.length,
            total: devices.length,
          })) +
      `${filterNote ? ` · ${filterNote}` : ""}${span}` +
      t("overview.updatedAt", {
        time: new Date().toLocaleTimeString(I18n.localeTag()),
      });
  }

  function updateCurrent() {
    currentEl.innerHTML = "";
    const picked = selectedDevices();
    if (foldCurrentMetaEl) {
      foldCurrentMetaEl.textContent = picked.length
        ? picked.length === 1
          ? t("compare.sensorsMeta", { n: picked.length })
          : t("compare.sensorsMetaPlural", { n: picked.length })
        : t("compare.noneSelected");
    }
    if (!picked.length) {
      const empty = document.createElement("div");
      empty.className = "metric metric-empty";
      empty.innerHTML =
        `<span class="metric-label">${escapeHtml(t("compare.selection"))}</span>` +
        `<span class="metric-value metric-time">${escapeHtml(
          t("compare.noDevicesMetric")
        )}</span>`;
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
            <span class="metric-label">${escapeHtml(t("compare.metric.temp"))}</span>
            <span class="metric-value">${fmtNum(device.temperature_c, 1, " °C")}</span>
          </div>
          <div class="metric">
            <span class="metric-label">${escapeHtml(t("compare.metric.humidity"))}</span>
            <span class="metric-value">${fmtNum(device.humidity, 1, " %")}</span>
          </div>
          <div class="metric">
            <span class="metric-label">${escapeHtml(t("compare.metric.dew"))}</span>
            <span class="metric-value">${
              device.temperature_c != null && device.humidity != null && device.humidity > 0
                ? fmtNum(dewPoint(device.temperature_c, device.humidity), 1, " °C")
                : "—"
            }</span>
          </div>
          <div class="metric">
            <span class="metric-label">${escapeHtml(t("compare.metric.battery"))}</span>
            <span class="metric-value">${device.battery != null ? `${device.battery} %` : "—"}</span>
          </div>
          <div class="metric">
            <span class="metric-label">${escapeHtml(t("compare.metric.signal"))}</span>
            <span class="metric-value metric-rssi">${rssiHtml(device.rssi)}</span>
          </div>
          <div class="metric">
            <span class="metric-label">${escapeHtml(t("compare.metric.last"))}</span>
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
      deviceList.innerHTML = `<p class="device-empty">${escapeHtml(
        t("compare.noDevices")
      )}</p>`;
      selected = new Set();
      return;
    }
    if (!visible.length) {
      deviceList.innerHTML = `<p class="device-empty">${escapeHtml(
        t("compare.noSensorsModel")
      )}</p>`;
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
    // Keep selection of filtered-out devices; only auto-pick among visible ones.
    if (!selectedVisible.length) {
      selected.add(visible[0].address);
    }

    // Build façade group buttons: one button per shared exterior orientation.
    const facadeGroupBtns = document.getElementById("facade-group-btns");
    if (facadeGroupBtns) {
      facadeGroupBtns.innerHTML = "";
      /** facadeKey → Set of addresses */
      const facadeAddrs = new Map();
      const useFacades =
        apartmentLastRooms &&
        apartmentLastRooms.some(
          (r) => Array.isArray(r.exterior) && r.exterior.length > 0
        );

      for (const d of visible) {
        const room = (d.room || "").toLowerCase();
        if (!room) continue;
        let key;
        let label;
        if (useFacades) {
          key = facadeKeyForRoom(room);
          if (!key) continue;
          label = facadeDisplayLabel(key);
        } else {
          // Fallback: rooms that have both interior and exterior sensors
          const roomDevices = visible.filter(
            (x) => (x.room || "").toLowerCase() === room
          );
          const hasIn = roomDevices.some(
            (x) => (x.zone || "").toLowerCase() !== "exterior"
          );
          const hasOut = roomDevices.some(
            (x) => (x.zone || "").toLowerCase() === "exterior"
          );
          if (!hasIn || !hasOut) continue;
          key = `room:${room}`;
          label = room.charAt(0).toUpperCase() + room.slice(1);
        }
        if (!facadeAddrs.has(key)) {
          facadeAddrs.set(key, { label, addrs: new Set() });
        }
        facadeAddrs.get(key).addrs.add(d.address);
      }

      if (facadeAddrs.size) {
        const prefix = document.createElement("span");
        prefix.className = "facade-group-label";
        prefix.textContent = t("compare.facade.groupLabel");
        facadeGroupBtns.appendChild(prefix);

        for (const [key, { label, addrs }] of facadeAddrs) {
          if (addrs.size < 2) continue;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "facade-group-btn";
          btn.textContent = label;
          btn.title = t("compare.facade.groupTitle", { room: label });
          btn.addEventListener("click", () => {
            for (const d of visible) {
              if (addrs.has(d.address)) selected.add(d.address);
              else selected.delete(d.address);
            }
            fillDeviceList();
            persistSelection();
            updateCurrent();
            loadHistory().catch((err) => {
              statusEl.textContent = `Error: ${err.message}`;
            });
          });
          facadeGroupBtns.appendChild(btn);
        }
        facadeGroupBtns.hidden = facadeGroupBtns.querySelectorAll("button").length === 0;
      } else {
        facadeGroupBtns.hidden = true;
      }
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
    renderWidgetCurveList();
  }

  function syncWidgetRangeFromCompare() {
    if (widgetPastEl) {
      const past = isCustomRange()
        ? Math.max(1, Math.round((customUntil - customSince) / 3600))
        : hours;
      const pastOpt = [...widgetPastEl.options].find(
        (o) => Number(o.value) === Number(past)
      );
      if (pastOpt) {
        widgetPastEl.value = pastOpt.value;
      } else if (past > 0) {
        let best = widgetPastEl.options[0];
        let bestDiff = Infinity;
        for (const o of widgetPastEl.options) {
          const d = Math.abs(Number(o.value) - past);
          if (d < bestDiff) {
            bestDiff = d;
            best = o;
          }
        }
        widgetPastEl.value = best.value;
      }
    }
    if (widgetFutureEl) {
      const fut = Number(forecastFutureHours) || 0;
      const futOpt = [...widgetFutureEl.options].find(
        (o) => Number(o.value) === fut
      );
      if (futOpt) widgetFutureEl.value = futOpt.value;
    }
    if (widgetForecastEl) {
      widgetForecastEl.checked =
        !!showForecast && Number(widgetFutureEl?.value || 0) > 0;
    }
  }

  function renderWidgetCurveList() {
    if (!widgetCurveListEl) return;
    const visible = filteredDevices();
    const previous = new Set(widgetSelected);
    widgetCurveListEl.innerHTML = "";
    if (!visible.length) {
      widgetSelected = new Set();
      updateWidgetExport();
      return;
    }
    const known = new Set(visible.map((d) => d.address));
    widgetSelected = new Set([...previous].filter((a) => known.has(a)));
    if (!widgetSelected.size) {
      for (const d of selectedDevices()) widgetSelected.add(d.address);
    }
    if (!widgetSelected.size && visible[0]) {
      widgetSelected.add(visible[0].address);
    }

    for (const d of visible) {
      const id = `widget-curve-${d.address.replaceAll(":", "")}`;
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.id = id;
      input.value = d.address;
      input.checked = widgetSelected.has(d.address);
      input.addEventListener("change", () => {
        if (input.checked) widgetSelected.add(d.address);
        else widgetSelected.delete(d.address);
        updateWidgetExport();
      });
      const text = document.createElement("span");
      text.textContent = deviceLabel(d);
      text.style.color = colorFor(d.address);
      label.append(input, text);
      widgetCurveListEl.appendChild(label);
    }
    updateWidgetExport();
  }

  function buildWidgetUrl() {
    const addrs = [...widgetSelected];
    if (!addrs.length) return "";
    const q = new URLSearchParams();
    q.set("metric", (widgetMetricEl && widgetMetricEl.value) || "temp");
    q.set("addr", addrs.join(","));
    q.set("past", String((widgetPastEl && widgetPastEl.value) || "24"));
    const future = Number((widgetFutureEl && widgetFutureEl.value) || 0);
    q.set("future", String(future));
    const forecastOn =
      widgetForecastEl && widgetForecastEl.checked && future > 0;
    q.set("forecast", forecastOn ? "1" : "0");
    q.set(
      "transparent",
      widgetTransparentEl && widgetTransparentEl.checked ? "1" : "0"
    );
    q.set("legend", widgetLegendEl && !widgetLegendEl.checked ? "0" : "1");
    const refresh = Number((widgetRefreshEl && widgetRefreshEl.value) || 0);
    if (refresh > 0) q.set("refresh", String(refresh));
    // Bake GPS into the share URL so embeds / OBS don't need localStorage.
    if (
      forecastOn &&
      browserGeo &&
      Number.isFinite(browserGeo.latitude) &&
      Number.isFinite(browserGeo.longitude)
    ) {
      q.set("lat", String(browserGeo.latitude));
      q.set("lon", String(browserGeo.longitude));
    }
    return `${window.location.origin}/widget?${q.toString()}`;
  }

  function updateWidgetExport() {
    if (!widgetUrlEl) return;
    const url = buildWidgetUrl();
    widgetUrlEl.value = url;
    if (widgetOpenBtn) {
      widgetOpenBtn.href = url || "/widget";
      widgetOpenBtn.toggleAttribute("aria-disabled", !url);
    }
    if (widgetExportStatusEl) {
      widgetExportStatusEl.textContent = url
        ? ""
        : t("compare.widget.needCurves");
    }
    if (widgetPreviewEl) {
      if (widgetPreviewTimer) clearTimeout(widgetPreviewTimer);
      widgetPreviewTimer = setTimeout(() => {
        if (!url) {
          widgetPreviewEl.removeAttribute("src");
          return;
        }
        if (foldWidgetExportEl && !foldWidgetExportEl.open) return;
        if (widgetPreviewEl.getAttribute("src") !== url) {
          widgetPreviewEl.src = url;
        }
      }, 350);
    }
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
    await ensureApartmentRooms();
    fillDeviceList();
    populateCoverageDevices();
    updateOverview();
    updateCurrent();
    await loadDoors();
  }

  async function fetchHistory(address) {
    const params = new URLSearchParams({
      address,
    });
    if (isCustomRange()) {
      params.set("since", String(customSince));
      params.set("until", String(customUntil));
    } else {
      params.set("hours", String(hours));
    }
    const res = await fetch(`/api/history?${params}`);
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
      const spreadSec = document.getElementById("spread-section");
      if (spreadSec) spreadSec.hidden = true;
      statusEl.textContent = t("compare.selectDevice");
      historyLoaded = true;
      return;
    }

    const overlayHours = rangeOverlayHours();
    const hvacPromise = showHvac
      ? Promise.all([
          fetch(`/api/hvac`).then(async (res) =>
            res.ok ? res.json() : { climate: null, power: null, active: false }
          ),
          fetch(`/api/hvac/history?hours=${overlayHours}`).then(async (res) =>
            res.ok ? res.json() : { events: [], bands: [] }
          ),
          fetch(`/api/power/history?hours=${overlayHours}`).then(async (res) =>
            res.ok ? res.json() : { points: [] }
          ),
          fetch(`/api/energy/summary?hours=${overlayHours}`).then(async (res) =>
            res.ok ? res.json() : { enabled: false, heat_gain_w: [] }
          ),
        ]).catch((err) => {
          console.warn(err);
          return [
            { climate: null, power: null, active: false },
            { events: [], bands: [] },
            { points: [] },
            { enabled: false, heat_gain_w: [] },
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

    if (
      (forecast && forecast.enabled) ||
      (forecast &&
        forecast.station &&
        (forecast.station.enabled ||
          (Array.isArray(forecast.station.stations) &&
            forecast.station.stations.some((s) => s && s.enabled))))
    ) {
      const outdoor = (forecast && forecast.outdoor) || [];
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

      const stationBlock = forecast.station || {};
      rememberAvailableStations(stationBlock);
      const stationList = filterStationList(stationsFromBlock(stationBlock));
      const stationColors = ["#6fbf73", "#e8a838", "#5dade2", "#af7ac5"];
      stationList.forEach((station, idx) => {
        const stationPts = (station && station.points) || [];
        if (!station || !station.enabled || !stationPts.length) return;
        const stName = station.station_name || station.station_id || "Station";
        const stColor = stationColors[idx % stationColors.length];
        tempDatasets.push(
          makeDataset(
            `${stName} (station)`,
            stColor,
            stationPts
              .filter((p) => p.temperature_c != null)
              .map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
            false,
            { borderWidth: 2.25, pointRadius: 2 }
          )
        );
        const humPts = stationPts.filter(
          (p) => p.humidity != null && Number.isFinite(Number(p.humidity))
        );
        if (humPts.length) {
          humDatasets.push(
            makeDataset(
              `${stName} (station)`,
              stColor,
              humPts.map((p) => ({ x: p.ts * 1000, y: p.humidity })),
              false,
              { borderWidth: 2.25, pointRadius: 2 }
            )
          );
          dewDatasets.push(
            makeDataset(
              `${stName} (station)`,
              stColor,
              humPts
                .filter((p) => p.temperature_c != null && p.humidity > 0)
                .map((p) => ({
                  x: p.ts * 1000,
                  y: dewPoint(p.temperature_c, p.humidity),
                })),
              false,
              { borderWidth: 2.25, pointRadius: 2 }
            )
          );
        }
      });

      if (showForecast && forecast.enabled) {
        const projections = forecast.projections || {};
        const showAuto = projectionScenario === "auto";
        const showClosed =
          projectionScenario === "closed" || projectionScenario === "both";
        const showOpen =
          projectionScenario === "open" || projectionScenario === "both";
        const showCoolest = projectionScenario === "coolest";
        const showWarmest = projectionScenario === "warmest";
        for (const { device } of results) {
          const proj = projections[device.address];
          if (!proj) continue;
          const color = colorFor(device.address);
          const scenarios = proj.window_scenarios || {};
          const closedPts =
            (scenarios.windows_closed && scenarios.windows_closed.points) || [];
          const openPts =
            (scenarios.windows_open && scenarios.windows_open.points) || [];
          const coolPts =
            (scenarios.strategy_coolest &&
              scenarios.strategy_coolest.points) ||
            [];
          const warmPts =
            (scenarios.strategy_warmest &&
              scenarios.strategy_warmest.points) ||
            [];

          if (showAuto && (proj.points || []).length) {
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
          }

          if (showClosed && closedPts.length) {
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
          if (showOpen && openPts.length) {
            const openSrc =
              scenarios.windows_open && scenarios.windows_open.source === "facade"
                ? "windows open · façade"
                : "windows open";
            tempDatasets.push(
              makeDataset(
                `${deviceLabel(device)} (${openSrc})`,
                color,
                openPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [1, 3], borderWidth: 1.85 }
              )
            );
          }
          if (showCoolest && coolPts.length) {
            tempDatasets.push(
              makeDataset(
                `${deviceLabel(device)} (coolest open/close)`,
                color,
                coolPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [6, 2], borderWidth: 1.75 }
              )
            );
          }
          if (showWarmest && warmPts.length) {
            tempDatasets.push(
              makeDataset(
                `${deviceLabel(device)} (warmest open/close)`,
                color,
                warmPts.map((p) => ({ x: p.ts * 1000, y: p.temperature_c })),
                false,
                { borderDash: [4, 2, 1, 2], borderWidth: 1.75 }
              )
            );
          }
        }
      }
    }

    let hvacExtra = "";
    if (showHvac && hvacBundle) {
      const [snapshot, hvacHist, powerHist, energyHist] = hvacBundle;
      renderHvacStatus(snapshot);
      const bands = (hvacHist && hvacHist.bands) || [];
      setTempHvacBands(bands);
      const powerPoints = (powerHist && powerHist.points) || [];
      const heatGain = (energyHist && energyHist.heat_gain_w) || [];
      if (powerPoints.length || heatGain.length) {
        setTempPowerScale(true);
        if (powerPoints.length) {
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
        }
        if (heatGain.length) {
          tempDatasets.push(
            makeDataset(
              "Heat gain (indoor)",
              "#c4782a",
              heatGain.map((p) => ({ x: p.ts * 1000, y: p.watts })),
              false,
              {
                yAxisID: "yPower",
                borderWidth: 1.75,
                borderDash: [2, 2],
              }
            )
          );
        }
      } else {
        setTempPowerScale(false);
      }
      if (bands.length || powerPoints.length || heatGain.length) {
        hvacExtra =
          ` · AC bands×${bands.length}` +
          (powerPoints.length ? `, power ${powerPoints.length} pt` : "") +
          (heatGain.length ? `, heat ${heatGain.length} pt` : "");
      }
    } else {
      renderHvacStatus(null);
      setTempHvacBands([]);
      setTempPowerScale(false);
    }

    await ensureApartmentRooms();
    renderSpread(results);

    tempChart.data.datasets = withLegendState("temp", tempDatasets);
    humChart.data.datasets = withLegendState("hum", humDatasets);
    dewChart.data.datasets = withLegendState("dew", dewDatasets);
    const showLegend = tempDatasets.length > 1;
    tempChart.options.plugins.legend.display = showLegend;
    humChart.options.plugins.legend.display = showLegend;
    dewChart.options.plugins.legend.display = showLegend;

    // Lock the X axis to the selected window so empty history is visible
    // (otherwise Chart.js zooms to the first available sample).
    let { xMin, xMax } = rangeAxisBounds();
    if (!isCustomRange()) {
      for (const ds of tempDatasets) {
        for (const p of ds.data || []) {
          if (p && Number(p.x) > xMax) xMax = Number(p.x);
        }
      }
    }
    suppressChartRangeSync = true;
    try {
      for (const chart of [tempChart, humChart, dewChart]) {
        if (!chart || !chart.options.scales || !chart.options.scales.x) continue;
        chart.options.scales.x.min = xMin;
        chart.options.scales.x.max = xMax;
      }
    } finally {
      suppressChartRangeSync = false;
    }

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
    renderProjections(forecast);
    historyLoaded = true;
    evaluateWindowNotifications(forecast).catch((err) => console.warn(err));
    updateWindowBanner(forecast).catch((err) => console.warn(err));

    const totalPoints = results.reduce((n, r) => n + r.points.length, 0);
    const names = results.map((r) => deviceLabel(r.device)).join(", ");
    let extra = "";
    if (forecast && forecast.enabled && forecast.location) {
      const src =
        forecast.location.source === "browser"
          ? t("compare.forecastGps")
          : t("compare.forecastConfig");
      const cache = forecast.cache_hit
        ? forecast.stale
          ? t("compare.forecastStale")
          : t("compare.forecastCached")
        : "";
      extra = t("compare.forecastLoc", {
        name: forecast.location.name,
        src,
        cache,
      });
    } else if (forecast && forecast.error) {
      extra = t("compare.forecastOffError", { error: forecast.error });
    } else if (showForecast && forecast && !forecast.enabled) {
      extra = t("compare.forecastOffHint");
    }
    statusEl.textContent = t("compare.status", {
      names,
      points: totalPoints,
      range: formatRangeLabel(),
      extra,
      window: windowExtra,
      hvac: hvacExtra,
      time: new Date().toLocaleTimeString(I18n.localeTag()),
    });
  }

  async function refresh() {
    try {
      await updateSystemHealth();
      await loadFederation();
      await loadDevices();
      if (currentView === "compare") {
        await loadHistory();
      } else if (currentView === "facades") {
        await loadFacades();
        await updateWindowBanner(null);
      } else if (currentView === "network") {
        await loadNetwork();
      } else if (currentView === "coverage") {
        await loadCoverage();
      } else if (currentView === "backfill") {
        await loadBackfill();
      } else {
        const bannerPromise = updateWindowBanner(null);
        if (windowNotify) {
          if (!apartmentLastRooms) {
            fetch("/api/apartment?hours=1")
              .then((r) => r.ok ? r.json() : null)
              .then((d) => { if (d && d.rooms) apartmentLastRooms = d.rooms; })
              .catch(() => {});
          }
          await evaluateWindowNotifications(null);
        }
        await bannerPromise;
      }
    } catch (err) {
      console.error(err);
      const msg = t("common.error", { error: err.message });
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
    // Keep widget curves in sync with Compare selection when the export panel
    // is closed (user is still picking sensors); leave manual picks alone when open.
    if (!foldWidgetExportEl || !foldWidgetExportEl.open) {
      widgetSelected = new Set(selected);
      renderWidgetCurveList();
    }
    loadHistory().catch((err) => {
      statusEl.textContent = `Error: ${err.message}`;
    });
  }

  viewButtons.forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      setView(btn.dataset.view, { url: "push" });
    });
  });

  if (dataMegaToggle) {
    dataMegaToggle.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (DATA_VIEWS.has(currentView)) {
        // Already in Data — toggle the submenu only.
        setDataMegaOpen(!isDataMegaOpen());
        return;
      }
      setView("coverage", { url: "push" });
    });
  }

  document.addEventListener("click", (ev) => {
    if (!dataMegaEl || !isDataMegaOpen()) return;
    if (DATA_VIEWS.has(currentView)) return;
    if (dataMegaEl.contains(ev.target)) return;
    setDataMegaOpen(false);
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape" || !isDataMegaOpen()) return;
    if (DATA_VIEWS.has(currentView)) return;
    setDataMegaOpen(false);
  });

  window.addEventListener("popstate", () => {
    const fromPath = pathToView(window.location.pathname) || "overview";
    setView(fromPath, { url: "none" });
  });

  let mapFontScaleResizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(mapFontScaleResizeTimer);
    mapFontScaleResizeTimer = setTimeout(() => {
      applyMapFontScale(sectionSvgEl, SECTION_VB_W);
      applyMapFontScale(networkSvgEl, NETWORK_VB_W / networkZoom);
    }, 150);
  });

  if (networkZoomInBtn) {
    networkZoomInBtn.addEventListener("click", () => {
      setNetworkZoom(networkZoom * 1.25);
    });
  }
  if (networkZoomOutBtn) {
    networkZoomOutBtn.addEventListener("click", () => {
      setNetworkZoom(networkZoom / 1.25);
    });
  }
  if (networkZoomResetBtn) {
    networkZoomResetBtn.addEventListener("click", () => {
      networkZoom = 1;
      centerNetworkPan();
      applyNetworkViewBox();
    });
  }
  networkMetricButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      setNetworkMapMetric(btn.dataset.mapMetric);
    });
  });

  function getMapChatSessionId() {
    try {
      // Prefer persistent localStorage; migrate leftover sessionStorage once.
      const fromLocal = localStorage.getItem(MAP_CHAT_SESSION_KEY);
      if (fromLocal) return fromLocal;
      const fromSession = sessionStorage.getItem(MAP_CHAT_SESSION_KEY);
      if (fromSession) {
        localStorage.setItem(MAP_CHAT_SESSION_KEY, fromSession);
        sessionStorage.removeItem(MAP_CHAT_SESSION_KEY);
        return fromSession;
      }
    } catch (_) {
      /* ignore */
    }
    return "";
  }

  function setMapChatSessionId(id) {
    const sid = String(id || "").trim();
    try {
      if (sid) localStorage.setItem(MAP_CHAT_SESSION_KEY, sid);
      else localStorage.removeItem(MAP_CHAT_SESSION_KEY);
      sessionStorage.removeItem(MAP_CHAT_SESSION_KEY);
    } catch (_) {
      /* ignore */
    }
  }

  function formatMapChatSessionWhen(ts) {
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return "—";
    try {
      return new Date(n * 1000).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return "—";
    }
  }

  function formatMapChatMessageWhen(ts) {
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return "";
    try {
      const d = new Date(n * 1000);
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      return d.toLocaleString(undefined, sameDay
        ? { hour: "2-digit", minute: "2-digit" }
        : {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          });
    } catch (_) {
      return "";
    }
  }

  function mapChatMessageBodyEl(el) {
    if (!el) return null;
    return el.querySelector(":scope > .map-chat-msg-body") || el;
  }

  function setMapChatMessageTime(el, createdAt) {
    if (!el) return;
    let timeEl = el.querySelector(":scope > .map-chat-msg-time");
    const n = Number(createdAt);
    if (!Number.isFinite(n) || n <= 0) {
      if (timeEl) {
        timeEl.hidden = true;
        timeEl.textContent = "";
        timeEl.removeAttribute("datetime");
      }
      delete el.dataset.createdAt;
      return;
    }
    if (!timeEl) {
      timeEl = document.createElement("time");
      timeEl.className = "map-chat-msg-time";
      el.insertBefore(timeEl, el.firstChild);
    }
    timeEl.hidden = false;
    timeEl.dateTime = new Date(n * 1000).toISOString();
    timeEl.textContent = formatMapChatMessageWhen(n);
    el.dataset.createdAt = String(n);
  }

  function setMapChatControlsEnabled(on) {
    if (mapChatInputEl) mapChatInputEl.disabled = !on || mapChatBusy;
    if (mapChatSendBtn) mapChatSendBtn.disabled = !on || mapChatBusy;
    if (mapChatSessionEl) mapChatSessionEl.disabled = !on || mapChatBusy;
    if (mapChatClearBtn) {
      const hasSession = Boolean(getMapChatSessionId());
      const hasLog = Boolean(mapChatLogEl && mapChatLogEl.children.length);
      mapChatClearBtn.disabled = mapChatBusy || (!hasSession && !hasLog);
    }
  }

  function currentWindowBannerPayload() {
    if (!windowBannerModel) return { hidden: true, tone: "idle", title: "", detail: "" };
    return {
      hidden: Boolean(windowBannerModel.hidden),
      tone: windowBannerModel.tone || "idle",
      title: windowBannerModel.title || "",
      detail: windowBannerModel.detail || "",
    };
  }

  function sanitizeMapChatHtml(html) {
    const tmp = document.createElement("div");
    tmp.innerHTML = String(html || "");
    tmp.querySelectorAll("script,style,iframe,object,embed,link,meta").forEach((n) => n.remove());
    tmp.querySelectorAll("*").forEach((n) => {
      [...n.attributes].forEach((attr) => {
        const name = attr.name || "";
        const value = attr.value || "";
        if (/^on/i.test(name) || (name === "href" && /^\s*javascript:/i.test(value))) {
          n.removeAttribute(name);
        }
      });
    });
    return tmp.innerHTML;
  }

  function renderMapChatMarkdown(src) {
    const text = String(src || "");
    if (!text) return "";
    if (typeof marked === "undefined" || typeof marked.parse !== "function") {
      return escapeHtml(text).replaceAll("\n", "<br>");
    }
    try {
      const html = marked.parse(text, { breaks: true, gfm: true, async: false });
      return sanitizeMapChatHtml(html);
    } catch (_) {
      return escapeHtml(text).replaceAll("\n", "<br>");
    }
  }

  function setMapChatMessageBody(el, role, text, { pending = false } = {}) {
    if (!el) return;
    const bodyEl = mapChatMessageBodyEl(el);
    if (!bodyEl) return;
    const body = text || "";
    if (pending || role !== "assistant") {
      bodyEl.classList.remove("map-chat-md");
      bodyEl.textContent = body;
      return;
    }
    bodyEl.classList.add("map-chat-md");
    bodyEl.innerHTML = renderMapChatMarkdown(body);
  }

  function appendMapChatMessage(role, text, { pending = false, createdAt = null } = {}) {
    if (!mapChatLogEl) return null;
    // Assistant replies may contain block markdown (lists/tables); use a div.
    const el = document.createElement("div");
    el.className = `map-chat-msg ${role}${pending ? " pending" : ""}`;
    const timeEl = document.createElement("time");
    timeEl.className = "map-chat-msg-time";
    el.appendChild(timeEl);
    const bodyEl = document.createElement("div");
    bodyEl.className = "map-chat-msg-body";
    el.appendChild(bodyEl);
    setMapChatMessageTime(el, createdAt);
    setMapChatMessageBody(el, role, text, { pending });
    mapChatLogEl.appendChild(el);
    mapChatLogEl.scrollTop = mapChatLogEl.scrollHeight;
    return el;
  }

  function appendMapChatContext({ banner, snapshot } = {}) {
    if (!mapChatLogEl) return;
    const details = document.createElement("details");
    details.className = "map-chat-context";
    const summary = document.createElement("summary");
    summary.textContent = t("map.chat.context");
    details.appendChild(summary);
    const bannerBox = document.createElement("p");
    bannerBox.className = "map-chat-context-banner";
    if (banner && !banner.hidden && (banner.title || banner.detail)) {
      const title = document.createElement("strong");
      title.textContent = banner.title || "";
      bannerBox.appendChild(title);
      if (banner.detail) {
        bannerBox.appendChild(document.createTextNode(` — ${banner.detail}`));
      }
    } else {
      bannerBox.textContent = t("map.chat.bannerHidden");
    }
    details.appendChild(bannerBox);
    if (snapshot) {
      const pre = document.createElement("pre");
      pre.textContent =
        typeof snapshot === "string"
          ? snapshot
          : JSON.stringify(snapshot, null, 2);
      details.appendChild(pre);
    }
    mapChatLogEl.appendChild(details);
    mapChatLogEl.scrollTop = mapChatLogEl.scrollHeight;
  }

  function renderMapChatExchange(ex) {
    const createdAt = ex.created_at;
    appendMapChatMessage("user", ex.user_message || "", { createdAt });
    appendMapChatContext({ banner: ex.banner, snapshot: ex.snapshot });
    if (ex.error) {
      appendMapChatMessage(
        "assistant",
        t("map.chat.error", { error: ex.error }),
        { createdAt }
      );
    } else if (ex.assistant_message) {
      appendMapChatMessage("assistant", ex.assistant_message, { createdAt });
    }
  }

  async function refreshMapChatSessions({ selectId } = {}) {
    if (!mapChatSessionEl) return;
    const current = selectId != null ? String(selectId) : getMapChatSessionId();
    try {
      const res = await fetch("/api/map-chat/sessions?limit=40");
      if (!res.ok) return;
      const data = await res.json();
      const sessions = data.sessions || [];
      mapChatSessionEl.innerHTML = "";
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = t("map.chat.sessionNew");
      mapChatSessionEl.appendChild(blank);
      for (const s of sessions) {
        const opt = document.createElement("option");
        opt.value = s.session_id;
        opt.textContent = t("map.chat.sessionLabel", {
          when: formatMapChatSessionWhen(s.updated_at),
          n: String(s.turn_count || 0),
          preview: s.preview || s.session_id.slice(0, 8),
        });
        mapChatSessionEl.appendChild(opt);
      }
      if (current && [...mapChatSessionEl.options].some((o) => o.value === current)) {
        mapChatSessionEl.value = current;
      } else {
        mapChatSessionEl.value = "";
      }
      mapChatSessionsLoaded = true;
    } catch (err) {
      console.warn("map chat sessions load failed", err);
    }
  }

  async function loadMapChatHistory(sessionId) {
    if (!mapChatLogEl) return;
    const sid = String(sessionId || getMapChatSessionId() || "").trim();
    if (!sid) {
      mapChatLogEl.innerHTML = "";
      return;
    }
    try {
      const params = new URLSearchParams({
        session_id: sid,
        limit: "100",
        include_snapshot: "1",
      });
      const res = await fetch(`/api/map-chat/history?${params}`);
      if (!res.ok) return;
      const data = await res.json();
      const exchanges = data.exchanges || [];
      mapChatLogEl.innerHTML = "";
      for (const ex of exchanges) {
        renderMapChatExchange(ex);
      }
      setMapChatControlsEnabled(mapChatReady);
    } catch (err) {
      console.warn("map chat history load failed", err);
    }
  }

  async function selectMapChatSession(sessionId) {
    const sid = String(sessionId || "").trim();
    setMapChatSessionId(sid);
    if (mapChatSessionEl) mapChatSessionEl.value = sid;
    if (!sid) {
      if (mapChatLogEl) mapChatLogEl.innerHTML = "";
      setMapChatControlsEnabled(mapChatReady);
      return;
    }
    await loadMapChatHistory(sid);
    setMapChatControlsEnabled(mapChatReady);
  }

  function setMapChatStatus(text, { error = false } = {}) {
    if (!mapChatStatusEl) return;
    mapChatStatusEl.textContent = text || "";
    mapChatStatusEl.classList.toggle("is-error", Boolean(error));
  }

  async function ensureMapChatStatus() {
    if (!foldMapChatEl) return;
    if (!mapChatStatusLoaded) {
      setMapChatStatus(t("map.chat.checking"));
      try {
        const res = await fetch("/api/map-chat/status");
        const data = await res.json();
        mapChatStatusLoaded = true;
        if (!data.enabled) {
          mapChatReady = false;
          setMapChatStatus(t("map.chat.disabled"), { error: true });
          setMapChatControlsEnabled(false);
          return;
        }
        if (!data.agent_found) {
          mapChatReady = false;
          setMapChatStatus(t("map.chat.missingAgent"), { error: true });
          setMapChatControlsEnabled(false);
          return;
        }
        if (!data.ready) {
          mapChatReady = false;
          setMapChatStatus(t("map.chat.notLoggedIn"), { error: true });
          setMapChatControlsEnabled(false);
          return;
        }
        mapChatReady = true;
        mapChatModel = data.model || "auto";
        setMapChatStatus(t("map.chat.ready", { model: mapChatModel }));
        if (mapChatMetaEl) {
          mapChatMetaEl.textContent = mapChatModel;
        }
        setMapChatControlsEnabled(true);
      } catch (err) {
        mapChatReady = false;
        setMapChatStatus(t("map.chat.error", { error: err.message || String(err) }), {
          error: true,
        });
        setMapChatControlsEnabled(false);
        return;
      }
    }
    if (!mapChatReady) return;
    await refreshMapChatSessions();
    const sid = getMapChatSessionId();
    if (sid && mapChatLogEl && !mapChatLogEl.children.length) {
      await loadMapChatHistory(sid);
    }
  }

  async function sendMapChatMessage(raw) {
    const message = String(raw || "").trim();
    if (!message || !mapChatReady || mapChatBusy) return;
    mapChatBusy = true;
    setMapChatControlsEnabled(true);
    const banner = currentWindowBannerPayload();
    const provisionalAt = Date.now() / 1000;
    const userEl = appendMapChatMessage("user", message, {
      createdAt: provisionalAt,
    });
    appendMapChatContext({ banner });
    if (mapChatInputEl) mapChatInputEl.value = "";
    const assistantEl = appendMapChatMessage("assistant", t("map.chat.busy"), {
      pending: true,
      createdAt: provisionalAt,
    });
    setMapChatStatus(t("map.chat.busy"));
    const sessionId = getMapChatSessionId();
    let gotText = false;
    try {
      const res = await fetch("/api/map-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: sessionId || null,
          banner,
        }),
      });
      if (!res.ok) {
        let detail = res.statusText;
        try {
          const errBody = await res.json();
          detail = errBody.detail || detail;
        } catch (_) {
          /* ignore */
        }
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let outSession = sessionId;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const dataLine = chunk
            .split("\n")
            .map((l) => l.trim())
            .find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          let ev;
          try {
            ev = JSON.parse(dataLine.slice(5).trim());
          } catch (_) {
            continue;
          }
          if (ev.session_id) {
            outSession = ev.session_id;
            setMapChatSessionId(ev.session_id);
          }
          if (ev.type === "delta" && ev.text) {
            if (assistantEl.classList.contains("pending")) {
              assistantEl.classList.remove("pending");
              assistantEl.dataset.raw = "";
            }
            assistantEl.dataset.raw = (assistantEl.dataset.raw || "") + ev.text;
            setMapChatMessageBody(assistantEl, "assistant", assistantEl.dataset.raw);
            gotText = true;
            if (mapChatLogEl) mapChatLogEl.scrollTop = mapChatLogEl.scrollHeight;
          } else if (ev.type === "done") {
            if (ev.session_id) {
              outSession = ev.session_id;
              setMapChatSessionId(ev.session_id);
            }
            if (!gotText && ev.text) {
              assistantEl.classList.remove("pending");
              assistantEl.dataset.raw = ev.text;
              setMapChatMessageBody(assistantEl, "assistant", ev.text);
              gotText = true;
            } else if (gotText && assistantEl.dataset.raw) {
              setMapChatMessageBody(assistantEl, "assistant", assistantEl.dataset.raw);
            }
          } else if (ev.type === "saved") {
            if (ev.session_id) {
              outSession = ev.session_id;
              setMapChatSessionId(ev.session_id);
            }
            if (ev.created_at != null) {
              setMapChatMessageTime(userEl, ev.created_at);
              setMapChatMessageTime(assistantEl, ev.created_at);
            }
          } else if (ev.type === "error") {
            throw new Error(ev.message || "map chat failed");
          }
        }
      }
      if (!gotText) {
        assistantEl.classList.remove("pending");
        const bodyEl = mapChatMessageBodyEl(assistantEl);
        if (bodyEl) {
          bodyEl.classList.remove("map-chat-md");
          bodyEl.textContent = "…";
        }
      }
      setMapChatStatus(t("map.chat.ready", { model: mapChatModel }));
      await refreshMapChatSessions({ selectId: outSession });
    } catch (err) {
      if (assistantEl) {
        assistantEl.classList.remove("pending");
        const bodyEl = mapChatMessageBodyEl(assistantEl);
        if (bodyEl) {
          bodyEl.classList.remove("map-chat-md");
          bodyEl.textContent = t("map.chat.error", {
            error: err.message || String(err),
          });
        }
      }
      setMapChatStatus(
        t("map.chat.error", { error: err.message || String(err) }),
        { error: true }
      );
    } finally {
      mapChatBusy = false;
      setMapChatControlsEnabled(mapChatReady);
    }
  }

  if (mapChatFormEl) {
    mapChatFormEl.addEventListener("submit", (ev) => {
      ev.preventDefault();
      sendMapChatMessage(mapChatInputEl ? mapChatInputEl.value : "");
    });
  }
  if (mapChatInputEl) {
    mapChatInputEl.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        sendMapChatMessage(mapChatInputEl.value);
      }
    });
  }
  if (mapChatSessionEl) {
    mapChatSessionEl.addEventListener("change", () => {
      selectMapChatSession(mapChatSessionEl.value).catch((err) =>
        console.warn(err)
      );
    });
  }
  if (mapChatClearBtn) {
    mapChatClearBtn.addEventListener("click", () => {
      selectMapChatSession("").catch((err) => console.warn(err));
      refreshMapChatSessions({ selectId: "" }).catch((err) => console.warn(err));
    });
  }
  if (foldMapChatEl) {
    foldMapChatEl.addEventListener("toggle", () => {
      localStorage.setItem(FOLD_MAP_CHAT_KEY, foldMapChatEl.open ? "1" : "0");
      if (foldMapChatEl.open) {
        ensureMapChatStatus().catch((err) => console.warn(err));
      }
    });
  }

  if (sectionShowSmallEl) {
    sectionShowSmallEl.addEventListener("change", () => {
      setSectionShowSmall(sectionShowSmallEl.checked);
    });
  }
  if (sectionPathClearBtn) {
    sectionPathClearBtn.addEventListener("click", () => {
      clearSectionWaypoints();
    });
  }
  mapRoomRangeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const h = Number(btn.dataset.mapHours);
      if (!Number.isFinite(h) || h <= 0) return;
      mapRoomHours = h;
      mapRoomRangeButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (selectedMapRoomId) {
        loadMapRoomCharts().catch((err) => {
          if (mapRoomChartsStatusEl) {
            mapRoomChartsStatusEl.textContent = `Error: ${err.message}`;
          }
        });
      }
    });
  });
  if (mapRoomChartsCloseBtn) {
    mapRoomChartsCloseBtn.addEventListener("click", () => {
      clearMapRoomSelection();
    });
  }
  if (networkCanvasWrapEl && networkSvgEl) {
    // Drag-pan and wheel-zoom disabled: keep the map fixed.
    // Use the +/- / reset buttons to change zoom.
  }

  deviceList.addEventListener("change", onSelectionChange);

  selectAllBtn.addEventListener("click", () => {
    const visible = filteredDevices();
    for (const d of visible) {
      selected.add(d.address);
    }
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
    const visibleAddrs = new Set(filteredDevices().map((d) => d.address));
    selected = new Set([...selected].filter((a) => !visibleAddrs.has(a)));
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

  if (overviewDeviceFilterEl) {
    overviewDeviceFilterEl.addEventListener("input", () => {
      overviewTextFilter = overviewDeviceFilterEl.value || "";
      localStorage.setItem(OVERVIEW_TEXT_FILTER_KEY, overviewTextFilter);
      updateOverview();
    });
  }

  rangeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      setRelativeRange(btn.dataset.hours);
      reloadRangeDependentViews();
    });
  });

  function bindRangeSelect(selectEl, customEl, sinceEl, untilEl) {
    if (!selectEl) return;
    selectEl.addEventListener("change", () => {
      const val = selectEl.value;
      if (!val) {
        setRelativeRange(24);
        reloadRangeDependentViews();
        return;
      }
      if (val === "custom") {
        const until = Date.now() / 1000;
        const since = until - (Number(hours) || 24) * 3600;
        if (customEl) customEl.hidden = false;
        if (sinceEl) sinceEl.value = toDatetimeLocalValue(since);
        if (untilEl) untilEl.value = toDatetimeLocalValue(until);
        rangeButtons.forEach((b) => b.classList.remove("active"));
        selectEl.classList.add("active");
        if (rangeSelectEl && selectEl !== rangeSelectEl) {
          rangeSelectEl.value = "custom";
          rangeSelectEl.classList.add("active");
        }
        if (facadeRangeSelectEl && selectEl !== facadeRangeSelectEl) {
          facadeRangeSelectEl.value = "custom";
          facadeRangeSelectEl.classList.add("active");
        }
        return;
      }
      setRelativeRange(Number(val), { fromSelect: true });
      reloadRangeDependentViews();
    });
  }

  bindRangeSelect(rangeSelectEl, rangeCustomEl, rangeSinceEl, rangeUntilEl);
  bindRangeSelect(
    facadeRangeSelectEl,
    facadeRangeCustomEl,
    facadeRangeSinceEl,
    facadeRangeUntilEl
  );

  function bindRangeApply(btn, sinceEl, untilEl, statusTarget) {
    if (!btn) return;
    let lastEdited = "until";
    if (sinceEl) {
      sinceEl.addEventListener("change", () => {
        lastEdited = "since";
        coerceCustomBoundInputs(sinceEl, untilEl, "since");
      });
    }
    if (untilEl) {
      untilEl.addEventListener("change", () => {
        lastEdited = "until";
        coerceCustomBoundInputs(sinceEl, untilEl, "until");
      });
    }
    btn.addEventListener("click", () => {
      const coerced = coerceCustomBoundInputs(sinceEl, untilEl, lastEdited);
      const since =
        coerced?.since ?? fromDatetimeLocalValue(sinceEl && sinceEl.value);
      const until =
        coerced?.until ?? fromDatetimeLocalValue(untilEl && untilEl.value);
      if (since == null || until == null) {
        if (statusTarget) {
          statusTarget.textContent = "Choose valid From / To dates";
        }
        return;
      }
      if (!setCustomRange(since, until)) {
        if (statusTarget) {
          statusTarget.textContent =
            "Custom range must be between a minute and 3 years";
        }
        return;
      }
      reloadRangeDependentViews();
    });
  }

  bindRangeApply(rangeApplyBtn, rangeSinceEl, rangeUntilEl, statusEl);
  bindRangeApply(
    facadeRangeApplyBtn,
    facadeRangeSinceEl,
    facadeRangeUntilEl,
    facadeStatusEl
  );

  if (rangeResetZoomBtn) {
    rangeResetZoomBtn.addEventListener("click", () => {
      resetCompareZoom();
    });
  }

  if (showForecastEl) {
    showForecastEl.checked = showForecast;
    showForecastEl.addEventListener("change", () => {
      showForecast = showForecastEl.checked;
      localStorage.setItem(FORECAST_KEY, showForecast ? "1" : "0");
      if (!showForecast) clearProjections();
      syncForecastToggleControls();
      updateGeoStatus();
      reloadRangeDependentViews();
    });
  }

  if (facadeShowForecastEl) {
    facadeShowForecastEl.checked = showForecast;
    facadeShowForecastEl.addEventListener("change", () => {
      showForecast = facadeShowForecastEl.checked;
      localStorage.setItem(FORECAST_KEY, showForecast ? "1" : "0");
      if (!showForecast) clearProjections();
      syncForecastToggleControls();
      updateGeoStatus();
      reloadRangeDependentViews();
    });
  }

  document
    .querySelectorAll(".forecast-future-ranges > button[data-forecast-future]")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        setForecastFutureHours(btn.dataset.forecastFuture);
      });
    });
  syncForecastFutureButtons();
  syncForecastToggleControls();

  function bindProjectionScenario(el) {
    if (!el) return;
    el.addEventListener("change", () => {
      const next = el.value;
      projectionScenario = [
        "auto",
        "closed",
        "open",
        "both",
        "coolest",
        "warmest",
      ].includes(next)
        ? next
        : "closed";
      localStorage.setItem(PROJECTION_SCENARIO_KEY, projectionScenario);
      syncProjectionScenarioControl();
      if (showForecast) reloadRangeDependentViews();
    });
  }
  bindProjectionScenario(projectionScenarioEl);
  bindProjectionScenario(facadeProjectionScenarioEl);

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
      syncForecastToggleControls();
      reloadRangeDependentViews();
    });
  }
  if (facadeShowWindowBandsEl) {
    facadeShowWindowBandsEl.checked = showWindowBands;
    facadeShowWindowBandsEl.addEventListener("change", () => {
      showWindowBands = facadeShowWindowBandsEl.checked;
      localStorage.setItem(WINDOW_BANDS_KEY, showWindowBands ? "1" : "0");
      syncForecastToggleControls();
      reloadRangeDependentViews();
    });
  }

  if (facadeLocateBtn) {
    facadeLocateBtn.addEventListener("click", () => {
      requestBrowserGeo(true).then(() => {
        updateGeoStatus();
        if (currentView === "facades") {
          loadFacades().catch((err) => {
            if (facadeStatusEl) {
              facadeStatusEl.textContent = `Error: ${err.message}`;
            }
          });
        }
      });
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

  function syncWindowNotifyBtn() {
    if (!windowNotifyEl) return;
    windowNotifyEl.setAttribute("aria-pressed", windowNotify ? "true" : "false");
    const diag = diagnoseWindowNotify();
    let title = windowNotify ? t("windowNotify.on") : t("windowNotify.off");
    if (!windowNotify && diag.code !== "ok" && diag.code !== "granted_off") {
      title = diag.status;
    } else if (!windowNotify && diag.code === "granted_off") {
      title = t("windowNotify.readyClick");
    }
    windowNotifyEl.title = title;
    windowNotifyEl.setAttribute(
      "aria-label",
      windowNotify ? t("windowNotify.disable") : t("windowNotify.enable")
    );
  }

  function isNotifyStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true
    );
  }

  function notifyHttpsHintUrl() {
    if (location.protocol === "https:") return location.origin;
    const host = location.hostname || "127.0.0.1";
    return `https://${host}:8081`;
  }

  /**
   * Detect notification problems and propose fixes (Safari standalone friendly).
   * @returns {{
   *   ok: boolean,
   *   code: string,
   *   tone: "ok"|"warn"|"bad",
   *   status: string,
   *   fix: string,
   *   actions: string[]
   * }}
   */
  function diagnoseWindowNotify() {
    const standalone = isNotifyStandalone();
    const secure = !!window.isSecureContext;
    const hasApi = "Notification" in window;
    const hasSw = "serviceWorker" in navigator;
    const perm = hasApi ? Notification.permission : "missing";
    const pending = getWindowNotifyPending();
    const httpsUrl = notifyHttpsHintUrl();

    if (!hasApi) {
      return {
        ok: false,
        code: "unsupported",
        tone: "bad",
        status: t("windowNotify.diag.unsupported.status"),
        fix: t("windowNotify.diag.unsupported.fix"),
        actions: [],
      };
    }
    if (!secure) {
      return {
        ok: false,
        code: "insecure",
        tone: "bad",
        status: t("windowNotify.diag.insecure.status"),
        fix: t("windowNotify.diag.insecure.fix", { url: httpsUrl }),
        actions: ["copyHttps", "reload"],
      };
    }
    if (perm === "denied") {
      return {
        ok: false,
        code: "denied",
        tone: "bad",
        status: t("windowNotify.diag.denied.status"),
        fix: t(
          pending === "reloaded"
            ? "windowNotify.diag.denied.fixQuit"
            : "windowNotify.diag.denied.fix",
          { app: "Govee Charts" }
        ),
        actions: pending === "reloaded" ? ["reload"] : ["reload", "retry"],
      };
    }
    if (perm === "default") {
      return {
        ok: false,
        code: "prompt",
        tone: "warn",
        status: t("windowNotify.diag.prompt.status"),
        fix: t("windowNotify.diag.prompt.fix"),
        actions: ["enable"],
      };
    }
    if (perm === "granted" && !windowNotify) {
      return {
        ok: true,
        code: "granted_off",
        tone: "warn",
        status: t("windowNotify.diag.grantedOff.status"),
        fix: t("windowNotify.diag.grantedOff.fix"),
        actions: ["enable"],
      };
    }
    if (!hasSw) {
      return {
        ok: true,
        code: "no_sw",
        tone: "warn",
        status: t("windowNotify.diag.noSw.status"),
        fix: t("windowNotify.diag.noSw.fix"),
        actions: ["test", "reload"],
      };
    }
    if (!standalone) {
      return {
        ok: true,
        code: "browser_tab",
        tone: "ok",
        status: t("windowNotify.diag.okTab.status"),
        fix: t("windowNotify.diag.okTab.fix"),
        actions: ["test", "disable"],
      };
    }
    return {
      ok: true,
      code: "ok",
      tone: "ok",
      status: t("windowNotify.diag.ok.status"),
      fix: t("windowNotify.diag.ok.fix"),
      actions: ["test", "disable"],
    };
  }

  function showWindowNotifyHint(code, extraFix) {
    const diag = diagnoseWindowNotify();
    const key =
      code === "unsupported"
        ? "windowNotify.unsupported"
        : code === "insecure"
          ? "windowNotify.insecure"
          : code === "denied"
            ? "windowNotify.denied"
            : code === "pending"
              ? "windowNotify.pending"
              : code === "ready"
                ? "windowNotify.ready"
                : code === "reloading"
                  ? "windowNotify.reloading"
                  : "windowNotify.blocked";
    const status = code === "ready" ? t("windowNotify.ready") : t(key);
    const fix =
      extraFix ||
      (code === "ready" || code === "pending" || code === "reloading"
        ? ""
        : diag.fix);
    const detail = fix ? `${status}\n\n${fix}` : status;
    console.info("[notify] hint", code, { status, fix, diag });
    if (geoStatusEl) geoStatusEl.textContent = status;
    if (statusEl) statusEl.textContent = status;
    if (overviewStatus) overviewStatus.textContent = status;
    const banner = document.getElementById("window-banner");
    const titleEl = document.getElementById("window-banner-title");
    const detailEl = document.getElementById("window-banner-detail");
    if (banner && titleEl) {
      banner.classList.add("notify-fix-banner");
      titleEl.textContent = t("windowNotify.title");
      if (detailEl) detailEl.textContent = detail;
      banner.hidden = false;
    }
    if (windowNotifyEl) windowNotifyEl.title = status;
    renderSettingsNotify();
  }

  function setWindowNotifyPending(value) {
    try {
      if (!value) localStorage.removeItem(WINDOW_NOTIFY_PENDING_KEY);
      else localStorage.setItem(WINDOW_NOTIFY_PENDING_KEY, value);
    } catch (_) {
      /* ignore */
    }
  }

  function getWindowNotifyPending() {
    try {
      return localStorage.getItem(WINDOW_NOTIFY_PENDING_KEY) || "";
    } catch (_) {
      return "";
    }
  }

  function softReloadForNotify() {
    const url = new URL(window.location.href);
    url.searchParams.set("_notify", String(Date.now()));
    window.location.replace(url.pathname + url.search + url.hash);
  }

  function activateWindowNotify() {
    windowNotify = true;
    localStorage.setItem(WINDOW_NOTIFY_KEY, "1");
    setWindowNotifyPending("");
    syncWindowNotifyBtn();
    console.info("[notify] enabled");
    renderSettingsNotify();
    ensureNotifyServiceWorker()
      .then(() => evaluateWindowNotifications(null))
      .catch((err) => console.warn("[notify] evaluate failed", err));
  }

  function testWindowNotify() {
    sendWindowNotification(
      t("windowNotify.testTitle"),
      t("windowNotify.testBody"),
      "govee-window-test"
    );
  }

  /**
   * Safari standalone often keeps a stale Notification.permission after the user
   * flips the OS toggle — a document reload usually picks up "granted" without
   * quitting the web app. Auto-enable once permission is visible.
   * @param {{allowSoftReload?: boolean}} [opts]
   */
  function recoverWindowNotifyPermission(opts) {
    if (!("Notification" in window)) return;
    const allowSoftReload = !!(opts && opts.allowSoftReload);
    const pending = getWindowNotifyPending();
    const perm = Notification.permission;
    console.info("[notify] recover", {
      pending,
      perm,
      windowNotify,
      allowSoftReload,
    });

    if (perm === "granted") {
      if (pending || !windowNotify) {
        activateWindowNotify();
        showWindowNotifyHint("ready");
      } else {
        syncWindowNotifyBtn();
        renderSettingsNotify();
      }
      return;
    }

    if (!pending) {
      renderSettingsNotify();
      return;
    }

    // Still not granted after returning from Settings — soft-reload once.
    if (pending === "wait" && allowSoftReload) {
      setWindowNotifyPending("reloaded");
      showWindowNotifyHint("reloading");
      console.info("[notify] soft-reload to refresh permission");
      setTimeout(softReloadForNotify, 450);
      return;
    }

    if (pending === "reloaded") {
      showWindowNotifyHint("denied");
      return;
    }

    renderSettingsNotify();
  }

  function runNotifyDiagAction(action) {
    console.info("[notify] action", action);
    if (action === "enable") {
      onWindowNotifyClick();
      return;
    }
    if (action === "disable") {
      if (windowNotify) onWindowNotifyClick();
      else renderSettingsNotify();
      return;
    }
    if (action === "retry") {
      setWindowNotifyPending("wait");
      if (Notification.permission === "granted") {
        activateWindowNotify();
        return;
      }
      if (Notification.permission === "default") {
        const pending = requestNotifyPermission();
        Promise.resolve(pending).then((perm) => {
          if (perm === "granted") activateWindowNotify();
          else {
            showWindowNotifyHint(perm === "denied" ? "denied" : "blocked");
          }
        });
        return;
      }
      showWindowNotifyHint("denied");
      return;
    }
    if (action === "reload") {
      if (getWindowNotifyPending() === "wait") {
        setWindowNotifyPending("reloaded");
      }
      showWindowNotifyHint("reloading");
      setTimeout(softReloadForNotify, 250);
      return;
    }
    if (action === "test") {
      if (Notification.permission !== "granted") {
        showWindowNotifyHint("denied");
        return;
      }
      if (!windowNotify) activateWindowNotify();
      testWindowNotify();
      return;
    }
    if (action === "copyHttps") {
      const url = notifyHttpsHintUrl();
      const done = () => {
        showWindowNotifyHint(
          "insecure",
          t("windowNotify.diag.insecure.copied", { url })
        );
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done).catch(done);
      } else {
        done();
      }
    }
  }

  function renderSettingsNotify() {
    const statusElN = document.getElementById("settings-notify-status");
    const fixEl = document.getElementById("settings-notify-fix");
    const actionsEl = document.getElementById("settings-notify-actions");
    if (!statusElN || !actionsEl) return;
    const diag = diagnoseWindowNotify();
    statusElN.textContent = diag.status;
    statusElN.dataset.tone = diag.tone;
    if (fixEl) {
      fixEl.textContent = diag.fix || "";
      fixEl.hidden = !diag.fix;
    }
    actionsEl.replaceChildren();
    const labels = {
      enable: t("windowNotify.action.enable"),
      disable: t("windowNotify.action.disable"),
      retry: t("windowNotify.action.retry"),
      reload: t("windowNotify.action.reload"),
      test: t("windowNotify.action.test"),
      copyHttps: t("windowNotify.action.copyHttps"),
    };
    for (const action of diag.actions) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "backfill-btn";
      btn.textContent = labels[action] || action;
      btn.addEventListener("click", () => runNotifyDiagAction(action));
      actionsEl.appendChild(btn);
    }
  }

  function onWindowNotifyClick() {
    const permNow =
      "Notification" in window ? Notification.permission : "missing";
    console.info("[notify] click", {
      windowNotify,
      permission: permNow,
      secure: !!window.isSecureContext,
      standalone: isNotifyStandalone(),
    });
    if (windowNotify) {
      windowNotify = false;
      localStorage.setItem(WINDOW_NOTIFY_KEY, "0");
      setWindowNotifyPending("");
      syncWindowNotifyBtn();
      renderSettingsNotify();
      console.info("[notify] disabled");
      return;
    }
    if (!("Notification" in window)) {
      showWindowNotifyHint("unsupported");
      syncWindowNotifyBtn();
      return;
    }
    if (!window.isSecureContext) {
      showWindowNotifyHint("insecure");
      syncWindowNotifyBtn();
      return;
    }
    if (Notification.permission === "granted") {
      activateWindowNotify();
      showWindowNotifyHint("ready");
      return;
    }
    // User intends to enable — remember so return-from-Settings can finish the job.
    setWindowNotifyPending("wait");
    if (Notification.permission === "denied") {
      windowNotify = false;
      localStorage.setItem(WINDOW_NOTIFY_KEY, "0");
      syncWindowNotifyBtn();
      showWindowNotifyHint("denied");
      return;
    }
    showWindowNotifyHint("pending");
    // Synchronous call from the click handler (do not await anything before this).
    const pending = requestNotifyPermission();
    Promise.resolve(pending).then((perm) => {
      if (perm === "granted") {
        activateWindowNotify();
        showWindowNotifyHint("ready");
        return;
      }
      windowNotify = false;
      localStorage.setItem(WINDOW_NOTIFY_KEY, "0");
      setWindowNotifyPending("wait");
      syncWindowNotifyBtn();
      showWindowNotifyHint(perm === "denied" ? "denied" : "blocked");
    });
  }

  // Wire the bell immediately (before TTS/other init that might throw).
  try {
    if (windowNotifyEl) {
      syncWindowNotifyBtn();
      windowNotifyEl.addEventListener("click", onWindowNotifyClick);
      console.info("[notify] handler ready");
      let notifyWasHidden = document.visibilityState === "hidden";
      const onForeground = () => {
        const hidden = document.visibilityState === "hidden";
        const returning = notifyWasHidden && !hidden;
        notifyWasHidden = hidden;
        if (hidden) return;
        syncWindowNotifyBtn();
        recoverWindowNotifyPermission({ allowSoftReload: returning });
      };
      document.addEventListener("visibilitychange", onForeground);
      window.addEventListener("focus", () => {
        if (document.visibilityState === "hidden") return;
        syncWindowNotifyBtn();
        recoverWindowNotifyPermission({ allowSoftReload: false });
      });
      window.addEventListener("pageshow", (ev) => {
        recoverWindowNotifyPermission({
          allowSoftReload: false,
          fromPageShow: true,
        });
        // After our soft-reload, pending is "reloaded" — finish enable if granted.
        if (ev.persisted) syncWindowNotifyBtn();
      });
      if (getWindowNotifyPending()) {
        recoverWindowNotifyPermission({ allowSoftReload: false });
      }
    }
    renderSettingsNotify();
  } catch (err) {
    console.error("[notify] failed to wire bell", err);
  }

  function syncTtsBtn() {
    if (!ttsEl) return;
    ttsEl.setAttribute("aria-pressed", ttsEnabled ? "true" : "false");
    ttsEl.title = ttsEnabled ? t("tts.on") : t("tts.off");
    ttsEl.setAttribute(
      "aria-label",
      ttsEnabled ? t("tts.disable") : t("tts.enable")
    );
  }

  if (ttsEl) {
    populateTtsVoiceOptions();
    if (useMacVoices && window.speechSynthesis) {
      window.speechSynthesis.addEventListener?.(
        "voiceschanged",
        populateTtsVoiceOptions
      );
    }
    syncTtsBtn();
    ttsEl.addEventListener("click", () => {
      ttsEnabled = !ttsEnabled;
      localStorage.setItem(TTS_KEY, ttsEnabled ? "1" : "0");
      syncTtsBtn();
      ttsVoicePollAttempts = 0;
      populateTtsVoiceOptions();
      if (ttsEnabled) speak(t("tts.enabledSpeak"), { force: true });
    });
  }

  if (ttsVoiceSelectEl) {
    ttsVoiceSelectEl.addEventListener("change", () => {
      ttsVoiceURI = ttsVoiceSelectEl.value;
      localStorage.setItem(TTS_VOICE_KEY, ttsVoiceURI);
      // Same user gesture: unlock audio + speak (Safari Mac / edge play()).
      speak(t("tts.enabledSpeak"), { force: true });
    });
  }

  if (ttsVoiceTestBtn) {
    ttsVoiceTestBtn.addEventListener("click", () => {
      // Prefer the banner currently on screen; fall back to the last remembered one.
      let text = "";
      if (systemBannerModel && !systemBannerModel.hidden) {
        text = systemBannerModel.detail
          ? `${systemBannerModel.title}. ${systemBannerModel.detail}`
          : systemBannerModel.title || "";
      } else if (windowBannerModel && !windowBannerModel.hidden) {
        text = windowBannerModel.detail
          ? `${windowBannerModel.title}. ${windowBannerModel.detail}`
          : windowBannerModel.title || "";
      }
      if (!text) text = lastDisplayedAlertText;
      if (!text) text = t("settings.voiceTestEmpty");
      speak(text, { force: true });
    });
  }

  function syncDoorBeepBtn() {
    if (!doorBeepEl) return;
    doorBeepEl.setAttribute("aria-pressed", doorBeepEnabled ? "true" : "false");
    doorBeepEl.title = doorBeepEnabled ? t("doorBeep.on") : t("doorBeep.off");
    doorBeepEl.setAttribute(
      "aria-label",
      doorBeepEnabled ? t("doorBeep.disable") : t("doorBeep.enable")
    );
  }

  if (doorBeepEl) {
    syncDoorBeepBtn();
    doorBeepEl.addEventListener("click", () => {
      doorBeepEnabled = !doorBeepEnabled;
      localStorage.setItem(DOOR_BEEP_KEY, doorBeepEnabled ? "1" : "0");
      syncDoorBeepBtn();
      if (doorBeepEnabled) beepDoor(true);
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

  function hardReload() {
    // Bypass cached HTML/assets after UI restart (server also version-busts static URLs).
    const url = new URL(window.location.href);
    url.searchParams.set("_cb", String(Date.now()));
    window.location.replace(url.pathname + url.search + url.hash);
  }

  async function waitForWorkers(timeoutMs = 45000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (!res.ok) continue;
        const data = await res.json().catch(() => ({}));
        if (data.workers_available) return true;
      } catch {
        // still unavailable
      }
    }
    return false;
  }

  const homeBtn = document.getElementById("home-btn");
  if (homeBtn) {
    // Portal lives on plain HTTP port 80 of the same host, regardless of
    // which protocol/port this dashboard itself was reached on.
    homeBtn.href = `http://${window.location.hostname}/`;
  }

  if (gitPullBtn) {
    gitPullBtn.addEventListener("click", async () => {
      if (
        !window.confirm(
          "Pull latest commits (git pull --ff-only)? Restart UI/workers afterward if code changed."
        )
      ) {
        return;
      }
      gitPullBtn.disabled = true;
      if (restartStatusEl) {
        restartStatusEl.hidden = false;
        restartStatusEl.textContent = "Pulling…";
      }
      try {
        const res = await fetch("/api/git/pull", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail =
            typeof data.detail === "string"
              ? data.detail
              : data.message || `HTTP ${res.status}`;
          throw new Error(detail);
        }
        if (restartStatusEl) {
          restartStatusEl.textContent = data.message || "Pull complete.";
        }
        if (data.changed) {
          // Static assets may already be newer; hard-reload HTML/JS.
          hardReload();
        }
      } catch (err) {
        if (restartStatusEl) {
          restartStatusEl.textContent = `Git pull failed: ${err.message}`;
        }
      } finally {
        gitPullBtn.disabled = false;
      }
    });
  }

  if (restartUiBtn) {
    restartUiBtn.addEventListener("click", async () => {
      if (
        !window.confirm(
          "Restart UI now? The page will reload when the service is back."
        )
      ) {
        return;
      }
      restartUiBtn.disabled = true;
      if (restartStatusEl) {
        restartStatusEl.hidden = false;
        restartStatusEl.textContent = "UI restarting…";
      }
      try {
        const res = await fetch("/api/restart?target=ui", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || `HTTP ${res.status}`);
        }
        if (restartStatusEl) {
          restartStatusEl.textContent = data.message || "UI restarting…";
        }
        const ok = await waitForHealth();
        if (ok) {
          if (restartStatusEl) restartStatusEl.textContent = "Back online — reloading…";
          hardReload();
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
          hardReload();
          return;
        }
        if (restartStatusEl) {
          restartStatusEl.textContent = `Restart failed: ${err.message}`;
        }
      } finally {
        restartUiBtn.disabled = false;
      }
    });
  }

  if (restartWorkersBtn) {
    restartWorkersBtn.addEventListener("click", async () => {
      if (
        !window.confirm(
          "Restart workers now? The UI should remain available."
        )
      ) {
        return;
      }
      restartWorkersBtn.disabled = true;
      if (restartStatusEl) {
        restartStatusEl.hidden = false;
        restartStatusEl.textContent = "Workers restarting…";
      }
      try {
        const res = await fetch("/api/restart?target=workers", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || `HTTP ${res.status}`);
        }
        if (restartStatusEl) {
          restartStatusEl.textContent = data.message || "Workers restarting…";
        }
        const ok = await waitForWorkers(30000);
        if (restartStatusEl) {
          restartStatusEl.textContent = ok
            ? "Workers back online."
            : "Workers restart requested. Waiting for heartbeat…";
        }
      } catch (err) {
        if (restartStatusEl) {
          restartStatusEl.textContent = `Workers restart failed: ${err.message}`;
        }
      } finally {
        restartWorkersBtn.disabled = false;
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

  if (backfillSensorListEl) {
    backfillSensorListEl.addEventListener("change", (ev) => {
      const input = ev.target;
      if (!(input instanceof HTMLInputElement) || input.type !== "checkbox") {
        return;
      }
      const address = input.dataset.address;
      const flag = input.dataset.flag || "enabled";
      if (!address) return;
      const patch =
        flag === "gatt_enabled"
          ? { gatt_enabled: input.checked }
          : { enabled: input.checked };
      setBackfillDeviceFlags(address, patch).catch((err) => {
        console.warn(err);
      });
    });
  }
  if (backfillSelectAllBtn) {
    backfillSelectAllBtn.addEventListener("click", () => {
      setBackfillDevicesBulk(true).catch((err) => console.warn(err));
    });
  }
  if (backfillClearAllBtn) {
    backfillClearAllBtn.addEventListener("click", () => {
      setBackfillDevicesBulk(false).catch((err) => console.warn(err));
    });
  }

  if (coverageDropzoneEl && coverageImportFileEl) {
    const openFilePicker = () => coverageImportFileEl.click();
    coverageDropzoneEl.addEventListener("click", openFilePicker);
    coverageDropzoneEl.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        openFilePicker();
      }
    });
    ["dragenter", "dragover"].forEach((type) => {
      coverageDropzoneEl.addEventListener(type, (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        coverageDropzoneEl.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach((type) => {
      coverageDropzoneEl.addEventListener(type, (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (type === "dragleave") coverageDropzoneEl.classList.remove("is-dragover");
      });
    });
    coverageDropzoneEl.addEventListener("drop", (ev) => {
      coverageDropzoneEl.classList.remove("is-dragover");
      const files = ev.dataTransfer && ev.dataTransfer.files;
      if (files && files.length) addFilesToBatch(files);
    });
    coverageImportFileEl.addEventListener("change", () => {
      if (coverageImportFileEl.files && coverageImportFileEl.files.length) {
        addFilesToBatch(coverageImportFileEl.files);
        coverageImportFileEl.value = "";
      }
    });
  }

  if (mailInboxNewBtn) {
    mailInboxNewBtn.addEventListener("click", () => {
      setMailInbox(null).catch((err) => console.warn(err));
    });
  }
  if (mailInboxUseBtn) {
    mailInboxUseBtn.addEventListener("click", () => {
      const address = (mailInboxExistingEl && mailInboxExistingEl.value) || "";
      if (!address.trim()) {
        if (mailInboxStatusEl) {
          mailInboxStatusEl.textContent = "Enter an existing inbox address first.";
        }
        return;
      }
      setMailInbox(address.trim()).catch((err) => console.warn(err));
    });
  }
  if (mailInboxFetchBtn) {
    mailInboxFetchBtn.addEventListener("click", () => {
      fetchMailInbox().catch((err) => console.warn(err));
    });
  }
  if (mailInboxClearBtn) {
    mailInboxClearBtn.addEventListener("click", () => {
      clearMailInbox().catch((err) => console.warn(err));
    });
  }
  if (mailInboxCopyBtn) {
    mailInboxCopyBtn.addEventListener("click", async () => {
      const address = mailInboxState && mailInboxState.address;
      if (!address) return;
      try {
        await navigator.clipboard.writeText(address);
        if (mailInboxStatusEl) mailInboxStatusEl.textContent = "Address copied.";
      } catch (err) {
        if (mailInboxStatusEl) {
          mailInboxStatusEl.textContent = `Copy failed: ${err.message}`;
        }
      }
    });
  }
  if (mailInboxMessagesEl) {
    mailInboxMessagesEl.addEventListener("click", async (ev) => {
      const btn = ev.target instanceof HTMLElement
        ? ev.target.closest("button.mail-copy-code")
        : null;
      if (!(btn instanceof HTMLButtonElement)) return;
      const code = btn.dataset.code || "";
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code);
        if (mailInboxStatusEl) {
          mailInboxStatusEl.textContent = `Code ${code} copied — paste it in Govee.`;
        }
      } catch (err) {
        if (mailInboxStatusEl) {
          mailInboxStatusEl.textContent = `Copy code failed: ${err.message}`;
        }
      }
    });
  }
  loadMailInbox().catch((err) => console.warn(err));

  if (coverageBatchBodyEl) {
    coverageBatchBodyEl.addEventListener("change", (ev) => {
      const t = ev.target;
      if (!(t instanceof HTMLElement)) return;
      const row = t.closest("tr[data-batch-id]");
      if (!row) return;
      const item = batchItemById(row.dataset.batchId || "");
      if (!item) return;
      if (t.matches("input[data-batch-include]")) {
        item.included = /** @type {HTMLInputElement} */ (t).checked;
        syncBatchSelectAll();
        updateBatchImportButton();
        updateBatchStatusLine();
        return;
      }
      if (t.matches("select[data-batch-sensor]")) {
        const addr = /** @type {HTMLSelectElement} */ (t).value;
        item.address = addr;
        item.match = addr ? "exact" : "none";
        item.included = Boolean(addr);
        item.preview = null;
        item.error = null;
        item.status = "pending";
        coverageBatchActiveId = item.id;
        renderCoverageBatch();
        if (addr) {
          analyzeCoverageBatchItem(item)
            .then(() => renderCoverageBatch())
            .catch((err) => console.warn(err));
        }
      }
    });
    coverageBatchBodyEl.addEventListener("click", (ev) => {
      const t = ev.target;
      if (!(t instanceof HTMLElement)) return;
      if (t.matches("input, select, option, label")) return;
      const row = t.closest("tr[data-batch-id]");
      if (!row) return;
      const item = batchItemById(row.dataset.batchId || "");
      if (!item) return;
      coverageBatchActiveId = item.id;
      coverageBatchBodyEl.querySelectorAll("tr[data-batch-id]").forEach((el) => {
        el.classList.toggle("is-active", el.dataset.batchId === item.id);
      });
      showBatchItemRecap(item);
      if (item.address && coverageDeviceEl) {
        coverageAddress = item.address;
        coverageDeviceEl.value = item.address;
        persistCoverageState();
        loadCoverageDetail().catch((err) => console.warn(err));
      }
    });
  }
  if (coverageBatchSelectAllEl) {
    coverageBatchSelectAllEl.addEventListener("change", () => {
      const on = coverageBatchSelectAllEl.checked;
      coverageBatch.forEach((it) => {
        if (it.status !== "done") it.included = on && Boolean(it.address);
      });
      renderCoverageBatch();
    });
  }
  if (coverageImportAnalyzeBtn) {
    coverageImportAnalyzeBtn.addEventListener("click", () => {
      analyzeCoverageBatch().catch((err) => console.warn(err));
    });
  }
  if (coverageImportOverwriteEl) {
    coverageImportOverwriteEl.addEventListener("change", () => {
      updateBatchImportButton();
      updateBatchStatusLine();
      renderCoverageBatch();
      if (coverageBatch.some((it) => it.address && it.status !== "done")) {
        analyzeCoverageBatch().catch((err) => console.warn(err));
      }
    });
  }
  if (coverageImportClearBtn) {
    coverageImportClearBtn.addEventListener("click", () => {
      clearCoverageBatch();
    });
  }
  if (coverageImportConfirmBtn) {
    coverageImportConfirmBtn.addEventListener("click", () => {
      confirmCoverageBatch().catch((err) => console.warn(err));
    });
  }

  if (coverageDeviceEl) {
    coverageDeviceEl.addEventListener("change", () => {
      coverageAddress = coverageDeviceEl.value || "";
      persistCoverageState();
      if (coverageImportDeviceEl && coverageAddress) {
        coverageImportDeviceEl.value = coverageAddress;
      }
      loadCoverageDetail().catch((err) => console.warn(err));
      if (coverageAllListEl) {
        coverageAllListEl.querySelectorAll(".coverage-all-row").forEach((el) => {
          el.classList.toggle("active", el.dataset.address === coverageAddress);
        });
      }
    });
  }

  coverageRangeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      coverageHours = btn.dataset.covHours || "1";
      persistCoverageState();
      syncCoverageRangeButtons();
      loadCoverage().catch((err) => console.warn(err));
    });
  });

  if (systemDeviceEl) {
    systemDeviceEl.addEventListener("change", () => {
      syncSystemSelectionFromDom();
      loadSystemDeviceSources().catch((err) => console.warn(err));
    });
  }

  if (systemDeviceFilterEl) {
    systemDeviceFilterEl.addEventListener("input", () => {
      systemDeviceFilter = systemDeviceFilterEl.value || "";
      renderSystemDeviceOptions();
    });
  }

  if (systemSelectAllBtn && systemDeviceEl) {
    systemSelectAllBtn.addEventListener("click", () => {
      [...systemDeviceEl.options].forEach((o) => {
        o.selected = true;
        systemSelectedAddresses.add(String(o.value || "").toUpperCase());
      });
      loadSystemDeviceSources().catch((err) => console.warn(err));
    });
  }
  if (systemClearAllBtn && systemDeviceEl) {
    systemClearAllBtn.addEventListener("click", () => {
      systemSelectedAddresses.clear();
      [...systemDeviceEl.options].forEach((o) => {
        o.selected = false;
      });
      loadSystemDeviceSources().catch((err) => console.warn(err));
    });
  }

  systemGrainButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      systemGrain = btn.dataset.sysGrain === "hour" ? "hour" : "day";
      if (systemGrain === "hour" && systemDays > 14) {
        systemDays = 7;
      }
      if (systemGrain === "day" && systemDays < 1) {
        systemDays = 7;
      }
      // Prefer 24h when switching to hour from a long day range.
      if (systemGrain === "hour" && systemDays >= 30) {
        systemDays = 1;
      }
      syncSystemRangeButtons();
      loadSystemDeviceSources().catch((err) => console.warn(err));
    });
  });

  systemRangeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      systemDays = Number(btn.dataset.sysDays) || 30;
      syncSystemRangeButtons();
      loadSystemDeviceSources().catch((err) => console.warn(err));
    });
  });

  coverageAggButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      coverageAggBucket = btn.dataset.aggBucket || "day";
      persistCoverageState();
      syncCoverageAggButtons();
      loadCoverageAggregates().catch((err) => console.warn(err));
    });
  });

  if (doorLogCloseBtn) {
    doorLogCloseBtn.addEventListener("click", () => {
      hideDoorLog();
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
  if (foldMapChatEl) {
    foldMapChatEl.open = localStorage.getItem(FOLD_MAP_CHAT_KEY) === "1";
  }

  function bindWidgetExportControls() {
    const controls = [
      widgetMetricEl,
      widgetPastEl,
      widgetFutureEl,
      widgetForecastEl,
      widgetTransparentEl,
      widgetLegendEl,
      widgetRefreshEl,
    ];
    for (const el of controls) {
      if (!el) continue;
      el.addEventListener("change", () => {
        if (el === widgetFutureEl && widgetForecastEl) {
          if (Number(widgetFutureEl.value) === 0) {
            widgetForecastEl.checked = false;
          } else if (!widgetForecastEl.checked) {
            widgetForecastEl.checked = true;
          }
        }
        updateWidgetExport();
      });
    }
    if (widgetCurvesSelectionBtn) {
      widgetCurvesSelectionBtn.addEventListener("click", () => {
        widgetSelected = new Set(selectedDevices().map((d) => d.address));
        renderWidgetCurveList();
      });
    }
    if (widgetCurvesAllBtn) {
      widgetCurvesAllBtn.addEventListener("click", () => {
        widgetSelected = new Set(filteredDevices().map((d) => d.address));
        renderWidgetCurveList();
      });
    }
    if (widgetCurvesNoneBtn) {
      widgetCurvesNoneBtn.addEventListener("click", () => {
        widgetSelected = new Set();
        renderWidgetCurveList();
      });
    }
    if (widgetCopyBtn) {
      widgetCopyBtn.addEventListener("click", async () => {
        const url = buildWidgetUrl();
        if (!url) {
          if (widgetExportStatusEl) {
            widgetExportStatusEl.textContent = t("compare.widget.needCurves");
          }
          return;
        }
        try {
          await navigator.clipboard.writeText(url);
          if (widgetExportStatusEl) {
            widgetExportStatusEl.textContent = t("compare.widget.copied");
          }
        } catch (_) {
          widgetUrlEl?.select();
          document.execCommand("copy");
          if (widgetExportStatusEl) {
            widgetExportStatusEl.textContent = t("compare.widget.copied");
          }
        }
      });
    }
    if (foldWidgetExportEl) {
      foldWidgetExportEl.addEventListener("toggle", () => {
        if (foldWidgetExportEl.open) {
          syncWidgetRangeFromCompare();
          if (!widgetSelected.size) {
            widgetSelected = new Set(selectedDevices().map((d) => d.address));
          }
          renderWidgetCurveList();
          updateWidgetExport();
        }
      });
    }
    if (widgetUrlEl) {
      widgetUrlEl.addEventListener("focus", () => widgetUrlEl.select());
    }
  }
  bindWidgetExportControls();

  const savedCovHours = localStorage.getItem("govee-charts.coverageHours");
  if (savedCovHours && COVERAGE_RANGE_HOURS.has(savedCovHours)) {
    coverageHours = savedCovHours;
  }
  syncCoverageRangeButtons();

  const savedMapMetric = localStorage.getItem("govee-charts.mapMetric");
  if (
    savedMapMetric === "humidity" ||
    savedMapMetric === "temp" ||
    savedMapMetric === "both"
  ) {
    networkMapMetric = savedMapMetric;
  }
  syncNetworkMetricButtons();

  const savedSectionShowSmall = localStorage.getItem(
    "govee-charts.sectionShowSmall"
  );
  if (savedSectionShowSmall === "1" || savedSectionShowSmall === "0") {
    sectionShowSmall = savedSectionShowSmall === "1";
  }
  try {
    const rawWp = localStorage.getItem("govee-charts.sectionWaypoints");
    if (rawWp) {
      const parsed = JSON.parse(rawWp);
      if (Array.isArray(parsed)) {
        sectionWaypoints = parsed
          .map((x) => String(x || "").trim())
          .filter(Boolean);
      }
    }
  } catch (_) {
    sectionWaypoints = [];
  }
  syncSectionPathControls();

  loadPersistedRange();
  syncRangeControls();
  refreshViewsStickyState();
  window.addEventListener("resize", refreshViewsStickyState);

  if (settingsLocaleEl) {
    settingsLocaleEl.value = I18n.getLocale();
    settingsLocaleEl.addEventListener("change", () => {
      I18n.setLocale(settingsLocaleEl.value);
    });
  }

  function refreshLocaleDependentUi() {
    if (settingsLocaleEl) settingsLocaleEl.value = I18n.getLocale();
    applyChartHeight(chartHeight, { persist: false });
    syncTtsBtn();
    syncWindowNotifyBtn();
    syncDoorBeepBtn();
    renderSettingsNotify();
    syncModelFilterButtons();
    edgeVoicesCache = [];
    edgeVoicesLang = "";
    populateTtsVoiceOptions();
    renderSettingsStations();
    updateOverview();
    updateDoorsTable();
    fillDeviceList();
    updateCurrent();
    updateSystemHealth().catch((err) => console.warn(err));
    updateWindowBanner(null).catch((err) => console.warn(err));
    if (selectedDoorId) {
      const sensor = doorSensors.find((s) => s.sensor_id === selectedDoorId);
      if (sensor) {
        loadDoorLog(sensor).catch((err) => console.warn(err));
      }
    }
    if (currentView === "compare" && historyLoaded) {
      loadHistory().catch((err) => {
        statusEl.textContent = t("compare.error", { error: err.message });
      });
    }
  }

  I18n.applyDom(document);
  syncTtsBtn();
  syncWindowNotifyBtn();
  syncDoorBeepBtn();
  I18n.onLocaleChange(() => {
    refreshLocaleDependentUi();
  });

  // Drop one-shot cache-bust query left by hardReload() after UI restart.
  if (new URL(window.location.href).searchParams.has("_cb")) {
    const clean = new URL(window.location.href);
    clean.searchParams.delete("_cb");
    window.history.replaceState(
      window.history.state,
      "",
      clean.pathname + clean.search + clean.hash
    );
  }
  setView(currentView, { url: "replace" });
  refresh();
  setInterval(refresh, 30000);
})();
