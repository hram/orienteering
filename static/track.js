(function () {
  const workspace = document.querySelector("#track-workspace");
  if (!workspace) {
    return;
  }

  const draftId = workspace.dataset.draftId;
  const trainingType = workspace.dataset.trainingType || "";
  const uploadForm = document.querySelector("#track-upload-form");
  const status = document.querySelector("#track-status");
  const image = document.querySelector("#track-map-image");
  const svg = document.querySelector("#track-image-svg");
  const emptyStage = document.querySelector("#track-empty-stage");
  const viewport = document.querySelector("#track-image-viewport");
  const content = document.querySelector("#track-image-content");
  const splitsStatus = document.querySelector("#track-splits-status");
  const layerTabsContainer = document.querySelector("#track-map-layer-tabs");
  const layerTabs = Array.from(document.querySelectorAll("#track-map-layer-tabs .map-layer-tab"));

  const mapLayers = normalizeMapLayers(parseJson(workspace.dataset.mapLayers, []));
  let activeLayerId = mapLayers[0]?.id || "map-1";
  let activeLayer = mapLayers.find((layer) => layer.id === activeLayerId) || mapLayers[0] || null;
  let transform = activeLayer?.georef_transform || null;
  const splitsEngine = window.OrienteeringSplits || createFallbackSplitsEngine();
  let courseControls = normalizeAllCourseControls();
  let trackPoints = normalizeTrackPoints(parseJson(workspace.dataset.trackPoints, []));
  let view = {scale: 1, translateX: 0, translateY: 0};
  let drag = null;
  let splitDrag = null;
  let persistTimer = null;
  const trackMarkerEngine = window.OrienteeringTrackMarkers;

  layerTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      setActiveLayer(tab.dataset.layerId || "map-1");
    });
  });
  stopViewportGestures(layerTabsContainer);

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(uploadForm);
    status.textContent = "Загружаю GPX...";

    const response = await fetch(`/api/imports/${draftId}/track-gpx`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      status.textContent = await response.text();
      return;
    }

    const payload = await response.json();
    trackPoints = normalizeTrackPoints(payload.track_points);
    autoAnnotateSplitMarkers();
    await saveDraftTrackPointsNow();
    drawAll();
  });

  if (image) {
    image.addEventListener("load", () => {
      fitImageToViewport();
      drawAll();
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

  svg?.addEventListener("pointermove", moveSplitMarker);
  svg?.addEventListener("pointerup", finishSplitMarkerDrag);
  svg?.addEventListener("pointercancel", finishSplitMarkerDrag);

  if (trackPoints.length && !hasSplitMarkers()) {
    autoAnnotateSplitMarkers();
    saveDraftTrackPointsNow();
  }

  setActiveLayer(activeLayerId);
  drawAll();

  function setActiveLayer(layerId) {
    const nextLayer = mapLayers.find((layer) => layer.id === layerId);
    if (!nextLayer) {
      return;
    }
    activeLayerId = nextLayer.id;
    activeLayer = nextLayer;
    transform = activeLayer.georef_transform || null;
    trackPoints = normalizeTrackPoints(trackPoints);
    layerTabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.layerId === activeLayerId);
    });
    if (image) {
      image.src = activeLayer.map_image_url || "";
      image.hidden = !activeLayer.map_image_url;
    }
    if (emptyStage) {
      emptyStage.hidden = Boolean(activeLayer.map_image_url);
    }
    fitImageToViewport();
    drawAll();
  }

  function drawAll() {
    drawImageTrack();
    if (status) {
      status.textContent = trackPoints.length
        ? `Точек трека: ${trackPoints.length}.`
        : "Загрузите GPX.";
    }
    updateSplitsStatus();
  }

  function drawImageTrack() {
    if (!image || !svg || !transform || !image.complete || image.naturalWidth === 0) {
      return;
    }

    svg.setAttribute("viewBox", `0 0 ${image.naturalWidth} ${image.naturalHeight}`);
    svg.innerHTML = "";

    const visibleCourseControls = activeCourseControls();
    if (visibleCourseControls.length >= 2) {
      addPolyline(
        visibleCourseControls.map((control) => ({pixel_x: control.pixel_x, pixel_y: control.pixel_y})),
        "course-line"
      );
    }

    visibleCourseControls.forEach((control) => {
      addControlMarker(control);
    });

    const visibleTrackPoints = activeLayerTrackPoints();
    if (visibleTrackPoints.length) {
      addPolyline(visibleTrackPoints.map((point) => point.pixel), "track-line");
      addSplitMarkers();
    }
  }

  function addPolyline(points, className) {
    if (points.length < 2) {
      return;
    }
    if (className === "course-line") {
      addPolylineOutline(points, className);
    }
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("class", className);
    polyline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    svg.appendChild(polyline);
  }

  function addPolylineOutline(points, className) {
    const outline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    outline.setAttribute("class", `${className} ${className}-outline`);
    outline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    svg.appendChild(outline);
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

  function addSplitMarkers() {
    getSplitMarkers().filter((marker) => marker.control.map_layer_id === activeLayerId).forEach((marker) => {
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      group.setAttribute("class", "split-cut-marker");
      group.setAttribute("transform", `translate(${marker.point.pixel.pixel_x} ${marker.point.pixel.pixel_y})`);
      group.dataset.trackIndex = String(marker.trackIndex);
      group.dataset.controlIndex = String(marker.control.index);
      group.dataset.controlOrder = String(marker.order);

      const halo = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      halo.setAttribute("class", "split-cut-marker-halo");
      halo.setAttribute("r", "12");
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("class", "split-cut-marker-dot");
      dot.setAttribute("r", "6");
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("y", "-16");
      label.textContent = marker.control.label;

      group.append(halo, dot, label);
      group.addEventListener("pointerdown", startSplitMarkerDrag);
      svg.appendChild(group);
    });
  }

  function startSplitMarkerDrag(event) {
    if (!image || !svg) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const markerNode = event.currentTarget;
    const order = Number(markerNode.dataset.controlOrder);
    const marker = getSplitMarkers().find((item) => item.order === order);
    if (!marker) {
      return;
    }
    svg.setPointerCapture(event.pointerId);
    splitDrag = {
      pointerId: event.pointerId,
      order,
      controlIndex: marker.control.index,
      trackIndex: marker.trackIndex,
    };
    svg.classList.add("dragging-split-marker");
  }

  function moveSplitMarker(event) {
    if (!splitDrag || splitDrag.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    const limits = splitMarkerLimits(splitDrag.order);
    const pointer = clientPointToViewportPoint(event.clientX, event.clientY);
    const pixel = viewportPointToImagePixel(pointer.x, pointer.y);
    const nextIndex = nearestTrackIndexToPixel(pixel, limits.min, limits.max);
    if (nextIndex === null || nextIndex === splitDrag.trackIndex) {
      return;
    }
    moveSplitMarkerAnnotation(splitDrag.trackIndex, nextIndex, splitDrag.controlIndex, splitDrag.order);
    splitDrag.trackIndex = nextIndex;
    drawAll();
  }

  function finishSplitMarkerDrag(event) {
    if (!splitDrag || splitDrag.pointerId !== event.pointerId) {
      return;
    }
    svg?.releasePointerCapture(event.pointerId);
    svg?.classList.remove("dragging-split-marker");
    splitDrag = null;
    persistDraftTrackPoints(250);
  }

  function autoAnnotateSplitMarkers() {
    clearSplitMarkerAnnotations();
    const layerMarkers = calculateLayerSplitMarkers();
    if (layerMarkers.length) {
      layerMarkers.forEach((marker) => {
        annotateSplitMarker(marker.trackIndex, marker.control, marker.order);
      });
      return;
    }

    const rows = splitsEngine.calculateSplits(courseControls, trackPoints);
    if (!rows.length) {
      return;
    }
    const splitControls = courseControls.filter((control) => control.kind !== "start-point");
    const firstRow = rows[0];
    annotateSplitMarker(firstRow.fromTrackIndex, firstRow.fromControl, splitControls.indexOf(firstRow.fromControl));
    rows.forEach((row) => {
      annotateSplitMarker(row.toTrackIndex, row.toControl, splitControls.indexOf(row.toControl));
    });
  }

  function calculateLayerSplitMarkers() {
    if (!trackMarkerEngine) {
      return [];
    }
    return trackMarkerEngine.calculateLayerSplitMarkers(mapLayers, courseControls, trackPoints);
  }

  function annotateSplitMarker(trackIndex, control, order) {
    if (!trackPoints[trackIndex] || !control || order < 0) {
      return;
    }
    trackPoints[trackIndex].split_control_index = control.index;
    trackPoints[trackIndex].split_control_label = control.label;
    trackPoints[trackIndex].split_control_kind = control.kind;
    trackPoints[trackIndex].split_control_order = order;
  }

  function clearSplitMarkerAnnotations() {
    trackPoints.forEach((point) => {
      delete point.split_control_index;
      delete point.split_control_label;
      delete point.split_control_kind;
      delete point.split_control_order;
    });
  }

  function moveSplitMarkerAnnotation(fromIndex, toIndex, controlIndex, order) {
    const source = trackPoints[fromIndex];
    const target = trackPoints[toIndex];
    if (!source || !target) {
      return;
    }
    const sourcePayload = {
      split_control_index: source.split_control_index || controlIndex,
      split_control_label: source.split_control_label,
      split_control_kind: source.split_control_kind,
      split_control_order: source.split_control_order,
    };
    const targetPayload = hasSplitMarkerAnnotation(target)
      ? {
          split_control_index: target.split_control_index,
          split_control_label: target.split_control_label,
          split_control_kind: target.split_control_kind,
          split_control_order: target.split_control_order,
        }
      : null;
    const nextFreeIndex = targetPayload ? nearestFreeTrackIndex(toIndex, order) : null;
    if (targetPayload && nextFreeIndex === null) {
      return;
    }
    if (targetPayload) {
      applySplitMarkerAnnotation(trackPoints[nextFreeIndex], targetPayload);
    }
    applySplitMarkerAnnotation(target, sourcePayload);
    clearSplitMarkerAnnotation(source);
  }

  function hasSplitMarkerAnnotation(point) {
    return Number.isFinite(Number(point?.split_control_order));
  }

  function applySplitMarkerAnnotation(point, payload) {
    point.split_control_index = payload.split_control_index;
    point.split_control_label = payload.split_control_label;
    point.split_control_kind = payload.split_control_kind;
    point.split_control_order = payload.split_control_order;
  }

  function clearSplitMarkerAnnotation(point) {
    delete point.split_control_index;
    delete point.split_control_label;
    delete point.split_control_kind;
    delete point.split_control_order;
  }

  function nearestFreeTrackIndex(originIndex, movingOrder) {
    const limits = splitMarkerLimitsForOrder(movingOrder, {ignoreLayerBoundary: true});
    let best = null;
    for (let offset = 1; offset < trackPoints.length; offset += 1) {
      for (const index of [originIndex + offset, originIndex - offset]) {
        if (index < limits.min || index > limits.max || index < 0 || index >= trackPoints.length) {
          continue;
        }
        if (hasSplitMarkerAnnotation(trackPoints[index])) {
          continue;
        }
        best = index;
        break;
      }
      if (best !== null) {
        return best;
      }
    }
    return null;
  }

  function splitMarkerLimitsForOrder(order, options = {}) {
    const markers = getSplitMarkers();
    const current = markers.find((marker) => marker.order === order);
    const previous = markers.filter((marker) => marker.order < order).at(-1);
    let next = markers.find((marker) => marker.order > order);
    if (!options.ignoreLayerBoundary && current && next && current.control.map_layer_id !== next.control.map_layer_id) {
      next = null;
    }
    return {
      min: previous ? previous.trackIndex + 1 : 0,
      max: next ? next.trackIndex - 1 : trackPoints.length - 1,
    };
  }

  function getSplitMarkers() {
    const splitControls = courseControls.filter((control) => control.kind !== "start-point");
    return trackPoints
      .map((point, trackIndex) => {
        const order = Number(point.split_control_order);
        const control = splitControls[order] || splitControls.find((item) => item.index === Number(point.split_control_index));
        if (!control || !Number.isFinite(order)) {
          return null;
        }
        return {point, trackIndex, control, order};
      })
      .filter(Boolean)
      .sort((a, b) => a.order - b.order);
  }

  function hasSplitMarkers() {
    return trackPoints.some((point) => Number.isFinite(Number(point.split_control_order)));
  }

  function hasCompleteSplitMarkers() {
    const expectedCount = courseControls.filter((control) => control.kind !== "start-point").length;
    const orders = new Set(
      trackPoints
        .map((point) => Number(point.split_control_order))
        .filter((order) => Number.isFinite(order))
    );
    return expectedCount > 0 && orders.size >= expectedCount;
  }

  function splitMarkerLimits(order) {
    return splitMarkerLimitsForOrder(order);
  }

  function nearestTrackIndexToPixel(pixel, minIndex, maxIndex) {
    let best = null;
    for (let index = minIndex; index <= maxIndex; index += 1) {
      const point = trackPoints[index];
      if (!point?.pixel) {
        continue;
      }
      const dx = point.pixel.pixel_x - pixel.pixel_x;
      const dy = point.pixel.pixel_y - pixel.pixel_y;
      const distance = dx * dx + dy * dy;
      if (!best || distance < best.distance) {
        best = {index, distance};
      }
    }
    return best ? best.index : null;
  }

  function updateSplitsStatus() {
    if (!splitsStatus) {
      return;
    }
    if (!trackPoints.length) {
      splitsStatus.textContent = "После загрузки GPX здесь появятся точки нарезки по КП.";
      return;
    }
    const markers = getSplitMarkers();
    const rows = splitsEngine.calculateSplits(courseControls, trackPoints);
    if (!markers.length || !rows.length) {
      splitsStatus.textContent = "Не удалось автоматически нарезать трек: проверьте КП и GPX.";
      return;
    }
    splitsStatus.textContent = `Нарезка: ${rows.length} отрезков, ${markers.length} точек на треке. Активный слой: ${activeLayer?.title || "карта"}.`;
  }

  async function persistDraftTrackPoints(delayMs) {
    if (persistTimer) {
      clearTimeout(persistTimer);
    }
    persistTimer = setTimeout(async () => {
      persistTimer = null;
      await saveDraftTrackPointsNow();
    }, delayMs);
  }

  async function saveDraftTrackPointsNow() {
    await fetch(`/api/imports/${draftId}/track-points`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({track_points: trackPoints.map(serializedTrackPoint)}),
    });
  }

  function normalizeTrackPoints(points) {
    return points.map((point, index) => ({
      ...point,
      pixel: transform ? geoToPixel(point) : {pixel_x: 0, pixel_y: 0},
      seconds: splitsEngine.parsePointSeconds(point, index),
    }));
  }

  function normalizeMapLayers(layers) {
    if (!Array.isArray(layers) || !layers.length) {
      return [{id: "map-1", title: "Карта 1", course_controls: []}];
    }
    return layers.map((layer, index) => ({
      ...layer,
      id: layer.id || `map-${index + 1}`,
      title: layer.title || `Карта ${index + 1}`,
      course_controls: Array.isArray(layer.course_controls) ? layer.course_controls : [],
    }));
  }

  function normalizeAllCourseControls() {
    const controls = [];
    mapLayers.forEach((layer) => {
      layer.course_controls.forEach((control) => {
        controls.push({...control, map_layer_id: control.map_layer_id || layer.id});
      });
    });
    return splitsEngine.normalizeCourseControls(controls, {trainingType});
  }

  function activeCourseControls() {
    return courseControls.filter((control) => control.map_layer_id === activeLayerId);
  }

  function activeLayerTrackPoints() {
    return trackPoints;
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
    for (const key of ["split_control_index", "split_control_label", "split_control_kind", "split_control_order"]) {
      if (point[key] !== null && typeof point[key] !== "undefined") {
        payload[key] = point[key];
      }
    }
    return payload;
  }

  function createFallbackSplitsEngine() {
    return {
      normalizeCourseControls(controls, options = {}) {
        const rogaine = options.isRogaine === true || options.trainingType === "rogaine";
        return controls.map((control, index) => ({
          ...control,
          index: index + 1,
          label: control.label || fallbackCourseControlLabel(index, controls.length, rogaine),
          kind: control.kind || fallbackCourseControlKind(index, controls.length, rogaine),
        }));
      },
      calculateSplits(controls, points) {
        const splitControls = controls.filter((control) => control.kind !== "start-point");
        if (splitControls.length < 2 || points.length < 2) {
          return [];
        }
        const rows = [];
        let previousControl = splitControls[0];
        let previousMatch = fallbackFindClosestTrackPoint(points, previousControl, 0, fallbackStartSearchEndIndex(points));
        if (!previousMatch) {
          return [];
        }
        const startSeconds = previousMatch.seconds;
        let previousAbsoluteSeconds = 0;
        for (const control of splitControls.slice(1)) {
          const match = fallbackFindClosestTrackPoint(points, control, previousMatch.index + 1);
          if (!match) {
            break;
          }
          const absoluteSeconds = Math.max(match.seconds - startSeconds, 0);
          rows.push({
            label: control.label || String(control.index),
            absoluteSeconds,
            splitSeconds: Math.max(absoluteSeconds - previousAbsoluteSeconds, 0),
            fromControl: previousControl,
            toControl: control,
            fromTrackIndex: previousMatch.index,
            toTrackIndex: match.index,
          });
          previousControl = control;
          previousMatch = match;
          previousAbsoluteSeconds = absoluteSeconds;
        }
        return rows;
      },
      parsePointSeconds(point, index) {
        return fallbackParsePointSeconds(point, index);
      },
    };
  }

  function fallbackCourseControlLabel(index, total, rogaine) {
    if (index === 0) {
      return "С";
    }
    if (!rogaine && total > 2 && index === 1) {
      return "К";
    }
    if (total > 1 && index === total - 1) {
      return "Ф";
    }
    return String(rogaine ? index : index - 1);
  }

  function fallbackCourseControlKind(index, total, rogaine) {
    if (index === 0) {
      return "start";
    }
    if (!rogaine && total > 2 && index === 1) {
      return "start-point";
    }
    if (total > 1 && index === total - 1) {
      return "finish";
    }
    return "control";
  }

  function fallbackFindClosestTrackPoint(points, control, startIndex, endIndex = points.length) {
    let best = null;
    for (let index = startIndex; index < endIndex; index += 1) {
      const point = points[index];
      const dx = point.lat - control.lat;
      const dy = point.lon - control.lon;
      const distance = dx * dx + dy * dy;
      if (!best || distance < best.distance) {
        best = {
          index,
          distance,
          seconds: point.seconds ?? fallbackParsePointSeconds(point, index),
        };
      }
    }
    return best;
  }

  function fallbackStartSearchEndIndex(points) {
    const firstSeconds = points[0]?.seconds ?? fallbackParsePointSeconds(points[0] || {}, 0);
    const fallbackEndIndex = Math.max(1, Math.ceil(points.length * 0.1));
    for (let index = 1; index < points.length; index += 1) {
      const seconds = points[index].seconds ?? fallbackParsePointSeconds(points[index], index);
      if (seconds - firstSeconds > 300) {
        return Math.max(1, Math.min(index, fallbackEndIndex));
      }
    }
    return fallbackEndIndex;
  }

  function fallbackParsePointSeconds(point, index) {
    if (point?.time) {
      const timestamp = Date.parse(point.time);
      if (!Number.isNaN(timestamp)) {
        return timestamp / 1000;
      }
    }
    return index;
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

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function stopViewportGestures(node) {
    if (!node) {
      return;
    }
    ["pointerdown", "pointermove", "pointerup", "pointercancel", "wheel"].forEach((eventName) => {
      node.addEventListener(eventName, (event) => {
        event.stopPropagation();
      });
    });
  }
})();
