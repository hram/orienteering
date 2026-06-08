(function () {
  const workspace = document.querySelector("#georef-workspace");
  if (!workspace) {
    return;
  }

  const draftId = workspace.dataset.draftId;
  let activeLayerId = workspace.dataset.activeLayerId || "map-1";
  const isRogaine = workspace.dataset.trainingType === "rogaine";
  const uploadForm = document.querySelector("#map-upload-form");
  const addLayerForm = document.querySelector("#add-map-layer-form");
  const image = document.querySelector("#map-image");
  const emptyStage = document.querySelector("#map-empty-stage");
  const imageStage = document.querySelector(".image-stage");
  const imageViewport = document.querySelector("#image-viewport");
  const imageContent = document.querySelector("#image-content");
  const pointList = document.querySelector("#control-point-list");
  const courseControlList = document.querySelector("#course-control-list");
  const result = document.querySelector("#georef-result");
  const courseResult = document.querySelector("#course-result");
  const uploadStatus = document.querySelector("#map-upload-status");
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
  const layerTabsContainer = document.querySelector(".map-layer-tabs");
  let layerTabs = Array.from(document.querySelectorAll(".map-layer-tab"));

  let mapLayers = normalizeMapLayers(parseExistingObject(workspace.dataset.mapLayers));
  let activeLayer = findMapLayer(activeLayerId) || mapLayers[0];
  activeLayerId = activeLayer.id;
  let points = [];
  let courseControls = [];
  let pendingPixel = null;
  let leafletMap = null;
  let geoMarkers = [];
  let courseMarkers = [];
  let courseLine = [];
  let fittingPreview = false;
  let currentMode = activeLayer.map_image_url ? "georef" : "file";
  let currentTransform = null;
  let overlayImage = null;
  let imageView = {
    scale: 1,
    translateX: 0,
    translateY: 0,
  };
  let imageDrag = null;

  loadActiveLayerState({preserveMode: false});
  bindLayerTabs();
  stopViewportGestures(layerTabsContainer);

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    storeActiveLayerState();
    const formData = new FormData(uploadForm);
    setUploadStatus("Загружаю карту...");

    const response = await fetch(`/api/imports/${draftId}/map-layers/${activeLayerId}/map-image`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      setUploadStatus(await response.text());
      return;
    }

    const payload = await response.json();
    mergeServerMapLayers(payload.draft?.map_layers || [], {preserveActiveLocal: true});
    activeLayer = findMapLayer(activeLayerId) || activeLayer;
    loadActiveLayerState({preserveMode: false});
    resetUploadForm();
    setUploadStatus("Картинка карты загружена.");
  });

  addLayerForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    storeActiveLayerState();
    const response = await fetch(`/api/imports/${draftId}/map-layers`, {method: "POST"});
    if (!response.ok) {
      setUploadStatus(await response.text());
      return;
    }
    const payload = await response.json();
    mergeServerMapLayers(payload.draft?.map_layers || [], {preserveActiveLocal: true});
    renderLayerTabs();
    setActiveLayer(payload.layer?.id || mapLayers.at(-1)?.id || activeLayerId);
  });

  if (image) {
    image.addEventListener("load", () => {
      fitImageToViewport();
      drawImageMarkers();
      updateMapOverlay();
    });
    if (image.complete) {
      fitImageToViewport();
    }
  }

  imageViewport?.addEventListener("wheel", (event) => {
    if (!activeLayer.map_image_url || !image) {
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
    if (!activeLayer.map_image_url || !image) {
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
    if (!wasClick || !activeLayer.map_image_url || !image) {
      return;
    }
    const pixel = clientPointToImagePixel(event.clientX, event.clientY);
    if (!isPixelInsideImage(pixel)) {
      return;
    }
    if (currentMode === "file") {
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

    const response = await fetch(`/api/imports/${draftId}/map-layers/${activeLayerId}/georef`, {
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
    storeActiveLayerState();
    updateMapOverlay();
    result.textContent = `Сохранено. Максимальная ошибка: ${payload.max_residual_meters.toFixed(1)} м.`;
    updateCourseModeAvailability();
  });

  saveCourseControlsButton?.addEventListener("click", async () => {
    if (!currentTransform) {
      courseResult.textContent = "Сначала сохраните привязку карты.";
      return;
    }

    storeActiveLayerState();
    let savedCount = 0;
    let latestPayload = null;
    for (const layer of mapLayers) {
      const controls = parseExistingPoints(layer.course_controls);
      if (!controls.length && layer.id !== activeLayerId) {
        continue;
      }
      const response = await fetch(`/api/imports/${draftId}/map-layers/${layer.id}/course-controls`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({controls}),
      });

      if (!response.ok) {
        courseResult.textContent = await response.text();
        return;
      }
      savedCount += controls.length;
      latestPayload = await response.json();
    }

    mergeServerMapLayers(latestPayload?.draft?.map_layers || [], {preserveActiveLocal: true});
    activeLayer = findMapLayer(activeLayerId) || activeLayer;
    courseControls = parseExistingPoints(activeLayer.course_controls);
    renumberCourseControls();
    courseResult.textContent = `Сохранено КП: ${savedCount}.`;
    drawAll();
  });

  overlayOpacity?.addEventListener("input", () => {
    updateOverlayOpacity();
  });

  modeTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      setMode(tab.dataset.mode);
    });
  });

  setMode(currentMode);
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
      if (currentMode === "file") {
        return;
      }
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

  function bindLayerTabs() {
    layerTabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        setActiveLayer(tab.dataset.layerId || "map-1");
      });
    });
  }

  function setActiveLayer(layerId) {
    const nextLayer = findMapLayer(layerId);
    if (!nextLayer || nextLayer.id === activeLayerId) {
      return;
    }
    storeActiveLayerState();
    activeLayerId = nextLayer.id;
    activeLayer = nextLayer;
    loadActiveLayerState({preserveMode: true});
  }

  function storeActiveLayerState() {
    const layer = findMapLayer(activeLayerId);
    if (!layer) {
      return;
    }
    layer.georef_control_points = points.map(copyPoint);
    layer.georef_transform = currentTransform ? {...currentTransform} : null;
    layer.course_controls = courseControls.map(copyPoint);
    renumberCourseControls();
  }

  function loadActiveLayerState(options = {}) {
    activeLayer = findMapLayer(activeLayerId) || mapLayers[0];
    activeLayerId = activeLayer.id;
    points = parseExistingPoints(activeLayer.georef_control_points);
    courseControls = parseExistingPoints(activeLayer.course_controls);
    currentTransform = activeLayer.georef_transform || null;
    pendingPixel = null;
    renumberCourseControls();
    updateLayerTabs();
    resetUploadForm();
    updateImageForActiveLayer();
    if (!options.preserveMode || !activeLayer.map_image_url) {
      currentMode = activeLayer.map_image_url ? "georef" : "file";
    } else if (currentMode === "course" && !currentTransform) {
      currentMode = "georef";
    } else if (currentMode === "file" && activeLayer.map_image_url) {
      currentMode = "georef";
    }
    setMode(currentMode);
    updateCourseModeAvailability();
    removeMapOverlay();
    drawAll();
  }

  function updateImageForActiveLayer() {
    if (!image) {
      return;
    }
    const imageUrl = activeLayer.map_image_url || "";
    image.hidden = !imageUrl;
    if (emptyStage) {
      emptyStage.hidden = Boolean(imageUrl);
    }
    if (!imageUrl) {
      image.removeAttribute("src");
      imageContent.style.width = "";
      imageContent.style.height = "";
      imageView = {scale: 1, translateX: 0, translateY: 0};
      imageContent.style.transform = "";
      removeMapOverlay();
      return;
    }
    if (imageUrl && image.getAttribute("src") !== imageUrl) {
      image.src = imageUrl;
      return;
    }
    if (imageUrl && image.complete) {
      fitImageToViewport();
    }
  }

  function resetUploadForm() {
    const input = uploadForm?.querySelector('input[type="file"]');
    if (input) {
      input.value = "";
    }
  }

  function renderLayerTabs() {
    if (!layerTabsContainer || !addLayerForm) {
      return;
    }
    layerTabs.forEach((tab) => tab.remove());
    mapLayers.forEach((layer) => {
      const tab = document.createElement("button");
      tab.className = "map-layer-tab";
      tab.type = "button";
      tab.dataset.layerId = layer.id;
      tab.textContent = layer.title;
      layerTabsContainer.insertBefore(tab, addLayerForm);
    });
    layerTabs = Array.from(document.querySelectorAll(".map-layer-tab"));
    bindLayerTabs();
    updateLayerTabs();
  }

  function updateLayerTabs() {
    layerTabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.layerId === activeLayerId);
    });
  }

  function mergeServerMapLayers(serverLayers, options = {}) {
    const nextLayers = normalizeMapLayers(serverLayers);
    for (const nextLayer of nextLayers) {
      const existing = findMapLayer(nextLayer.id);
      if (!existing) {
        mapLayers.push(nextLayer);
        continue;
      }
      const localState = options.preserveActiveLocal && existing.id === activeLayerId
        ? {
            georef_control_points: existing.georef_control_points,
            georef_transform: existing.georef_transform,
            course_controls: existing.course_controls,
          }
        : null;
      Object.assign(existing, nextLayer);
      if (localState) {
        Object.assign(existing, localState);
      }
    }
    if (!findMapLayer(activeLayerId)) {
      activeLayerId = mapLayers[0].id;
    }
  }

  function findMapLayer(layerId) {
    return mapLayers.find((layer) => layer.id === layerId) || null;
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
    const previewLayerId = activeLayerId;

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
      if (previewLayerId !== activeLayerId) {
        return;
      }
      currentTransform = payload.transform;
      storeActiveLayerState();
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
    if (!image || !activeLayer.map_image_url) {
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

    if (courseLine.length) {
      courseLine.forEach((line) => line.remove());
      courseLine = [];
    }
    if (courseControls.length >= 2) {
      const latLngs = courseControls.map((control) => [control.lat, control.lon]);
      courseLine = [
        L.polyline(latLngs, {color: "#000000", weight: 7, opacity: 0.95, dashArray: "10 8"}).addTo(leafletMap),
        L.polyline(latLngs, {color: "#FF1744", weight: 3, opacity: 1, dashArray: "10 8"}).addTo(leafletMap),
      ];
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
    currentMode = mode === "course" ? "course" : mode === "file" ? "file" : "georef";
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
    if (currentMode === "file") {
      imagePointLabel.textContent = activeLayer.map_image_url ? "Картинка карты загружена" : "Загрузите картинку карты";
      geoPointLabel.textContent = "Базовая карта";
      return;
    }
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

  function setUploadStatus(message) {
    if (uploadStatus) {
      uploadStatus.textContent = message;
      return;
    }
    if (result) {
      result.textContent = message;
    }
  }

  function normalizedCourseControls() {
    renumberCourseControls();
    return courseControls.map(copyPoint);
  }

  function renumberCourseControls() {
    const active = findMapLayer(activeLayerId);
    if (active) {
      active.course_controls = courseControls.map(copyPoint);
    }

    const flatControls = [];
    for (const layer of mapLayers) {
      const layerControls = parseExistingPoints(layer.course_controls);
      layerControls.forEach((control, layerIndex) => {
        flatControls.push({layer, control, layerIndex});
      });
    }

    flatControls.forEach((item, globalIndex) => {
      const normalized = {
        index: globalIndex + 1,
        label: courseControlLabel(globalIndex, flatControls.length),
        kind: courseControlKind(globalIndex, flatControls.length),
        map_layer_id: item.layer.id,
        pixel_x: item.control.pixel_x,
        pixel_y: item.control.pixel_y,
        lat: item.control.lat,
        lon: item.control.lon,
      };
      item.layer.course_controls[item.layerIndex] = normalized;
    });

    courseControls = parseExistingPoints(active?.course_controls);
  }

  function courseControlLabel(index, total) {
    if (index === 0) {
      return "С";
    }
    if (!isRogaine && total > 2 && index === 1) {
      return "К";
    }
    if (total > 1 && index === total - 1) {
      return "Ф";
    }
    return String(isRogaine ? index : index - 1);
  }

  function courseControlKind(index, total) {
    if (index === 0) {
      return "start";
    }
    if (!isRogaine && total > 2 && index === 1) {
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
    if (mapLayers.length > 1) {
      const total = mapLayers.reduce((sum, layer) => sum + parseExistingPoints(layer.course_controls).length, 0);
      return `Маршрут: КП ${total}.`;
    }
    if (isRogaine) {
      const total = courseControls.length;
      const intermediate = Math.max(total - (total > 1 ? 2 : 1), 0);
      return `Маршрут: старт, КП ${intermediate}, финиш.`;
    }
    const officialControls = Math.max(courseControls.length - 3, 0);
    return `Маршрут: старт, пункт К, КП ${officialControls}, финиш.`;
  }

  function parseExistingPoints(rawValue) {
    if (!rawValue) {
      return [];
    }
    if (Array.isArray(rawValue)) {
      return rawValue.map(copyPoint);
    }
    try {
      const parsed = JSON.parse(rawValue);
      return Array.isArray(parsed) ? parsed.map(copyPoint) : [];
    } catch (_error) {
      return [];
    }
  }

  function parseExistingObject(rawValue) {
    if (rawValue && typeof rawValue === "object") {
      return rawValue;
    }
    if (!rawValue || rawValue === "null") {
      return null;
    }
    try {
      return JSON.parse(rawValue);
    } catch (_error) {
      return null;
    }
  }

  function normalizeMapLayers(rawLayers) {
    const layers = Array.isArray(rawLayers) && rawLayers.length
      ? rawLayers
      : [{id: "map-1", title: "Карта 1"}];
    return layers.map((layer, index) => ({
      id: layer.id || `map-${index + 1}`,
      title: layer.title || `Карта ${index + 1}`,
      image_path: layer.image_path || null,
      image_filename: layer.image_filename || null,
      map_image_url: layer.map_image_url || "",
      georef_method: layer.georef_method || null,
      georef_control_points: parseExistingPoints(layer.georef_control_points),
      georef_transform: layer.georef_transform || null,
      georef_residuals: Array.isArray(layer.georef_residuals) ? layer.georef_residuals : [],
      course_controls: parseExistingPoints(layer.course_controls),
    }));
  }

  function copyPoint(point) {
    return {...point};
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
