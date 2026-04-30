(function (root) {
  function normalizeCourseControls(controls) {
    return controls.map((control, index) => ({
      ...control,
      index: index + 1,
      label: courseControlLabel(index, controls.length),
      kind: courseControlKind(index, controls.length),
    }));
  }

  function calculateSplits(courseControls, trackPoints) {
    if (!courseControls.length || !trackPoints.length) {
      return [];
    }

    const splitControls = courseControls.filter((control) => control.kind !== "start-point");
    const startControl = splitControls[0];
    const startMatch = startControl
      ? findClosestTrackPoint(trackPoints, startControl, 0, startSearchEndIndex(trackPoints))
      : null;
    if (!startMatch) {
      return [];
    }

    const rows = [];
    const startSeconds = startMatch.seconds;
    let nextSearchIndex = startMatch.index + 1;
    let previousAbsoluteSeconds = 0;
    let previousControl = startControl;
    let previousMatchIndex = startMatch.index;

    for (const control of splitControls.slice(1)) {
      const match = findClosestTrackPoint(trackPoints, control, nextSearchIndex);
      if (!match) {
        break;
      }

      const absoluteSeconds = Math.max(match.seconds - startSeconds, 0);
      rows.push({
        label: control.label || String(control.index),
        absoluteSeconds,
        splitSeconds: Math.max(absoluteSeconds - previousAbsoluteSeconds, 0),
        distanceMeters: courseStageDistanceMeters(courseControls, previousControl, control),
        paceSecondsPerMeter: null,
        fromControl: previousControl,
        viaControls: courseControlsBetween(courseControls, previousControl, control),
        toControl: control,
        fromTrackIndex: previousMatchIndex,
        toTrackIndex: match.index,
      });

      previousAbsoluteSeconds = absoluteSeconds;
      previousControl = control;
      previousMatchIndex = match.index;
      nextSearchIndex = match.index + 1;
    }

    for (const row of rows) {
      if (row.splitSeconds !== null && row.distanceMeters && row.distanceMeters > 0) {
        row.paceSecondsPerMeter = row.splitSeconds / row.distanceMeters;
      }
    }

    const rankedRows = rows
      .filter((row) => typeof row.paceSecondsPerMeter === "number")
      .sort((a, b) => b.paceSecondsPerMeter - a.paceSecondsPerMeter)
      .slice(0, 3);
    const slowestRows = new Set(rankedRows);
    const fastestRows = new Set(
      rows
        .filter((row) => typeof row.paceSecondsPerMeter === "number")
        .sort((a, b) => a.paceSecondsPerMeter - b.paceSecondsPerMeter)
        .slice(0, 3)
    );
    for (const row of rows) {
      row.isSlowest = slowestRows.has(row);
      row.isFastest = fastestRows.has(row);
    }

    return rows;
  }

  function courseControlsBetween(courseControls, previousControl, currentControl) {
    const previousIndex = previousControl.index - 1;
    const currentIndex = currentControl.index - 1;
    if (currentIndex - previousIndex <= 1) {
      return [];
    }
    return courseControls.slice(previousIndex + 1, currentIndex);
  }

  function startSearchEndIndex(trackPoints) {
    if (!trackPoints.length) {
      return 0;
    }
    const firstSeconds = trackPoints[0].seconds ?? parsePointSeconds(trackPoints[0], 0);
    const fallbackEndIndex = Math.max(1, Math.ceil(trackPoints.length * 0.1));
    for (let index = 1; index < trackPoints.length; index += 1) {
      const seconds = trackPoints[index].seconds ?? parsePointSeconds(trackPoints[index], index);
      if (seconds - firstSeconds > 300) {
        return Math.max(1, Math.min(index, fallbackEndIndex));
      }
    }
    return fallbackEndIndex;
  }

  function findClosestTrackPoint(trackPoints, control, startIndex, endIndex = trackPoints.length) {
    let best = null;
    for (let index = startIndex; index < endIndex; index += 1) {
      const point = trackPoints[index];
      const distanceMeters = haversineMeters(point, control);
      const seconds = point.seconds ?? parsePointSeconds(point, index);
      if (!best || distanceMeters < best.distanceMeters) {
        best = {
          index,
          point,
          distanceMeters,
          seconds,
        };
      }
    }
    return best;
  }

  function courseStageDistanceMeters(courseControls, previousControl, currentControl) {
    const previousIndex = previousControl.index - 1;
    const currentIndex = currentControl.index - 1;
    if (currentIndex <= previousIndex) {
      return 0;
    }

    let total = 0;
    for (let index = previousIndex + 1; index <= currentIndex; index += 1) {
      total += haversineMeters(courseControls[index - 1], courseControls[index]);
    }
    return total;
  }

  function parsePointSeconds(point, index) {
    if (point.time) {
      const timestamp = Date.parse(point.time);
      if (!Number.isNaN(timestamp)) {
        return timestamp / 1000;
      }
    }
    return index;
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

  function haversineMeters(a, b) {
    const radius = 6371000;
    const lat1 = toRadians(a.lat);
    const lat2 = toRadians(b.lat);
    const deltaLat = toRadians(b.lat - a.lat);
    const deltaLon = toRadians(b.lon - a.lon);
    const value =
      Math.sin(deltaLat / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
    return radius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
  }

  function toRadians(value) {
    return value * Math.PI / 180;
  }

  const api = {
    calculateSplits,
    normalizeCourseControls,
    parsePointSeconds,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.OrienteeringSplits = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
