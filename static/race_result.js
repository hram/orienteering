(function () {
  const workspace = document.querySelector("#race-result-workspace");
  if (!workspace || !window.OrienteeringSplits) {
    return;
  }

  const image = document.querySelector("#race-analysis-map-image");
  const splitAnalysisModal = document.querySelector("#split-analysis-modal");
  const splitAnalysisTitle = document.querySelector("#split-analysis-title");
  const splitAnalysisSvg = document.querySelector("#split-analysis-svg");
  const splitAnalysisClose = document.querySelector("#split-analysis-close");
  const splitDebugSnapshotButton = document.querySelector("#split-debug-snapshot");
  const splitPaceChart = document.querySelector("#split-pace-chart");
  const splitPaceStatus = document.querySelector("#split-pace-status");
  const splitChatMessages = document.querySelector("#split-chat-messages");
  const splitChatStart = document.querySelector("#split-chat-start");
  const splitChatStartButton = document.querySelector("#split-chat-start-button");
  const splitChatForm = document.querySelector("#split-chat-form");
  const splitChatInput = document.querySelector("#split-chat-input");
  const splitChatSubmit = document.querySelector("#split-chat-submit");

  const trainingId = workspace.dataset.trainingId;
  const transform = parseJson(workspace.dataset.transform, null);
  const courseControls = window.OrienteeringSplits.normalizeCourseControls(parseJson(workspace.dataset.courseControls, []));
  const trackPoints = parseJson(workspace.dataset.trackPoints, []).map((point, index) => ({
    ...point,
    pixel: transform ? geoToPixel(point) : {pixel_x: 0, pixel_y: 0},
    seconds: window.OrienteeringSplits.parsePointSeconds(point, index),
  }));
  const splits = window.OrienteeringSplits.calculateSplits(courseControls, trackPoints);

  let activeSplitAnalysisRow = null;
  let splitChatHistory = [];
  let splitPaceChartInstance = null;
  let splitAnalysisMarker = null;
  let splitAnalysisSeconds = 0;
  let splitPaceScrubPointerId = null;

  document.querySelectorAll(".race-split-analysis-button").forEach((button) => {
    button.addEventListener("click", () => {
      openSplitAnalysisByLabel(button.dataset.splitLabel);
    });
  });
  splitAnalysisClose?.addEventListener("click", closeSplitAnalysis);
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
  splitChatStartButton?.addEventListener("click", () => {
    sendSplitChatMessage("Разбери этот сплит по карте: что получилось хорошо, где могла быть потеря времени, и что попробовать в следующий раз.");
  });
  splitChatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    sendSplitChatMessage();
  });
  splitDebugSnapshotButton?.addEventListener("click", openSplitDebugSnapshot);
  splitPaceChart?.addEventListener("pointerdown", (event) => {
    if (!splitPaceChartInstance) {
      return;
    }
    event.preventDefault();
    splitPaceScrubPointerId = event.pointerId;
    splitPaceChart.setPointerCapture(event.pointerId);
    splitPaceChart.classList.add("scrubbing");
    seekToSplitPaceChartPointer(event);
  });
  splitPaceChart?.addEventListener("pointermove", (event) => {
    if (splitPaceScrubPointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    seekToSplitPaceChartPointer(event);
  });
  splitPaceChart?.addEventListener("pointerup", finishSplitPaceScrub);
  splitPaceChart?.addEventListener("pointercancel", finishSplitPaceScrub);

  function openSplitAnalysisByLabel(label) {
    const normalized = normalizeSplitLabel(label);
    const row = splits.find((split) => normalizeSplitLabel(split.label) === normalized);
    if (!row || !image || !image.complete || !image.naturalWidth) {
      return;
    }
    openSplitAnalysis(row);
  }

  function openSplitAnalysis(row) {
    if (!splitAnalysisModal || !splitAnalysisSvg) {
      return;
    }
    splitAnalysisTitle.textContent = `Сплит ${row.label}`;
    activeSplitAnalysisRow = row;
    splitAnalysisSeconds = 0;
    resetSplitChat(row);
    renderSplitAnalysisMap(row);
    drawSplitPaceChart(row);
    splitAnalysisModal.hidden = false;
    document.body.classList.add("modal-open");
    splitChatStartButton?.focus();
  }

  function closeSplitAnalysis() {
    splitAnalysisModal.hidden = true;
    document.body.classList.remove("modal-open");
    activeSplitAnalysisRow = null;
    splitAnalysisMarker = null;
    splitAnalysisSeconds = 0;
    destroySplitPaceChart();
  }

  function resetSplitChat(row) {
    splitChatHistory = [];
    splitChatMessages.innerHTML = "";
    appendSplitChatMessage("assistant", `Я тренер. Нажми «Начать диалог», и я разберу сплит ${row.label}.`);
    setSplitChatStarted(false);
  }

  async function sendSplitChatMessage(forcedQuestion = null) {
    if (!activeSplitAnalysisRow) {
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

  function renderSplitAnalysisMap(row) {
    const coursePoints = [row.fromControl, ...row.viaControls, row.toControl];
    const trackSegment = splitTrackSegment(row);
    const focusPoints = [...coursePoints.map(controlPixel), ...trackSegment.map((point) => point.pixel)];
    splitAnalysisSvg.innerHTML = "";
    splitAnalysisSvg.setAttribute("viewBox", splitViewBox(focusPoints, image.naturalWidth, image.naturalHeight).join(" "));

    const mapImage = document.createElementNS("http://www.w3.org/2000/svg", "image");
    mapImage.setAttribute("href", image.currentSrc || image.src);
    mapImage.setAttribute("x", "0");
    mapImage.setAttribute("y", "0");
    mapImage.setAttribute("width", String(image.naturalWidth));
    mapImage.setAttribute("height", String(image.naturalHeight));
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
    splitAnalysisMarker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    splitAnalysisMarker.setAttribute("class", "split-athlete-marker");
    splitAnalysisMarker.setAttribute("r", "8");
    splitAnalysisMarker.setAttribute("fill", "#18a0fb");
    splitAnalysisMarker.setAttribute("stroke", "#ffffff");
    splitAnalysisMarker.setAttribute("stroke-width", "4");
    splitAnalysisSvg.appendChild(splitAnalysisMarker);
    updateSplitAnalysisAthlete(0);
  }

  function drawSplitPaceChart(row) {
    destroySplitPaceChart();
    const trackSegment = splitTrackSegment(row);
    const baseSeconds = trackSegment[0]?.seconds || 0;
    const series = calculateTrackPaceSeries(trackSegment, baseSeconds);
    const duration = Math.max(row.splitSeconds || 0, 1);
    if (series.length < 2 || !window.Chart) {
      splitPaceStatus.textContent = series.length < 2 ? "нет данных" : "график недоступен";
      return;
    }
    const average = series.reduce((sum, point) => sum + point.pace, 0) / series.length;
    splitPaceStatus.textContent = `${formatPace(average)} мин/км`;
    const bounds = calculatePaceBoundsForSeries(series);
    const playheadPlugin = {
      id: "splitPacePlayhead",
      afterDatasetsDraw(chart) {
        const xScale = chart.scales.x;
        const area = chart.chartArea;
        if (!xScale || !area) {
          return;
        }
        const x = xScale.getPixelForValue(clamp(splitAnalysisSeconds, 0, duration));
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
    splitPaceChartInstance = new window.Chart(splitPaceChart, {
      type: "line",
      data: {
        datasets: [{
          label: "Темп",
          data: series.map((point) => ({x: point.seconds, y: point.pace})),
          borderColor: "#1565c0",
          backgroundColor: "rgba(21, 101, 192, 0.18)",
          borderWidth: 2,
          pointRadius: 0,
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
          x: {type: "linear", min: 0, max: duration, ticks: {maxTicksLimit: 6, callback: (value) => formatTime(Number(value))}},
          y: {min: bounds.min, max: bounds.max, ticks: {maxTicksLimit: 4, callback: (value) => formatPace(Number(value))}},
        },
      },
      plugins: [playheadPlugin],
    });
  }

  async function splitAnalysisSnapshotDataUrl() {
    const clonedSvg = splitAnalysisSvg.cloneNode(true);
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clonedSvg.querySelector(".split-athlete-marker")?.remove();
    const mapImage = clonedSvg.querySelector("image");
    if (mapImage) {
      mapImage.setAttribute("href", await imageElementDataUrl(image));
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

  async function openSplitDebugSnapshot() {
    const dataUrl = await splitAnalysisSnapshotDataUrl();
    const snapshotWindow = window.open();
    if (snapshotWindow) {
      snapshotWindow.document.write(`<img src="${dataUrl}" alt="PNG для AI" style="max-width:100%;height:auto">`);
      snapshotWindow.document.close();
    }
  }

  function splitAnalysisPayload(row) {
    const trackSegment = splitTrackSegment(row);
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
    label.setAttribute("font-size", "12");
    label.setAttribute("font-weight", "700");
    label.setAttribute("text-anchor", "middle");
    label.textContent = control.label;
    group.append(circle, label);
    splitAnalysisSvg.appendChild(group);
  }

  function seekToSplitPaceChartPointer(event) {
    if (!splitPaceChartInstance || !activeSplitAnalysisRow || !window.Chart) {
      return;
    }
    const xScale = splitPaceChartInstance.scales.x;
    const position = window.Chart.helpers?.getRelativePosition
      ? window.Chart.helpers.getRelativePosition(event, splitPaceChartInstance)
      : {x: event.clientX - splitPaceChart.getBoundingClientRect().left};
    seekSplitAnalysis(clamp(xScale.getValueForPixel(position.x), 0, Math.max(activeSplitAnalysisRow.splitSeconds || 0, 0)));
  }

  function finishSplitPaceScrub(event) {
    if (splitPaceScrubPointerId !== event.pointerId) {
      return;
    }
    splitPaceChart.releasePointerCapture(event.pointerId);
    splitPaceChart.classList.remove("scrubbing");
    splitPaceScrubPointerId = null;
  }

  function seekSplitAnalysis(seconds) {
    splitAnalysisSeconds = clamp(seconds, 0, Math.max(activeSplitAnalysisRow.splitSeconds || 0, 0));
    updateSplitAnalysisAthlete(splitAnalysisSeconds);
    splitPaceChartInstance?.update("none");
  }

  function updateSplitAnalysisAthlete(seconds) {
    if (!activeSplitAnalysisRow || !splitAnalysisMarker) {
      return;
    }
    const pixel = interpolateTrackSegmentPixel(splitTrackSegment(activeSplitAnalysisRow), seconds);
    splitAnalysisMarker.setAttribute("cx", String(pixel.pixel_x));
    splitAnalysisMarker.setAttribute("cy", String(pixel.pixel_y));
  }

  function splitTrackSegment(row) {
    return trackPoints.slice(row.fromTrackIndex, row.toTrackIndex + 1);
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

  function calculatePaceBoundsForSeries(series) {
    const values = series.map((point) => point.pace);
    const min = Math.min(...values);
    const max = Math.max(...values);
    if (min === max) {
      return {min: min - 0.5, max: max + 0.5};
    }
    const padding = Math.max((max - min) * 0.12, 0.3);
    return {min: Math.max(0, min - padding), max: max + padding};
  }

  function destroySplitPaceChart() {
    if (splitPaceChartInstance) {
      splitPaceChartInstance.destroy();
      splitPaceChartInstance = null;
    }
  }

  function setSplitChatPending(isPending) {
    splitChatInput.disabled = isPending;
    splitChatSubmit.disabled = isPending;
    splitChatStartButton.disabled = isPending;
  }

  function setSplitChatStarted(isStarted) {
    splitChatStart.hidden = isStarted;
    splitChatForm.hidden = !isStarted;
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

  function controlPixel(control) {
    return {pixel_x: control.pixel_x, pixel_y: control.pixel_y};
  }

  function geoToPixel(point) {
    const determinant = transform.lon_a * transform.lat_b - transform.lon_b * transform.lat_a;
    if (Math.abs(determinant) < 1e-12) {
      return {pixel_x: 0, pixel_y: 0};
    }
    const deltaLon = point.lon - transform.lon_c;
    const deltaLat = point.lat - transform.lat_c;
    return {
      pixel_x: (deltaLon * transform.lat_b - deltaLat * transform.lon_b) / determinant,
      pixel_y: (transform.lon_a * deltaLat - transform.lat_a * deltaLon) / determinant,
    };
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

  function normalizeSplitLabel(label) {
    return String(label).trim().toUpperCase() === "F" ? "Ф" : String(label).trim();
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

  function parseJson(rawValue, fallback) {
    if (!rawValue) {
      return fallback;
    }
    try {
      return JSON.parse(rawValue);
    } catch (_error) {
      return fallback;
    }
  }
})();
