(function () {
  const workspace = document.querySelector("#race-result-workspace");
  if (!workspace || !window.OrienteeringSplits || !window.SplitAnalysisDialog) {
    return;
  }

  const image = document.querySelector("#race-analysis-map-image");
  const trainingId = workspace.dataset.trainingId;
  const raceResultId = workspace.dataset.raceResultId || null;
  const trainingType = workspace.dataset.trainingType || "";
  const mapLayers = normalizeMapLayers(parseJson(workspace.dataset.mapLayers, []));
  const transform = mapLayers[0]?.georef_transform || parseJson(workspace.dataset.transform, null);
  const courseControls = normalizeAllCourseControls();
  const trackPoints = parseJson(workspace.dataset.trackPoints, []).map((point, index) => ({
    ...point,
    pixel: transform ? geoToPixel(point) : {pixel_x: 0, pixel_y: 0},
    seconds: window.OrienteeringSplits.parsePointSeconds(point, index),
  }));
  const hasTrack = trackPoints.length >= 2;
  const splits = window.OrienteeringSplits.calculateSplits(courseControls, trackPoints);
  const problemToggle = document.querySelector("#race-problem-toggle");
  const problemPanel = document.querySelector("#race-problem-panel");

  document.querySelectorAll(".race-split-analysis-button").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.scoreVisitIndex !== undefined) {
        openScoreVisitAnalysis(Number(button.dataset.scoreVisitIndex));
        return;
      }
      openSplitAnalysisByLabel(button.dataset.splitLabel);
    });
  });

  function openScoreVisitAnalysis(visitIndex) {
    if (!Number.isInteger(visitIndex) || visitIndex < 0) {
      return;
    }
    if (hasTrack) {
      const row = splits[visitIndex];
      if (!row || !image) {
        return;
      }
      window.SplitAnalysisDialog.open({
        trainingId,
        raceResultId,
        row,
        rows: pagerRowsForScoreVisits(),
        rowIndex: pagerRowsForScoreVisits().indexOf(row),
        image,
        mapLayers,
        trackPoints,
        transform,
      });
      return;
    }

    const row = buildProtocolVisitRow(visitIndex);
    if (!row || !image || !window.SplitViewDialog) {
      return;
    }
    window.SplitViewDialog.open({
      trainingId,
      row,
      image,
      mapLayers,
    });
  }

  function openSplitAnalysisByLabel(label) {
    const normalized = normalizeSplitLabel(label);
    if (hasTrack) {
      const rowIndex = splits.findIndex((split) => normalizeSplitLabel(split.label) === normalized);
      const row = splits[rowIndex];
      if (!row || !image) {
        return;
      }
      window.SplitAnalysisDialog.open({
        trainingId,
        raceResultId,
        row,
        rows: pagerRowsForSplits(),
        rowIndex: pagerRowsForSplits().indexOf(row),
        image,
        mapLayers,
        trackPoints,
        transform,
      });
      return;
    }

    const row = buildProtocolSplitRow(normalized);
    if (!row || !image || !window.SplitViewDialog) {
      return;
    }
    window.SplitViewDialog.open({
      trainingId,
      row,
      image,
      mapLayers,
    });
  }

  function normalizeMapLayers(layers) {
    if (Array.isArray(layers) && layers.length) {
      return layers.map((layer, index) => ({
        ...layer,
        id: layer.id || `map-${index + 1}`,
        title: layer.title || `Карта ${index + 1}`,
        course_controls: Array.isArray(layer.course_controls) ? layer.course_controls : [],
      }));
    }
    return [{
      id: "map-1",
      title: "Карта 1",
      map_image_url: workspace.dataset.mapImageUrl || "",
      georef_transform: parseJson(workspace.dataset.transform, null),
      course_controls: parseJson(workspace.dataset.courseControls, []),
    }];
  }

  function normalizeAllCourseControls() {
    const controls = [];
    mapLayers.forEach((layer) => {
      layer.course_controls.forEach((control) => {
        controls.push({...control, map_layer_id: control.map_layer_id || layer.id});
      });
    });
    return window.OrienteeringSplits.normalizeCourseControls(controls, {trainingType});
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

  function normalizeSplitLabel(label) {
    return String(label).trim().toUpperCase() === "F" ? "Ф" : String(label).trim();
  }

  function problemModeActive() {
    return Boolean(problemToggle?.checked && problemPanel && !problemPanel.hidden);
  }

  function pagerRowsForScoreVisits() {
    if (!problemModeActive()) {
      return splits;
    }
    const rows = Array.from(problemPanel.querySelectorAll(".race-split-analysis-button[data-score-visit-index]"))
      .map((button) => splits[Number(button.dataset.scoreVisitIndex)])
      .filter(Boolean);
    return rows.length ? rows : splits;
  }

  function pagerRowsForSplits() {
    if (!problemModeActive()) {
      return splits;
    }
    const rows = Array.from(problemPanel.querySelectorAll(".race-split-analysis-button[data-split-label]"))
      .map((button) => {
        const label = normalizeSplitLabel(button.dataset.splitLabel);
        return splits.find((split) => normalizeSplitLabel(split.label) === label);
      })
      .filter(Boolean);
    return rows.length ? rows : splits;
  }

  function buildProtocolSplitRow(label) {
    const splitControls = courseControls.filter((control) => control.kind !== "start-point");
    const targetIndex = splitControls.findIndex((control) => normalizeSplitLabel(control.label) === label);
    if (targetIndex <= 0) {
      return null;
    }
    const toControl = splitControls[targetIndex];
    const fromControl = splitControls[targetIndex - 1];
    const viaControls = courseControlsBetween(courseControls, fromControl, toControl);
    return {
      label,
      fromControl,
      viaControls,
      toControl,
    };
  }

  function buildProtocolVisitRow(visitIndex) {
    const splitControls = courseControls.filter((control) => control.kind !== "start-point");
    const targetIndex = visitIndex + 1;
    if (targetIndex <= 0 || targetIndex >= splitControls.length) {
      return null;
    }
    const toControl = splitControls[targetIndex];
    const fromControl = splitControls[targetIndex - 1];
    const viaControls = courseControlsBetween(courseControls, fromControl, toControl);
    return {
      label: toControl.label,
      fromControl,
      viaControls,
      toControl,
    };
  }

  function courseControlsBetween(allControls, previousControl, currentControl) {
    const previousIndex = previousControl.index - 1;
    const currentIndex = currentControl.index - 1;
    if (currentIndex - previousIndex <= 1) {
      return [];
    }
    return allControls.slice(previousIndex + 1, currentIndex);
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
