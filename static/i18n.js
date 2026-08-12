/**
 * Client-side i18n (en / fr). No build step.
 * HTML: data-i18n, data-i18n-placeholder, data-i18n-title, data-i18n-aria-label
 * JS: I18n.t(key, vars?), I18n.setLocale(lang), I18n.onLocaleChange(fn)
 */
(() => {
  const STORAGE_KEY = "govee-charts.locale";
  const SUPPORTED = new Set(["en", "fr"]);

  /** @type {Record<string, Record<string, string>>} */
  const CATALOGS = {
    en: {
      "brand.tagline": "Temperature and humidity — local BLE scan",
      "nav.views": "Views",
      "nav.overview": "Overview",
      "nav.compare": "Compare",
      "nav.facades": "Facades",
      "nav.map": "Map",
      "nav.data": "Data",
      "nav.coverage": "Coverage",
      "nav.backfill": "Backfill",
      "nav.system": "System",
      "nav.settings": "Settings",
      "nav.peers": "Federation peers",
      "nav.home": "Home",
      "nav.homeTitle": "Back to the portal (port 80)",
      "nav.gitPull": "Git pull",
      "nav.gitPullTitle": "git pull --ff-only",
      "nav.restartUi": "Restart UI",
      "nav.restartUiTitle": "Restart UI service",
      "nav.restartWorkers": "Restart workers",
      "nav.restartWorkersTitle": "Restart workers service",
      "alerts.bar": "Alerts",
      "tts.title": "Voice alerts (text-to-speech)",
      "tts.aria": "Toggle voice alerts",
      "tts.on": "Voice alerts on — click to disable",
      "tts.off": "Voice alerts off — click to enable",
      "tts.disable": "Disable voice alerts",
      "tts.enable": "Enable voice alerts",
      "tts.unsupported": "Voice alerts not supported by this browser",
      "tts.enabledSpeak": "Voice alerts enabled",
      "tts.voiceLabel": "Voice for alerts",
      "tts.voiceDefault": "Browser default",
      "tts.groupMac": "Mac (Safari)",
      "tts.groupServer": "Server (edge-tts)",
      "tts.groupHome": "Home TTS",
      "tts.homeSpeakers": "Home TTS (alerts channel)",
      "windowNotify.title": "Window alerts",
      "windowNotify.aria": "Toggle window alerts",
      "windowNotify.on": "Window alerts on — click to disable",
      "windowNotify.off": "Window alerts off — click to enable",
      "windowNotify.disable": "Disable window alerts",
      "windowNotify.enable": "Enable window alerts",
      "windowNotify.ready": "Window alerts on",
      "windowNotify.readyClick":
        "Notifications allowed — click the bell to turn window alerts on",
      "windowNotify.pending": "Waiting for notification permission…",
      "windowNotify.reloading":
        "Refreshing permission — reloading the app…",
      "windowNotify.unsupported": "Notifications not supported in this browser",
      "windowNotify.insecure":
        "Notifications need HTTPS (open the app via https://…:8081, not http)",
      "windowNotify.denied":
        "Notifications blocked — allow them in system/Safari settings, then return here",
      "windowNotify.blocked":
        "Notifications were not granted — allow the prompt or enable them in Settings, then return here",
      "windowNotify.testTitle": "Govee Charts — test",
      "windowNotify.testBody": "Window alerts are working.",
      "windowNotify.action.enable": "Enable bell",
      "windowNotify.action.disable": "Disable bell",
      "windowNotify.action.retry": "Ask again",
      "windowNotify.action.reload": "Reload app",
      "windowNotify.action.test": "Send test",
      "windowNotify.action.copyHttps": "Copy HTTPS link",
      "windowNotify.diag.unsupported.status": "This browser has no Notification API.",
      "windowNotify.diag.unsupported.fix":
        "Use Safari or Chrome on a desktop, or a Home Screen / Dock web app on Apple devices that support web notifications.",
      "windowNotify.diag.insecure.status": "Not a secure context (HTTP).",
      "windowNotify.diag.insecure.fix":
        "Open the app over HTTPS, e.g. {url} (accept the certificate once), then add it to the Dock / Home Screen again if needed.",
      "windowNotify.diag.insecure.copied":
        "HTTPS link ready: {url} — open it, then use the bell again.",
      "windowNotify.diag.denied.status": "Browser permission is denied.",
      "windowNotify.diag.denied.fix":
        "In System Settings → Notifications → {app} (or Safari → Settings → Websites → Notifications), set to Allow, then return to this app. It will reload and turn the bell on.",
      "windowNotify.diag.denied.fixQuit":
        "Permission still denied after reload. Quit the web app completely (Cmd+Q), reopen it, then use Reload or the bell.",
      "windowNotify.diag.prompt.status": "Permission not requested yet.",
      "windowNotify.diag.prompt.fix":
        "Click Enable bell (or the header bell) and accept the Safari prompt.",
      "windowNotify.diag.grantedOff.status": "Permission granted, alerts still off.",
      "windowNotify.diag.grantedOff.fix":
        "Click Enable bell to turn window alerts on.",
      "windowNotify.diag.noSw.status": "Alerts on, but no service worker.",
      "windowNotify.diag.noSw.fix":
        "Safari standalone prefers a service worker. Reload the app on HTTPS; if it still fails, quit and reopen.",
      "windowNotify.diag.okTab.status": "Window alerts are on (browser tab).",
      "windowNotify.diag.okTab.fix":
        "For background alerts on iPhone/iPad, add the site to the Home Screen and open it from there.",
      "windowNotify.diag.ok.status": "Window alerts are on.",
      "windowNotify.diag.ok.fix":
        "You can send a test notification or disable the bell.",
      "doorBeep.title": "Beep on door / window open or close",
      "doorBeep.aria": "Toggle door / window beep",
      "doorBeep.on": "Door / window beep on — click to disable",
      "doorBeep.off": "Door / window beep off — click to enable",
      "doorBeep.disable": "Disable door / window beep",
      "doorBeep.enable": "Enable door / window beep",

      "settings.title": "Settings",
      "settings.hint": "Language, voice, and weather station preferences are stored in this browser.",
      "settings.language": "Language",
      "settings.languageHelp": "User interface language",
      "settings.voice": "Voice for alerts",
      "settings.voiceHelp":
        "Only voices for the selected language. Enable voice alerts with the speaker button in the alert bar.",
      "settings.voiceTest": "Test",
      "settings.voiceTestTitle": "Speak the last alert banner",
      "settings.voiceTestEmpty": "No alert banner to replay yet.",
      "settings.notify": "Window notifications",
      "settings.notifyHelp":
        "Diagnoses browser permission issues (especially Safari standalone) and offers fixes.",
      "settings.stations": "Weather stations",
      "settings.stationsHelp":
        "Choose which stations appear on Compare charts and projection cards. Stored in this browser.",
      "settings.stationsEmpty": "No weather stations configured on this node.",
      "settings.stationsCoords": "{lat}, {lon}",
      "settings.service": "Service",
      "settings.serviceHelp":
        "Pull the latest code, then restart UI and/or workers to apply changes.",
      "settings.lang.en": "English",
      "settings.lang.fr": "Français",

      "overview.title": "All sensors",
      "overview.hint":
        "Edit name / zone / height / height cm / room inline — use Charts to open compare graphs",
      "overview.filter": "Filter",
      "overview.filterPlaceholder": "Name or MAC…",
      "overview.filterModel": "Filter by model",
      "overview.filterCategory": "Filter by category",
      "overview.zone": "Zone",
      "overview.height": "Height",
      "overview.room": "Room",
      "overview.sort": "Sort sensors",
      "overview.sortLabel": "Sort",
      "overview.sort.name": "Name",
      "overview.sort.temp": "Temp",
      "overview.sort.humidity": "Humidity",
      "overview.sort.battery": "Battery",
      "overview.sort.signal": "Signal",
      "overview.sort.zone": "Zone",
      "overview.sort.room": "Room",
      "overview.sort.updated": "Updated",
      "overview.loading": "Loading…",
      "overview.doorsTitle": "Doors & windows",
      "overview.doorsHint":
        "Contact sensors — set kind/room; click a name for open/close log",
      "overview.col.sensor": "Sensor",
      "overview.col.state": "State",
      "overview.col.kind": "Kind",
      "overview.col.room": "Room",
      "overview.col.updated": "Updated",
      "overview.doorLogTitle": "Open / close log",
      "overview.doorLogClose": "Close",
      "overview.doorLogCloseTitle": "Close log",
      "overview.doorLogHint": "Last 7 days",
      "overview.col.time": "Time",
      "overview.col.source": "Source",
      "overview.selectContact": "Select a contact…",
      "overview.noDevices": "No devices detected",
      "overview.waitingBle": "Waiting for BLE devices…",
      "overview.noSensorsFilter": "No sensors for these filters",
      "overview.statusFiltered": "{shown} / {total} sensor(s) · filters active",
      "overview.statusCount": "{shown} / {total} sensor(s)",
      "overview.statusCountSame": "{n} sensor(s)",
      "overview.allModels": "All models",
      "overview.all": "All",
      "overview.charts": "Charts",
      "overview.chartsTitle": "Open compare charts for this sensor",
      "overview.chartsAria": "Open compare charts for {name}",
      "overview.pushMeta": "Push meta",
      "overview.pushMetaTitle":
        "Push name, zone, height, height cm, and room to federation peers",
      "overview.pushing": "Pushing…",
      "overview.pushed": "Pushed",
      "overview.partial": "Partial",
      "overview.metaPushedFail":
        "Meta pushed to {ok}/{total} peer(s). Failed: {fail}",
      "overview.metaPushedOk": "Meta pushed to {ok} peer(s) for {name}.",
      "overview.metaPushFailed": "Meta push failed: {error}",
      "overview.namePlaceholder": "Name",
      "overview.nameTitle": "Friendly name (saved on this node)",
      "overview.nameFailed": "Name update failed: {error}",
      "overview.heightCm": "Height cm",
      "overview.heightCmTitle": "Mounting height above floor (cm)",
      "overview.heightCmInvalid": "Height cm must be 0–600",
      "overview.catFailed": "Category update failed: {error}",
      "overview.doorLogNamed": "{name} — open / close log",
      "overview.doorLogLastDays": "Last {n} days",
      "overview.doorLogLastHours": "Last {n} h",
      "overview.doorLogEmpty": "No open/close events in this period",
      "overview.doorLogUnavailable": "Log unavailable: {error}",
      "overview.noDoors": "No contact sensors",
      "overview.noDoorsYet": "No door/window contacts yet",
      "overview.waitingDoors":
        "Waiting for MQTT contact sensors (enable [doors] in config)…",
      "overview.doorsUnavailable": "Doors unavailable",
      "overview.federation": "Federation",
      "overview.battery": "Battery {value}",
      "overview.updatedAt": " · updated {time}",

      "compare.selection": "Selection",
      "compare.devices": "Devices",
      "compare.devicesGroup": "Devices to compare",
      "compare.all": "All",
      "compare.none": "None",
      "compare.facade.groupLabel": "Facade:",
      "compare.facade.groupTitle": "Select all sensors on façade {room}",
      "compare.timeRange": "Time range",
      "compare.longerRange": "Longer range",
      "compare.longerTimeRange": "Longer time range",
      "compare.more": "More…",
      "compare.custom": "Custom…",
      "compare.from": "From",
      "compare.to": "To",
      "compare.apply": "Apply",
      "compare.resetZoom": "Reset zoom",
      "compare.resetZoomTitle": "Reset chart zoom",
      "compare.zoomHint":
        "Drag on a chart to zoom · Shift-drag to pan · double-click to reset",
      "compare.forecast": "Forecast & projections",
      "compare.future": "Future",
      "compare.forecastHorizon": "Forecast horizon",
      "compare.scenario": "Scenario",
      "compare.scenarioTitle": "Which window scenario to plot",
      "compare.scenario.auto": "Current opening",
      "compare.scenario.closed": "Windows closed",
      "compare.scenario.open": "Windows open",
      "compare.scenario.both": "Closed + open",
      "compare.scenario.coolest": "Coolest (open/close)",
      "compare.scenario.warmest": "Warmest (open/close)",
      "compare.windowBands": "Window open / close",
      "compare.hvac": "AC & power",
      "compare.locate": "Locate",
      "compare.locateTitle": "Use browser location",
      "compare.chartHeight": "Chart height",
      "compare.chartHeightPx": "{n} px",
      "compare.currentReadings": "Current readings",
      "compare.foldProjections": "Forecast & projections",
      "compare.temp": "Temperature (°C)",
      "compare.hum": "Humidity (%)",
      "compare.dew": "Dew point (°C)",
      "compare.spread.title": "Temperature spread by room (°C)",
      "compare.spread.hint": "Max − min across sensors sharing the same room, over the selected period.",
      "compare.spread.titleFacade": "Temperature spread by façade (°C)",
      "compare.spread.hintFacade": "Max − min across all sensors (indoor + outdoor) sharing the same façade orientation.",
      "compare.spread.interior": "indoor",
      "compare.spread.exterior": "outdoor",
      "compare.spread.spreadSuffix": "spread",
      "compare.openCools": "open cools",
      "compare.openHeats": "open heats",
      "compare.tooHumid": "too humid",
      "compare.acOn": "AC on",
      "compare.powerNote": "· power (W) on right axis",
      "compare.loading": "Loading…",
      "compare.selectDevice": "Select at least one device…",
      "compare.widget.title": "Export widget",
      "compare.widget.meta": "shareable chart link",
      "compare.widget.hint":
        "Build a standalone chart URL for iframes or bookmarks. Curves default to the current Compare selection.",
      "compare.widget.metric": "Metric",
      "compare.widget.metric.temp": "Temperature",
      "compare.widget.metric.hum": "Humidity",
      "compare.widget.metric.dew": "Dew point",
      "compare.widget.past": "Past",
      "compare.widget.future": "Future",
      "compare.widget.futureOff": "Off",
      "compare.widget.forecast": "Include forecast",
      "compare.widget.transparent": "Transparent background",
      "compare.widget.legend": "Show legend",
      "compare.widget.refresh": "Auto-refresh",
      "compare.widget.refreshOff": "Off",
      "compare.widget.curves": "Curves",
      "compare.widget.useSelection": "Use selection",
      "compare.widget.allVisible": "All visible",
      "compare.widget.none": "None",
      "compare.widget.link": "Link",
      "compare.widget.copy": "Copy",
      "compare.widget.open": "Open",
      "compare.widget.preview": "Preview",
      "compare.widget.copied": "Link copied",
      "compare.widget.needCurves": "Select at least one curve.",
      "compare.widget.iframe":
        '<iframe src="{url}" width="100%" height="320" style="border:0;background:transparent" loading="lazy"></iframe>',
      "compare.noDevices": "No devices detected",
      "compare.noDevicesMetric": "No devices",
      "compare.noSensorsModel": "No sensors for this model",
      "compare.error": "Error: {error}",
      "compare.status":
        "{names} · {points} point(s) · {range}{extra}{window}{hvac} · updated {time}",
      "compare.forecastGps": "GPS",
      "compare.forecastConfig": "config",
      "compare.forecastCached": ", cached",
      "compare.forecastStale": ", stale cache",
      "compare.forecastLoc": " · forecast {name} ({src}{cache})",
      "compare.forecastOffError": " · forecast off ({error})",
      "compare.forecastOffHint":
        " · forecast off (allow location or set [weather] place)",
      "compare.windowLegendTitle":
        "Based on {label} vs outdoor (temp ±{delta} °C, dew point vs indoor air)",
      "compare.noneSelected": "· none selected",
      "compare.sensorsMeta": "· {n} sensor",
      "compare.sensorsMetaPlural": "· {n} sensors",
      "compare.metric.temp": "Temperature",
      "compare.metric.humidity": "Humidity",
      "compare.metric.dew": "Dew point",
      "compare.metric.battery": "Battery",
      "compare.metric.signal": "Signal",
      "compare.metric.last": "Last reading",

      "banner.workersOffline": "Workers offline",
      "banner.workersDetail":
        "BLE collector / workers not responding ({age}). Restart workers if this persists.",
      "banner.noHeartbeat": "no heartbeat",
      "banner.lastSeen": "last seen {age} ago",
      "banner.bleStalled": "BLE scan stalled",
      "banner.bleNoAdsStart": "no advertisements since start",
      "banner.bleNoAdsFor": "no advertisements for {age}",
      "banner.bleDetail":
        "{age}. Check the USB Bluetooth dongle / BlueZ, then restart workers.",
      "banner.noRoomsContacts":
        "No interior rooms with both a sensor and a contact",
      "banner.noContacts": "No door/window contacts linked to rooms",
      "banner.assignRooms":
        "Assign a room on Overview → Doors & windows to include them here.",
      "banner.enableDoors":
        "Enable [doors] and map contacts to rooms on Overview.",
      "banner.outdoor": "Outdoor {temp} °C",
      "banner.dewRh": " · dew {dew} °C · RH {rh} %",
      "banner.openNow": "Open now: {names}",
      "banner.allClosed": "All tracked openings closed",
      "banner.noAction": "No strong window action",
      "banner.tempsClose":
        "{climate}. Indoor and outdoor temperatures are close. {open}.",
      "banner.closeTitle": "Close windows — {rooms}",
      "banner.closeHumid":
        "{climate}. Outdoor is cooler but too humid while openings are still open. {open}.",
      "banner.closeWarm":
        "{climate}. Outdoor air is warmer than indoors. {open}.",
      "banner.alsoOpen": " Also open: {rooms}.",
      "banner.openTitle": "Open windows — {rooms}",
      "banner.openDetail":
        "{climate}. Outdoor is cooler and dry enough. {open}.",
      "banner.okOpenTitle": "Windows OK open — {rooms}",
      "banner.okOpenDetail": "{climate}. Cooling with outdoor air. {open}.",
      "banner.closedOk": " Closed OK: {rooms}.",
      "banner.okClosedTitle": "Windows OK closed — {rooms}",
      "banner.okClosedDetail": "{climate}. {open}.",
      "notify.openTitle": "Open windows — {label}",
      "notify.openBody":
        "Outdoor air is cooler ({out} °C vs {in} °C indoors) and dry enough.",
      "notify.closeTitle": "Close windows — {label}",
      "notify.closeBody":
        "Outdoor air is warmer ({out} °C vs {in} °C indoors).",
      "notify.humidTitle": "Keep windows closed — {label}",
      "notify.humidBody":
        "Outdoor is cooler ({out} °C) but too humid (high dew point).",
      "notify.neutralTitle": "Windows — {label}",
      "notify.neutralBody":
        "Indoor and outdoor temperatures are close ({in} °C / {out} °C).",
      "common.error": "Error: {error}",
    },
    fr: {
      "brand.tagline": "Température et humidité — scan BLE local",
      "nav.views": "Vues",
      "nav.overview": "Vue d’ensemble",
      "nav.compare": "Comparer",
      "nav.facades": "Façades",
      "nav.map": "Plan",
      "nav.data": "Données",
      "nav.coverage": "Couverture",
      "nav.backfill": "Rattrapage",
      "nav.system": "Système",
      "nav.settings": "Réglages",
      "nav.peers": "Pairs de fédération",
      "nav.home": "Accueil",
      "nav.homeTitle": "Retour au portail (port 80)",
      "nav.gitPull": "Git pull",
      "nav.gitPullTitle": "git pull --ff-only",
      "nav.restartUi": "Redémarrer l’UI",
      "nav.restartUiTitle": "Redémarrer le service UI",
      "nav.restartWorkers": "Redémarrer les workers",
      "nav.restartWorkersTitle": "Redémarrer le service workers",
      "alerts.bar": "Alertes",
      "tts.title": "Alertes vocales (synthèse vocale)",
      "tts.aria": "Activer/désactiver les alertes vocales",
      "tts.on": "Alertes vocales activées — cliquer pour désactiver",
      "tts.off": "Alertes vocales désactivées — cliquer pour activer",
      "tts.disable": "Désactiver les alertes vocales",
      "tts.enable": "Activer les alertes vocales",
      "tts.unsupported": "Alertes vocales non prises en charge par ce navigateur",
      "tts.enabledSpeak": "Alertes vocales activées",
      "tts.voiceLabel": "Voix des alertes",
      "tts.voiceDefault": "Défaut du navigateur",
      "tts.groupMac": "Mac (Safari)",
      "tts.groupServer": "Serveur (edge-tts)",
      "tts.groupHome": "Home TTS",
      "tts.homeSpeakers": "Home TTS (canal alerts)",
      "windowNotify.title": "Alertes fenêtres",
      "windowNotify.aria": "Activer/désactiver les alertes fenêtres",
      "windowNotify.on": "Alertes fenêtres activées — cliquer pour désactiver",
      "windowNotify.off": "Alertes fenêtres désactivées — cliquer pour activer",
      "windowNotify.disable": "Désactiver les alertes fenêtres",
      "windowNotify.enable": "Activer les alertes fenêtres",
      "windowNotify.ready": "Alertes fenêtres activées",
      "windowNotify.readyClick":
        "Notifications autorisées — cliquez sur la cloche pour activer les alertes",
      "windowNotify.pending": "En attente de l’autorisation des notifications…",
      "windowNotify.reloading":
        "Mise à jour de l’autorisation — rechargement de l’app…",
      "windowNotify.unsupported":
        "Notifications non prises en charge par ce navigateur",
      "windowNotify.insecure":
        "Les notifications nécessitent HTTPS (ouvrez l’app via https://…:8081, pas http)",
      "windowNotify.denied":
        "Notifications refusées — autorisez-les dans les réglages système/Safari, puis revenez ici",
      "windowNotify.blocked":
        "Notifications non accordées — acceptez l’invite ou activez-les dans Réglages, puis revenez ici",
      "windowNotify.testTitle": "Govee Charts — test",
      "windowNotify.testBody": "Les alertes fenêtres fonctionnent.",
      "windowNotify.action.enable": "Activer la cloche",
      "windowNotify.action.disable": "Désactiver la cloche",
      "windowNotify.action.retry": "Redemander",
      "windowNotify.action.reload": "Recharger l’app",
      "windowNotify.action.test": "Envoyer un test",
      "windowNotify.action.copyHttps": "Copier le lien HTTPS",
      "windowNotify.diag.unsupported.status":
        "Ce navigateur n’a pas d’API Notification.",
      "windowNotify.diag.unsupported.fix":
        "Utilisez Safari ou Chrome sur ordinateur, ou une app Dock / écran d’accueil sur appareil Apple compatible.",
      "windowNotify.diag.insecure.status": "Contexte non sécurisé (HTTP).",
      "windowNotify.diag.insecure.fix":
        "Ouvrez l’app en HTTPS, p.ex. {url} (acceptez le certificat une fois), puis rajoutez-la au Dock / écran d’accueil si besoin.",
      "windowNotify.diag.insecure.copied":
        "Lien HTTPS prêt : {url} — ouvrez-le, puis réessayez la cloche.",
      "windowNotify.diag.denied.status": "Permission navigateur refusée.",
      "windowNotify.diag.denied.fix":
        "Dans Réglages Système → Notifications → {app} (ou Safari → Réglages → Sites web → Notifications), choisissez Autoriser, puis revenez dans l’app : elle se recharge et allume la cloche.",
      "windowNotify.diag.denied.fixQuit":
        "Permission encore refusée après rechargement. Quittez complètement l’app web (Cmd+Q), rouvrez-la, puis utilisez Recharger ou la cloche.",
      "windowNotify.diag.prompt.status": "Permission pas encore demandée.",
      "windowNotify.diag.prompt.fix":
        "Cliquez sur Activer la cloche (ou la cloche en haut) et acceptez l’invite Safari.",
      "windowNotify.diag.grantedOff.status":
        "Permission OK, mais les alertes sont encore off.",
      "windowNotify.diag.grantedOff.fix":
        "Cliquez sur Activer la cloche pour allumer les alertes fenêtres.",
      "windowNotify.diag.noSw.status": "Alertes on, mais pas de service worker.",
      "windowNotify.diag.noSw.fix":
        "Safari standalone préfère un service worker. Rechargez l’app en HTTPS ; si ça échoue encore, quittez et rouvrez.",
      "windowNotify.diag.okTab.status": "Alertes fenêtres activées (onglet).",
      "windowNotify.diag.okTab.fix":
        "Pour les alertes en arrière-plan sur iPhone/iPad, ajoutez le site à l’écran d’accueil et ouvrez-le depuis l’icône.",
      "windowNotify.diag.ok.status": "Alertes fenêtres activées.",
      "windowNotify.diag.ok.fix":
        "Vous pouvez envoyer une notification test ou désactiver la cloche.",
      "doorBeep.title": "Bip à l’ouverture / fermeture porte ou fenêtre",
      "doorBeep.aria": "Activer/désactiver le bip porte / fenêtre",
      "doorBeep.on": "Bip porte / fenêtre activé — cliquer pour désactiver",
      "doorBeep.off": "Bip porte / fenêtre désactivé — cliquer pour activer",
      "doorBeep.disable": "Désactiver le bip porte / fenêtre",
      "doorBeep.enable": "Activer le bip porte / fenêtre",

      "settings.title": "Réglages",
      "settings.hint":
        "La langue, la voix et les stations météo sont enregistrées dans ce navigateur.",
      "settings.language": "Langue",
      "settings.languageHelp": "Langue de l’interface",
      "settings.voice": "Voix des alertes",
      "settings.voiceHelp":
        "Uniquement les voix de la langue choisie. Activez les alertes vocales avec le bouton haut-parleur dans la barre d’alertes.",
      "settings.voiceTest": "Tester",
      "settings.voiceTestTitle": "Lire la dernière bannière d’alerte",
      "settings.voiceTestEmpty": "Aucune bannière d’alerte à rejouer pour l’instant.",
      "settings.notify": "Notifications fenêtres",
      "settings.notifyHelp":
        "Diagnostique les problèmes de permission (surtout Safari standalone) et propose des correctifs.",
      "settings.stations": "Stations météo",
      "settings.stationsHelp":
        "Choisir les stations affichées sur les graphiques Comparer et les cartes de projection. Enregistré dans ce navigateur.",
      "settings.stationsEmpty": "Aucune station météo configurée sur ce nœud.",
      "settings.stationsCoords": "{lat}, {lon}",
      "settings.service": "Service",
      "settings.serviceHelp":
        "Récupérer le dernier code, puis redémarrer l’UI et/ou les workers pour appliquer les changements.",
      "settings.lang.en": "English",
      "settings.lang.fr": "Français",

      "overview.title": "Tous les capteurs",
      "overview.hint":
        "Modifier nom / zone / hauteur / hauteur cm / pièce en ligne — Charts ouvre les graphiques",
      "overview.filter": "Filtrer",
      "overview.filterPlaceholder": "Nom ou MAC…",
      "overview.filterModel": "Filtrer par modèle",
      "overview.filterCategory": "Filtrer par catégorie",
      "overview.zone": "Zone",
      "overview.height": "Hauteur",
      "overview.room": "Pièce",
      "overview.sort": "Trier les capteurs",
      "overview.sortLabel": "Tri",
      "overview.sort.name": "Nom",
      "overview.sort.temp": "Temp",
      "overview.sort.humidity": "Humidité",
      "overview.sort.battery": "Batterie",
      "overview.sort.signal": "Signal",
      "overview.sort.zone": "Zone",
      "overview.sort.room": "Pièce",
      "overview.sort.updated": "Maj",
      "overview.loading": "Chargement…",
      "overview.doorsTitle": "Portes et fenêtres",
      "overview.doorsHint":
        "Capteurs de contact — définir type/pièce ; cliquer un nom pour le journal",
      "overview.col.sensor": "Capteur",
      "overview.col.state": "État",
      "overview.col.kind": "Type",
      "overview.col.room": "Pièce",
      "overview.col.updated": "Maj",
      "overview.doorLogTitle": "Journal ouverture / fermeture",
      "overview.doorLogClose": "Fermer",
      "overview.doorLogCloseTitle": "Fermer le journal",
      "overview.doorLogHint": "7 derniers jours",
      "overview.col.time": "Heure",
      "overview.col.source": "Source",
      "overview.selectContact": "Choisir un contact…",
      "overview.noDevices": "Aucun appareil détecté",
      "overview.waitingBle": "En attente d’appareils BLE…",
      "overview.noSensorsFilter": "Aucun capteur pour ces filtres",
      "overview.statusFiltered":
        "{shown} / {total} capteur(s) · filtres actifs",
      "overview.statusCount": "{shown} / {total} capteur(s)",
      "overview.statusCountSame": "{n} capteur(s)",
      "overview.allModels": "Tous les modèles",
      "overview.all": "Tous",
      "overview.charts": "Graphiques",
      "overview.chartsTitle": "Ouvrir les graphiques de comparaison",
      "overview.chartsAria": "Ouvrir les graphiques pour {name}",
      "overview.pushMeta": "Pousser méta",
      "overview.pushMetaTitle":
        "Pousser nom, zone, hauteur, hauteur cm et pièce vers les pairs",
      "overview.pushing": "Envoi…",
      "overview.pushed": "Envoyé",
      "overview.partial": "Partiel",
      "overview.metaPushedFail":
        "Méta poussée vers {ok}/{total} pair(s). Échecs : {fail}",
      "overview.metaPushedOk":
        "Méta poussée vers {ok} pair(s) pour {name}.",
      "overview.metaPushFailed": "Échec poussée méta : {error}",
      "overview.namePlaceholder": "Nom",
      "overview.nameTitle": "Nom convivial (enregistré sur ce nœud)",
      "overview.nameFailed": "Échec mise à jour du nom : {error}",
      "overview.heightCm": "Hauteur cm",
      "overview.heightCmTitle": "Hauteur de montage au-dessus du sol (cm)",
      "overview.heightCmInvalid": "Hauteur cm doit être entre 0 et 600",
      "overview.catFailed": "Échec mise à jour catégorie : {error}",
      "overview.doorLogNamed": "{name} — journal ouverture / fermeture",
      "overview.doorLogLastDays": "{n} derniers jours",
      "overview.doorLogLastHours": "{n} dernières h",
      "overview.doorLogEmpty": "Aucun événement sur cette période",
      "overview.doorLogUnavailable": "Journal indisponible : {error}",
      "overview.noDoors": "Aucun capteur de contact",
      "overview.noDoorsYet": "Aucun contact porte/fenêtre pour l’instant",
      "overview.waitingDoors":
        "En attente des contacts MQTT (activer [doors] dans la config)…",
      "overview.doorsUnavailable": "Portes indisponibles",
      "overview.federation": "Fédération",
      "overview.battery": "Batterie {value}",
      "overview.updatedAt": " · maj {time}",

      "compare.selection": "Sélection",
      "compare.devices": "Appareils",
      "compare.devicesGroup": "Appareils à comparer",
      "compare.all": "Tous",
      "compare.none": "Aucun",
      "compare.facade.groupLabel": "Façade :",
      "compare.facade.groupTitle": "Sélectionner tous les capteurs de la façade {room}",
      "compare.timeRange": "Période",
      "compare.longerRange": "Période longue",
      "compare.longerTimeRange": "Période plus longue",
      "compare.more": "Plus…",
      "compare.custom": "Perso…",
      "compare.from": "Du",
      "compare.to": "Au",
      "compare.apply": "Appliquer",
      "compare.resetZoom": "Réinit. zoom",
      "compare.resetZoomTitle": "Réinitialiser le zoom du graphique",
      "compare.zoomHint":
        "Glisser pour zoomer · Maj+glisser pour panoramiquer · double-clic pour réinit.",
      "compare.forecast": "Prévisions et projections",
      "compare.future": "Futur",
      "compare.forecastHorizon": "Horizon de prévision",
      "compare.scenario": "Scénario",
      "compare.scenarioTitle": "Scénario de fenêtres à tracer",
      "compare.scenario.auto": "Ouverture actuelle",
      "compare.scenario.closed": "Fenêtres fermées",
      "compare.scenario.open": "Fenêtres ouvertes",
      "compare.scenario.both": "Fermé + ouvert",
      "compare.scenario.coolest": "Le plus frais (ouv./ferm.)",
      "compare.scenario.warmest": "Le plus chaud (ouv./ferm.)",
      "compare.windowBands": "Ouverture / fermeture fenêtres",
      "compare.hvac": "Clim et puissance",
      "compare.locate": "Localiser",
      "compare.locateTitle": "Utiliser la position du navigateur",
      "compare.chartHeight": "Hauteur des graphiques",
      "compare.chartHeightPx": "{n} px",
      "compare.currentReadings": "Mesures actuelles",
      "compare.foldProjections": "Prévisions et projections",
      "compare.temp": "Température (°C)",
      "compare.hum": "Humidité (%)",
      "compare.dew": "Point de rosée (°C)",
      "compare.spread.title": "Écart de température par pièce (°C)",
      "compare.spread.hint": "Max − min entre les capteurs partageant la même pièce, sur la période sélectionnée.",
      "compare.spread.titleFacade": "Écart de température par façade (°C)",
      "compare.spread.hintFacade": "Max − min entre tous les capteurs (intérieur + extérieur) partageant la même orientation de façade.",
      "compare.spread.interior": "intérieur",
      "compare.spread.exterior": "extérieur",
      "compare.spread.spreadSuffix": "écart",
      "compare.openCools": "ouvrir refroidit",
      "compare.openHeats": "ouvrir réchauffe",
      "compare.tooHumid": "trop humide",
      "compare.acOn": "clim allumée",
      "compare.powerNote": "· puissance (W) sur l’axe droit",
      "compare.loading": "Chargement…",
      "compare.selectDevice": "Sélectionnez au moins un appareil…",
      "compare.widget.title": "Exporter un widget",
      "compare.widget.meta": "lien de graphique partageable",
      "compare.widget.hint":
        "Construit une URL de graphique autonome pour iframe ou signet. Les courbes reprennent la sélection Compare.",
      "compare.widget.metric": "Métrique",
      "compare.widget.metric.temp": "Température",
      "compare.widget.metric.hum": "Humidité",
      "compare.widget.metric.dew": "Point de rosée",
      "compare.widget.past": "Passé",
      "compare.widget.future": "Futur",
      "compare.widget.futureOff": "Désactivé",
      "compare.widget.forecast": "Inclure la prévision",
      "compare.widget.transparent": "Fond transparent",
      "compare.widget.legend": "Afficher la légende",
      "compare.widget.refresh": "Actualisation auto",
      "compare.widget.refreshOff": "Désactivée",
      "compare.widget.curves": "Courbes",
      "compare.widget.useSelection": "Sélection",
      "compare.widget.allVisible": "Tous visibles",
      "compare.widget.none": "Aucun",
      "compare.widget.link": "Lien",
      "compare.widget.copy": "Copier",
      "compare.widget.open": "Ouvrir",
      "compare.widget.preview": "Aperçu",
      "compare.widget.copied": "Lien copié",
      "compare.widget.needCurves": "Sélectionnez au moins une courbe.",
      "compare.widget.iframe":
        '<iframe src="{url}" width="100%" height="320" style="border:0;background:transparent" loading="lazy"></iframe>',
      "compare.noDevices": "Aucun appareil détecté",
      "compare.noDevicesMetric": "Aucun appareil",
      "compare.noSensorsModel": "Aucun capteur pour ce modèle",
      "compare.error": "Erreur : {error}",
      "compare.status":
        "{names} · {points} point(s) · {range}{extra}{window}{hvac} · maj {time}",
      "compare.forecastGps": "GPS",
      "compare.forecastConfig": "config",
      "compare.forecastCached": ", cache",
      "compare.forecastStale": ", cache périmé",
      "compare.forecastLoc": " · prévision {name} ({src}{cache})",
      "compare.forecastOffError": " · prévision off ({error})",
      "compare.forecastOffHint":
        " · prévision off (autoriser la localisation ou régler [weather] place)",
      "compare.windowLegendTitle":
        "D’après {label} vs extérieur (temp ±{delta} °C, point de rosée vs air intérieur)",
      "compare.noneSelected": "· aucune sélection",
      "compare.sensorsMeta": "· {n} capteur",
      "compare.sensorsMetaPlural": "· {n} capteurs",
      "compare.metric.temp": "Température",
      "compare.metric.humidity": "Humidité",
      "compare.metric.dew": "Point de rosée",
      "compare.metric.battery": "Batterie",
      "compare.metric.signal": "Signal",
      "compare.metric.last": "Dernière mesure",

      "banner.workersOffline": "Workers hors ligne",
      "banner.workersDetail":
        "Collecteur BLE / workers sans réponse ({age}). Redémarrez les workers si cela persiste.",
      "banner.noHeartbeat": "aucun heartbeat",
      "banner.lastSeen": "vu il y a {age}",
      "banner.bleStalled": "Scan BLE bloqué",
      "banner.bleNoAdsStart": "aucune publicité depuis le démarrage",
      "banner.bleNoAdsFor": "aucune publicité depuis {age}",
      "banner.bleDetail":
        "{age}. Vérifiez le dongle Bluetooth USB / BlueZ, puis redémarrez les workers.",
      "banner.noRoomsContacts":
        "Aucune pièce intérieure avec capteur et contact",
      "banner.noContacts": "Aucun contact porte/fenêtre lié aux pièces",
      "banner.assignRooms":
        "Assignez une pièce dans Vue d’ensemble → Portes et fenêtres.",
      "banner.enableDoors":
        "Activez [doors] et associez les contacts aux pièces dans Vue d’ensemble.",
      "banner.outdoor": "Extérieur {temp} °C",
      "banner.dewRh": " · rosée {dew} °C · HR {rh} %",
      "banner.openNow": "Ouvert : {names}",
      "banner.allClosed": "Toutes les ouvertures suivies sont fermées",
      "banner.noAction": "Pas d’action fenêtre forte",
      "banner.tempsClose":
        "{climate}. Températures intérieure et extérieure proches. {open}.",
      "banner.closeTitle": "Fermer les fenêtres — {rooms}",
      "banner.closeHumid":
        "{climate}. L’extérieur est plus frais mais trop humide alors que des ouvertures restent ouvertes. {open}.",
      "banner.closeWarm":
        "{climate}. L’air extérieur est plus chaud qu’à l’intérieur. {open}.",
      "banner.alsoOpen": " À ouvrir aussi : {rooms}.",
      "banner.openTitle": "Ouvrir les fenêtres — {rooms}",
      "banner.openDetail":
        "{climate}. L’extérieur est plus frais et assez sec. {open}.",
      "banner.okOpenTitle": "Fenêtres OK ouvertes — {rooms}",
      "banner.okOpenDetail":
        "{climate}. Refroidissement à l’air extérieur. {open}.",
      "banner.closedOk": " Fermées OK : {rooms}.",
      "banner.okClosedTitle": "Fenêtres OK fermées — {rooms}",
      "banner.okClosedDetail": "{climate}. {open}.",
      "notify.openTitle": "Ouvrir les fenêtres — {label}",
      "notify.openBody":
        "L’air extérieur est plus frais ({out} °C vs {in} °C dedans) et assez sec.",
      "notify.closeTitle": "Fermer les fenêtres — {label}",
      "notify.closeBody":
        "L’air extérieur est plus chaud ({out} °C vs {in} °C dedans).",
      "notify.humidTitle": "Garder les fenêtres fermées — {label}",
      "notify.humidBody":
        "L’extérieur est plus frais ({out} °C) mais trop humide (point de rosée élevé).",
      "notify.neutralTitle": "Fenêtres — {label}",
      "notify.neutralBody":
        "Températures intérieure et extérieure proches ({in} °C / {out} °C).",
      "common.error": "Erreur : {error}",
    },
  };

  /** @type {string} */
  let locale = detectInitial();

  /** @type {Set<(lang: string) => void>} */
  const listeners = new Set();

  function detectInitial() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && SUPPORTED.has(saved)) return saved;
    } catch (_) {
      /* ignore */
    }
    const nav = String(
      (typeof navigator !== "undefined" &&
        (navigator.language || navigator.userLanguage)) ||
        "en"
    ).toLowerCase();
    return nav.startsWith("fr") ? "fr" : "en";
  }

  function getLocale() {
    return locale;
  }

  /** BCP-47 tag for dates / number formatting. */
  function localeTag() {
    return locale === "fr" ? "fr-FR" : "en-GB";
  }

  /** Language tag for speechSynthesis when no voice is selected. */
  function speechLang() {
    return locale === "fr" ? "fr-FR" : "en-US";
  }

  /**
   * @param {string} key
   * @param {Record<string, string|number>|null} [vars]
   */
  function t(key, vars) {
    const catalog = CATALOGS[locale] || CATALOGS.en;
    let text = catalog[key];
    if (text == null) text = (CATALOGS.en || {})[key];
    if (text == null) text = key;
    if (vars) {
      text = String(text).replace(/\{(\w+)\}/g, (_, name) =>
        vars[name] != null ? String(vars[name]) : `{${name}}`
      );
    }
    return text;
  }

  /**
   * @param {ParentNode|Document|null} [root]
   */
  function applyDom(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      el.textContent = t(key);
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (!key) return;
      el.setAttribute("placeholder", t(key));
    });
    scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.getAttribute("data-i18n-title");
      if (!key) return;
      el.setAttribute("title", t(key));
    });
    scope.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
      const key = el.getAttribute("data-i18n-aria-label");
      if (!key) return;
      el.setAttribute("aria-label", t(key));
    });
  }

  /**
   * @param {string} lang
   * @param {{silent?: boolean}} [opts]
   */
  function setLocale(lang, opts) {
    const next = SUPPORTED.has(lang) ? lang : "en";
    const changed = next !== locale;
    locale = next;
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch (_) {
      /* ignore */
    }
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
    applyDom(document);
    if (!opts || !opts.silent) {
      listeners.forEach((fn) => {
        try {
          fn(locale);
        } catch (err) {
          console.warn("onLocaleChange failed", err);
        }
      });
    }
    return changed;
  }

  /**
   * @param {(lang: string) => void} fn
   * @returns {() => void}
   */
  function onLocaleChange(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  // Apply saved/detected locale to <html> early; DOM text on DOMContentLoaded
  // if app.js runs later — app.js also calls applyDom after wiring.
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }

  window.I18n = {
    STORAGE_KEY,
    SUPPORTED: [...SUPPORTED],
    t,
    getLocale,
    setLocale,
    localeTag,
    speechLang,
    applyDom,
    onLocaleChange,
  };
})();
