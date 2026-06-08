(function (root) {
  const modal = document.querySelector("#split-analysis-modal");
  if (!modal) {
    return;
  }

  const title = document.querySelector("#split-analysis-title");
  const svg = document.querySelector("#split-analysis-svg");
  const closeButton = document.querySelector("#split-analysis-close");
  const previousButton = document.querySelector("#split-analysis-prev");
  const nextButton = document.querySelector("#split-analysis-next");
  const reviewReasonSelect = document.querySelector("#split-review-reason");
  const reviewCustomInput = document.querySelector("#split-review-custom");
  const orientToggle = document.querySelector("#split-orient-toggle");
  const debugSnapshotButton = document.querySelector("#split-debug-snapshot");
  const exportSpeedSelect = document.querySelector("#split-export-speed");
  const exportVideoButton = document.querySelector("#split-export-video");
  const exportStatus = document.querySelector("#split-export-status");
  const drawToggleButton = document.querySelector("#split-draw-toggle");
  const drawClearButton = document.querySelector("#split-draw-clear");
  const routeStats = document.querySelector("#split-route-stats");
  const paceChart = document.querySelector("#split-pace-chart");
  const paceStatus = document.querySelector("#split-pace-status");
  const chatMessages = document.querySelector("#split-chat-messages");
  const chatStart = document.querySelector("#split-chat-start");
  const chatStartButton = document.querySelector("#split-chat-start-button");
  const chatForm = document.querySelector("#split-chat-form");
  const chatInput = document.querySelector("#split-chat-input");
  const chatSubmit = document.querySelector("#split-chat-submit");

  let active = null;
  let chatHistory = [];
  let chartInstance = null;
  let athleteMarker = null;
  let analysisSeconds = 0;
  let scrubPointerId = null;
  let paceSeries = [];
  let drawMode = false;
  let altRoutePoints = [];
  let altRouteLine = null;
  let mapLayer = null;
  let currentProjection = null;
  let drawPointerId = null;
  let errorReasons = [];
  let reasonsLoaded = false;
  let reviewSaveTimer = null;
  let reviewRequestId = 0;
  let activationRequestId = 0;
  let videoExporting = false;
  const layerImageCache = new Map();

  closeButton?.addEventListener("click", close);
  previousButton?.addEventListener("click", () => navigateSplit(-1));
  nextButton?.addEventListener("click", () => navigateSplit(1));
  reviewReasonSelect?.addEventListener("change", () => {
    updateReviewCustomVisibility();
    scheduleSaveReview(0);
  });
  reviewCustomInput?.addEventListener("input", () => {
    scheduleSaveReview(450);
  });
  reviewCustomInput?.addEventListener("blur", () => {
    scheduleSaveReview(0);
  });
  orientToggle?.addEventListener("change", () => {
    if (active) {
      renderMap();
    }
  });
  debugSnapshotButton?.addEventListener("click", openDebugSnapshot);
  exportVideoButton?.addEventListener("click", exportSplitVideo);
  modal.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.matches("[data-close-split-analysis]")) {
      close();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      close();
      return;
    }
    if (modal.hidden || isTextEntryTarget(event.target)) {
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      navigateSplit(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      navigateSplit(1);
    }
  });
  chatStartButton?.addEventListener("click", () => {
    sendChatMessage("Разбери этот сплит по карте: что получилось хорошо, где могла быть потеря времени, и что попробовать в следующий раз.");
  });
  chatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    sendChatMessage();
  });
  paceChart?.addEventListener("pointerdown", (event) => {
    if (!chartInstance) {
      return;
    }
    event.preventDefault();
    scrubPointerId = event.pointerId;
    paceChart.setPointerCapture(event.pointerId);
    paceChart.classList.add("scrubbing");
    seekToChartPointer(event);
  });
  paceChart?.addEventListener("pointermove", (event) => {
    if (scrubPointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    seekToChartPointer(event);
  });
  paceChart?.addEventListener("pointerup", finishScrub);
  paceChart?.addEventListener("pointercancel", finishScrub);
  drawToggleButton?.addEventListener("click", toggleDrawMode);
  drawClearButton?.addEventListener("click", clearAltRoute);
  svg?.addEventListener("pointerdown", onSvgPointerDown);
  svg?.addEventListener("pointermove", onSvgPointerMove);
  svg?.addEventListener("pointerup", onSvgPointerUp);
  svg?.addEventListener("pointercancel", onSvgPointerUp);

  async function open(options) {
    if (!options?.row || !svg) {
      return;
    }
    if (!hasMapLayerImage(options) && !options?.image) {
      return;
    }
    if (!hasMapLayerImage(options) && (!options.image.complete || !options.image.naturalWidth || !options.image.naturalHeight)) {
      options.image.addEventListener("load", () => open(options), {once: true});
      return;
    }
    active = {
      trainingId: options.trainingId,
      raceResultId: options.raceResultId || null,
      row: options.row,
      rows: Array.isArray(options.rows) && options.rows.length ? options.rows : [options.row],
      rowIndex: Number.isInteger(options.rowIndex) ? options.rowIndex : 0,
      image: options.image || null,
      fallbackImage: options.image || null,
      sourceTrackPoints: options.trackPoints || [],
      trackPoints: options.trackPoints || [],
      transform: options.transform || null,
      fallbackTransform: options.transform || null,
      mapLayers: normalizeMapLayers(options.mapLayers),
      mapLayerId: null,
    };
    if (!active.rows[active.rowIndex] || active.rows[active.rowIndex] !== active.row) {
      const index = active.rows.indexOf(active.row);
      active.rowIndex = index >= 0 ? index : 0;
      active.row = active.rows[active.rowIndex] || active.row;
    }
    await activateCurrentSplit();
    if (!active) {
      return;
    }
    modal.hidden = false;
    document.body.classList.add("modal-open");
    chatStartButton?.focus();
  }

  function close() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
    if (reviewSaveTimer) {
      clearTimeout(reviewSaveTimer);
      reviewSaveTimer = null;
    }
    reviewRequestId += 1;
    activationRequestId += 1;
    videoExporting = false;
    active = null;
    athleteMarker = null;
    altRouteLine = null;
    mapLayer = null;
    currentProjection = null;
    altRoutePoints = [];
    drawMode = false;
    drawPointerId = null;
    svg?.classList.remove("is-drawing");
    analysisSeconds = 0;
    destroyPaceChart();
    updateDrawButtons();
    updatePagerButtons();
    if (routeStats) {
      routeStats.hidden = true;
    }
  }

  function navigateSplit(delta) {
    if (!active || !active.rows?.length) {
      return;
    }
    const nextIndex = active.rowIndex + delta;
    if (nextIndex < 0 || nextIndex >= active.rows.length) {
      return;
    }
    active.rowIndex = nextIndex;
    active.row = active.rows[nextIndex];
    activateCurrentSplit();
  }

  async function activateCurrentSplit() {
    if (!active) {
      return;
    }
    const requestId = ++activationRequestId;
    analysisSeconds = 0;
    altRoutePoints = [];
    drawMode = false;
    drawPointerId = null;
    svg?.classList.remove("is-drawing");
    await prepareActiveSplitLayer(active.row);
    if (!active || requestId !== activationRequestId) {
      return;
    }
    updateTitle();
    resetChat(active.row);
    renderMap();
    drawPaceChart();
    updateDrawButtons();
    updateRouteStats();
    updatePagerButtons();
    loadReviewForActiveSplit();
  }

  function updateTitle() {
    if (!title || !active) {
      return;
    }
    title.textContent = `Сплит ${active.row.label}`;
  }

  function updatePagerButtons() {
    const count = active?.rows?.length || 0;
    if (previousButton) {
      previousButton.disabled = !active || active.rowIndex <= 0;
    }
    if (nextButton) {
      nextButton.disabled = !active || active.rowIndex >= count - 1;
    }
  }

  function hasMapLayerImage(options) {
    return Array.isArray(options?.mapLayers) && options.mapLayers.some((layer) => layer?.map_image_url);
  }

  function normalizeMapLayers(layers) {
    if (!Array.isArray(layers)) {
      return [];
    }
    return layers
      .filter((layer) => layer && typeof layer === "object")
      .map((layer, index) => ({
        ...layer,
        id: layer.id || `map-${index + 1}`,
        georef_transform: layer.georef_transform || null,
      }));
  }

  async function prepareActiveSplitLayer(row) {
    if (!active) {
      return;
    }
    const layer = splitMapLayer(row);
    const image = await imageForLayer(layer, active.fallbackImage);
    active.mapLayerId = layer?.id || null;
    active.image = image;
    active.transform = layer?.georef_transform || active.fallbackTransform || null;
    active.trackPoints = projectTrackPoints(active.sourceTrackPoints, active.transform);
  }

  function splitMapLayer(row) {
    if (!active?.mapLayers?.length) {
      return null;
    }
    const preferredLayerId =
      row?.toControl?.map_layer_id ||
      row?.viaControls?.find((control) => control?.map_layer_id)?.map_layer_id ||
      row?.fromControl?.map_layer_id ||
      null;
    return active.mapLayers.find((layer) => layer.id === preferredLayerId)
      || active.mapLayers.find((layer) => layer.map_image_url)
      || active.mapLayers[0]
      || null;
  }

  async function imageForLayer(layer, fallbackImage) {
    if (layer?.map_image_url) {
      const cacheKey = `${layer.id || ""}:${layer.map_image_url}`;
      if (!layerImageCache.has(cacheKey)) {
        layerImageCache.set(cacheKey, loadImage(layer.map_image_url));
      }
      return await layerImageCache.get(cacheKey);
    }
    if (!fallbackImage) {
      return null;
    }
    if (!fallbackImage.complete || !fallbackImage.naturalWidth || !fallbackImage.naturalHeight) {
      await new Promise((resolve) => fallbackImage.addEventListener("load", resolve, {once: true}));
    }
    return fallbackImage;
  }

  function projectTrackPoints(points, transform) {
    if (!Array.isArray(points)) {
      return [];
    }
    return points.map((point) => ({
      ...point,
      pixel: transform && Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lon))
        ? geoToPixel(point, transform)
        : point.pixel || {pixel_x: 0, pixel_y: 0},
    }));
  }

  function geoToPixel(point, transform) {
    const determinant = transform.lon_a * transform.lat_b - transform.lon_b * transform.lat_a;
    if (Math.abs(determinant) < 1e-12) {
      return {pixel_x: 0, pixel_y: 0};
    }
    const lon = point.lon - transform.lon_c;
    const lat = point.lat - transform.lat_c;
    return {
      pixel_x: (lon * transform.lat_b - transform.lon_b * lat) / determinant,
      pixel_y: (transform.lon_a * lat - lon * transform.lat_a) / determinant,
    };
  }

  async function ensureErrorReasons() {
    if (reasonsLoaded) {
      return;
    }
    try {
      const response = await fetch("/api/error-reasons");
      const payload = await response.json();
      errorReasons = Array.isArray(payload.reasons) ? payload.reasons : [];
      renderReasonOptions();
    } catch (_error) {
      errorReasons = [];
    } finally {
      reasonsLoaded = true;
    }
  }

  function renderReasonOptions(selectedReasonId = "") {
    if (!reviewReasonSelect) {
      return;
    }
    const previousValue = selectedReasonId || reviewReasonSelect.value;
    reviewReasonSelect.innerHTML = "";
    reviewReasonSelect.appendChild(reasonOption("", "Не выбрана"));
    errorReasons
      .filter((reason) => reason.is_active || reason.reason_id === previousValue)
      .forEach((reason) => {
        const label = reason.is_active ? reason.label : `${reason.label} (архив)`;
        reviewReasonSelect.appendChild(reasonOption(reason.reason_id, label));
      });
    reviewReasonSelect.appendChild(reasonOption("__custom__", "Свой вариант"));
    reviewReasonSelect.value = previousValue || "";
  }

  function reasonOption(value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
  }

  async function loadReviewForActiveSplit() {
    if (!active || !reviewReasonSelect || !reviewCustomInput) {
      return;
    }
    const requestId = ++reviewRequestId;
    await ensureErrorReasons();
    if (!active || requestId !== reviewRequestId) {
      return;
    }
    renderReasonOptions();
    reviewReasonSelect.value = "";
    reviewCustomInput.value = "";
    updateReviewCustomVisibility();
    try {
      const response = await fetch("/api/split-error-review/get", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(reviewKey(active.row)),
      });
      const payload = await response.json();
      if (!active || requestId !== reviewRequestId) {
        return;
      }
      applyReview(payload.review);
    } catch (_error) {
      applyReview(null);
    }
  }

  function applyReview(review) {
    if (!reviewReasonSelect || !reviewCustomInput) {
      return;
    }
    const reasonId = review?.reason_id || "";
    const customReason = review?.custom_reason || "";
    renderReasonOptions(reasonId);
    if (customReason) {
      reviewReasonSelect.value = "__custom__";
      reviewCustomInput.value = customReason;
    } else {
      reviewReasonSelect.value = reasonId;
      reviewCustomInput.value = "";
    }
    updateReviewCustomVisibility();
  }

  function updateReviewCustomVisibility() {
    if (!reviewReasonSelect || !reviewCustomInput) {
      return;
    }
    reviewCustomInput.hidden = reviewReasonSelect.value !== "__custom__";
  }

  function scheduleSaveReview(delayMs) {
    if (reviewSaveTimer) {
      clearTimeout(reviewSaveTimer);
    }
    reviewSaveTimer = setTimeout(saveReview, delayMs);
  }

  async function saveReview() {
    if (!active || !reviewReasonSelect || !reviewCustomInput) {
      return;
    }
    const selected = reviewReasonSelect.value;
    const problemIndex = active.row.__problemIndex;
    const payload = {
      ...reviewKey(active.row),
      reason_id: selected && selected !== "__custom__" ? selected : null,
      custom_reason: selected === "__custom__" ? reviewCustomInput.value.trim() : null,
    };
    try {
      const response = await fetch("/api/split-error-review", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (result.review?.reviewed_at && problemIndex !== undefined) {
        root.dispatchEvent(new CustomEvent("orienteering:split-reviewed", {
          detail: {problemIndex},
        }));
      }
    } catch (_error) {}
  }

  function reviewKey(row) {
    return {
      training_id: active.trainingId,
      race_result_id: active.raceResultId,
      split_label: String(row.label),
      from_control_label: String(row.fromControl.label),
      to_control_label: String(row.toControl.label),
    };
  }

  function resetChat(row) {
    chatHistory = [];
    if (!chatMessages) {
      return;
    }
    chatMessages.innerHTML = "";
    appendChatMessage("assistant", `Я тренер. Нажми «Начать диалог», и я разберу сплит ${row.label}.`);
    setChatStarted(false);
  }

  async function sendChatMessage(forcedQuestion = null) {
    if (!active || !chatInput || !chatMessages) {
      return;
    }
    const question = forcedQuestion || chatInput.value.trim();
    if (!question) {
      return;
    }
    if (!forcedQuestion) {
      chatInput.value = "";
      appendChatMessage("user", question);
    }
    chatHistory.push({role: "user", content: question});
    const pending = appendChatMessage("assistant", "Думаю...");
    setChatStarted(true);
    setChatPending(true);

    try {
      const response = await fetch("/api/split-analysis/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          training_id: active.trainingId,
          split: splitPayload(active.row),
          messages: chatHistory.slice(0, -1),
          question,
          image_data_url: await snapshotDataUrl(),
        }),
      });
      const payload = await response.json();
      const answer = payload.answer || "Не получилось сформулировать ответ.";
      renderAssistantMessage(pending, answer);
      chatHistory.push({role: "assistant", content: answer});
    } catch (error) {
      pending.textContent = `Не удалось связаться с тренером: ${error.message}`;
    } finally {
      setChatPending(false);
      chatInput.focus();
    }
  }

  function renderMap() {
    const row = active.row;
    const image = active.image;
    const coursePoints = splitCoursePoints(row);
    const trackSegment = splitTrackSegment(row);
    const focusPoints = [
      ...coursePoints.map(controlPixel),
      ...trackSegment.map((point) => point.pixel),
      ...altRoutePoints,
    ];
    currentProjection = orientToggle?.checked ? splitProjection(row) : null;
    svg.innerHTML = "";
    svg.setAttribute(
      "viewBox",
      (currentProjection
        ? orientedViewBox(focusPoints, currentProjection)
        : splitViewBox(focusPoints, image.naturalWidth, image.naturalHeight)
      ).join(" ")
    );

    const mapImage = document.createElementNS("http://www.w3.org/2000/svg", "image");
    mapImage.setAttribute("href", image.currentSrc || image.src);
    mapImage.setAttribute("x", "0");
    mapImage.setAttribute("y", "0");
    mapImage.setAttribute("width", String(image.naturalWidth));
    mapImage.setAttribute("height", String(image.naturalHeight));
    mapImage.setAttribute("preserveAspectRatio", "xMidYMid meet");

    appendArrowMarker();
    mapLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    if (currentProjection) {
      mapLayer.setAttribute("transform", projectionMatrix(currentProjection));
    }
    mapLayer.appendChild(mapImage);
    svg.appendChild(mapLayer);
    if (coursePoints.length >= 2) {
      addPolyline(coursePoints.map(controlPixel), "split-course-line");
    }
    if (trackSegment.length >= 2) {
      addPolyline(trackSegment.map((point) => point.pixel), "split-track-line");
    }
    altRouteLine = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    altRouteLine.setAttribute("class", "split-alt-route-line");
    altRouteLine.setAttribute("fill", "none");
    mapLayer.appendChild(altRouteLine);
    renderAltRoute();
    coursePoints.forEach((control, index) => {
      addControlMarker(control, index === 0 ? "from" : index === coursePoints.length - 1 ? "to" : "via");
    });
    athleteMarker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    athleteMarker.setAttribute("class", "split-athlete-marker");
    athleteMarker.setAttribute("r", "8");
    athleteMarker.setAttribute("fill", "#18a0fb");
    athleteMarker.setAttribute("stroke", "#ffffff");
    athleteMarker.setAttribute("stroke-width", "4");
    mapLayer.appendChild(athleteMarker);
    updateAthlete(0);
  }

  function drawPaceChart() {
    destroyPaceChart();
    if (!paceChart || !paceStatus || !active) {
      return;
    }
    const row = active.row;
    const trackSegment = splitTrackSegment(row);
    const baseSeconds = trackSegment[0]?.seconds || 0;
    const series = calculateTrackPaceSeries(trackSegment, baseSeconds);
    paceSeries = series;
    const duration = Math.max(row.splitSeconds || 0, 1);
    if (series.length < 2) {
      paceStatus.textContent = "нет данных";
      return;
    }
    if (!root.Chart) {
      paceStatus.textContent = "график недоступен";
      return;
    }
    const bounds = calculatePaceBounds(series);
    const playheadPlugin = {
      id: "splitPacePlayhead",
      afterDatasetsDraw(chart) {
        const xScale = chart.scales.x;
        const area = chart.chartArea;
        if (!xScale || !area) {
          return;
        }
        const x = xScale.getPixelForValue(clamp(analysisSeconds, 0, duration));
        const context = chart.ctx;
        context.save();
        context.strokeStyle = "#b21f5b";
        context.lineWidth = 2;
        context.beginPath();
        context.moveTo(x, area.top);
        context.lineTo(x, area.bottom);
        context.stroke();
        context.restore();
      },
    };
    chartInstance = new root.Chart(paceChart, {
      type: "line",
      data: {
        datasets: [{
          label: "Темп",
          data: series.map((point) => ({x: point.seconds, y: point.pace})),
          borderColor(context) {
            return createPaceGradient(context.chart, 1);
          },
          backgroundColor(context) {
            return createPaceGradient(context.chart, 0.22);
          },
          borderWidth: 2,
          pointRadius: 0,
          pointHitRadius: 8,
          tension: 0.25,
          fill: true,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        parsing: false,
        plugins: {legend: {display: false}, tooltip: {enabled: false}},
        scales: {
          x: {
            type: "linear",
            min: 0,
            max: duration,
            grid: {color: "rgba(102, 116, 124, 0.14)"},
            ticks: {maxTicksLimit: 6, callback: (value) => formatTime(Number(value))},
          },
          y: {
            min: bounds.min,
            max: bounds.max,
            grid: {color: "rgba(102, 116, 124, 0.14)"},
            ticks: {maxTicksLimit: 4, callback: (value) => formatPace(Number(value))},
          },
        },
      },
      plugins: [playheadPlugin],
    });
    updatePaceStatus();
  }

  async function snapshotDataUrl() {
    if (!svg || !active?.image) {
      return null;
    }
    const clonedSvg = svg.cloneNode(true);
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clonedSvg.querySelector(".split-athlete-marker")?.remove();
    const mapImage = clonedSvg.querySelector("image");
    if (mapImage) {
      mapImage.setAttribute("href", await imageElementDataUrl(active.image));
    }
    const source = new XMLSerializer().serializeToString(clonedSvg);
    const svgUrl = URL.createObjectURL(new Blob([source], {type: "image/svg+xml;charset=utf-8"}));
    try {
      const rendered = await loadImage(svgUrl);
      const canvas = document.createElement("canvas");
      canvas.width = 1280;
      canvas.height = 820;
      const context = canvas.getContext("2d");
      context.fillStyle = "#eef3f5";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(rendered, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/png");
    } finally {
      URL.revokeObjectURL(svgUrl);
    }
  }

  async function exportSplitVideo() {
    if (!active || !svg || !exportVideoButton || videoExporting) {
      return;
    }
    if (!("MediaRecorder" in root) || !HTMLCanvasElement.prototype.captureStream) {
      setExportStatus("Видео не поддерживается браузером");
      return;
    }
    const trackSegment = splitTrackSegment(active.row);
    const duration = Math.max(active.row.splitSeconds || 0, 0);
    if (trackSegment.length < 2 || duration <= 0) {
      setExportStatus("Нет данных трека для видео");
      return;
    }

    videoExporting = true;
    exportVideoButton.disabled = true;
    setExportStatus("Готовлю...");
    try {
      const speed = Number(exportSpeedSelect?.value || 5) || 5;
      const canvas = document.createElement("canvas");
      canvas.width = 1280;
      canvas.height = 820;
      const context = canvas.getContext("2d");
      if (!context) {
        throw new Error("Canvas недоступен");
      }
      const baseImage = await splitMapBaseImage(canvas.width, canvas.height);
      const viewBox = parseViewBox(svg.getAttribute("viewBox"), active.image.naturalWidth, active.image.naturalHeight);
      const stream = canvas.captureStream(30);
      const mimeType = supportedVideoMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
      const chunks = [];
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data?.size) {
          chunks.push(event.data);
        }
      });
      const stopped = new Promise((resolve) => {
        recorder.addEventListener("stop", resolve, {once: true});
      });

      recorder.start();
      const startedAt = performance.now();
      const outputDuration = duration / speed;
      await new Promise((resolve) => {
        const draw = (timestamp) => {
          if (!videoExporting) {
            resolve();
            return;
          }
          const elapsed = Math.max((timestamp - startedAt) / 1000, 0);
          const seconds = clamp(elapsed * speed, 0, duration);
          drawExportFrame(context, baseImage, canvas, viewBox, trackSegment, seconds, exportRouteStats());
          setExportStatus(`Запись ${Math.round(seconds / duration * 100)}%`);
          if (elapsed >= outputDuration) {
            resolve();
            return;
          }
          requestAnimationFrame(draw);
        };
        draw(startedAt);
        requestAnimationFrame(draw);
      });
      if (recorder.state !== "inactive") {
        recorder.stop();
      }
      await stopped;
      stream.getTracks().forEach((track) => track.stop());
      if (!chunks.length) {
        throw new Error("Браузер не вернул видеоданные");
      }
      saveVideoBlob(new Blob(chunks, {type: recorder.mimeType || "video/webm"}));
      setExportStatus("Готово");
    } catch (error) {
      setExportStatus(`Ошибка: ${error.message}`);
    } finally {
      videoExporting = false;
      exportVideoButton.disabled = false;
    }
  }

  async function splitMapBaseImage(width, height) {
    const clonedSvg = svg.cloneNode(true);
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clonedSvg.setAttribute("width", String(width));
    clonedSvg.setAttribute("height", String(height));
    clonedSvg.querySelector(".split-athlete-marker")?.remove();
    const mapImage = clonedSvg.querySelector("image");
    if (mapImage) {
      mapImage.setAttribute("href", await imageElementDataUrl(active.image));
    }
    const source = new XMLSerializer().serializeToString(clonedSvg);
    const svgUrl = URL.createObjectURL(new Blob([source], {type: "image/svg+xml;charset=utf-8"}));
    try {
      return await loadImage(svgUrl);
    } finally {
      URL.revokeObjectURL(svgUrl);
    }
  }

  function drawExportFrame(context, baseImage, canvas, viewBox, trackSegment, seconds, statsRows) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#eef3f5";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(baseImage, 0, 0, canvas.width, canvas.height);
    drawExportRouteStats(context, statsRows, canvas.width, canvas.height);
    const pixel = interpolateTrackSegmentPixel(trackSegment, seconds);
    const visiblePoint = currentProjection ? projectPoint(pixel, currentProjection) : pixel;
    const canvasPoint = viewBoxPointToCanvas(visiblePoint, viewBox, canvas.width, canvas.height);
    const radius = Math.max(5, Math.min(12, 8 * canvasPoint.scale));
    context.save();
    context.shadowColor = "rgba(0, 0, 0, 0.35)";
    context.shadowBlur = 5;
    context.shadowOffsetY = 2;
    context.fillStyle = "#18a0fb";
    context.strokeStyle = "#ffffff";
    context.lineWidth = Math.max(2, 4 * canvasPoint.scale);
    context.beginPath();
    context.arc(canvasPoint.x, canvasPoint.y, radius, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    context.restore();
  }

  function exportRouteStats() {
    if (!active) {
      return [];
    }
    const courseMeters = Number.isFinite(active.row.distanceMeters) && active.row.distanceMeters > 0
      ? active.row.distanceMeters
      : courseLengthMeters();
    const trackMeters = trackLengthMeters();
    const altMeters = altRouteLengthMeters();
    const rows = [];
    if (Number.isFinite(courseMeters) && courseMeters > 0) {
      rows.push({color: "#FF1744", label: "прямая", meters: courseMeters});
    }
    if (Number.isFinite(trackMeters) && trackMeters > 0) {
      rows.push({color: "#1565c0", label: "трек", meters: trackMeters});
    }
    if (Number.isFinite(altMeters) && altMeters > 0) {
      rows.push({color: "#b026ff", label: "альт.", meters: altMeters});
    }
    return rows;
  }

  function drawExportRouteStats(context, rows, canvasWidth, canvasHeight) {
    if (!rows.length) {
      return;
    }
    context.save();
    context.font = "18px Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
    const paddingX = 16;
    const paddingY = 12;
    const rowHeight = 24;
    const markerWidth = 28;
    const gap = 10;
    const width = Math.ceil(Math.max(
      ...rows.map((row) => markerWidth + gap + context.measureText(`${row.label}: ${formatMeters(row.meters)}`).width),
    ) + paddingX * 2);
    const height = paddingY * 2 + rows.length * rowHeight;
    const x = 24;
    const y = canvasHeight - height - 24;
    roundRectPath(context, x, y, width, height, 8);
    context.fillStyle = "rgba(255, 255, 255, 0.92)";
    context.fill();
    context.strokeStyle = "#d7e1e6";
    context.lineWidth = 1;
    context.stroke();
    rows.forEach((row, index) => {
      const rowY = y + paddingY + index * rowHeight + rowHeight / 2;
      context.strokeStyle = row.color;
      context.lineWidth = 5;
      context.lineCap = "round";
      context.beginPath();
      context.moveTo(x + paddingX, rowY);
      context.lineTo(x + paddingX + markerWidth, rowY);
      context.stroke();
      context.fillStyle = "#334147";
      context.fillText(`${row.label}: ${formatMeters(row.meters)}`, x + paddingX + markerWidth + gap, rowY + 6);
    });
    context.restore();
  }

  function roundRectPath(context, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    context.beginPath();
    context.moveTo(x + r, y);
    context.lineTo(x + width - r, y);
    context.quadraticCurveTo(x + width, y, x + width, y + r);
    context.lineTo(x + width, y + height - r);
    context.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    context.lineTo(x + r, y + height);
    context.quadraticCurveTo(x, y + height, x, y + height - r);
    context.lineTo(x, y + r);
    context.quadraticCurveTo(x, y, x + r, y);
    context.closePath();
  }

  function parseViewBox(value, fallbackWidth, fallbackHeight) {
    const parts = String(value || "").trim().split(/\s+/).map(Number);
    if (parts.length === 4 && parts.every(Number.isFinite) && parts[2] > 0 && parts[3] > 0) {
      return {x: parts[0], y: parts[1], width: parts[2], height: parts[3]};
    }
    return {x: 0, y: 0, width: fallbackWidth, height: fallbackHeight};
  }

  function viewBoxPointToCanvas(point, viewBox, canvasWidth, canvasHeight) {
    const scale = Math.min(canvasWidth / viewBox.width, canvasHeight / viewBox.height);
    const offsetX = (canvasWidth - viewBox.width * scale) / 2;
    const offsetY = (canvasHeight - viewBox.height * scale) / 2;
    return {
      x: offsetX + (point.pixel_x - viewBox.x) * scale,
      y: offsetY + (point.pixel_y - viewBox.y) * scale,
      scale,
    };
  }

  function supportedVideoMimeType() {
    return [
      "video/webm;codecs=vp9",
      "video/webm;codecs=vp8",
      "video/webm",
    ].find((type) => MediaRecorder.isTypeSupported(type)) || "";
  }

  function saveVideoBlob(blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `split-${String(active?.row?.label || "analysis").replace(/[^\w.-]+/g, "_")}.webm`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  function setExportStatus(message) {
    if (exportStatus) {
      exportStatus.textContent = message;
    }
  }

  async function openDebugSnapshot() {
    if (!active || !debugSnapshotButton) {
      return;
    }
    const originalText = debugSnapshotButton.textContent;
    debugSnapshotButton.disabled = true;
    debugSnapshotButton.textContent = "Готовлю...";
    try {
      const dataUrl = await snapshotDataUrl();
      if (!dataUrl) {
        throw new Error("Снимок сплита пустой");
      }
      const snapshotWindow = window.open();
      if (!snapshotWindow) {
        throw new Error("Браузер заблокировал открытие окна");
      }
      snapshotWindow.document.write(`<!doctype html>
        <html lang="ru">
          <head>
            <meta charset="utf-8">
            <title>PNG для AI · Сплит ${active.row.label}</title>
            <style>
              body { margin: 0; background: #162024; display: grid; min-height: 100vh; place-items: center; }
              img { max-width: 100vw; max-height: 100vh; object-fit: contain; background: #eef3f5; }
            </style>
          </head>
          <body>
            <img src="${dataUrl}" alt="PNG для AI">
          </body>
        </html>`);
      snapshotWindow.document.close();
    } catch (error) {
      appendChatMessage("assistant", `Не удалось подготовить PNG для AI: ${error.message}`);
    } finally {
      debugSnapshotButton.disabled = false;
      debugSnapshotButton.textContent = originalText;
    }
  }

  function splitPayload(row) {
    const trackSegment = splitTrackSegment(row);
    const payload = {
      label: row.label,
      from: row.fromControl.label,
      via: row.viaControls.map((control) => control.label),
      to: row.toControl.label,
      absolute_seconds: Math.round(row.absoluteSeconds),
      split_seconds: row.splitSeconds === null ? null : Math.round(row.splitSeconds),
      course_distance_meters: row.distanceMeters === null ? null : Math.round(row.distanceMeters),
      pace_seconds_per_meter: row.paceSecondsPerMeter,
      track_points_count: trackSegment.length,
      track_start_index: row.fromTrackIndex,
      track_end_index: row.toTrackIndex,
    };
    const altMeters = altRouteLengthMeters();
    if (altMeters !== null) {
      payload.alt_route_length_meters = Math.round(altMeters);
    }
    return payload;
  }

  function appendArrowMarker() {
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
    marker.setAttribute("id", "split-arrow-head");
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", "9");
    marker.setAttribute("refY", "5");
    marker.setAttribute("markerWidth", "5");
    marker.setAttribute("markerHeight", "5");
    marker.setAttribute("orient", "auto-start-reverse");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
    path.setAttribute("fill", "#FF1744");
    path.setAttribute("stroke", "#000000");
    path.setAttribute("stroke-width", "1.5");
    path.setAttribute("stroke-linejoin", "round");
    marker.appendChild(path);
    defs.appendChild(marker);
    svg.appendChild(defs);
  }

  function addPolyline(points, className) {
    if (className === "split-course-line") {
      addPolylineOutline(points, className);
    }
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("class", className);
    polyline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke-linecap", "round");
    polyline.setAttribute("stroke-linejoin", "round");
    if (className === "split-course-line") {
      polyline.setAttribute("stroke", "#FF1744");
      polyline.setAttribute("stroke-width", "5");
      polyline.setAttribute("marker-end", "url(#split-arrow-head)");
    } else {
      polyline.setAttribute("stroke", "#1565c0");
      polyline.setAttribute("stroke-width", "6");
    }
    (mapLayer || svg).appendChild(polyline);
  }

  function addPolylineOutline(points, className) {
    const outline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    outline.setAttribute("class", `${className} ${className}-outline`);
    outline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    outline.setAttribute("fill", "none");
    outline.setAttribute("stroke", "#000000");
    outline.setAttribute("stroke-width", "9");
    outline.setAttribute("stroke-linecap", "round");
    outline.setAttribute("stroke-linejoin", "round");
    (mapLayer || svg).appendChild(outline);
  }

  function addControlMarker(control, role) {
    const point = controlPixel(control);
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", `split-control-marker split-control-${role}`);
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", String(point.pixel_x));
    circle.setAttribute("cy", String(point.pixel_y));
    circle.setAttribute("r", role === "via" ? "8" : "10");
    circle.setAttribute("fill", role === "via" ? "#0f6b4f" : "#b21f5b");
    circle.setAttribute("stroke", "#ffffff");
    circle.setAttribute("stroke-width", "3");
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(point.pixel_x));
    label.setAttribute("y", String(point.pixel_y + 4));
    label.setAttribute("fill", "#ffffff");
    label.setAttribute("font-family", "Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif");
    label.setAttribute("font-size", "12");
    label.setAttribute("font-weight", "700");
    label.setAttribute("text-anchor", "middle");
    label.textContent = control.label;
    group.append(circle, label);
    (mapLayer || svg).appendChild(group);
  }

  function seekToChartPointer(event) {
    if (!chartInstance || !active || !root.Chart) {
      return;
    }
    const xScale = chartInstance.scales.x;
    if (!xScale) {
      return;
    }
    const position = root.Chart.helpers?.getRelativePosition
      ? root.Chart.helpers.getRelativePosition(event, chartInstance)
      : {x: event.clientX - paceChart.getBoundingClientRect().left};
    seek(clamp(xScale.getValueForPixel(position.x), 0, Math.max(active.row.splitSeconds || 0, 0)));
  }

  function finishScrub(event) {
    if (scrubPointerId !== event.pointerId) {
      return;
    }
    paceChart?.releasePointerCapture(event.pointerId);
    paceChart?.classList.remove("scrubbing");
    scrubPointerId = null;
  }

  function seek(seconds) {
    if (!active) {
      return;
    }
    analysisSeconds = clamp(seconds, 0, Math.max(active.row.splitSeconds || 0, 0));
    updateAthlete(analysisSeconds);
    updatePaceStatus();
    chartInstance?.update("none");
  }

  function updateAthlete(seconds) {
    if (!active || !athleteMarker) {
      return;
    }
    const segment = splitTrackSegment(active.row);
    if (!segment.length) {
      return;
    }
    const pixel = interpolateTrackSegmentPixel(segment, seconds);
    athleteMarker.setAttribute("cx", String(pixel.pixel_x));
    athleteMarker.setAttribute("cy", String(pixel.pixel_y));
  }

  function splitTrackSegment(row) {
    return active.trackPoints.slice(row.fromTrackIndex, row.toTrackIndex + 1);
  }

  function interpolateTrackSegmentPixel(segment, seconds) {
    if (segment.length === 1 || seconds <= 0) {
      return segment[0].pixel;
    }
    const absoluteSeconds = segment[0].seconds + seconds;
    for (let index = 1; index < segment.length; index += 1) {
      const previous = segment[index - 1];
      const current = segment[index];
      if (current.seconds >= absoluteSeconds) {
        const ratio = clamp((absoluteSeconds - previous.seconds) / Math.max(current.seconds - previous.seconds, 0.001), 0, 1);
        return {
          pixel_x: previous.pixel.pixel_x + (current.pixel.pixel_x - previous.pixel.pixel_x) * ratio,
          pixel_y: previous.pixel.pixel_y + (current.pixel.pixel_y - previous.pixel.pixel_y) * ratio,
        };
      }
    }
    return segment[segment.length - 1].pixel;
  }

  function calculateTrackPaceSeries(points, baseSeconds) {
    const raw = [];
    for (let index = 1; index < points.length; index += 1) {
      const previous = points[index - 1];
      const current = points[index];
      const seconds = current.seconds - previous.seconds;
      const meters = haversineMeters(previous, current);
      if (seconds <= 0 || meters < 0.5) {
        continue;
      }
      raw.push({seconds: current.seconds - baseSeconds, pace: seconds / 60 / (meters / 1000)});
    }
    return raw.map((point, index) => {
      const window = raw.slice(Math.max(index - 2, 0), Math.min(index + 3, raw.length));
      return {...point, pace: window.reduce((sum, item) => sum + item.pace, 0) / window.length};
    }).filter((point) => point.pace >= 2 && point.pace <= 30);
  }

  function calculatePaceBounds(series) {
    const values = series.map((point) => point.pace);
    const min = Math.min(...values);
    const max = Math.max(...values);
    if (min === max) {
      return {min: min - 0.5, max: max + 0.5};
    }
    const padding = Math.max((max - min) * 0.12, 0.3);
    return {min: Math.max(0, min - padding), max: max + padding};
  }

  function updatePaceStatus() {
    if (!paceStatus || !active) {
      return;
    }
    if (paceSeries.length < 2) {
      paceStatus.textContent = "нет данных";
      return;
    }
    const pace = paceAt(analysisSeconds);
    paceStatus.textContent = pace ? `${formatPace(pace)} мин/км` : "--:-- мин/км";
  }

  function paceAt(seconds) {
    if (!paceSeries.length) {
      return null;
    }
    let closest = paceSeries[0];
    for (const point of paceSeries) {
      if (Math.abs(point.seconds - seconds) < Math.abs(closest.seconds - seconds)) {
        closest = point;
      }
    }
    return closest.pace;
  }

  function destroyPaceChart() {
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
  }

  function setChatPending(isPending) {
    if (chatInput) {
      chatInput.disabled = isPending;
    }
    if (chatSubmit) {
      chatSubmit.disabled = isPending;
    }
    if (chatStartButton) {
      chatStartButton.disabled = isPending;
    }
  }

  function setChatStarted(isStarted) {
    if (chatStart) {
      chatStart.hidden = isStarted;
    }
    if (chatForm) {
      chatForm.hidden = !isStarted;
    }
  }

  function appendChatMessage(role, text) {
    const message = document.createElement("div");
    message.className = `split-chat-message split-chat-message-${role}`;
    if (role === "assistant") {
      renderAssistantMessage(message, text);
    } else {
      message.textContent = text;
    }
    chatMessages.appendChild(message);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return message;
  }

  function renderAssistantMessage(element, text) {
    element.textContent = "";
    for (const part of String(text).split(/(\*\*[^*]+\*\*)/g)) {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        const strong = document.createElement("strong");
        strong.textContent = part.slice(2, -2);
        element.appendChild(strong);
      } else {
        element.appendChild(document.createTextNode(part));
      }
    }
  }

  function isTextEntryTarget(target) {
    if (!(target instanceof Element)) {
      return false;
    }
    if (target.closest("textarea, select, [contenteditable='true']")) {
      return true;
    }
    const input = target.closest("input");
    if (!(input instanceof HTMLInputElement)) {
      return false;
    }
    return !["checkbox", "radio", "button", "submit", "reset"].includes(input.type);
  }

  async function imageElementDataUrl(sourceImage) {
    const response = await fetch(sourceImage.currentSrc || sourceImage.src);
    return await blobToDataUrl(await response.blob());
  }

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const nextImage = new Image();
      nextImage.onload = () => resolve(nextImage);
      nextImage.onerror = () => reject(new Error("Не удалось подготовить картинку сплита"));
      nextImage.src = src;
    });
  }

  function splitViewBox(points, imageWidth, imageHeight) {
    if (!points.length) {
      return [0, 0, imageWidth, imageHeight];
    }
    let minX = Math.min(...points.map((point) => point.pixel_x));
    let maxX = Math.max(...points.map((point) => point.pixel_x));
    let minY = Math.min(...points.map((point) => point.pixel_y));
    let maxY = Math.max(...points.map((point) => point.pixel_y));
    const minSize = 180;
    if (maxX - minX < minSize) {
      const center = (minX + maxX) / 2;
      minX = center - minSize / 2;
      maxX = center + minSize / 2;
    }
    if (maxY - minY < minSize) {
      const center = (minY + maxY) / 2;
      minY = center - minSize / 2;
      maxY = center + minSize / 2;
    }
    const padding = Math.max(maxX - minX, maxY - minY) * 0.18;
    minX = clamp(minX - padding, 0, imageWidth);
    minY = clamp(minY - padding, 0, imageHeight);
    maxX = clamp(maxX + padding, 0, imageWidth);
    maxY = clamp(maxY + padding, 0, imageHeight);
    return [minX, minY, Math.max(maxX - minX, minSize), Math.max(maxY - minY, minSize)];
  }

  function splitProjection(row) {
    const coursePoints = splitCoursePoints(row);
    if (coursePoints.length < 2) {
      return null;
    }
    const from = controlPixel(coursePoints[0]);
    const to = controlPixel(coursePoints[coursePoints.length - 1]);
    const dx = to.pixel_x - from.pixel_x;
    const dy = to.pixel_y - from.pixel_y;
    const length = Math.hypot(dx, dy);
    if (length < 1) {
      return null;
    }
    const unit = {x: dx / length, y: dy / length};
    return {
      from,
      unit,
      perpendicular: {x: -unit.y, y: unit.x},
      length,
    };
  }

  function projectionMatrix(projection) {
    const p = projection.perpendicular;
    const v = projection.unit;
    const from = projection.from;
    const a = p.x;
    const b = -v.x;
    const c = p.y;
    const d = -v.y;
    const e = -(a * from.pixel_x + c * from.pixel_y);
    const f = v.x * from.pixel_x + v.y * from.pixel_y;
    return `matrix(${a}, ${b}, ${c}, ${d}, ${e}, ${f})`;
  }

  function projectPoint(point, projection) {
    const dx = point.pixel_x - projection.from.pixel_x;
    const dy = point.pixel_y - projection.from.pixel_y;
    return {
      pixel_x: dx * projection.perpendicular.x + dy * projection.perpendicular.y,
      pixel_y: -(dx * projection.unit.x + dy * projection.unit.y),
    };
  }

  function unprojectPoint(point, projection) {
    return {
      pixel_x:
        projection.from.pixel_x +
        point.pixel_x * projection.perpendicular.x -
        point.pixel_y * projection.unit.x,
      pixel_y:
        projection.from.pixel_y +
        point.pixel_x * projection.perpendicular.y -
        point.pixel_y * projection.unit.y,
    };
  }

  function orientedViewBox(points, projection) {
    const projected = (points.length ? points : [projection.from]).map((point) => projectPoint(point, projection));
    const maxAbsX = Math.max(90, ...projected.map((point) => Math.abs(point.pixel_x)));
    const minY = Math.min(-projection.length, ...projected.map((point) => point.pixel_y));
    const maxY = Math.max(0, ...projected.map((point) => point.pixel_y));
    const padding = Math.max(projection.length * 0.18, 60);
    const width = Math.max(240, maxAbsX * 2 + padding * 2);
    const height = Math.max(
      260,
      projection.length * 1.65,
      (padding - minY) / 0.72,
      (maxY + padding) / 0.28
    );
    return [-width / 2, -height * 0.72, width, height];
  }

  function controlPixel(control) {
    return {pixel_x: control.pixel_x, pixel_y: control.pixel_y};
  }

  function splitCoursePoints(row) {
    const points = [row.fromControl, ...(Array.isArray(row.viaControls) ? row.viaControls : []), row.toControl]
      .filter(Boolean);
    if (!active?.mapLayerId) {
      return points;
    }
    const layerPoints = points.filter((control) => (control.map_layer_id || active.mapLayerId) === active.mapLayerId);
    return layerPoints.length ? layerPoints : points;
  }

  function createPaceGradient(chart, alpha) {
    const area = chart.chartArea;
    if (!area) {
      return `rgba(21, 101, 192, ${alpha})`;
    }
    const gradient = chart.ctx.createLinearGradient(0, area.bottom, 0, area.top);
    gradient.addColorStop(0, `rgba(20, 140, 85, ${alpha})`);
    gradient.addColorStop(0.5, `rgba(238, 185, 73, ${alpha})`);
    gradient.addColorStop(1, `rgba(190, 45, 65, ${alpha})`);
    return gradient;
  }

  function haversineMeters(a, b) {
    const radius = 6371000;
    const lat1 = toRadians(a.lat);
    const lat2 = toRadians(b.lat);
    const deltaLat = toRadians(b.lat - a.lat);
    const deltaLon = toRadians(b.lon - a.lon);
    const value = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
    return radius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
  }

  function formatTime(seconds) {
    const total = Math.max(Math.floor(seconds), 0);
    return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  }

  function formatPace(pace) {
    const minutes = Math.floor(pace);
    const seconds = Math.round((pace - minutes) * 60);
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function toRadians(value) {
    return value * Math.PI / 180;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function toggleDrawMode() {
    if (!active) {
      return;
    }
    drawMode = !drawMode;
    svg?.classList.toggle("is-drawing", drawMode);
    updateDrawButtons();
  }

  function clearAltRoute() {
    altRoutePoints = [];
    renderAltRoute();
    updateDrawButtons();
    updateRouteStats();
  }

  function updateDrawButtons() {
    if (drawToggleButton) {
      drawToggleButton.setAttribute("aria-pressed", drawMode ? "true" : "false");
    }
    if (drawClearButton) {
      drawClearButton.hidden = altRoutePoints.length < 2;
    }
  }

  function onSvgPointerDown(event) {
    if (!drawMode || !active || !svg) {
      return;
    }
    event.preventDefault();
    drawPointerId = event.pointerId;
    try {
      svg.setPointerCapture(event.pointerId);
    } catch (_) {}
    altRoutePoints = [];
    const point = pointerToSvgCoords(event);
    if (point) {
      altRoutePoints.push(point);
    }
    renderAltRoute();
  }

  function onSvgPointerMove(event) {
    if (drawPointerId === null || drawPointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    const point = pointerToSvgCoords(event);
    if (!point) {
      return;
    }
    const previous = altRoutePoints[altRoutePoints.length - 1];
    if (previous) {
      const dx = point.pixel_x - previous.pixel_x;
      const dy = point.pixel_y - previous.pixel_y;
      if (dx * dx + dy * dy < 4) {
        return;
      }
    }
    altRoutePoints.push(point);
    renderAltRoute();
  }

  function onSvgPointerUp(event) {
    if (drawPointerId === null || drawPointerId !== event.pointerId) {
      return;
    }
    try {
      svg.releasePointerCapture(event.pointerId);
    } catch (_) {}
    drawPointerId = null;
    if (altRoutePoints.length < 2) {
      altRoutePoints = [];
      renderAltRoute();
    }
    updateDrawButtons();
    updateRouteStats();
  }

  function pointerToSvgCoords(event) {
    if (!svg || typeof svg.createSVGPoint !== "function") {
      return null;
    }
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) {
      return null;
    }
    const local = point.matrixTransform(ctm.inverse());
    if (currentProjection) {
      return unprojectPoint({pixel_x: local.x, pixel_y: local.y}, currentProjection);
    }
    return {pixel_x: local.x, pixel_y: local.y};
  }

  function renderAltRoute() {
    if (!altRouteLine) {
      return;
    }
    if (altRoutePoints.length < 2) {
      altRouteLine.setAttribute("points", "");
      return;
    }
    altRouteLine.setAttribute(
      "points",
      altRoutePoints.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "),
    );
  }

  function pixelToGeo(point) {
    const transform = active?.transform;
    if (!transform) {
      return null;
    }
    const deltaLon = transform.lon_a * point.pixel_x + transform.lon_b * point.pixel_y;
    const deltaLat = transform.lat_a * point.pixel_x + transform.lat_b * point.pixel_y;
    return {lon: deltaLon + transform.lon_c, lat: deltaLat + transform.lat_c};
  }

  function trackLengthMeters() {
    if (!active) {
      return null;
    }
    const segment = splitTrackSegment(active.row);
    if (segment.length < 2) {
      return null;
    }
    let meters = 0;
    for (let index = 1; index < segment.length; index += 1) {
      meters += haversineMeters(segment[index - 1], segment[index]);
    }
    return meters;
  }

  function courseLengthMeters() {
    if (!active || !active.transform) {
      return null;
    }
    const points = splitCoursePoints(active.row);
    if (points.length < 2) {
      return null;
    }
    let meters = 0;
    for (let index = 1; index < points.length; index += 1) {
      const a = pixelToGeo(points[index - 1]);
      const b = pixelToGeo(points[index]);
      if (!a || !b) {
        return null;
      }
      meters += haversineMeters(a, b);
    }
    return meters;
  }

  function altRouteLengthMeters() {
    if (altRoutePoints.length < 2 || !active?.transform) {
      return null;
    }
    let meters = 0;
    for (let index = 1; index < altRoutePoints.length; index += 1) {
      const a = pixelToGeo(altRoutePoints[index - 1]);
      const b = pixelToGeo(altRoutePoints[index]);
      if (!a || !b) {
        return null;
      }
      meters += haversineMeters(a, b);
    }
    return meters;
  }

  function updateRouteStats() {
    if (!routeStats) {
      return;
    }
    if (!active) {
      routeStats.hidden = true;
      routeStats.replaceChildren();
      return;
    }
    const courseMeters = Number.isFinite(active.row.distanceMeters) && active.row.distanceMeters > 0
      ? active.row.distanceMeters
      : courseLengthMeters();
    const trackMeters = trackLengthMeters();
    const altMeters = altRouteLengthMeters();
    const rows = [];
    if (Number.isFinite(courseMeters) && courseMeters > 0) {
      rows.push({color: "#FF1744", label: "прямая", meters: courseMeters});
    }
    if (Number.isFinite(trackMeters) && trackMeters > 0) {
      rows.push({color: "#1565c0", label: "трек", meters: trackMeters});
    }
    if (Number.isFinite(altMeters) && altMeters > 0) {
      rows.push({color: "#b026ff", label: "альт.", meters: altMeters});
    }
    if (!rows.length) {
      routeStats.hidden = true;
      routeStats.replaceChildren();
      return;
    }
    routeStats.hidden = false;
    routeStats.replaceChildren(...rows.map(buildRouteStatsRow));
  }

  function buildRouteStatsRow(item) {
    const row = document.createElement("div");
    row.className = "split-route-stats-row";
    const marker = document.createElement("span");
    marker.className = "split-route-stats-marker";
    marker.style.background = item.color;
    const text = document.createElement("span");
    text.textContent = `${item.label}: ${formatMeters(item.meters)}`;
    row.append(marker, text);
    return row;
  }

  function formatMeters(meters) {
    if (meters >= 1000) {
      return `${(meters / 1000).toFixed(2)} км`;
    }
    return `${Math.round(meters)} м`;
  }

  root.SplitAnalysisDialog = {open, close};
})(typeof globalThis !== "undefined" ? globalThis : window);
