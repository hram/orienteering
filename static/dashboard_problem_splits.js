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

  function openProblemSplit(item) {
    const training = trainings[item.training_id];
    if (!training?.map_image_url) {
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
      trackPoints: trackPointsForTraining(training),
      transform: training.transform || null,
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
    return window.OrienteeringSplits.normalizeCourseControls(
      training.course_controls || [],
      {trainingType: training.training_type || ""}
    );
  }

  function trackPointsForTraining(training) {
    const transform = training.transform;
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
    const image = new Image();
    image.alt = "";
    image.src = training.map_image_url;
    imageCache.set(training.training_id, image);
    return image;
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
