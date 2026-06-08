(function (root) {
  const modal = document.querySelector("#split-view-modal");
  if (!modal) {
    return;
  }

  const title = document.querySelector("#split-view-title");
  const summary = document.querySelector("#split-view-summary");
  const stageLabel = document.querySelector("#split-view-stage");
  const viaLabel = document.querySelector("#split-view-via");
  const distanceLabel = document.querySelector("#split-view-distance");
  const svg = document.querySelector("#split-view-svg");
  const closeButton = document.querySelector("#split-view-close");

  let active = null;
  const layerImageCache = new Map();

  closeButton?.addEventListener("click", close);
  modal.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.matches("[data-close-split-view]")) {
      close();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      close();
    }
  });

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
    const mapLayers = normalizeMapLayers(options.mapLayers);
    const mapLayer = splitMapLayer(options.row, mapLayers);
    const image = await imageForLayer(mapLayer, options.image);
    active = {
      row: options.row,
      image,
      mapLayerId: mapLayer?.id || null,
    };
    if (title) {
      title.textContent = `Сплит ${active.row.label}`;
    }
    if (summary) {
      summary.textContent = `${active.row.fromControl.label} → ${active.row.toControl.label}`;
    }
    if (stageLabel) {
      stageLabel.textContent = `${active.row.fromControl.label} → ${active.row.toControl.label}`;
    }
    if (viaLabel) {
      viaLabel.textContent = active.row.viaControls.length
        ? active.row.viaControls.map((control) => control.label).join(", ")
        : "без промежуточных КП";
    }
    if (distanceLabel) {
      const distance = stageDistanceMeters(active.row.fromControl, active.row.viaControls, active.row.toControl);
      distanceLabel.textContent = formatDistance(distance);
    }
    renderMap();
    modal.hidden = false;
    document.body.classList.add("modal-open");
    closeButton?.focus();
  }

  function close() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
    active = null;
  }

  function renderMap() {
    if (!active || !svg) {
      return;
    }
    const image = active.image;
    const coursePoints = splitCoursePoints(active.row);
    const focusPoints = coursePoints.map(controlPixel);
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
    if (coursePoints.length >= 2) {
      addPolyline(coursePoints.map(controlPixel), "split-view-line");
    }
    coursePoints.forEach((control, index) => {
      addControlMarker(control, index === 0 ? "from" : index === coursePoints.length - 1 ? "to" : "via");
    });
  }

  function appendArrowMarker() {
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
    marker.setAttribute("id", "split-view-arrow-head");
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
    if (className === "split-view-line") {
      addPolylineOutline(points, className);
    }
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke-linecap", "round");
    polyline.setAttribute("stroke-linejoin", "round");
    polyline.setAttribute("class", className);
    polyline.setAttribute("marker-end", "url(#split-view-arrow-head)");
    svg.appendChild(polyline);
  }

  function addPolylineOutline(points, className) {
    const outline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    outline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    outline.setAttribute("fill", "none");
    outline.setAttribute("stroke-linecap", "round");
    outline.setAttribute("stroke-linejoin", "round");
    outline.setAttribute("class", `${className} ${className}-outline`);
    svg.appendChild(outline);
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

  function splitCoursePoints(row) {
    const points = [row.fromControl, ...(Array.isArray(row.viaControls) ? row.viaControls : []), row.toControl]
      .filter(Boolean);
    if (!active?.mapLayerId) {
      return points;
    }
    const layerPoints = points.filter((control) => (control.map_layer_id || active.mapLayerId) === active.mapLayerId);
    return layerPoints.length ? layerPoints : points;
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
      .map((layer, index) => ({...layer, id: layer.id || `map-${index + 1}`}));
  }

  function splitMapLayer(row, mapLayers) {
    if (!mapLayers.length) {
      return null;
    }
    const preferredLayerId =
      row?.toControl?.map_layer_id ||
      row?.viaControls?.find((control) => control?.map_layer_id)?.map_layer_id ||
      row?.fromControl?.map_layer_id ||
      null;
    return mapLayers.find((layer) => layer.id === preferredLayerId)
      || mapLayers.find((layer) => layer.map_image_url)
      || mapLayers[0]
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
    return fallbackImage;
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const nextImage = new Image();
      nextImage.onload = () => resolve(nextImage);
      nextImage.onerror = () => reject(new Error("Не удалось подготовить картинку сплита"));
      nextImage.src = src;
    });
  }

  function stageDistanceMeters(fromControl, viaControls, toControl) {
    const controls = [fromControl, ...viaControls, toControl];
    let total = 0;
    for (let index = 1; index < controls.length; index += 1) {
      total += haversineMeters(controls[index - 1], controls[index]);
    }
    return total;
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

  function formatDistance(meters) {
    if (meters < 1000) {
      return `${Math.round(meters)} м`;
    }
    return `${(meters / 1000).toFixed(2)} км`;
  }

  function toRadians(value) {
    return value * Math.PI / 180;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  root.SplitViewDialog = {open, close};
})(typeof globalThis !== "undefined" ? globalThis : window);
