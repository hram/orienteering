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

  function open(options) {
    if (!options?.row || !options?.image || !svg) {
      return;
    }
    if (!options.image.complete || !options.image.naturalWidth || !options.image.naturalHeight) {
      options.image.addEventListener("load", () => open(options), {once: true});
      return;
    }
    active = {
      row: options.row,
      image: options.image,
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
    const coursePoints = [active.row.fromControl, ...active.row.viaControls, active.row.toControl];
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
    path.setAttribute("fill", "#b21f5b");
    marker.appendChild(path);
    defs.appendChild(marker);
    svg.appendChild(defs);
  }

  function addPolyline(points, className) {
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", points.map((point) => `${point.pixel_x},${point.pixel_y}`).join(" "));
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke-linecap", "round");
    polyline.setAttribute("stroke-linejoin", "round");
    polyline.setAttribute("class", className);
    polyline.setAttribute("marker-end", "url(#split-view-arrow-head)");
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
