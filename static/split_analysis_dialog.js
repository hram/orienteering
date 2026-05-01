(function (root) {
  const modal = document.querySelector("#split-analysis-modal");
  if (!modal) {
    return;
  }

  const title = document.querySelector("#split-analysis-title");
  const svg = document.querySelector("#split-analysis-svg");
  const closeButton = document.querySelector("#split-analysis-close");
  const debugSnapshotButton = document.querySelector("#split-debug-snapshot");
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

  closeButton?.addEventListener("click", close);
  debugSnapshotButton?.addEventListener("click", openDebugSnapshot);
  modal.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.matches("[data-close-split-analysis]")) {
      close();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      close();
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

  function open(options) {
    if (!options?.row || !options?.image || !svg) {
      return;
    }
    if (!options.image.complete || !options.image.naturalWidth || !options.image.naturalHeight) {
      options.image.addEventListener("load", () => open(options), {once: true});
      return;
    }
    active = {
      trainingId: options.trainingId,
      row: options.row,
      image: options.image,
      trackPoints: options.trackPoints || [],
    };
    analysisSeconds = 0;
    if (title) {
      title.textContent = `Сплит ${active.row.label}`;
    }
    resetChat(active.row);
    renderMap();
    drawPaceChart();
    modal.hidden = false;
    document.body.classList.add("modal-open");
    chatStartButton?.focus();
  }

  function close() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
    active = null;
    athleteMarker = null;
    analysisSeconds = 0;
    destroyPaceChart();
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
    const coursePoints = [row.fromControl, ...row.viaControls, row.toControl];
    const trackSegment = splitTrackSegment(row);
    const focusPoints = [...coursePoints.map(controlPixel), ...trackSegment.map((point) => point.pixel)];
    svg.innerHTML = "";
    svg.setAttribute("viewBox", splitViewBox(focusPoints, image.naturalWidth, image.naturalHeight).join(" "));

    const mapImage = document.createElementNS("http://www.w3.org/2000/svg", "image");
    mapImage.setAttribute("href", image.currentSrc || image.src);
    mapImage.setAttribute("x", "0");
    mapImage.setAttribute("y", "0");
    mapImage.setAttribute("width", String(image.naturalWidth));
    mapImage.setAttribute("height", String(image.naturalHeight));
    mapImage.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.appendChild(mapImage);

    appendArrowMarker();
    if (trackSegment.length >= 2) {
      addPolyline(trackSegment.map((point) => point.pixel), "split-track-line");
    }
    if (coursePoints.length >= 2) {
      addPolyline(coursePoints.map(controlPixel), "split-course-line");
    }
    coursePoints.forEach((control, index) => {
      addControlMarker(control, index === 0 ? "from" : index === coursePoints.length - 1 ? "to" : "via");
    });
    athleteMarker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    athleteMarker.setAttribute("class", "split-athlete-marker");
    athleteMarker.setAttribute("r", "8");
    athleteMarker.setAttribute("fill", "#18a0fb");
    athleteMarker.setAttribute("stroke", "#ffffff");
    athleteMarker.setAttribute("stroke-width", "4");
    svg.appendChild(athleteMarker);
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
    const duration = Math.max(row.splitSeconds || 0, 1);
    if (series.length < 2) {
      paceStatus.textContent = "нет данных";
      return;
    }
    const average = series.reduce((sum, point) => sum + point.pace, 0) / series.length;
    paceStatus.textContent = `${formatPace(average)} мин/км`;
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
    path.setAttribute("fill", "#b21f5b");
    marker.appendChild(path);
    defs.appendChild(marker);
    svg.appendChild(defs);
  }

  function addPolyline(points, className) {
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
    svg.appendChild(polyline);
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
    svg.appendChild(group);
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

  root.SplitAnalysisDialog = {open, close};
})(typeof globalThis !== "undefined" ? globalThis : window);
