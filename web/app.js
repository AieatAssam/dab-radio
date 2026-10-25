"use strict";

(() => {
  const $ = (selector, root) => (root || document).querySelector(selector);
  const audio = $("#radio-audio");
  const stationList = $("#station-list");
  const searchInput = $("#station-search");
  const channelSelect = $("#channel-select");
  const favoriteKeys = "dab-radio-favourites";
  const volumeKey = "dab-radio-volume";
  const fallbackVolume = 0.72;
  const state = {
    data: null,
    fresh: false,
    hasLoaded: false,
    stations: [],
    channels: [],
    selectedStation: null,
    favoritesOnly: false,
    favorites: readFavorites(),
    stationRenderKey: "",
    channelRenderKey: "",
    audioStarted: false,
    desiredPlaying: false,
    buffering: false,
    ignoreStartupBuffer: false,
    underruns: 0,
    context: null,
    source: null,
    preGain: null,
    filters: {},
    limiter: null,
    preGainTarget: null,
    analyser: null,
    frequencyData: null,
    frameId: 0,
    lastFrame: 0,
    lastStatPaint: 0,
    lastSlideKey: "",
    slideFailed: false,
    actionMessage: "",
    actionError: false,
    scanRequestError: "",
    scanWasActive: false,
    scanResumeWanted: false,
    pollBusy: false,
    pollTimer: 0,
    retryTimer: 0,
    retryCount: 0,
    stablePlayTimer: 0,
    resettingStream: false,
    audioError: ""
  };

  let miniPlayer = null;
  let miniNavigationBusy = false;

  const eqInputs = Array.from(document.querySelectorAll("[data-eq]"));
  const eqValues = {
    low: $("#eq-low-value"),
    mid: $("#eq-mid-value"),
    high: $("#eq-high-value")
  };

  function readFavorites() {
    try {
      const value = JSON.parse(localStorage.getItem(favoriteKeys) || "[]");
      return new Set(Array.isArray(value) ? value.map(String) : []);
    } catch (_error) {
      return new Set();
    }
  }

  function saveFavorites() {
    try {
      localStorage.setItem(favoriteKeys, JSON.stringify(Array.from(state.favorites)));
    } catch (_error) {
      /* The playlist still works when storage is unavailable. */
    }
  }

  function get(object, key) {
    return object && Object.prototype.hasOwnProperty.call(object, key) ? object[key] : undefined;
  }

  function firstValue() {
    for (let i = 0; i < arguments.length; i += 1) {
      const value = arguments[i];
      if (value !== undefined && value !== null && value !== "") return value;
    }
    return undefined;
  }

  function asText(value) {
    if (value === undefined || value === null || value === "") return "";
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) return value.map(asText).filter(Boolean).join(" · ");
    const nested = firstValue(value.text, value.value, value.label, value.name, value.title, value.description);
    if (nested !== undefined) return asText(nested);
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return "";
    }
  }

  function setText(selector, value, emptyValue) {
    const node = typeof selector === "string" ? $(selector) : selector;
    if (!node) return;
    const text = asText(value);
    const next = text || emptyValue || "—";
    if (node.textContent !== next) node.textContent = next;
  }

  function displayValue(value, unit) {
    const text = asText(value);
    if (!text) return "—";
    if (unit && typeof value === "number" && Number.isFinite(value)) return text + " " + unit;
    return text;
  }

  function channelOf(item) {
    return asText(item && item.channel);
  }

  function stationServiceId(item) {
    if (!item) return "";
    return asText(firstValue(item.id, item.sid, item.service_id, item.service));
  }

  function favoriteKey(item) {
    const id = stationServiceId(item);
    if (id) return id.toLowerCase();
    return (asText(item && item.name) + "|" + channelOf(item)).toLowerCase();
  }

  function selectedFields(selected) {
    if (!selected) return { channel: "", service: "" };
    if (typeof selected === "string" || typeof selected === "number") {
      return { channel: "", service: String(selected) };
    }
    return {
      channel: asText(selected.channel),
      service: asText(firstValue(selected.service, selected.id, selected.sid, selected.service_id))
    };
  }

  function findSelected(stations, selected) {
    const fields = selectedFields(selected);
    if (!fields.service) return null;
    const wanted = fields.service.toLowerCase();
    return stations.find((item) => {
      const ids = [item.id, item.sid, item.service_id, item.service].filter((value) => value !== undefined && value !== null).map((value) => String(value).toLowerCase());
      const channelMatches = !fields.channel || !channelOf(item) || channelOf(item).toLowerCase() === fields.channel.toLowerCase();
      return ids.includes(wanted) && channelMatches;
    }) || null;
  }

  function currentMetadata() {
    return (state.data && state.data.metadata) || {};
  }

  function currentReceiver() {
    return (state.data && state.data.receiver) || {};
  }

  function currentStats() {
    return (state.data && state.data.stats) || {};
  }

  function selectedChannel() {
    return asText(firstValue(state.data && state.data.selected && state.data.selected.channel, state.selectedStation && state.selectedStation.channel, currentReceiver().channel));
  }

  function formatSampleRate(value) {
    if (value === undefined || value === null || value === "") return "—";
    if (typeof value === "string" && /[a-z]/i.test(value)) return value;
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return asText(value);
    return numeric >= 1000 ? (numeric / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 }) + " kHz" : numeric + " Hz";
  }

  function formatBitrate(value) {
    if (value === undefined || value === null || value === "") return "—";
    if (typeof value === "string" && /kb|kbps|kbit/i.test(value)) return value;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toLocaleString() + " kb/s" : asText(value);
  }

  function formatDb(value) {
    if (value === undefined || value === null || value === "") return "—";
    if (typeof value === "string" && /db/i.test(value)) return value;
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return asText(value);
    return (numeric > 0 ? "+" : "") + numeric.toFixed(1) + " dB";
  }

  function formatBytes(value) {
    const numeric = Number(value);
    if (value === undefined || value === null || value === "" || !Number.isFinite(numeric)) return "—";
    if (numeric < 1000) return Math.round(numeric) + " B";
    const units = ["kB", "MB", "GB", "TB"];
    let amount = numeric;
    let unitIndex = -1;
    while (amount >= 1000 && unitIndex < units.length - 1) {
      amount /= 1000;
      unitIndex += 1;
    }
    return amount.toFixed(amount >= 100 ? 0 : amount >= 10 ? 1 : 2) + " " + units[unitIndex];
  }

  function formatTimestamp(value) {
    if (value === undefined || value === null || value === "") return "—";
    let date;
    if (typeof value === "number" || /^\d{10,13}$/.test(String(value))) {
      const numeric = Number(value);
      date = new Date(numeric < 100000000000 ? numeric * 1000 : numeric);
    } else {
      date = new Date(value);
    }
    return Number.isNaN(date.getTime()) ? asText(value) : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return "--:--";
    const whole = Math.floor(seconds);
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const remainder = whole % 60;
    const two = (number) => String(number).padStart(2, "0");
    return hours > 0 ? two(hours) + ":" + two(minutes) + ":" + two(remainder) : two(minutes) + ":" + two(remainder);
  }

  function scanInfo() {
    return (state.data && state.data.scan) || {};
  }

  function radioTextValue(value) {
    if (value === undefined || value === null) return "";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (Array.isArray(value)) return value.map(radioTextValue).filter(Boolean).join(" · ");
    if (typeof value === "object") return asText(firstValue(value.label, value.text, value.value, value.dls, value.message));
    return "";
  }

  function renderConnection() {
    const receiver = currentReceiver();
    const scan = scanInfo();
    const hasError = Boolean(receiver.error || receiver.status === "error");
    const isReady = receiver.status === "ready" || receiver.status === "healthy";
    const label = !state.fresh ? (state.hasLoaded ? "STALE" : "CONNECTING") : hasError ? "ISSUE" : isReady ? "ONLINE" : asText(receiver.status).toUpperCase() || "STARTING";
    setText("#connection-label", label);
    setText("#hardware-name", receiver.hardware && receiver.hardware.name);
    setText("#footer-status", !state.fresh ? (state.hasLoaded ? "Receiver state is not updating" : "Connecting to receiver…") : hasError ? asText(receiver.error) || "Receiver reports an error" : scan.active ? "Scanning ensemble " + asText(scan.channel) + "…" : isReady ? "Receiver online" : "Receiver " + (asText(receiver.status) || "starting"));

    const led = $("#receiver-led");
    const footerLed = $(".footer-led");
    led.classList.toggle("is-ready", state.fresh && isReady && !hasError);
    led.classList.toggle("is-error", state.fresh && hasError);
    footerLed.classList.toggle("is-ready", state.fresh && isReady && !hasError);
    footerLed.classList.toggle("is-error", state.fresh && hasError);
    setText("#stat-receiver-status", receiver.status);
    setText("#stat-hardware", receiver.hardware && receiver.hardware.name);

    const software = receiver.software || {};
    const softwareLabel = [asText(software.name), asText(software.version)].filter(Boolean).join(" · ");
    setText("#stat-software", softwareLabel);
    setText("#stat-gain", displayValue(receiver.hardware && receiver.hardware.gain, "dB"));
    const scanned = state.channels.filter((channel) => channel.scanned_at).length;
    setText("#stat-scanned", state.channels.length ? scanned + " / " + state.channels.length : "—");
    const latestScan = state.channels.reduce((latest, channel) => {
      if (!channel.scanned_at) return latest;
      const time = new Date(channel.scanned_at).getTime();
      return Number.isFinite(time) && time > latest ? time : latest;
    }, 0);
    setText("#stat-scan-time", latestScan ? formatTimestamp(latestScan) : "—");

    const errorNode = $("#receiver-error");
    errorNode.hidden = !receiver.error;
    errorNode.textContent = asText(receiver.error);

    const onAirLed = $("#on-air-led");
    onAirLed.classList.toggle("is-live", state.fresh && isReady && !hasError);
    if (scan.active) setText("#playback-state", "SCANNING");
    else if (hasError) setText("#playback-state", "RECEIVER ISSUE");
    else if (!state.fresh) setText("#playback-state", "STATE STALE");
    else if (audio && !audio.paused && !audio.ended) setText("#playback-state", audio.readyState >= 3 ? "LIVE" : "BUFFERING");
    else setText("#playback-state", "READY");
  }

  function renderChannels() {
    const previous = channelSelect.value;
    const channelMap = new Map();
    state.channels.forEach((channel) => {
      if (channel.channel) channelMap.set(String(channel.channel), channel);
    });
    state.stations.forEach((station) => {
      const channel = channelOf(station);
      if (channel && !channelMap.has(channel)) channelMap.set(channel, { channel: channel });
    });

    const options = [{ value: "all", label: "All ensembles" }];
    Array.from(channelMap.values()).forEach((channel) => {
      const parts = [String(channel.channel)];
      if (channel.frequency_mhz !== undefined && channel.frequency_mhz !== null) parts.push(Number(channel.frequency_mhz).toFixed(3) + " MHz");
      const serviceCount = Array.isArray(channel.services) ? channel.services.length : Number(channel.services);
      if (Number.isFinite(serviceCount)) parts.push(serviceCount + (serviceCount === 1 ? " service" : " services"));
      options.push({ value: String(channel.channel), label: parts.join(" · ") });
    });
    const signature = JSON.stringify(options);
    if (signature === state.channelRenderKey) return;
    const hadFocus = document.activeElement === channelSelect;
    const fragment = document.createDocumentFragment();
    const allOption = document.createElement("option");
    allOption.value = options[0].value;
    allOption.textContent = options[0].label;
    fragment.append(allOption);

    options.slice(1).forEach((channel) => {
      const option = document.createElement("option");
      option.value = channel.value;
      option.textContent = channel.label;
      fragment.append(option);
    });

    channelSelect.replaceChildren(fragment);
    channelSelect.value = channelMap.has(previous) ? previous : "all";
    state.channelRenderKey = signature;
    if (hadFocus) channelSelect.focus({ preventScroll: true });
  }

  function stationMatches(station, query, selectedChannelValue) {
    const key = favoriteKey(station);
    if (state.favoritesOnly && !state.favorites.has(key)) return false;
    if (selectedChannelValue !== "all" && channelOf(station) !== selectedChannelValue) return false;
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    const haystack = [station.name, station.label, station.id, station.sid, station.channel, station.source_codec, station.language, station.pty].map(asText).join(" ").toLowerCase();
    return haystack.includes(needle);
  }

  function makeStationRow(station) {
    const row = document.createElement("li");
    row.className = "station-row";
    const key = favoriteKey(station);
    const selected = Boolean(state.selectedStation && favoriteKey(state.selectedStation) === key);
    row.classList.toggle("is-selected", selected);

    const tune = document.createElement("button");
    tune.type = "button";
    tune.className = "station-select";
    tune.dataset.tune = key;
    tune.setAttribute("aria-label", "Tune " + (asText(station.name) || asText(station.label) || "service") + (channelOf(station) ? " on " + channelOf(station) : ""));
    if (selected) tune.setAttribute("aria-current", "true");
    const serviceId = stationServiceId(station);
    if (!serviceId || !channelOf(station) || scanInfo().active) tune.disabled = true;

    const name = document.createElement("span");
    name.className = "station-select__name";
    name.textContent = asText(firstValue(station.name, station.label)) || "Unnamed service";
    const meta = document.createElement("span");
    meta.className = "station-select__meta";
    [channelOf(station), asText(station.source_codec), serviceId].filter(Boolean).forEach((value) => {
      const item = document.createElement("span");
      item.textContent = value;
      meta.append(item);
    });
    tune.append(name, meta);

    const favorite = document.createElement("button");
    favorite.type = "button";
    favorite.className = "station-favorite";
    favorite.dataset.favorite = key;
    favorite.setAttribute("aria-label", (state.favorites.has(key) ? "Remove " : "Add ") + (asText(station.name) || "station") + (state.favorites.has(key) ? " from" : " to") + " favourites");
    favorite.setAttribute("aria-pressed", state.favorites.has(key) ? "true" : "false");
    favorite.innerHTML = '<svg viewBox="0 0 24 24" fill="' + (state.favorites.has(key) ? "currentColor" : "none") + '" aria-hidden="true"><path d="m12 3.5 2.7 5.45 6.02.88-4.36 4.25 1.03 6-5.39-2.83-5.39 2.83 1.03-6L3.28 9.83l6.02-.88L12 3.5Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    row.append(tune, favorite);
    return row;
  }

  function renderStations() {
    const query = searchInput.value;
    const selectedChannelValue = channelSelect.value || "all";
    const visible = state.stations.filter((station) => stationMatches(station, query, selectedChannelValue));
    const scan = scanInfo();
    let emptyMessage = "";
    if (!visible.length) {
      if (query) emptyMessage = "No services match “" + query + "”.";
      else if (state.favoritesOnly && !state.favorites.size) emptyMessage = "No favourites yet. Star a service to save it here.";
      else if (state.favoritesOnly) emptyMessage = "No saved favourites in this ensemble.";
      else if (scan.active) emptyMessage = "Scanning " + asText(scan.channel) + " · " + asText(scan.completed) + " of " + asText(scan.total) + " channels.";
      else if (currentReceiver().error) emptyMessage = "No services received. The receiver reports an issue.";
      else if (state.hasLoaded) emptyMessage = "No services have been reported by the receiver yet.";
      else emptyMessage = "Waiting for receiver state…";
    }
    const renderKey = JSON.stringify([
      visible.map((station) => [favoriteKey(station), station.name, station.label, station.channel, station.source_codec, station.sid, state.favorites.has(favoriteKey(station)), Boolean(state.selectedStation && favoriteKey(state.selectedStation) === favoriteKey(station))]),
      emptyMessage,
      state.favoritesOnly
    ]);
    if (renderKey !== state.stationRenderKey) {
      stationList.replaceChildren();
      if (visible.length) {
        const fragment = document.createDocumentFragment();
        visible.forEach((station) => fragment.append(makeStationRow(station)));
        stationList.append(fragment);
      } else {
        const empty = document.createElement("li");
        empty.className = "playlist-empty";
        const led = document.createElement("span");
        led.className = "empty-led";
        led.setAttribute("aria-hidden", "true");
        const message = document.createElement("span");
        message.textContent = emptyMessage;
        empty.append(led, message);
        stationList.append(empty);
      }
      state.stationRenderKey = renderKey;
    }

    setText("#station-count", state.stations.length);
    const favoriteCount = state.stations.filter((station) => state.favorites.has(favoriteKey(station))).length;
    setText("#favorite-count", favoriteCount);
    setText("#service-summary", state.stations.length ? visible.length + " shown · " + state.stations.length + " services" : "Awaiting services");
    setText("#ensemble-summary", state.channels.length ? state.channels.filter((channel) => channel.scanned_at).length + " scanned" : "—");
  }

  function currentSlideUrl() {
    const metadata = currentMetadata();
    const station = state.selectedStation || {};
    const mot = firstValue(metadata.mot, station.mot);
    const direct = firstValue(metadata.slide_url, station.slide_url, mot && typeof mot === "object" && firstValue(mot.url, mot.slide_url, mot.src));
    const directUrl = direct ? String(direct) : "";
    const isSelectedSlideEndpoint = /^\/api\/slide(?:$|\?)/.test(directUrl);
    if (directUrl && !isSelectedSlideEndpoint) return directUrl;
    if (mot === undefined || mot === null || mot === false || mot === "") return "";
    if (typeof mot === "object") {
      const hasImage = Number(mot.time) > 0 || Number(mot.lastchange) > 0;
      if (!hasImage) return "";
    }
    return directUrl || "/api/slide";
  }

  function currentSlideKey(url) {
    const mot = firstValue(currentMetadata().mot, state.selectedStation && state.selectedStation.mot);
    return url + "|" + (mot && typeof mot === "object" ? JSON.stringify(mot) : asText(mot));
  }

  function renderSlide() {
    const figure = $("#radio-slide");
    const image = $("#slide-image");
    const url = currentSlideUrl();
    const key = currentSlideKey(url);
    const station = state.selectedStation || {};
    const metadata = currentMetadata();
    const spiService = metadata.spi && metadata.spi.service;
    const stationLogo = !url && firstValue(spiService && spiService.logo_url, station.logo_url);
    if (!url && !stationLogo) {
      figure.hidden = true;
      image.removeAttribute("src");
      state.lastSlideKey = "";
      return;
    }
    if (!url && stationLogo) {
      figure.dataset.kind = "logo";
      const logoKey = "station-logo|" + stationLogo;
      if (logoKey === state.lastSlideKey) return;
      state.lastSlideKey = logoKey;
      figure.hidden = true;
      image.alt = "Station logo: " + asText(firstValue(spiService && spiService.name, station.name));
      setText("#slide-caption", asText(firstValue(spiService && spiService.name, station.name)), "Station logo");
      image.src = stationLogo;
      return;
    }
    figure.dataset.kind = "slide";
    if (key === state.lastSlideKey) return;

    state.lastSlideKey = key;
    state.slideFailed = false;
    figure.hidden = true;
    const caption = asText(firstValue(currentMetadata().mot && typeof currentMetadata().mot === "object" && firstValue(currentMetadata().mot.title, currentMetadata().mot.caption, currentMetadata().mot.description), currentMetadata().programme, state.selectedStation && state.selectedStation.name));
    image.alt = caption ? "DAB slideshow: " + caption : "Current station slideshow";
    setText("#slide-caption", caption, "");
    const cacheKey = encodeURIComponent(key).slice(0, 140);
    const separator = url.includes("?") ? "&" : "?";
    image.src = url === "/api/slide" ? url + separator + "v=" + cacheKey : url;
  }

  function renderMetadata() {
    const metadata = currentMetadata();
    const station = state.selectedStation;
    const fields = selectedFields(state.data && state.data.selected);
    const name = station ? asText(firstValue(station.name, station.label)) : fields.service ? "Service " + fields.service : "No service selected";
    setText("#current-service", name);
    const dls = firstValue(metadata.dls, station && station.dls);
    const radioText = radioTextValue(dls);
    const radioTextNode = $("#radio-text");
    const nextRadioText = radioText || "Waiting for live radio text…";
    if (radioTextNode.textContent !== nextRadioText) radioTextNode.textContent = nextRadioText;
    radioTextNode.classList.toggle("is-empty", !radioText);
    $(".text-signal").classList.toggle("is-stale", !radioText || !state.fresh);
    setText("#text-source", radioText ? (metadata.live === false ? "DLS · SAVED" : "DLS · LIVE") : "DLS · WAITING");

    const dlplus = metadata.dlplus || {};
    const tags = Array.isArray(dlplus.tags) ? dlplus.tags : [];
    const tagValue = (name) => dlplus.item_running ? tags.find((tag) => tag.name === name)?.text : undefined;
    const artist = asText(firstValue(metadata.artist, tagValue("ITEM.ARTIST"), metadata.performer));
    const title = asText(firstValue(metadata.title, tagValue("ITEM.TITLE")));
    const spi = metadata.spi || {};
    const currentProgramme = spi.current_programme || {};
    const programme = asText(firstValue(metadata.programme, currentProgramme.name, metadata.program));
    const detail = [artist, title].filter(Boolean).join(" · ") || programme;
    const programmeNode = $("#programme-line");
    programmeNode.textContent = detail;
    const desc = asText(firstValue(metadata.programme_description, currentProgramme.description, spi.service && spi.service.description));
    setText("#programme-description", desc, "");
    setText("#stat-dlplus-status", dlplus.available ? "Available" : "Unavailable");
    setText("#stat-dlplus-source", dlplus.available ? "DAB DL+ tags" : "—");
    setText("#stat-spi-status", ({ ready: "Available", unavailable: "Not supplied", loading: "Loading" })[spi.status]);
    setText("#stat-spi-source", firstValue(spi.source));
    const guide = $("#programme-guide");
    guide.replaceChildren();
    const programmes = Array.isArray(spi.programmes) ? spi.programmes : [];
    $(".programme-guide-details").hidden = !programmes.length;
    setText("#stat-spi-guide", ({ ready: "Available", empty: "Not supplied", not_published: "Not supplied" })[spi.guide_status]);
    programmes.slice(0, 12).forEach((item) => {
      const li = document.createElement("li");
      const readableTime = (value) => {
        const date = new Date(value);
        return Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
      };
      const time = [item.start && readableTime(item.start), item.end && readableTime(item.end)].filter(Boolean).join("–");
      li.textContent = [time, item.name, item.description].filter(Boolean).join(" · ");
      guide.append(li);
    });

    const favorite = $("#current-favorite");
    const isFavorite = station ? state.favorites.has(favoriteKey(station)) : false;
    favorite.disabled = !station;
    favorite.setAttribute("aria-pressed", isFavorite ? "true" : "false");
    favorite.setAttribute("aria-label", (isFavorite ? "Remove " : "Add ") + (name || "current station") + (isFavorite ? " from" : " to") + " favourites");

    const channel = selectedChannel();
    setText("#tuned-channel", channel);
    $("#current-favorite").dataset.favorite = station ? favoriteKey(station) : "";
    renderSlide();
  }

  function componentsOf(metadata, station) {
    const components = firstValue(metadata.components, station && station.components);
    if (components === undefined || components === null || components === "") return [];
    if (Array.isArray(components)) return components.map(asText).filter(Boolean);
    if (typeof components === "object") {
      return Object.keys(components).map((key) => {
        const value = components[key];
        return typeof value === "boolean" ? (value ? key : "") : key + ": " + asText(value);
      }).filter(Boolean);
    }
    return [asText(components)];
  }

  function renderComponents() {
    const list = $("#component-list");
    list.replaceChildren();
    const components = componentsOf(currentMetadata(), state.selectedStation);
    if (!components.length) components.push("—");
    components.forEach((component) => {
      const item = document.createElement("li");
      item.textContent = component;
      list.append(item);
    });
  }

  function renderStats() {
    const station = state.selectedStation || {};
    const metadata = currentMetadata();
    const stats = currentStats();
    const selection = selectedFields(state.data && state.data.selected);
    const sourceCodec = firstValue(station.source_codec, metadata.source_codec);
    const deliveryCodec = firstValue(station.codec, metadata.codec);
    const bitrate = firstValue(station.bitrate, metadata.bitrate);
    const sampleRate = firstValue(station.sample_rate, metadata.sample_rate);
    const sourceMode = firstValue(station.source_mode, metadata.source_mode, station.mode, metadata.mode);

    setText("#broadcast-readout", sourceCodec);
    setText("#delivery-readout", deliveryCodec);
    setText("#bitrate-readout", formatBitrate(bitrate));

    setText("#stat-source-codec", sourceCodec);
    setText("#stat-browser-codec", deliveryCodec);
    setText("#stat-bitrate", formatBitrate(bitrate));
    setText("#stat-sample-rate", formatSampleRate(sampleRate));
    setText("#stat-source-mode", sourceMode);
    setText("#stat-channel", firstValue(selection.channel, station.channel, currentReceiver().channel));
    setText("#stat-service-id", firstValue(selection.service, station.id, station.sid));
    setText("#stat-language", firstValue(station.language, metadata.language));
    setText("#stat-pty", firstValue(station.pty, metadata.pty));
    setText("#stat-snr", displayValue(stats.snr, "dB"));
    setText("#stat-frequency-correction", firstValue(stats.frequency_correction, stats.frequencyCorrection));
    setText("#stat-fic-errors", firstValue(stats.fic_crc_errors, stats.fic_crc_error_count));
    setText("#stat-last-fct0", formatTimestamp(firstValue(stats.time_last_fct0_frame, stats.last_fct0_frame)));

    setText("#stat-buffer", state.audioStarted ? formatBufferAhead() : "—");
    setText("#stat-underruns", state.underruns + " · this session");
    setText("#stat-limiter", state.limiter ? Math.abs(state.limiter.reduction).toFixed(1) + " dB" : "—");
    setText("#stat-output-rate", state.context ? formatSampleRate(state.context.sampleRate) : "—");
    setText("#stat-clients", get(stats, "stream_clients"));
    setText("#stat-bytes", formatBytes(get(stats, "stream_bytes")));
    setText("#stat-reconnects", get(stats, "stream_reconnects"));
    setText("#stat-backend-errors", get(stats, "stream_errors"));
    setText("#stat-slow-disconnects", get(stats, "stream_slow_disconnects"));
    setText("#stat-stream-last-error", get(stats, "stream_last_error"));
    setText("#stat-audio-level", firstValue(metadata.audiolevel, metadata.audio_level));
    setText("#stat-xpad-errors", firstValue(metadata.xpaderror, metadata.xpad_error));
    setText("#stat-service-errors", firstValue(station.errors, metadata.errors));
    setText("#stat-error-counters", firstValue(metadata.errorcounters, metadata.error_counters));
    renderComponents();
  }

  function renderScan() {
    const scan = scanInfo();
    const progress = $("#scan-progress");
    const scanButton = $("#scan-button");
    const active = Boolean(scan.active);
    if (active && !state.scanWasActive) {
      state.scanResumeWanted = state.scanResumeWanted || state.desiredPlaying;
      if (state.desiredPlaying) pausePlayback();
    }
    if (!active && state.scanWasActive && state.scanResumeWanted) {
      state.scanResumeWanted = false;
      window.setTimeout(startPlayback, 250);
    }
    state.scanWasActive = active;
    progress.hidden = !active;
    scanButton.disabled = false;
    scanButton.classList.toggle("is-loading", active);
    scanButton.setAttribute("aria-busy", active ? "true" : "false");
    scanButton.querySelector("span").textContent = active ? "Cancel scan" : "Scan";
    scanButton.setAttribute("aria-label", active ? "Cancel channel scan" : "Scan channels");
    if (active) {
      setText("#scan-label", "Scanning " + asText(scan.channel));
      const completed = Number(scan.completed);
      const total = Number(scan.total);
      setText("#scan-count", Number.isFinite(completed) && Number.isFinite(total) ? completed + " / " + total : "—");
      $("#scan-meter").max = Number.isFinite(total) && total > 0 ? total : 1;
      $("#scan-meter").value = Number.isFinite(completed) ? completed : 0;
    }
    const completed = Number(scan.completed);
    const total = Number(scan.total);
    let message = state.scanRequestError ? "Scan could not start: " + state.scanRequestError : "";
    if (!message && scan.error) message = "Scan stopped: " + asText(scan.error);
    if (!message && !active && scan.started_at && scan.finished_at && Number.isFinite(completed) && Number.isFinite(total) && total > 0 && completed < total) {
      message = "Scan stopped after " + completed + " of " + total + " channels.";
    }
    const feedback = $("#scan-feedback");
    feedback.hidden = !message;
    if (feedback.textContent !== message) feedback.textContent = message;
  }

  function renderAll() {
    renderConnection();
    renderChannels();
    state.selectedStation = findSelected(state.stations, state.data && state.data.selected);
    renderMetadata();
    renderStations();
    renderScan();
    renderStats();
    syncTransportUI();
  }

  async function pollState() {
    if (state.pollBusy) return;
    if (state.pollTimer) {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = 0;
    }
    state.pollBusy = true;
    try {
      const response = await fetch("/api/state", { cache: "no-store", headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("State request returned " + response.status);
      const data = await response.json();
      if (!data || typeof data !== "object") throw new Error("Invalid receiver state");
      state.data = data;
      state.stations = Array.isArray(data.stations) ? data.stations : [];
      state.channels = Array.isArray(data.channels) ? data.channels : [];
      state.fresh = true;
      state.hasLoaded = true;
      renderAll();
    } catch (_error) {
      state.fresh = false;
      renderConnection();
      if (!state.hasLoaded) {
        renderChannels();
        renderStations();
      }
    } finally {
      state.pollBusy = false;
      if (state.pollTimer) window.clearTimeout(state.pollTimer);
      state.pollTimer = window.setTimeout(pollState, 1000);
    }
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: body ? JSON.stringify(body) : undefined
    });
    if (!response.ok) {
      let message = "Request failed (" + response.status + ")";
      try {
        const result = await response.json();
        message = asText(firstValue(result.detail, result.error, result.message)) || message;
      } catch (_error) {
        /* Keep the HTTP status when the backend sends no JSON body. */
      }
      throw new Error(message);
    }
    return response;
  }

  async function tuneStation(station) {
    const channel = channelOf(station);
    const service = station && firstValue(station.id, station.sid, station.service_id, station.service);
    if (!channel || service === undefined || service === null || service === "") return;
    state.actionMessage = "Tuning " + asText(station.name || station.label) + "…";
    state.actionError = false;
    setText("#transport-message", state.actionMessage);
    try {
      await postJson("/api/tune", { channel: channel, service: String(service) });
      await restartForTune();
      await pollState();
    } catch (error) {
      state.actionMessage = error.message || "Tune request failed";
      state.actionError = true;
      setText("#transport-message", state.actionMessage);
    }
  }

  async function scanChannels() {
    const button = $("#scan-button");
    if (scanInfo().active) {
      try { await postJson("/api/scan/cancel"); await pollState(); }
      catch (error) { state.scanRequestError = error.message || "Scan cancellation failed"; renderScan(); }
      return;
    }
    state.scanRequestError = "";
    renderScan();
    button.disabled = true;
    button.classList.add("is-loading");
    button.setAttribute("aria-busy", "true");
    try {
      await postJson("/api/scan");
      await pollState();
    } catch (error) {
      state.actionMessage = error.message || "Scan request failed";
      state.actionError = true;
      state.scanRequestError = state.actionMessage;
      renderScan();
      setText("#transport-message", state.actionMessage);
      button.disabled = false;
      button.classList.remove("is-loading");
      button.setAttribute("aria-busy", "false");
    }
  }

  function toggleFavorite(key) {
    if (!key) return;
    if (state.favorites.has(key)) state.favorites.delete(key);
    else state.favorites.add(key);
    saveFavorites();
    renderMetadata();
    renderStations();
  }

  function dbToGain(decibels) {
    return Math.pow(10, decibels / 20);
  }

  function eqGain(name) {
    const input = eqInputs.find((item) => item.dataset.eq === name);
    return input ? input.valueAsNumber : 0;
  }

  function updateHeadroom() {
    const positiveBoost = ["low", "mid", "high"].reduce((sum, name) => sum + Math.max(0, eqGain(name)), 0);
    const headroomDb = -(6 + positiveBoost);
    const label = "−" + Math.abs(headroomDb).toFixed(1) + " dB";
    setText("#headroom-readout", label);
    if (state.preGain && state.context) {
      const targetGain = dbToGain(headroomDb);
      const reducing = state.preGainTarget !== null && targetGain < state.preGainTarget;
      state.preGain.gain.setTargetAtTime(targetGain, state.context.currentTime, reducing ? 0.003 : 0.04);
      state.preGainTarget = targetGain;
    }
  }

  function setupAudioGraph() {
    if (state.context) {
      return state.context.state === "running" ? Promise.resolve(true) : state.context.resume().then(() => true).catch(() => false);
    }
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return Promise.resolve(false);
    try {
      const context = new Context();
      const source = context.createMediaElementSource(audio);
      const preGain = context.createGain();
      const initialPositiveBoost = ["low", "mid", "high"].reduce((sum, name) => sum + Math.max(0, eqGain(name)), 0);
      preGain.gain.value = dbToGain(-(6 + initialPositiveBoost));
      const low = context.createBiquadFilter();
      low.type = "lowshelf";
      low.frequency.value = 120;
      low.gain.value = eqGain("low");
      const mid = context.createBiquadFilter();
      mid.type = "peaking";
      mid.frequency.value = 1000;
      mid.Q.value = 0.8;
      mid.gain.value = eqGain("mid");
      const high = context.createBiquadFilter();
      high.type = "highshelf";
      high.frequency.value = 8000;
      high.gain.value = eqGain("high");
      const limiter = context.createDynamicsCompressor();
      limiter.threshold.value = -6;
      limiter.knee.value = 2;
      limiter.ratio.value = 20;
      limiter.attack.value = 0.005;
      limiter.release.value = 0.16;
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.68;
      analyser.minDecibels = -90;
      analyser.maxDecibels = -18;

      source.connect(preGain);
      preGain.connect(low);
      low.connect(mid);
      mid.connect(high);
      high.connect(limiter);
      limiter.connect(analyser);
      analyser.connect(context.destination);

      state.context = context;
      state.source = source;
      state.preGain = preGain;
      state.preGainTarget = preGain.gain.value;
      state.filters = { low: low, mid: mid, high: high };
      state.limiter = limiter;
      state.analyser = analyser;
      state.frequencyData = new Uint8Array(analyser.frequencyBinCount);
      updateHeadroom();
      renderStats();
      return context.resume().then(() => true);
    } catch (_error) {
      return Promise.resolve(false);
    }
  }

  function syncTransportUI() {
    const playing = !audio.paused && !audio.ended;
    const button = $("#play-button");
    button.disabled = Boolean(scanInfo().active);
    button.classList.toggle("is-playing", playing);
    button.setAttribute("aria-label", playing ? "Pause live radio" : "Play live radio");
    setText("#transport-title", state.selectedStation ? asText(firstValue(state.selectedStation.name, state.selectedStation.label)) : "Live radio");
    if (state.audioError) setText("#transport-message", state.audioError);
    else if (state.actionMessage) setText("#transport-message", state.actionMessage);
    else if (playing && audio.readyState >= 3) setText("#transport-message", "Receiving live audio");
    else if (playing) setText("#transport-message", "Buffering live audio…");
    else setText("#transport-message", state.selectedStation ? "Ready to listen" : "Select a service, then press play");
    if (state.actionError) $("#transport-message").classList.add("is-error");
    else $("#transport-message").classList.remove("is-error");
    $("#spectrum-state").classList.toggle("is-live", playing && Boolean(state.analyser));
    setText("#spectrum-state", playing && state.analyser ? "LIVE" : playing ? "PLAYING" : "READY");
    if (playing && !state.frameId) startSpectrum();
    if (!playing && state.frameId) stopSpectrum();
    if (miniPlayer) miniPlayer.refresh();
  }

  async function startPlayback() {
    state.desiredPlaying = true;
    state.audioError = "";
    state.actionMessage = "";
    await setupAudioGraph();
    if (!audio.getAttribute("src") || audio.ended || audio.error) attachLiveStream();
    audio.volume = Math.min(1, Math.max(0, Number($("#volume-range").value)));
    audio.muted = $("#mute-button").getAttribute("aria-pressed") === "true";
    try {
      await audio.play();
    } catch (error) {
      const message = error && error.name === "NotAllowedError" ? "Playback was blocked by the browser. Press play to try again." : "Live audio could not start.";
      if (error && error.name === "NotAllowedError") {
        state.desiredPlaying = false;
        state.audioError = message;
      } else {
        queueStreamRetry(message);
      }
    }
    syncTransportUI();
  }

  function attachLiveStream() {
    state.ignoreStartupBuffer = true;
    state.buffering = true;
    audio.src = "/stream.mp3?session=" + Date.now();
    audio.load();
  }

  function clearRetry() {
    if (state.retryTimer) window.clearTimeout(state.retryTimer);
    state.retryTimer = 0;
    if (state.stablePlayTimer) window.clearTimeout(state.stablePlayTimer);
    state.stablePlayTimer = 0;
  }

  function resetToLiveStream() {
    state.resettingStream = true;
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    state.ignoreStartupBuffer = true;
    state.buffering = true;
    audio.src = "/stream.mp3?session=" + Date.now();
    audio.load();
    state.resettingStream = false;
  }

  function queueStreamRetry(message) {
    if (!state.desiredPlaying || state.retryTimer) return;
    if (state.retryCount >= 3) {
      state.desiredPlaying = false;
      state.audioError = "The live stream stopped. Press play to reconnect.";
      state.retryCount = 0;
      state.resettingStream = true;
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      state.resettingStream = false;
      syncTransportUI();
      return;
    }
    const delays = [600, 1500, 3000];
    const delay = delays[state.retryCount];
    state.retryCount += 1;
    state.audioError = message;
    setText("#transport-message", message);
    state.retryTimer = window.setTimeout(() => {
      state.retryTimer = 0;
      resetToLiveStream();
      startPlayback();
    }, delay);
    syncTransportUI();
  }

  function pausePlayback() {
    state.desiredPlaying = false;
    state.audioError = "";
    state.actionMessage = "";
    state.retryCount = 0;
    clearRetry();
    state.resettingStream = true;
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    state.resettingStream = false;
    state.buffering = false;
    syncTransportUI();
  }

  async function restartForTune() {
    state.desiredPlaying = true;
    state.retryCount = 0;
    clearRetry();
    resetToLiveStream();
    await startPlayback();
  }

  function formatBufferAhead() {
    if (!audio || audio.readyState === 0 || !audio.buffered || !audio.buffered.length || !Number.isFinite(audio.currentTime)) return "—";
    let end = null;
    for (let index = 0; index < audio.buffered.length; index += 1) {
      const start = audio.buffered.start(index);
      const rangeEnd = audio.buffered.end(index);
      if (start <= audio.currentTime && audio.currentTime <= rangeEnd) end = rangeEnd;
    }
    if (end === null) return "—";
    return Math.max(0, end - audio.currentTime).toFixed(1) + " s";
  }

  function updateSessionTime() {
    const active = state.desiredPlaying && state.audioStarted && !audio.paused && audio.readyState >= 2;
    setText("#session-time", active && Number.isFinite(audio.currentTime) ? formatTime(audio.currentTime) : "--:--");
  }

  function setVolume(value) {
    const numeric = Math.min(1, Math.max(0, Number(value)));
    audio.volume = numeric;
    try { localStorage.setItem(volumeKey, String(numeric)); } catch (_error) { /* Optional preference. */ }
    $("#mute-button").setAttribute("aria-pressed", audio.muted ? "true" : "false");
    $("#mute-button").setAttribute("aria-label", audio.muted ? "Unmute audio" : "Mute audio");
  }

  function updateEq(input) {
    const name = input.dataset.eq;
    const gain = input.valueAsNumber;
    const output = eqValues[name];
    if (output) output.textContent = (gain > 0 ? "+" : "") + gain.toFixed(1) + " dB";
    if (state.filters[name]) state.filters[name].gain.setTargetAtTime(gain, state.context.currentTime, 0.025);
    updateHeadroom();
  }

  function resizeSpectrum() {
    const canvas = $("#spectrum-canvas");
    if (!canvas) return;
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.round(bounds.width * ratio);
    const height = Math.round(bounds.height * ratio);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }

  function drawSpectrum(now) {
    const canvas = $("#spectrum-canvas");
    const context = canvas && canvas.getContext("2d");
    if (!context || !canvas.width || !canvas.height) return;
    const bounds = canvas.getBoundingClientRect();
    const scaleX = canvas.width / bounds.width;
    const scaleY = canvas.height / bounds.height;
    const width = canvas.width;
    const height = canvas.height;
    context.clearRect(0, 0, width, height);
    if (!state.analyser || !state.frequencyData || audio.paused || audio.readyState < 2) return;

    state.analyser.getByteFrequencyData(state.frequencyData);
    const style = getComputedStyle(document.documentElement);
    const green = style.getPropertyValue("--color-led-green").trim();
    const amber = style.getPropertyValue("--color-led-amber").trim();
    const count = Math.max(20, Math.floor(bounds.width / 9));
    const minHz = 40;
    const maxHz = Math.min(16000, state.context.sampleRate / 2);
    const nyquist = state.context.sampleRate / 2;
    const barGap = Math.max(2, Math.round(2.5 * scaleX));
    const barWidth = Math.max(1, (width - barGap * (count - 1)) / count);
    const usableHeight = height * 0.88;
    const minLog = Math.log(minHz);
    const logSpan = Math.log(maxHz) - minLog;

    for (let bar = 0; bar < count; bar += 1) {
      const lowHz = Math.exp(minLog + (bar / count) * logSpan);
      const highHz = Math.exp(minLog + ((bar + 1) / count) * logSpan);
      const startBin = Math.max(1, Math.floor(lowHz / nyquist * state.frequencyData.length));
      const endBin = Math.max(startBin + 1, Math.ceil(highHz / nyquist * state.frequencyData.length));
      let magnitude = 0;
      for (let bin = startBin; bin < Math.min(endBin, state.frequencyData.length); bin += 1) {
        magnitude = Math.max(magnitude, state.frequencyData[bin]);
      }
      const barHeight = Math.max(0, (magnitude / 255) * usableHeight);
      if (barHeight < 1) continue;
      const ratio = bar / Math.max(1, count - 1);
      const segments = Math.max(1, Math.floor(barHeight / (3.4 * scaleY)));
      const segmentHeight = Math.max(1, 2.1 * scaleY);
      const segmentGap = Math.max(1, 1.25 * scaleY);
      context.fillStyle = ratio > 0.68 ? amber : green;
      for (let segment = 0; segment < segments; segment += 1) {
        const y = height - (segment + 1) * (segmentHeight + segmentGap);
        if (y < 0) break;
        context.fillRect(bar * (barWidth + barGap), y, barWidth, segmentHeight);
      }
    }
  }

  function animationFrame(now) {
    state.frameId = requestAnimationFrame(animationFrame);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const interval = reducedMotion ? 200 : 1000 / 30;
    if (now - state.lastFrame < interval) return;
    state.lastFrame = now;
    if (!document.hidden) drawSpectrum(now);
    if (now - state.lastStatPaint > 500) {
      state.lastStatPaint = now;
      renderStats();
      updateSessionTime();
    }
  }

  function startSpectrum() {
    resizeSpectrum();
    state.lastFrame = 0;
    state.frameId = requestAnimationFrame(animationFrame);
  }

  function stopSpectrum() {
    cancelAnimationFrame(state.frameId);
    state.frameId = 0;
    drawSpectrum(0);
    renderStats();
    updateSessionTime();
  }

  function onMediaWaiting() {
    if (state.ignoreStartupBuffer) {
      state.buffering = true;
      syncTransportUI();
      return;
    }
    if (state.audioStarted && !audio.paused && !state.buffering) {
      state.underruns += 1;
      state.buffering = true;
      renderStats();
    }
    syncTransportUI();
  }

  function setScanButtonDefaults() {
    const button = $("#scan-button");
    button.disabled = false;
    button.classList.remove("is-loading");
    button.setAttribute("aria-busy", "false");
    button.querySelector("span").textContent = "Scan";
  }

  function installEvents() {
    $("#play-button").addEventListener("click", () => {
      if (audio.paused || audio.ended) {
        state.retryCount = 0;
        clearRetry();
        startPlayback();
      }
      else pausePlayback();
    });

    $("#mute-button").addEventListener("click", () => {
      audio.muted = !audio.muted;
      setVolume($("#volume-range").value);
    });

    let storedVolume = fallbackVolume;
    try {
      const rawVolume = localStorage.getItem(volumeKey);
      if (rawVolume !== null) {
        const saved = Number(rawVolume);
        if (Number.isFinite(saved) && saved >= 0 && saved <= 1) storedVolume = saved;
      }
    } catch (_error) {
      /* Use the in-memory default. */
    }
    $("#volume-range").value = String(storedVolume);
    audio.volume = Math.min(1, storedVolume);
    $("#volume-range").addEventListener("input", (event) => setVolume(event.currentTarget.value));

    $("#refresh-button").addEventListener("click", (event) => {
      const button = event.currentTarget;
      button.classList.add("is-loading");
      pollState().finally(() => window.setTimeout(() => button.classList.remove("is-loading"), 160));
    });
    $("#scan-button").addEventListener("click", scanChannels);
    $("#all-filter").addEventListener("click", () => {
      state.favoritesOnly = false;
      $("#all-filter").classList.add("is-active");
      $("#all-filter").setAttribute("aria-pressed", "true");
      $("#favorites-filter").classList.remove("is-active");
      $("#favorites-filter").setAttribute("aria-pressed", "false");
      renderStations();
    });
    $("#favorites-filter").addEventListener("click", () => {
      state.favoritesOnly = true;
      $("#favorites-filter").classList.add("is-active");
      $("#favorites-filter").setAttribute("aria-pressed", "true");
      $("#all-filter").classList.remove("is-active");
      $("#all-filter").setAttribute("aria-pressed", "false");
      renderStations();
    });

    searchInput.addEventListener("input", renderStations);
    channelSelect.addEventListener("change", renderStations);
    stationList.addEventListener("click", (event) => {
      const favorite = event.target.closest("[data-favorite]");
      if (favorite) {
        toggleFavorite(favorite.dataset.favorite);
        return;
      }
      const tune = event.target.closest("[data-tune]");
      if (!tune || tune.disabled) return;
      const station = state.stations.find((item) => favoriteKey(item) === tune.dataset.tune);
      if (station) tuneStation(station);
    });
    $("#current-favorite").addEventListener("click", (event) => toggleFavorite(event.currentTarget.dataset.favorite));

    eqInputs.forEach((input) => {
      input.addEventListener("input", () => {
        updateEq(input);
        renderStats();
      });
    });
    $("#eq-reset").addEventListener("click", () => {
      eqInputs.forEach((input) => {
        input.value = "0";
        updateEq(input);
      });
      renderStats();
    });

    $("#slide-image").addEventListener("load", () => {
      state.slideFailed = false;
      $("#radio-slide").hidden = false;
    });
    $("#slide-image").addEventListener("error", () => {
      state.slideFailed = true;
      $("#radio-slide").hidden = true;
    });

    audio.addEventListener("playing", () => {
      state.audioStarted = true;
      state.buffering = false;
      state.ignoreStartupBuffer = false;
      state.audioError = "";
      if (state.stablePlayTimer) window.clearTimeout(state.stablePlayTimer);
      state.stablePlayTimer = window.setTimeout(() => {
        state.retryCount = 0;
        state.stablePlayTimer = 0;
      }, 20000);
      syncTransportUI();
      renderStats();
    });
    audio.addEventListener("waiting", onMediaWaiting);
    audio.addEventListener("stalled", onMediaWaiting);
    audio.addEventListener("canplay", () => syncTransportUI());
    audio.addEventListener("pause", () => {
      state.buffering = false;
      syncTransportUI();
    });
    audio.addEventListener("ended", () => {
      if (state.desiredPlaying && !state.resettingStream) queueStreamRetry("Stream disconnected. Reconnecting…");
      syncTransportUI();
    });
    audio.addEventListener("error", () => {
      if (state.resettingStream) return;
      state.audioError = "The live stream is unavailable.";
      if (state.desiredPlaying) queueStreamRetry(state.audioError);
      syncTransportUI();
    });
    audio.addEventListener("timeupdate", updateSessionTime);

    $("#stats-drawer").addEventListener("toggle", () => {
      if ($("#stats-drawer").open) renderStats();
    });

    document.addEventListener("keydown", (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
      const target = event.target;
      const typing = target && (target.matches("input, textarea, select") || target.isContentEditable);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        searchInput.focus({ preventScroll: true });
      } else if (event.code === "Space" && !typing && !(target && target.matches("button, a, summary, [role='button']"))) {
        event.preventDefault();
        if (audio.paused || audio.ended) startPlayback();
        else pausePlayback();
      }
    });

    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(resizeSpectrum);
      observer.observe($(".spectrum-display"));
    } else {
      window.addEventListener("resize", resizeSpectrum, { passive: true });
    }
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && !audio.paused) resizeSpectrum();
    });
  }

  function miniSnapshot() {
    const metadata = currentMetadata();
    const station = state.selectedStation;
    const radioText = radioTextValue(firstValue(metadata.dls, station && station.dls));
    return {
      station: station ? asText(firstValue(station.name, station.label)) : "Choose a station in the player",
      title: asText(metadata.title) || radioText || "Live radio",
      artist: asText(firstValue(metadata.artist, metadata.programme)),
      radioText: radioText,
      playing: state.desiredPlaying,
      buffering: state.desiredPlaying && (state.buffering || audio.readyState < 3),
      volume: audio.volume,
      muted: audio.muted,
      canPlay: !!station && !scanInfo().active,
      canNavigate: !miniNavigationBusy && miniStations().length > 1,
      scanActive: Boolean(scanInfo().active),
      error: state.audioError || (state.actionError ? state.actionMessage : "") || (scanInfo().active ? "Scanning channels — playback resumes afterwards" : "")
    };
  }

  function miniStations() {
    return state.stations.filter((station) => stationMatches(station, searchInput.value, channelSelect.value || "all"));
  }

  async function navigateMini(direction) {
    if (miniNavigationBusy || scanInfo().active) return;
    const stations = miniStations();
    if (!stations.length) return;
    const index = stations.findIndex((station) => state.selectedStation && favoriteKey(station) === favoriteKey(state.selectedStation));
    const next = index < 0 ? (direction > 0 ? 0 : stations.length - 1) : (index + direction + stations.length) % stations.length;
    miniNavigationBusy = true;
    try { await tuneStation(stations[next]); }
    finally { miniNavigationBusy = false; miniPlayer?.refresh(); }
  }

  function installMiniPlayer() {
    const launch = $("#mini-player-button");
    const feedback = $("#mini-player-feedback");
    if (!window.DABMiniPlayer) { launch.hidden = true; return; }
    if (!window.isSecureContext) {
      launch.disabled = true;
      launch.title = "Mini player requires HTTPS or localhost";
      launch.setAttribute("aria-label", launch.title);
      return;
    }
    launch.disabled = false;
    launch.title = "Open mini player";
    launch.setAttribute("aria-label", launch.title);
    const fail = (message) => { feedback.textContent = message; feedback.hidden = !message; };
    miniPlayer = window.DABMiniPlayer.create({
      snapshot: miniSnapshot,
      getAnalyser: () => state.analyser,
      play: () => { state.retryCount = 0; clearRetry(); return startPlayback(); },
      stop: pausePlayback,
      previous: () => navigateMini(-1),
      next: () => navigateMini(1),
      setVolume: (value) => { $("#volume-range").value = String(value); setVolume(value); },
      toggleMute: () => { audio.muted = !audio.muted; setVolume($("#volume-range").value); },
      onError: fail
    });
    launch.addEventListener("click", () => {
      fail("");
      try { Promise.resolve(miniPlayer.open()).catch((error) => fail(error.message || "Mini player could not open.")); }
      catch (error) { fail(error.message || "Mini player could not open."); }
    });
  }

  eqInputs.forEach(updateEq);
  setScanButtonDefaults();
  installEvents();
  installMiniPlayer();
  renderStations();
  renderConnection();
  pollState();
})();
