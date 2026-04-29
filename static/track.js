(function () {
  const workspace = document.querySelector("#track-workspace");
  if (!workspace) {
    return;
  }

  const draftId = workspace.dataset.draftId;
  const uploadForm = document.querySelector("#track-upload-form");
  const status = document.querySelector("#track-status");
  const image = document.querySelector("#track-map-image");
  const svg = document.querySelector("#track-image-svg");
  const viewport = document.querySelector("#track-image-viewport");
  const content = document.querySelector("#track-image-content");

  const transform = parseJson(workspace.dataset.transform, null);
  const courseControls = normalizeCourseControls(parseJson(workspace.dataset.courseControls, []));
  let trackPoints = parseJson(workspace.dataset.trackPoints, []);
  let view = {scale: 1, translateX: 0, translateY: 0};
  let drag = null;

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
    trackPoints = payload.track_points;
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

  drawAll();

  function drawAll() {
    drawImageTrack();
    if (status) {
      status.textContent = trackPoints.length
        ? `Точек трека: ${trackPoints.length}.`
        : "Загрузите GPX.";
    }
  }

  function drawImageTrack() {
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

    courseControls.forEach((control) => {
      addControlMarker(control);
    });

    if (trackPoints.length) {
      addPolyline(trackPoints.map(geoToPixel), "track-line");
    }
  }

  function addPolyline(points, className) {
    if (points.length < 2) {
      return;
    }
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

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }
})();
