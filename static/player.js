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
  const splitProblemsOnly = document.querySelector("#split-problems-only");

  const trainingId = workspace.dataset.trainingId;
  const transform = parseJson(workspace.dataset.transform, null);
  const splitsEngine = window.OrienteeringSplits;
  const courseControls = splitsEngine.normalizeCourseControls(parseJson(workspace.dataset.courseControls, []));
  const hasRaceResult = workspace.dataset.hasRaceResult === "true";
  const raceResultSplitGaps = parseJson(workspace.dataset.raceResultSplitGaps, {}) || {};
  const splitsColumnCount = hasRaceResult ? 7 : 6;
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

  splitProblemsOnly?.addEventListener("change", () => {
    renderSplitsTable();
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
    return calculateTrackPaceSeries(trackPoints, trackPoints[0]?.seconds || 0);
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
      raw.push({
        seconds: current.seconds - baseSeconds,
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

    const visibleSplits = splitProblemsOnly?.checked ? splits.filter(isProblemSplit) : splits;
    if (!visibleSplits.length) {
      appendEmptySplitsRow("Проблемных сплитов нет.");
      if (splitsStatus) {
        splitsStatus.textContent = `Рассчитано КП: ${splits.length}. Проблемных нет.`;
      }
      return;
    }

    for (const row of visibleSplits) {
      const tr = document.createElement("tr");
      if (row.isSlowest) {
        tr.classList.add("split-fastest");
      } else if (row.isFastest) {
        tr.classList.add("split-fast");
      }
      const cells = [
        appendCell(row.label),
        appendCell(formatDuration(row.absoluteSeconds)),
        appendCell(row.splitSeconds === null ? "—" : formatDuration(row.splitSeconds)),
      ];
      if (hasRaceResult) {
        cells.push(appendGapCell(raceResultSplitGaps[row.label]));
      }
      cells.push(
        appendCell(formatDistance(row.distanceMeters)),
        appendCell(formatPacePerMeter(row.paceSecondsPerMeter)),
        appendSplitActionCell(row)
      );
      tr.append(...cells);
      splitsTableBody.appendChild(tr);
    }

    if (splitsStatus) {
      splitsStatus.textContent = splitProblemsOnly?.checked
        ? `Рассчитано КП: ${splits.length}. Проблемы: ${visibleSplits.length}.`
        : `Рассчитано КП: ${splits.length}.`;
    }
  }

  function isProblemSplit(row) {
    const gap = raceResultSplitGaps[row.label];
    return row.isSlowest || gap?.tone === "hot" || gap?.tone === "warm";
  }

  function appendEmptySplitsRow(message) {
    const tr = document.createElement("tr");
    tr.className = "splits-empty-row";
    const td = document.createElement("td");
    td.colSpan = splitsColumnCount;
    td.textContent = message;
    tr.appendChild(td);
    splitsTableBody.appendChild(tr);
  }

  function appendCell(text) {
    const td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  function appendGapCell(gap) {
    const td = document.createElement("td");
    if (!gap || !gap.text) {
      td.textContent = "—";
      return td;
    }
    const span = document.createElement("span");
    span.classList.add("race-split-gap");
    if (gap.tone === "hot") {
      span.classList.add("race-split-gap-hot");
    } else if (gap.tone === "warm") {
      span.classList.add("race-split-gap-warm");
    } else if (gap.tone === "good") {
      span.classList.add("race-split-gap-good");
    }
    span.textContent = gap.text;
    td.appendChild(span);
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
    window.SplitAnalysisDialog?.open({
      trainingId,
      row,
      image,
      trackPoints,
    });
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
