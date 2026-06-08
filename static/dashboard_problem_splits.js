(function () {
  const workspace = document.querySelector("#dashboard-problem-workspace");
  if (!workspace || !window.OrienteeringSplits || !window.SplitAnalysisDialog) {
    return;
  }

  const dashboard = parseJson(workspace.dataset.dashboard, {});
  const trainings = dashboard.trainings || {};
  const problemSplits = Array.isArray(dashboard.splits) ? dashboard.splits : [];
  const rowCache = new Map();
  const imageCache = new Map();

  workspace.querySelectorAll(".split-analysis-button[data-problem-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const problemIndex = Number(button.dataset.problemIndex);
      const item = problemSplits.find((split) => split.problem_index === problemIndex);
      if (item) {
        openProblemSplit(item);
      }
    });
  });

  window.addEventListener("orienteering:split-reviewed", (event) => {
    if (workspace.dataset.removeReviewed === "false") {
      return;
    }
    const problemIndex = Number(event.detail?.problemIndex);
    if (!Number.isFinite(problemIndex)) {
      return;
    }
    const button = workspace.querySelector(`.split-analysis-button[data-problem-index="${problemIndex}"]`);
    const row = button?.closest(".dashboard-split-card, tr");
    if (row) {
      row.remove();
    }
    const index = problemSplits.findIndex((split) => split.problem_index === problemIndex);
    if (index >= 0) {
      problemSplits.splice(index, 1);
    }
    rowCache.clear();
    updateProblemTotal();
  });

  function openProblemSplit(item) {
    const training = trainings[item.training_id];
    if (!hasTrainingMapImage(training)) {
      return;
    }
    const rows = problemRowsForTraining(item.training_id);
    const row = rows.find((candidate) => candidate.__problemIndex === item.problem_index);
    if (!row) {
      return;
    }
    window.SplitAnalysisDialog.open({
      trainingId: item.training_id,
      raceResultId: item.race_result_id,
      row,
      rows,
      rowIndex: Math.max(rows.indexOf(row), 0),
      image: imageForTraining(training),
      mapLayers: mapLayersForTraining(training),
      trackPoints: trackPointsForTraining(training),
      transform: transformForTraining(training),
    });
  }

  function problemRowsForTraining(trainingId) {
    if (rowCache.has(trainingId)) {
      return rowCache.get(trainingId);
    }
    const training = trainings[trainingId];
    if (!training) {
      return [];
    }
    const allRows = window.OrienteeringSplits.calculateSplits(
      courseControlsForTraining(training),
      trackPointsForTraining(training)
    );
    const rows = problemSplits
      .filter((item) => item.training_id === trainingId)
      .map((item) => {
        const row = allRows[item.split_index];
        if (!row) {
          return null;
        }
        return {
          ...row,
          __problemIndex: item.problem_index,
        };
      })
      .filter(Boolean);
    rowCache.set(trainingId, rows);
    return rows;
  }

  function courseControlsForTraining(training) {
    const mapLayers = mapLayersForTraining(training);
    if (mapLayers.length) {
      const controls = [];
      mapLayers.forEach((layer) => {
        (layer.course_controls || []).forEach((control) => {
          controls.push({...control, map_layer_id: control.map_layer_id || layer.id});
        });
      });
      if (controls.length) {
        return window.OrienteeringSplits.normalizeCourseControls(
          controls,
          {trainingType: training.training_type || ""}
        );
      }
    }
    return window.OrienteeringSplits.normalizeCourseControls(
      training.course_controls || [],
      {trainingType: training.training_type || ""}
    );
  }

  function trackPointsForTraining(training) {
    const transform = transformForTraining(training);
    return (training.track_points || []).map((point, index) => ({
      ...point,
      pixel: transform ? geoToPixel(point, transform) : {pixel_x: 0, pixel_y: 0},
      seconds: window.OrienteeringSplits.parsePointSeconds(point, index),
    }));
  }

  function imageForTraining(training) {
    if (imageCache.has(training.training_id)) {
      return imageCache.get(training.training_id);
    }
    const mapLayer = mapLayersForTraining(training).find((layer) => layer.map_image_url);
    const imageUrl = training.map_image_url || mapLayer?.map_image_url || "";
    if (!imageUrl) {
      return null;
    }
    const image = new Image();
    image.alt = "";
    image.src = imageUrl;
    imageCache.set(training.training_id, image);
    return image;
  }

  function hasTrainingMapImage(training) {
    return Boolean(training?.map_image_url)
      || mapLayersForTraining(training).some((layer) => layer.map_image_url);
  }

  function mapLayersForTraining(training) {
    if (Array.isArray(training?.map_layers) && training.map_layers.length) {
      return training.map_layers.map((layer, index) => ({
        ...layer,
        id: layer.id || `map-${index + 1}`,
        title: layer.title || `Карта ${index + 1}`,
        course_controls: Array.isArray(layer.course_controls) ? layer.course_controls : [],
        georef_transform: layer.georef_transform || null,
      }));
    }
    if (!training?.map_image_url && !training?.transform) {
      return [];
    }
    return [{
      id: "map-1",
      title: "Карта 1",
      map_image_url: training.map_image_url || "",
      georef_transform: training.transform || null,
      course_controls: Array.isArray(training.course_controls) ? training.course_controls : [],
    }];
  }

  function transformForTraining(training) {
    return mapLayersForTraining(training).find((layer) => layer.georef_transform)?.georef_transform
      || training?.transform
      || null;
  }

  function updateProblemTotal() {
    const summary = workspace.querySelector(".dashboard-problem-card .pane-header .muted")
      || workspace.querySelector(".pane-header .muted");
    if (!summary) {
      return;
    }
    const currentCount = Number.parseInt(summary.textContent, 10);
    const nextCount = Number.isFinite(currentCount) ? Math.max(currentCount - 1, 0) : problemSplits.length;
    if (workspace.classList.contains("dashboard-grid")) {
      summary.textContent = `${nextCount} проблемных сплитов`;
    } else {
      summary.textContent = `${nextCount} сплитов отсортированы по отставанию от лидера`;
    }
  }

  function geoToPixel(point, transform) {
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

  function parseJson(value, fallback) {
    try {
      return value ? JSON.parse(value) : fallback;
    } catch (_error) {
      return fallback;
    }
  }
})();
