(function (root) {
  function calculateLayerSplitMarkers(mapLayers, courseControls, trackPoints) {
    const layerControlGroups = mapLayers
      .map((layer) => ({
        layer,
        controls: courseControls.filter((control) => control.map_layer_id === layer.id && control.kind !== "start-point"),
      }))
      .filter((group) => group.controls.length);
    if (layerControlGroups.length <= 1 || !trackPoints.length) {
      return [];
    }

    const starts = [];
    let previousStart = 0;
    for (let groupIndex = 0; groupIndex < layerControlGroups.length; groupIndex += 1) {
      const group = layerControlGroups[groupIndex];
      const firstControl = group.controls[0];
      const endIndex = groupIndex === 0 ? startSearchEndIndex(trackPoints) : trackPoints.length;
      const match = findClosestTrackPoint(trackPoints, firstControl, previousStart, endIndex);
      if (match === null) {
        return [];
      }
      starts.push(match);
      previousStart = Math.min(match + 1, trackPoints.length - 1);
    }

    const splitControls = courseControls.filter((control) => control.kind !== "start-point");
    const markers = [];
    for (let groupIndex = 0; groupIndex < layerControlGroups.length; groupIndex += 1) {
      const group = layerControlGroups[groupIndex];
      const endIndex = groupIndex + 1 < starts.length ? starts[groupIndex + 1] : trackPoints.length;
      const matches = matchControlSequence(trackPoints, group.controls, starts[groupIndex], endIndex);
      if (!matches.length) {
        return [];
      }
      for (let controlIndex = 0; controlIndex < group.controls.length; controlIndex += 1) {
        const control = group.controls[controlIndex];
        const match = matches[controlIndex];
        if (match === null) {
          return [];
        }
        markers.push({
          trackIndex: match,
          control,
          order: splitControls.indexOf(control),
        });
      }
    }
    return markers.filter((marker) => marker.order >= 0);
  }

  function matchControlSequence(trackPoints, controls, firstMatchIndex, endIndex) {
    if (!controls.length) {
      return [];
    }
    if (controls.length === 1) {
      return [firstMatchIndex];
    }

    const start = Math.min(firstMatchIndex + 1, trackPoints.length);
    const end = clamp(Math.ceil(endIndex), start, trackPoints.length);
    const remainingControls = controls.slice(1);
    if (end - start < remainingControls.length) {
      return [];
    }

    let previousCosts = null;
    const backPointers = [];
    for (let controlIndex = 0; controlIndex < remainingControls.length; controlIndex += 1) {
      const control = remainingControls[controlIndex];
      const costs = [];
      const previousIndexes = [];
      let bestPreviousCost = Infinity;
      let bestPreviousIndex = null;

      for (let trackIndex = start; trackIndex < end; trackIndex += 1) {
        const offset = trackIndex - start;
        if (controlIndex === 0) {
          bestPreviousCost = 0;
          bestPreviousIndex = firstMatchIndex;
        } else {
          const previousCost = previousCosts[offset - 1];
          if (previousCost < bestPreviousCost) {
            bestPreviousCost = previousCost;
            bestPreviousIndex = trackIndex - 1;
          }
        }

        if (bestPreviousIndex === null || !Number.isFinite(bestPreviousCost)) {
          costs[offset] = Infinity;
          previousIndexes[offset] = null;
          continue;
        }

        costs[offset] = bestPreviousCost + haversineMeters(trackPoints[trackIndex], control);
        previousIndexes[offset] = bestPreviousIndex;
      }

      previousCosts = costs;
      backPointers.push(previousIndexes);
    }

    let bestCost = Infinity;
    let bestIndex = null;
    for (let offset = 0; offset < previousCosts.length; offset += 1) {
      const cost = previousCosts[offset];
      if (cost < bestCost) {
        bestCost = cost;
        bestIndex = start + offset;
      }
    }
    if (bestIndex === null) {
      return [];
    }

    const matches = [firstMatchIndex, ...new Array(remainingControls.length)];
    let currentIndex = bestIndex;
    for (let controlIndex = remainingControls.length - 1; controlIndex >= 0; controlIndex -= 1) {
      matches[controlIndex + 1] = currentIndex;
      currentIndex = backPointers[controlIndex][currentIndex - start];
    }
    return matches;
  }

  function startSearchEndIndex(trackPoints) {
    if (!trackPoints.length) {
      return 0;
    }
    const firstSeconds = trackPointSeconds(trackPoints[0], 0);
    const fallbackEndIndex = Math.max(1, Math.ceil(trackPoints.length * 0.1));
    for (let index = 1; index < trackPoints.length; index += 1) {
      const seconds = trackPointSeconds(trackPoints[index], index);
      if (seconds - firstSeconds > 300) {
        return Math.max(1, Math.min(index, fallbackEndIndex));
      }
    }
    return fallbackEndIndex;
  }

  function findClosestTrackPoint(trackPoints, control, startIndex, endIndex) {
    let best = null;
    const start = clamp(Math.floor(startIndex), 0, trackPoints.length - 1);
    const end = clamp(Math.ceil(endIndex), start + 1, trackPoints.length);
    for (let index = start; index < end; index += 1) {
      const point = trackPoints[index];
      const distanceMeters = haversineMeters(point, control);
      if (!best || distanceMeters < best.distanceMeters) {
        best = {index, distanceMeters};
      }
    }
    return best ? best.index : null;
  }

  function trackPointSeconds(point, index) {
    if (Number.isFinite(Number(point?.seconds))) {
      return Number(point.seconds);
    }
    if (point?.time) {
      const timestamp = Date.parse(point.time);
      if (!Number.isNaN(timestamp)) {
        return timestamp / 1000;
      }
    }
    return index;
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

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  const api = {
    calculateLayerSplitMarkers,
    startSearchEndIndex,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.OrienteeringTrackMarkers = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
