(function () {
  const workspace = document.querySelector("#player-workspace");
  if (!workspace) {
    return;
  }

  const image = document.querySelector("#player-map-image");
  const svg = document.querySelector("#player-svg");
  const viewport = document.querySelector("#player-image-viewport");
  const content = document.querySelector("#player-image-content");
  const toggleButton = document.querySelector("#player-toggle");
  const speedSelect = document.querySelector("#player-speed");
  const positionInput = document.querySelector("#player-position");
  const timeLabel = document.querySelector("#player-time");
  const paceValue = document.querySelector("#pace-value");
  const paceChart = document.querySelector("#pace-chart");
  const trimLeftButton = document.querySelector("#trim-left");
  const trimRightButton = document.querySelector("#trim-right");
  const trimUndoButton = document.querySelector("#trim-undo");
  const saveTrackButton = document.querySelector("#save-track");
  const trackSaveStatus = document.querySelector("#track-save-status");
  const splitsStatus = document.querySelector("#splits-status");
  const splitsTableBody = document.querySelector("#splits-table-body");
  const splitAnalysisModal = document.querySelector("#split-analysis-modal");
  const splitAnalysisTitle = document.querySelector("#split-analysis-title");
  const splitAnalysisSvg = document.querySelector("#split-analysis-svg");
  const splitAnalysisClose = document.querySelector("#split-analysis-close");
  const splitDebugSnapshotButton = document.querySelector("#split-debug-snapshot");
  const splitChatMessages = document.querySelector("#split-chat-messages");
  const splitChatStart = document.querySelector("#split-chat-start");
  const splitChatStartButton = document.querySelector("#split-chat-start-button");
  const splitChatForm = document.querySelector("#split-chat-form");
  const splitChatInput = document.querySelector("#split-chat-input");
  const splitChatSubmit = document.querySelector("#split-chat-submit");

  const trainingId = workspace.dataset.trainingId;
  const transform = parseJson(workspace.dataset.transform, null);
  const splitsEngine = window.OrienteeringSplits;
  const courseControls = splitsEngine.normalizeCourseControls(parseJson(workspace.dataset.courseControls, []));
  let trackPoints = parseJson(workspace.dataset.trackPoints, []).map((point, index) => ({
    ...point,
    pixel: transform ? geoToPixel(point) : {pixel_x: 0, pixel_y: 0},
    seconds: splitsEngine.parsePointSeconds(point, index),
  }));

  let view = {scale: 1, translateX: 0, translateY: 0};
  let drag = null;
  let playing = false;
  let playheadSeconds = 0;
  let lastFrameTime = null;
  let athleteMarker = null;
  let paceChartInstance = null;
  let paceScrubPointerId = null;
  let trimHistory = [];
  let trackDirty = false;
  let activeSplitAnalysisRow = null;
  let splitChatHistory = [];

  let durationSeconds = calculateDurationSeconds();
  let paceSeries = calculatePaceSeries();

  toggleButton?.addEventListener("click", () => {
    playing = !playing;
    toggleButton.textContent = playing ? "⏸" : "▶";
    lastFrameTime = null;
    if (playing) {
      requestAnimationFrame(tick);
    }
  });

  speedSelect?.addEventListener("change", () => {
    lastFrameTime = null;
  });

  positionInput?.addEventListener("input", () => {
    seekToSeconds(sliderToSeconds());
  });

  if (image) {
    image.addEventListener("load", () => {
      fitImageToViewport();
      drawStaticLayers();
      updateAthlete();
    });
    if (image.complete) {
      fitImageToViewport();
    }
  }

  viewport?.addEventListener("wheel", (event) => {
    if (!image) {
      return;
    }
    event.preventDefault();
    const pointer = clientPointToViewportPoint(event.clientX, event.clientY);
    const before = viewportPointToImagePixel(pointer.x, pointer.y);
    const zoomFactor = event.deltaY < 0 ? 1.18 : 1 / 1.18;
    view.scale = clamp(view.scale * zoomFactor, 0.15, 10);
    view.translateX = pointer.x - before.pixel_x * view.scale;
    view.translateY = pointer.y - before.pixel_y * view.scale;
    applyView();
  }, {passive: false});

  viewport?.addEventListener("pointerdown", (event) => {
    if (!image) {
      return;
    }
    viewport.setPointerCapture(event.pointerId);
    drag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      translateX: view.translateX,
      translateY: view.translateY,
    };
    viewport.classList.add("dragging");
  });

  viewport?.addEventListener("pointermove", (event) => {
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    view.translateX = drag.translateX + event.clientX - drag.startX;
    view.translateY = drag.translateY + event.clientY - drag.startY;
    applyView();
  });

  viewport?.addEventListener("pointerup", finishDrag);
  viewport?.addEventListener("pointercancel", finishDrag);

  paceChart?.addEventListener("pointerdown", (event) => {
    if (!paceChartInstance) {
      return;
    }
    event.preventDefault();
    paceScrubPointerId = event.pointerId;
    paceChart.setPointerCapture(event.pointerId);
    paceChart.classList.add("scrubbing");
    seekToPaceChartPointer(event);
  });

  paceChart?.addEventListener("pointermove", (event) => {
    if (paceScrubPointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    seekToPaceChartPointer(event);
  });

  paceChart?.addEventListener("pointerup", finishPaceScrub);
  paceChart?.addEventListener("pointercancel", finishPaceScrub);

  trimLeftButton?.addEventListener("click", () => {
    trimTrack("left");
  });

  trimRightButton?.addEventListener("click", () => {
    trimTrack("right");
  });

  trimUndoButton?.addEventListener("click", () => {
    undoTrim();
  });

  saveTrackButton?.addEventListener("click", () => {
    saveTrack();
  });

  splitAnalysisClose?.addEventListener("click", closeSplitAnalysis);
  splitDebugSnapshotButton?.addEventListener("click", () => {
    openSplitDebugSnapshot();
  });
  splitAnalysisModal?.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.matches("[data-close-split-analysis]")) {
      closeSplitAnalysis();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && splitAnalysisModal && !splitAnalysisModal.hidden) {
      closeSplitAnalysis();
    }
  });
  splitChatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    sendSplitChatMessage();
  });
  splitChatStartButton?.addEventListener("click", () => {
    startSplitChat();
  });

  drawStaticLayers();
  drawPaceChart();
  renderSplitsTable();
  updateAthlete();
  updateTrimButtons();

  function tick(timestamp) {
    if (!playing) {
      return;
    }
    if (lastFrameTime === null) {
      lastFrameTime = timestamp;
    }

    const deltaSeconds = (timestamp - lastFrameTime) / 1000;
    lastFrameTime = timestamp;
    playheadSeconds += deltaSeconds * Number(speedSelect.value || 1);

    if (playheadSeconds >= durationSeconds) {
      playheadSeconds = durationSeconds;
      playing = false;
      toggleButton.textContent = "▶";
    }

    updateAthlete();
    if (playing) {
      requestAnimationFrame(tick);
    }
  }

  function drawStaticLayers() {
    if (!image || !svg || !transform || !image.complete || image.naturalWidth === 0) {
      return;
    }
    svg.setAttribute("viewBox", `0 0 ${image.naturalWidth} ${image.naturalHeight}`);
    svg.innerHTML = "";

    if (courseControls.length >= 2) {
      addPolyline(
        courseControls.map((control) => ({pixel_x: control.pixel_x, pixel_y: control.pixel_y})),
        "course-line"
      );
    }
    courseControls.forEach(addControlMarker);

    if (trackPoints.length >= 2) {
      addPolyline(trackPoints.map((point) => point.pixel), "track-line");
    }

    athleteMarker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    athleteMarker.setAttribute("class", "athlete-marker");
    athleteMarker.setAttribute("r", "9");
    svg.appendChild(athleteMarker);
  }

  function updateAthlete() {
    if (!athleteMarker || !trackPoints.length) {
      return;
    }
    const pixel = interpolateTrackPixel(playheadSeconds);
    athleteMarker.setAttribute("cx", String(pixel.pixel_x));
    athleteMarker.setAttribute("cy", String(pixel.pixel_y));
    positionInput.value = String(secondsToSlider(playheadSeconds));
    timeLabel.textContent = `${formatTime(playheadSeconds)} / ${formatTime(durationSeconds)}`;
    updatePaceCursor();
    updateTrimButtons();
    renderSplitsTable();
  }

  function seekToSeconds(seconds) {
    playheadSeconds = clamp(seconds, 0, durationSeconds);
    playing = false;
    toggleButton.textContent = "▶";
    updateAthlete();
  }

  function rebuildPlayerState(nextPlayheadSeconds) {
    durationSeconds = calculateDurationSeconds();
    paceSeries = calculatePaceSeries();
    playheadSeconds = clamp(nextPlayheadSeconds, 0, durationSeconds);
    playing = false;
    toggleButton.textContent = "▶";
    drawStaticLayers();
    drawPaceChart();
    updateAthlete();
    updateTrimButtons();
    renderSplitsTable();
  }

  function interpolateTrackPixel(seconds) {
    if (trackPoints.length === 1 || seconds <= 0) {
      return trackPoints[0].pixel;
    }
    if (seconds >= durationSeconds) {
      return trackPoints[trackPoints.length - 1].pixel;
    }

    const absoluteSeconds = trackPoints[0].seconds + seconds;
    for (let index = 1; index < trackPoints.length; index += 1) {
      const previous = trackPoints[index - 1];
      const current = trackPoints[index];
      if (current.seconds >= absoluteSeconds) {
        const span = Math.max(current.seconds - previous.seconds, 0.001);
        const ratio = clamp((absoluteSeconds - previous.seconds) / span, 0, 1);
        return {
          pixel_x: previous.pixel.pixel_x + (current.pixel.pixel_x - previous.pixel.pixel_x) * ratio,
          pixel_y: previous.pixel.pixel_y + (current.pixel.pixel_y - previous.pixel.pixel_y) * ratio,
        };
      }
    }
    return trackPoints[trackPoints.length - 1].pixel;
  }

  function calculateDurationSeconds() {
    if (trackPoints.length < 2) {
      return 0;
    }
    const first = trackPoints[0].seconds;
    const last = trackPoints[trackPoints.length - 1].seconds;
    return Math.max(last - first, trackPoints.length - 1);
  }

  function parsePointSeconds(point, index) {
    if (point.time) {
      const timestamp = Date.parse(point.time);
      if (!Number.isNaN(timestamp)) {
        return timestamp / 1000;
      }
    }
    return index;
  }

  function sliderToSeconds() {
    return Number(positionInput.value) / 1000 * durationSeconds;
  }

  function secondsToSlider(seconds) {
    if (durationSeconds <= 0) {
      return 0;
    }
    return Math.round(seconds / durationSeconds * 1000);
  }

  function addPolyline(points, className) {
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("class", className);
    polyline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    svg.appendChild(polyline);
  }

  function addControlMarker(control) {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "course-control-marker");
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", String(control.pixel_x));
    circle.setAttribute("cy", String(control.pixel_y));
    circle.setAttribute("r", "10");
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(control.pixel_x));
    label.setAttribute("y", String(control.pixel_y + 4));
    label.textContent = control.label;
    group.append(circle, label);
    svg.appendChild(group);
  }

  function drawPaceChart() {
    if (!paceChart) {
      return;
    }
    if (paceChartInstance) {
      paceChartInstance.destroy();
      paceChartInstance = null;
    }

    if (paceSeries.length < 2) {
      paceValue.textContent = "нет данных";
      return;
    }

    if (!window.Chart) {
      paceValue.textContent = "график недоступен";
      return;
    }

    const paceBounds = calculatePaceBounds();

    const playheadPlugin = {
      id: "pacePlayhead",
      afterDatasetsDraw(chart) {
        const xScale = chart.scales.x;
        const area = chart.chartArea;
        if (!xScale || !area) {
          return;
        }
        const x = xScale.getPixelForValue(clamp(playheadSeconds, 0, durationSeconds));
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

    paceChartInstance = new window.Chart(paceChart, {
      type: "line",
      data: {
        datasets: [{
          label: "Темп",
          data: paceSeries.map((point) => ({x: point.seconds, y: point.pace})),
          borderColor(context) {
            return createPaceGradient(context.chart, 1);
          },
          backgroundColor(context) {
            return createPaceGradient(context.chart, 0.28);
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
        interaction: {
          mode: "nearest",
          intersect: false,
        },
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            enabled: false,
          },
        },
        scales: {
          x: {
            type: "linear",
            min: 0,
            max: Math.max(durationSeconds, 1),
            grid: {
              color: "rgba(102, 116, 124, 0.16)",
            },
            ticks: {
              maxTicksLimit: 8,
              callback(value) {
                return formatTime(Number(value));
              },
            },
          },
          y: {
            min: paceBounds.min,
            max: paceBounds.max,
            reverse: false,
            grid: {
              color: "rgba(102, 116, 124, 0.16)",
            },
            ticks: {
              callback(value) {
                return formatPace(Number(value));
              },
            },
          },
        },
      },
      plugins: [playheadPlugin],
    });

    updatePaceCursor();
  }

  function calculatePaceBounds() {
    const values = paceSeries.map((point) => point.pace);
    const min = Math.min(...values);
    const max = Math.max(...values);
    if (min === max) {
      return {min: min - 0.5, max: max + 0.5};
    }
    return {min, max};
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

  function updatePaceCursor() {
    const pace = paceAt(playheadSeconds);
    if (paceValue) {
      paceValue.textContent = pace ? `${formatPace(pace)} мин/км` : "--:-- мин/км";
    }
    if (paceChartInstance) {
      paceChartInstance.update("none");
    }
  }

  function calculatePaceSeries() {
    const raw = [];
    for (let index = 1; index < trackPoints.length; index += 1) {
      const previous = trackPoints[index - 1];
      const current = trackPoints[index];
      const seconds = current.seconds - previous.seconds;
      const meters = haversineMeters(previous, current);
      if (seconds <= 0 || meters < 0.5) {
        continue;
      }
      raw.push({
        seconds: current.seconds - trackPoints[0].seconds,
        pace: seconds / 60 / (meters / 1000),
      });
    }

    return raw.map((point, index) => {
      const from = Math.max(index - 2, 0);
      const to = Math.min(index + 3, raw.length);
      const window = raw.slice(from, to);
      const average = window.reduce((sum, item) => sum + item.pace, 0) / window.length;
      return {...point, pace: average};
    }).filter((point) => point.pace >= 2 && point.pace <= 30);
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

  function trimTrack(direction) {
    if (trackPoints.length < 2 || durationSeconds <= 0) {
      return;
    }
    const cutPoint = interpolateTrackPoint(playheadSeconds);
    if (!cutPoint) {
      return;
    }

    const startSeconds = trackPoints[0].seconds;
    const cutAbsoluteSeconds = startSeconds + playheadSeconds;
    const nextTrackPoints = direction === "left"
      ? [cutPoint, ...trackPoints.filter((point) => point.seconds > cutAbsoluteSeconds)]
      : [...trackPoints.filter((point) => point.seconds < cutAbsoluteSeconds), cutPoint];

    if (nextTrackPoints.length < 2) {
      return;
    }

    trimHistory.push(trackPoints.map(copyTrackPoint));
    trackPoints = nextTrackPoints;
    markTrackDirty();
    rebuildPlayerState(direction === "left" ? 0 : calculateDurationSeconds());
  }

  function undoTrim() {
    const previousTrackPoints = trimHistory.pop();
    if (!previousTrackPoints) {
      updateTrimButtons();
      return;
    }
    trackPoints = previousTrackPoints;
    markTrackDirty();
    rebuildPlayerState(0);
  }

  function interpolateTrackPoint(seconds) {
    if (!trackPoints.length) {
      return null;
    }
    if (seconds <= 0 || trackPoints.length === 1) {
      return copyTrackPoint(trackPoints[0]);
    }
    if (seconds >= durationSeconds) {
      return copyTrackPoint(trackPoints[trackPoints.length - 1]);
    }

    const absoluteSeconds = trackPoints[0].seconds + seconds;
    for (let index = 1; index < trackPoints.length; index += 1) {
      const previous = trackPoints[index - 1];
      const current = trackPoints[index];
      if (current.seconds >= absoluteSeconds) {
        const span = Math.max(current.seconds - previous.seconds, 0.001);
        const ratio = clamp((absoluteSeconds - previous.seconds) / span, 0, 1);
        const point = {
          ...current,
          lat: interpolateNumber(previous.lat, current.lat, ratio),
          lon: interpolateNumber(previous.lon, current.lon, ratio),
          seconds: absoluteSeconds,
          pixel: {
            pixel_x: interpolateNumber(previous.pixel.pixel_x, current.pixel.pixel_x, ratio),
            pixel_y: interpolateNumber(previous.pixel.pixel_y, current.pixel.pixel_y, ratio),
          },
        };
        if (typeof previous.ele === "number" && typeof current.ele === "number") {
          point.ele = interpolateNumber(previous.ele, current.ele, ratio);
        }
        point.time = secondsToIsoTime(absoluteSeconds, current.time || previous.time);
        return point;
      }
    }
    return copyTrackPoint(trackPoints[trackPoints.length - 1]);
  }

  function updateTrimButtons() {
    const canTrim = trackPoints.length >= 2 && durationSeconds > 2;
    if (trimLeftButton) {
      trimLeftButton.disabled = !canTrim || playheadSeconds <= 1;
    }
    if (trimRightButton) {
      trimRightButton.disabled = !canTrim || playheadSeconds >= durationSeconds - 1;
    }
    if (trimUndoButton) {
      trimUndoButton.disabled = trimHistory.length === 0;
    }
    if (saveTrackButton) {
      saveTrackButton.disabled = !trackDirty || trackPoints.length < 2;
    }
  }

  async function saveTrack() {
    if (!trainingId || trackPoints.length < 2 || !saveTrackButton) {
      return;
    }
    saveTrackButton.disabled = true;
    if (trackSaveStatus) {
      trackSaveStatus.textContent = "Сохраняю...";
    }

    const response = await fetch(`/api/trainings/${trainingId}/track-points`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({track_points: trackPoints.map(serializedTrackPoint)}),
    });

    if (!response.ok) {
      saveTrackButton.disabled = false;
      if (trackSaveStatus) {
        trackSaveStatus.textContent = "Не удалось сохранить";
      }
      return;
    }

    trimHistory = [];
    trackDirty = false;
    updateTrimButtons();
    renderSplitsTable();
    if (trackSaveStatus) {
      trackSaveStatus.textContent = "Сохранено";
    }
  }

  function markTrackDirty() {
    trackDirty = true;
    if (trackSaveStatus) {
      trackSaveStatus.textContent = "Есть несохраненные изменения";
    }
    updateTrimButtons();
  }

  function copyTrackPoint(point) {
    return {
      ...point,
      pixel: point.pixel ? {...point.pixel} : {pixel_x: 0, pixel_y: 0},
    };
  }

  function renderSplitsTable() {
    if (!splitsTableBody) {
      return;
    }

    splitsTableBody.innerHTML = "";

    if (!trackPoints.length) {
      appendEmptySplitsRow("Загрузите трек, чтобы увидеть сплиты.");
      if (splitsStatus) {
        splitsStatus.textContent = "Авторасчет по ближайшим КП";
      }
      return;
    }

    const splits = calculateSplits();
    if (!splits.length) {
      appendEmptySplitsRow("Недостаточно данных для расчета сплитов.");
      if (splitsStatus) {
        splitsStatus.textContent = "Сплиты не рассчитаны";
      }
      return;
    }

    for (const row of splits) {
      const tr = document.createElement("tr");
      if (row.isSlowest) {
        tr.classList.add("split-fastest");
      } else if (row.isFastest) {
        tr.classList.add("split-fast");
      }
      tr.append(
        appendCell(row.label),
        appendCell(formatDuration(row.absoluteSeconds)),
        appendCell(row.splitSeconds === null ? "—" : formatDuration(row.splitSeconds)),
        appendCell(formatDistance(row.distanceMeters)),
        appendCell(formatPacePerMeter(row.paceSecondsPerMeter)),
        appendSplitActionCell(row)
      );
      splitsTableBody.appendChild(tr);
    }

    if (splitsStatus) {
      splitsStatus.textContent = `Рассчитано КП: ${splits.length}.`;
    }
  }

  function appendEmptySplitsRow(message) {
    const tr = document.createElement("tr");
    tr.className = "splits-empty-row";
    const td = document.createElement("td");
    td.colSpan = 6;
    td.textContent = message;
    tr.appendChild(td);
    splitsTableBody.appendChild(tr);
  }

  function appendCell(text) {
    const td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  function appendSplitActionCell(row) {
    const td = document.createElement("td");
    td.className = "split-action-cell";
    const button = document.createElement("button");
    button.className = "split-analysis-button";
    button.type = "button";
    button.setAttribute("aria-label", `Анализ сплита ${row.label}`);
    button.title = "Анализ сплита";
    button.addEventListener("click", () => {
      openSplitAnalysis(row);
    });
    button.appendChild(createSplitAnalysisIcon());
    td.appendChild(button);
    return td;
  }

  function createSplitAnalysisIcon() {
    const svgIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svgIcon.setAttribute("viewBox", "0 0 24 24");
    svgIcon.setAttribute("aria-hidden", "true");
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", "4 16 9 11 13 14 20 7");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M4 20h16");
    svgIcon.append(polyline, path);
    return svgIcon;
  }

  function openSplitAnalysis(row) {
    if (!splitAnalysisModal || !splitAnalysisSvg || !image || !image.naturalWidth || !image.naturalHeight) {
      return;
    }
    if (splitAnalysisTitle) {
      splitAnalysisTitle.textContent = `Сплит ${row.label}`;
    }
    activeSplitAnalysisRow = row;
    resetSplitChat(row);
    renderSplitAnalysisMap(row);
    splitAnalysisModal.hidden = false;
    document.body.classList.add("modal-open");
    splitChatStartButton?.focus();
  }

  function closeSplitAnalysis() {
    if (!splitAnalysisModal) {
      return;
    }
    splitAnalysisModal.hidden = true;
    document.body.classList.remove("modal-open");
    activeSplitAnalysisRow = null;
  }

  function resetSplitChat(row) {
    splitChatHistory = [];
    if (!splitChatMessages) {
      return;
    }
    splitChatMessages.innerHTML = "";
    appendSplitChatMessage(
      "assistant",
      `Я тренер. Нажми «Начать диалог», и я разберу сплит ${row.label}.`
    );
    setSplitChatStarted(false);
  }

  function startSplitChat() {
    sendSplitChatMessage("Разбери этот сплит по карте: что получилось хорошо, где могла быть потеря времени, и что попробовать в следующий раз.");
  }

  async function sendSplitChatMessage(forcedQuestion = null) {
    if (!activeSplitAnalysisRow || !splitChatInput || !splitChatMessages) {
      return;
    }
    const question = forcedQuestion || splitChatInput.value.trim();
    if (!question) {
      return;
    }
    if (!forcedQuestion) {
      splitChatInput.value = "";
      appendSplitChatMessage("user", question);
    }
    splitChatHistory.push({role: "user", content: question});
    const pending = appendSplitChatMessage("assistant", "Думаю...");
    setSplitChatStarted(true);
    setSplitChatPending(true);

    try {
      const response = await fetch("/api/split-analysis/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          training_id: trainingId,
          split: splitAnalysisPayload(activeSplitAnalysisRow),
          messages: splitChatHistory.slice(0, -1),
          question,
          image_data_url: await splitAnalysisSnapshotDataUrl(),
        }),
      });
      const payload = await response.json();
      const answer = payload.answer || "Не получилось сформулировать ответ.";
      renderAssistantMessage(pending, answer);
      splitChatHistory.push({role: "assistant", content: answer});
    } catch (error) {
      pending.textContent = `Не удалось связаться с тренером: ${error.message}`;
    } finally {
      setSplitChatPending(false);
      splitChatInput.focus();
    }
  }

  function setSplitChatPending(isPending) {
    if (splitChatInput) {
      splitChatInput.disabled = isPending;
    }
    if (splitChatSubmit) {
      splitChatSubmit.disabled = isPending;
    }
    if (splitChatStartButton) {
      splitChatStartButton.disabled = isPending;
    }
  }

  function setSplitChatStarted(isStarted) {
    if (splitChatStart) {
      splitChatStart.hidden = isStarted;
    }
    if (splitChatForm) {
      splitChatForm.hidden = !isStarted;
    }
  }

  function appendSplitChatMessage(role, text) {
    const message = document.createElement("div");
    message.className = `split-chat-message split-chat-message-${role}`;
    if (role === "assistant") {
      renderAssistantMessage(message, text);
    } else {
      message.textContent = text;
    }
    splitChatMessages.appendChild(message);
    splitChatMessages.scrollTop = splitChatMessages.scrollHeight;
    return message;
  }

  function renderAssistantMessage(element, text) {
    element.textContent = "";
    const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
    for (const part of parts) {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        const strong = document.createElement("strong");
        strong.textContent = part.slice(2, -2);
        element.appendChild(strong);
      } else {
        element.appendChild(document.createTextNode(part));
      }
    }
  }

  function splitAnalysisPayload(row) {
    const trackSegment = trackPoints.slice(row.fromTrackIndex, row.toTrackIndex + 1);
    return {
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
  }

  async function splitAnalysisSnapshotDataUrl() {
    if (!splitAnalysisSvg || !image) {
      return null;
    }
    const clonedSvg = splitAnalysisSvg.cloneNode(true);
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const mapImage = clonedSvg.querySelector("image");
    if (mapImage) {
      mapImage.setAttribute("href", await imageElementDataUrl(image));
    }
    const source = new XMLSerializer().serializeToString(clonedSvg);
    const svgBlob = new Blob([source], {type: "image/svg+xml;charset=utf-8"});
    const svgUrl = URL.createObjectURL(svgBlob);
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

  async function openSplitDebugSnapshot() {
    if (!activeSplitAnalysisRow || !splitDebugSnapshotButton) {
      return;
    }
    const originalText = splitDebugSnapshotButton.textContent;
    splitDebugSnapshotButton.disabled = true;
    splitDebugSnapshotButton.textContent = "Готовлю...";
    try {
      const dataUrl = await splitAnalysisSnapshotDataUrl();
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
            <title>PNG для AI · Сплит ${activeSplitAnalysisRow.label}</title>
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
      appendSplitChatMessage("assistant", `Не удалось подготовить PNG для AI: ${error.message}`);
    } finally {
      splitDebugSnapshotButton.disabled = false;
      splitDebugSnapshotButton.textContent = originalText;
    }
  }

  async function imageElementDataUrl(sourceImage) {
    const response = await fetch(sourceImage.currentSrc || sourceImage.src);
    const blob = await response.blob();
    return await blobToDataUrl(blob);
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

  function renderSplitAnalysisMap(row) {
    const coursePoints = [row.fromControl, ...row.viaControls, row.toControl];
    const trackSegment = trackPoints.slice(row.fromTrackIndex, row.toTrackIndex + 1);
    const focusPoints = [
      ...coursePoints.map(controlPixel),
      ...trackSegment.map((point) => point.pixel),
    ];
    const viewBox = splitViewBox(focusPoints, image.naturalWidth, image.naturalHeight);

    splitAnalysisSvg.innerHTML = "";
    splitAnalysisSvg.setAttribute("viewBox", viewBox.join(" "));

    const mapImage = document.createElementNS("http://www.w3.org/2000/svg", "image");
    mapImage.setAttribute("href", image.currentSrc || image.src);
    mapImage.setAttribute("x", "0");
    mapImage.setAttribute("y", "0");
    mapImage.setAttribute("width", String(image.naturalWidth));
    mapImage.setAttribute("height", String(image.naturalHeight));
    mapImage.setAttribute("preserveAspectRatio", "xMidYMid meet");
    splitAnalysisSvg.appendChild(mapImage);

    appendSplitArrowMarker();
    if (trackSegment.length >= 2) {
      addAnalysisPolyline(trackSegment.map((point) => point.pixel), "split-track-line");
    }
    if (coursePoints.length >= 2) {
      addAnalysisPolyline(coursePoints.map(controlPixel), "split-course-line");
    }
    coursePoints.forEach((control, index) => {
      addAnalysisControlMarker(control, index === 0 ? "from" : index === coursePoints.length - 1 ? "to" : "via");
    });
  }

  function appendSplitArrowMarker() {
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
    path.setAttribute("fill", "#b21f5b");
    marker.appendChild(path);
    defs.appendChild(marker);
    splitAnalysisSvg.appendChild(defs);
  }

  function addAnalysisPolyline(points, className) {
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("class", className);
    polyline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke-linecap", "round");
    polyline.setAttribute("stroke-linejoin", "round");
    if (className === "split-course-line") {
      polyline.setAttribute("stroke", "#b21f5b");
      polyline.setAttribute("stroke-width", "5");
      polyline.setAttribute("marker-end", "url(#split-arrow-head)");
    } else {
      polyline.setAttribute("stroke", "#1565c0");
      polyline.setAttribute("stroke-width", "6");
    }
    splitAnalysisSvg.appendChild(polyline);
  }

  function addAnalysisControlMarker(control, role) {
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
    splitAnalysisSvg.appendChild(group);
  }

  function controlPixel(control) {
    return {pixel_x: control.pixel_x, pixel_y: control.pixel_y};
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

  function calculateSplits() {
    return splitsEngine.calculateSplits(courseControls, trackPoints);
  }

  function courseControlsBetween(previousControl, currentControl) {
    const previousIndex = previousControl.index - 1;
    const currentIndex = currentControl.index - 1;
    if (currentIndex - previousIndex <= 1) {
      return [];
    }
    return courseControls.slice(previousIndex + 1, currentIndex);
  }

  function findClosestTrackPoint(control, startIndex) {
    let best = null;
    for (let index = startIndex; index < trackPoints.length; index += 1) {
      const point = trackPoints[index];
      const distanceMeters = haversineMeters(point, control);
      const seconds = trackPointSeconds(point, index);
      if (!best || distanceMeters < best.distanceMeters) {
        best = {
          index,
          point,
          distanceMeters,
          seconds,
        };
      }
    }
    return best;
  }

  function trackPointSeconds(point, index) {
    if (point.time) {
      const timestamp = Date.parse(point.time);
      if (!Number.isNaN(timestamp)) {
        return timestamp / 1000;
      }
    }
    return index;
  }

  function courseStageDistanceMeters(previousControl, currentControl) {
    const previousIndex = previousControl.index - 1;
    const currentIndex = currentControl.index - 1;
    if (currentIndex <= previousIndex) {
      return 0;
    }

    let total = 0;
    for (let index = previousIndex + 1; index <= currentIndex; index += 1) {
      total += haversineMeters(courseControls[index - 1], courseControls[index]);
    }
    return total;
  }

  function formatDistance(meters) {
    if (meters === null || typeof meters === "undefined") {
      return "—";
    }
    if (meters < 1000) {
      return `${Math.round(meters)} м`;
    }
    return `${(meters / 1000).toFixed(2)} км`;
  }

  function formatPacePerMeter(value) {
    if (value === null || typeof value === "undefined") {
      return "—";
    }
    return value.toFixed(2);
  }

  function formatDuration(seconds) {
    const total = Math.max(Math.round(seconds), 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const rest = total % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
    }
    return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }

  function serializedTrackPoint(point) {
    const payload = {
      lat: point.lat,
      lon: point.lon,
    };
    if (typeof point.ele === "number") {
      payload.ele = point.ele;
    }
    if (point.time) {
      payload.time = point.time;
    }
    return payload;
  }

  function interpolateNumber(start, end, ratio) {
    return start + (end - start) * ratio;
  }

  function secondsToIsoTime(seconds, fallback) {
    if (!fallback) {
      return fallback;
    }
    const timestamp = seconds * 1000;
    if (!Number.isFinite(timestamp)) {
      return fallback;
    }
    return new Date(timestamp).toISOString();
  }

  function seekToPaceChartPointer(event) {
    const seconds = paceChartPointerToSeconds(event);
    if (seconds === null) {
      return;
    }
    seekToSeconds(seconds);
  }

  function paceChartPointerToSeconds(event) {
    if (!paceChartInstance || !window.Chart) {
      return null;
    }
    const xScale = paceChartInstance.scales.x;
    if (!xScale) {
      return null;
    }
    const position = window.Chart.helpers?.getRelativePosition
      ? window.Chart.helpers.getRelativePosition(event, paceChartInstance)
      : fallbackChartRelativePosition(event);
    return clamp(xScale.getValueForPixel(position.x), 0, durationSeconds);
  }

  function fallbackChartRelativePosition(event) {
    const rect = paceChart.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  function haversineMeters(a, b) {
    const radius = 6371000;
    const lat1 = toRadians(a.lat);
    const lat2 = toRadians(b.lat);
    const deltaLat = toRadians(b.lat - a.lat);
    const deltaLon = toRadians(b.lon - a.lon);
    const value =
      Math.sin(deltaLat / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
    return radius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
  }

  function toRadians(value) {
    return value * Math.PI / 180;
  }

  function geoToPixel(point) {
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

  function fitImageToViewport() {
    if (!image || !viewport || !content || image.naturalWidth === 0 || image.naturalHeight === 0) {
      return;
    }
    const rect = viewport.getBoundingClientRect();
    const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight, 1);
    view.scale = clamp(scale, 0.15, 10);
    view.translateX = Math.max((rect.width - image.naturalWidth * view.scale) / 2, 0);
    view.translateY = Math.max((rect.height - image.naturalHeight * view.scale) / 2, 0);
    content.style.width = `${image.naturalWidth}px`;
    content.style.height = `${image.naturalHeight}px`;
    applyView();
  }

  function applyView() {
    if (!content) {
      return;
    }
    content.style.transform = `translate(${view.translateX}px, ${view.translateY}px) scale(${view.scale})`;
  }

  function finishDrag(event) {
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    viewport?.releasePointerCapture(event.pointerId);
    viewport?.classList.remove("dragging");
    drag = null;
  }

  function finishPaceScrub(event) {
    if (paceScrubPointerId !== event.pointerId) {
      return;
    }
    paceChart?.releasePointerCapture(event.pointerId);
    paceChart?.classList.remove("scrubbing");
    paceScrubPointerId = null;
  }

  function clientPointToViewportPoint(clientX, clientY) {
    const rect = viewport.getBoundingClientRect();
    return {
      x: clientX - rect.left,
      y: clientY - rect.top,
    };
  }

  function viewportPointToImagePixel(x, y) {
    return {
      pixel_x: (x - view.translateX) / view.scale,
      pixel_y: (y - view.translateY) / view.scale,
    };
  }

  function parseJson(rawValue, fallback) {
    if (!rawValue || rawValue === "null") {
      return fallback;
    }
    try {
      return JSON.parse(rawValue);
    } catch (_error) {
      return fallback;
    }
  }

  function normalizeCourseControls(controls) {
    return controls.map((control, index) => ({
      ...control,
      index: index + 1,
      label: courseControlLabel(index, controls.length),
      kind: courseControlKind(index, controls.length),
    }));
  }

  function courseControlLabel(index, total) {
    if (index === 0) {
      return "С";
    }
    if (total > 2 && index === 1) {
      return "К";
    }
    if (total > 1 && index === total - 1) {
      return "Ф";
    }
    return String(index - 1);
  }

  function courseControlKind(index, total) {
    if (index === 0) {
      return "start";
    }
    if (total > 2 && index === 1) {
      return "start-point";
    }
    if (total > 1 && index === total - 1) {
      return "finish";
    }
    return "control";
  }

  function formatTime(seconds) {
    const total = Math.max(Math.floor(seconds), 0);
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }

  function formatPace(pace) {
    const minutes = Math.floor(pace);
    const seconds = Math.round((pace - minutes) * 60);
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }
})();
