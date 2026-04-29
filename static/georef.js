(function () {
  const workspace = document.querySelector("#georef-workspace");
  if (!workspace) {
    return;
  }

  const draftId = workspace.dataset.draftId;
  const uploadForm = document.querySelector("#map-upload-form");
  const image = document.querySelector("#map-image");
  const imageStage = document.querySelector(".image-stage");
  const imageViewport = document.querySelector("#image-viewport");
  const imageContent = document.querySelector("#image-content");
  const pointList = document.querySelector("#control-point-list");
  const courseControlList = document.querySelector("#course-control-list");
  const result = document.querySelector("#georef-result");
  const courseResult = document.querySelector("#course-result");
  const undoButton = document.querySelector("#undo-point");
  const saveButton = document.querySelector("#save-georef");
  const undoCourseControlButton = document.querySelector("#undo-course-control");
  const saveCourseControlsButton = document.querySelector("#save-course-controls");
  const overlayOpacity = document.querySelector("#overlay-opacity");
  const imagePointLabel = document.querySelector("#image-point-label");
  const geoPointLabel = document.querySelector("#geo-point-label");
  const modeTabs = Array.from(document.querySelectorAll(".mode-tab"));
  const modePanels = Array.from(document.querySelectorAll(".mode-panel"));
  const modeActions = Array.from(document.querySelectorAll(".mode-actions"));

  let points = parseExistingPoints(workspace.dataset.existingPoints);
  let courseControls = parseExistingPoints(workspace.dataset.existingCourseControls);
  let pendingPixel = null;
  let leafletMap = null;
  let geoMarkers = [];
  let courseMarkers = [];
  let courseLine = null;
  let fittingPreview = false;
  let currentMode = "georef";
  let currentTransform = parseExistingObject(workspace.dataset.existingTransform);
  let overlayImage = null;
  let imageView = {
    scale: 1,
    translateX: 0,
    translateY: 0,
  };
  let imageDrag = null;

  renumberCourseControls();

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(uploadForm);
    result.textContent = "Загружаю карту...";

    const response = await fetch(`/api/imports/${draftId}/map-image`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      result.textContent = await response.text();
      return;
    }

    window.location.reload();
  });

  if (image) {
    image.addEventListener("load", () => {
      fitImageToViewport();
      drawImageMarkers();
    });
    if (image.complete) {
      fitImageToViewport();
    }
  }

  imageViewport?.addEventListener("wheel", (event) => {
    if (!image) {
      return;
    }
    event.preventDefault();
    const pointer = clientPointToViewportPoint(event.clientX, event.clientY);
    const before = viewportPointToImagePixel(pointer.x, pointer.y);
    const zoomFactor = event.deltaY < 0 ? 1.18 : 1 / 1.18;
    imageView.scale = clamp(imageView.scale * zoomFactor, 0.15, 8);
    imageView.translateX = pointer.x - before.pixel_x * imageView.scale;
    imageView.translateY = pointer.y - before.pixel_y * imageView.scale;
    applyImageView();
  }, {passive: false});

  imageViewport?.addEventListener("pointerdown", (event) => {
    if (!image) {
      return;
    }
    imageViewport.setPointerCapture(event.pointerId);
    imageDrag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      translateX: imageView.translateX,
      translateY: imageView.translateY,
      moved: false,
    };
    imageViewport.classList.add("dragging");
  });

  imageViewport?.addEventListener("pointermove", (event) => {
    if (!imageDrag || imageDrag.pointerId !== event.pointerId) {
      return;
    }
    const deltaX = event.clientX - imageDrag.startX;
    const deltaY = event.clientY - imageDrag.startY;
    if (Math.abs(deltaX) + Math.abs(deltaY) > 3) {
      imageDrag.moved = true;
    }
    imageView.translateX = imageDrag.translateX + deltaX;
    imageView.translateY = imageDrag.translateY + deltaY;
    applyImageView();
  });

  imageViewport?.addEventListener("pointerup", (event) => {
    const wasClick = imageDrag && !imageDrag.moved;
    finishImageDrag(event);
    if (!wasClick || !image) {
      return;
    }
    const pixel = clientPointToImagePixel(event.clientX, event.clientY);
    if (!isPixelInsideImage(pixel)) {
      return;
    }
    if (currentMode === "course") {
      addCourseControl(pixel);
      return;
    }
    pendingPixel = pixel;
    drawImageMarkers();
    imagePointLabel.textContent = formatPixel(pendingPixel);
    geoPointLabel.textContent = "Кликните ту же точку на базовой карте";
  });
  imageViewport?.addEventListener("pointercancel", finishImageDrag);

  undoButton?.addEventListener("click", () => {
    points.pop();
    pendingPixel = null;
    drawAll();
  });

  undoCourseControlButton?.addEventListener("click", () => {
    courseControls.pop();
    drawAll();
  });

  saveButton?.addEventListener("click", async () => {
    if (points.length < 3) {
      result.textContent = "Нужно минимум 3 контрольные точки.";
      return;
    }

    const response = await fetch(`/api/imports/${draftId}/georef`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({control_points: points}),
    });

    if (!response.ok) {
      result.textContent = await response.text();
      return;
    }

    const payload = await response.json();
    currentTransform = payload.transform;
    updateMapOverlay();
    result.textContent = `Сохранено. Максимальная ошибка: ${payload.max_residual_meters.toFixed(1)} м.`;
    updateCourseModeAvailability();
  });

  saveCourseControlsButton?.addEventListener("click", async () => {
    if (!currentTransform) {
      courseResult.textContent = "Сначала сохраните привязку карты.";
      return;
    }

    const response = await fetch(`/api/imports/${draftId}/course-controls`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({controls: normalizedCourseControls()}),
    });

    if (!response.ok) {
      courseResult.textContent = await response.text();
      return;
    }

    courseResult.textContent = `Сохранено КП: ${courseControls.length}.`;
  });

  overlayOpacity?.addEventListener("input", () => {
    updateOverlayOpacity();
  });

  modeTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      setMode(tab.dataset.mode);
    });
  });

  initBaseMap();
  updateCourseModeAvailability();
  drawAll();

  function initBaseMap() {
    const mapNode = document.querySelector("#base-map");
    if (!mapNode || typeof L === "undefined") {
      if (result) {
        result.textContent = "Базовая карта не загрузилась.";
      }
      return;
    }

    leafletMap = L.map(mapNode, {zoomControl: true}).setView([55.751244, 37.618423], 10);
    const streetLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    });
    const satelliteLayer = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        maxZoom: 19,
        attribution:
          "Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community",
      }
    );

    streetLayer.addTo(leafletMap);
    L.control.layers(
      {
        "Карта": streetLayer,
        "Спутник": satelliteLayer,
      },
      {},
      {position: "topright", collapsed: false}
    ).addTo(leafletMap);

    leafletMap.on("zoom move resize", () => {
      updateMapOverlay();
    });

    leafletMap.on("click", (event) => {
      if (!pendingPixel) {
        geoPointLabel.textContent = "Сначала кликните точку на картинке";
        return;
      }

      points.push({
        ...pendingPixel,
        lat: event.latlng.lat,
        lon: event.latlng.lng,
      });
      pendingPixel = null;
      imagePointLabel.textContent = "Кликните по следующему ориентиру";
      geoPointLabel.textContent = "Затем кликните ту же точку здесь";
      drawAll();
      fitPreview();
    });
  }

  async function fitPreview() {
    if (fittingPreview) {
      return;
    }
    if (points.length < 3) {
      result.textContent = "Нужно минимум 3 точки.";
      return;
    }
    fittingPreview = true;

    try {
      const response = await fetch("/api/georef/fit", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({control_points: points}),
      });

      if (!response.ok) {
        result.textContent = "Точки выстроены неудачно. Нужны ориентиры не на одной линии.";
        return;
      }

      const payload = await response.json();
      currentTransform = payload.transform;
      updateMapOverlay();
      result.textContent = `Предпросмотр: максимальная ошибка ${payload.max_residual_meters.toFixed(1)} м.`;
    } finally {
      fittingPreview = false;
    }
  }

  function drawAll() {
    drawImageMarkers();
    drawGeoMarkers();
    drawCourseMarkers();
    renderPointList();
    renderCourseControlList();
    if (points.length < 3) {
      result.textContent = `Добавлено точек: ${points.length}. Нужно минимум 3.`;
    } else {
      fitPreview();
    }
  }

  function drawImageMarkers() {
    imageStage?.querySelectorAll(".image-marker").forEach((marker) => marker.remove());
    if (!image) {
      return;
    }

    points.forEach((point, index) => {
      addImageMarker(point.pixel_x, point.pixel_y, String(index + 1), false, "georef");
    });

    if (pendingPixel) {
      addImageMarker(pendingPixel.pixel_x, pendingPixel.pixel_y, "+", true, "georef");
    }

    courseControls.forEach((control) => {
      addImageMarker(control.pixel_x, control.pixel_y, courseControlDisplayLabel(control), false, "course");
    });
  }

  function addImageMarker(pixelX, pixelY, label, pending, kind) {
    const marker = document.createElement("span");
    marker.className = `image-marker ${kind}${pending ? " pending" : ""}`;
    marker.style.left = `${pixelX}px`;
    marker.style.top = `${pixelY}px`;
    marker.textContent = label;
    imageContent.appendChild(marker);
  }

  function drawGeoMarkers() {
    if (!leafletMap) {
      return;
    }
    geoMarkers.forEach((marker) => marker.remove());
    geoMarkers = points.map((point, index) => {
      const marker = L.marker([point.lat, point.lon], {draggable: true})
        .addTo(leafletMap)
        .bindTooltip(String(index + 1), {permanent: true, direction: "top", offset: [0, -12]});
      marker.on("dragend", () => {
        const latLng = marker.getLatLng();
        points[index] = {
          ...points[index],
          lat: latLng.lat,
          lon: latLng.lng,
        };
        renderPointList();
        fitPreview();
      });
      return marker;
    });
    if (points.length > 0) {
      const bounds = L.latLngBounds(points.map((point) => [point.lat, point.lon]));
      leafletMap.fitBounds(bounds.pad(0.25), {maxZoom: 16});
    }
  }

  function drawCourseMarkers() {
    if (!leafletMap) {
      return;
    }
    courseMarkers.forEach((marker) => marker.remove());
    courseMarkers = courseControls.map((control) => {
      return L.circleMarker([control.lat, control.lon], {
        radius: 7,
        color: "#ffffff",
        weight: 2,
        fillColor: "#b21f5b",
        fillOpacity: 1,
      })
        .addTo(leafletMap)
        .bindTooltip(courseControlDisplayLabel(control), {permanent: true, direction: "top", offset: [0, -8]});
    });

    if (courseLine) {
      courseLine.remove();
      courseLine = null;
    }
    if (courseControls.length >= 2) {
      courseLine = L.polyline(
        courseControls.map((control) => [control.lat, control.lon]),
        {color: "#b21f5b", weight: 3, opacity: 0.9}
      ).addTo(leafletMap);
    }
  }

  function updateMapOverlay() {
    if (!leafletMap || !image || !currentTransform) {
      removeMapOverlay();
      return;
    }

    if (!image.complete || image.naturalWidth === 0 || image.naturalHeight === 0) {
      image.addEventListener("load", updateMapOverlay, {once: true});
      return;
    }

    if (!overlayImage) {
      overlayImage = document.createElement("img");
      overlayImage.className = "georef-map-overlay";
      overlayImage.src = image.src;
      overlayImage.alt = "";
      overlayImage.width = image.naturalWidth;
      overlayImage.height = image.naturalHeight;
      leafletMap.getPanes().overlayPane.appendChild(overlayImage);
      updateOverlayOpacity();
    }

    const width = image.naturalWidth;
    const height = image.naturalHeight;
    const topLeft = layerPointForImagePixel(0, 0);
    const topRight = layerPointForImagePixel(width, 0);
    const bottomLeft = layerPointForImagePixel(0, height);

    const a = (topRight.x - topLeft.x) / width;
    const b = (topRight.y - topLeft.y) / width;
    const c = (bottomLeft.x - topLeft.x) / height;
    const d = (bottomLeft.y - topLeft.y) / height;
    const e = topLeft.x;
    const f = topLeft.y;

    overlayImage.style.width = `${width}px`;
    overlayImage.style.height = `${height}px`;
    overlayImage.style.transform = `matrix(${a}, ${b}, ${c}, ${d}, ${e}, ${f})`;
  }

  function removeMapOverlay() {
    overlayImage?.remove();
    overlayImage = null;
  }

  function updateOverlayOpacity() {
    if (!overlayImage || !overlayOpacity) {
      return;
    }
    overlayImage.style.opacity = String(Number(overlayOpacity.value) / 100);
  }

  function layerPointForImagePixel(pixelX, pixelY) {
    const latLng = pixelToLatLng(pixelX, pixelY);
    return leafletMap.latLngToLayerPoint(latLng);
  }

  function pixelToLatLng(pixelX, pixelY) {
    const lon =
      currentTransform.lon_a * pixelX +
      currentTransform.lon_b * pixelY +
      currentTransform.lon_c;
    const lat =
      currentTransform.lat_a * pixelX +
      currentTransform.lat_b * pixelY +
      currentTransform.lat_c;
    return L.latLng(lat, lon);
  }

  function renderPointList() {
    if (!pointList) {
      return;
    }
    pointList.innerHTML = "";
    points.forEach((point, index) => {
      const item = document.createElement("li");
      const text = document.createElement("span");
      text.textContent = `${index + 1}. ${formatPixel(point)} -> ${point.lat.toFixed(6)}, ${point.lon.toFixed(6)}`;

      const removeButton = document.createElement("button");
      removeButton.className = "icon-button danger";
      removeButton.type = "button";
      removeButton.setAttribute("aria-label", `Удалить точку ${index + 1}`);
      removeButton.title = "Удалить точку";
      removeButton.textContent = "×";
      removeButton.addEventListener("click", () => {
        points.splice(index, 1);
        pendingPixel = null;
        drawAll();
      });

      item.append(text, removeButton);
      pointList.appendChild(item);
    });
  }

  function renderCourseControlList() {
    if (!courseControlList) {
      return;
    }
    courseControlList.innerHTML = "";
    courseControls.forEach((control, index) => {
      const item = document.createElement("li");
      const text = document.createElement("span");
      text.textContent = `${courseControlDisplayLabel(control)}. ${formatPixel(control)} -> ${control.lat.toFixed(6)}, ${control.lon.toFixed(6)}`;

      const removeButton = document.createElement("button");
      removeButton.className = "icon-button danger";
      removeButton.type = "button";
      removeButton.setAttribute("aria-label", `Удалить точку маршрута ${courseControlDisplayLabel(control)}`);
      removeButton.title = "Удалить КП";
      removeButton.textContent = "×";
      removeButton.addEventListener("click", () => {
        courseControls.splice(index, 1);
        renumberCourseControls();
        drawAll();
      });

      item.append(text, removeButton);
      courseControlList.appendChild(item);
    });

    if (courseResult) {
      if (!currentTransform) {
        courseResult.textContent = "Сначала сохраните привязку карты.";
      } else {
        courseResult.textContent = routeSummaryText();
      }
    }
  }

  function addCourseControl(pixel) {
    if (!currentTransform) {
      courseResult.textContent = "Сначала сохраните привязку карты.";
      return;
    }
    const latLng = pixelToLatLng(pixel.pixel_x, pixel.pixel_y);
    courseControls.push({
      pixel_x: pixel.pixel_x,
      pixel_y: pixel.pixel_y,
      lat: latLng.lat,
      lon: latLng.lng,
    });
    renumberCourseControls();
    drawAll();
  }

  function setMode(mode) {
    currentMode = mode === "course" ? "course" : "georef";
    modeTabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.mode === currentMode);
    });
    modePanels.forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.panel === currentMode);
    });
    modeActions.forEach((actions) => {
      actions.classList.toggle("active", actions.dataset.actions === currentMode);
    });
    pendingPixel = null;
    drawImageMarkers();
    imagePointLabel.textContent = currentMode === "course"
      ? "Кликните по КП на картинке"
      : "Кликните по ориентиру";
    geoPointLabel.textContent = currentMode === "course"
      ? "КП автоматически появится на базовой карте"
      : "Затем кликните ту же точку здесь";
  }

  function updateCourseModeAvailability() {
    const courseTab = modeTabs.find((tab) => tab.dataset.mode === "course");
    if (!courseTab) {
      return;
    }
    courseTab.disabled = !currentTransform;
  }

  function normalizedCourseControls() {
    return courseControls.map((control, index) => ({
      index: index + 1,
      label: courseControlLabel(index, courseControls.length),
      kind: courseControlKind(index, courseControls.length),
      pixel_x: control.pixel_x,
      pixel_y: control.pixel_y,
      lat: control.lat,
      lon: control.lon,
    }));
  }

  function renumberCourseControls() {
    courseControls = normalizedCourseControls();
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

  function courseControlDisplayLabel(control) {
    return control.label || String(control.index);
  }

  function routeSummaryText() {
    const officialControls = Math.max(courseControls.length - 3, 0);
    return `Маршрут: старт, пункт К, КП ${officialControls}, финиш.`;
  }

  function parseExistingPoints(rawValue) {
    if (!rawValue) {
      return [];
    }
    try {
      const parsed = JSON.parse(rawValue);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function parseExistingObject(rawValue) {
    if (!rawValue || rawValue === "null") {
      return null;
    }
    try {
      return JSON.parse(rawValue);
    } catch (_error) {
      return null;
    }
  }

  function formatPixel(point) {
    return `x ${Math.round(point.pixel_x)}, y ${Math.round(point.pixel_y)}`;
  }

  function fitImageToViewport() {
    if (!image || !imageViewport || !imageContent || image.naturalWidth === 0 || image.naturalHeight === 0) {
      return;
    }
    const rect = imageViewport.getBoundingClientRect();
    const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight, 1);
    imageView.scale = clamp(scale, 0.15, 8);
    imageView.translateX = Math.max((rect.width - image.naturalWidth * imageView.scale) / 2, 0);
    imageView.translateY = Math.max((rect.height - image.naturalHeight * imageView.scale) / 2, 0);
    imageContent.style.width = `${image.naturalWidth}px`;
    imageContent.style.height = `${image.naturalHeight}px`;
    applyImageView();
  }

  function applyImageView() {
    if (!imageContent) {
      return;
    }
    imageContent.style.transform = `translate(${imageView.translateX}px, ${imageView.translateY}px) scale(${imageView.scale})`;
  }

  function finishImageDrag(event) {
    if (!imageDrag || imageDrag.pointerId !== event.pointerId) {
      return;
    }
    imageViewport?.releasePointerCapture(event.pointerId);
    imageViewport?.classList.remove("dragging");
    imageDrag = null;
  }

  function clientPointToImagePixel(clientX, clientY) {
    const viewportPoint = clientPointToViewportPoint(clientX, clientY);
    return viewportPointToImagePixel(viewportPoint.x, viewportPoint.y);
  }

  function clientPointToViewportPoint(clientX, clientY) {
    const rect = imageViewport.getBoundingClientRect();
    return {
      x: clientX - rect.left,
      y: clientY - rect.top,
    };
  }

  function viewportPointToImagePixel(x, y) {
    return {
      pixel_x: (x - imageView.translateX) / imageView.scale,
      pixel_y: (y - imageView.translateY) / imageView.scale,
    };
  }

  function isPixelInsideImage(point) {
    return (
      point.pixel_x >= 0 &&
      point.pixel_y >= 0 &&
      point.pixel_x <= image.naturalWidth &&
      point.pixel_y <= image.naturalHeight
    );
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }
})();
