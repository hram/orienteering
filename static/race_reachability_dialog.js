(function () {
  const workspace = document.querySelector("#race-result-workspace");
  const button = document.querySelector("#open-reachability-btn");
  const modal = document.querySelector("#reachability-modal");
  const closeButton = document.querySelector("#reachability-close");
  const subtitle = document.querySelector("#reachability-subtitle");
  const chartStatus = document.querySelector("#reachability-chart-status");
  const chartCanvas = document.querySelector("#reachability-chart");
  const zonesContainer = document.querySelector("#reachability-zones");

  if (!workspace || !button || !modal || !closeButton || !chartCanvas || !window.Chart) {
    return;
  }

  const chartData = parseJson(workspace.dataset.reachabilityChart, {});
  const selfName = chartData.self_name || "";
  const selfPlace = chartData.self_place || "";
  const selfGapSeconds = Number.isFinite(chartData.self_gap_seconds) ? chartData.self_gap_seconds : 0;
  const points = Array.isArray(chartData.points) ? chartData.points : [];

  let chartInstance = null;
  let zones = null;

  button.addEventListener("click", openModal);
  closeButton.addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.matches("[data-close-reachability]")) {
      closeModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }
  });

  function openModal() {
    modal.hidden = false;
    document.body.classList.add("modal-open");
    if (!chartInstance) {
      renderDialog();
    } else {
      requestAnimationFrame(() => {
        chartInstance.resize();
        chartInstance.update("none");
      });
    }
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
  }

  function renderDialog() {
    if (!points.length) {
      if (subtitle) {
        subtitle.textContent = "Недостаточно данных для анализа.";
      }
      if (chartStatus) {
        chartStatus.textContent = "";
      }
      if (zonesContainer) {
        zonesContainer.innerHTML = "";
      }
      return;
    }

    if (subtitle) {
      subtitle.textContent = [
        selfName,
        selfPlace ? `${selfPlace} место` : "",
        selfGapSeconds > 0 ? `+${formatDuration(selfGapSeconds)} до лидера` : "лидер",
      ].filter(Boolean).join(" · ");
    }

    zones = buildZones(points);
    renderLegend(zones);

    if (chartStatus) {
      chartStatus.textContent = `${points.length} участников`;
    }

    const ctx = chartCanvas.getContext("2d");
    const zonesPlugin = {
      id: "reachabilityZones",
      beforeDatasetsDraw(chart) {
        const {ctx, chartArea, scales} = chart;
        if (!chartArea || !scales?.x || !zones) {
          return;
        }
        for (let index = 0; index < zones.bands.length; index += 1) {
          const band = zones.bands[index];
          const x1 = scales.x.getPixelForValue(band.from);
          const x2 = scales.x.getPixelForValue(band.to);
          const left = Math.min(x1, x2);
          const width = Math.max(Math.abs(x2 - x1), 1);
          ctx.save();
          ctx.fillStyle = band.color.fill;
          ctx.fillRect(left, chartArea.top, width, chartArea.bottom - chartArea.top);
          ctx.restore();
          if (index < zones.bands.length - 1) {
            ctx.save();
            ctx.strokeStyle = band.color.border;
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(x2, chartArea.top);
            ctx.lineTo(x2, chartArea.bottom);
            ctx.stroke();
            ctx.restore();
          }
        }
      },
    };

    chartInstance = new window.Chart(ctx, {
      type: "scatter",
      plugins: [zonesPlugin],
      data: {
        datasets: [
          {
            label: "Соперники",
            data: points.filter((point) => !point.is_self).map((point) => ({
              x: point.x_seconds,
              y: point.place,
              name: point.name,
              is_self: false,
            })),
            backgroundColor: "#378ADD",
            borderColor: "#378ADD",
            pointRadius: 6,
            pointHoverRadius: 8,
          },
          {
            label: "Я",
            data: points.filter((point) => point.is_self).map((point) => ({
              x: point.x_seconds,
              y: point.place,
              name: point.name,
              is_self: true,
            })),
            backgroundColor: "#E24B4A",
            borderColor: "#ffffff",
            borderWidth: 2,
            pointRadius: 10,
            pointHoverRadius: 12,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: {display: false},
          tooltip: {
            callbacks: {
              label(context) {
                const raw = context.raw || {};
                const seconds = Math.round(context.parsed.x);
                const place = Math.round(context.parsed.y);
                const name = raw.name || "";
                if (raw.is_self) {
                  return `${name} — ${place} место (я)`;
                }
                if (seconds > 0) {
                  return `${name} — ${place} место, нужно сэкономить ${formatDuration(seconds)}`;
                }
                if (seconds < 0) {
                  return `${name} — ${place} место, я быстрее на ${formatDuration(Math.abs(seconds))}`;
                }
                return `${name} — ${place} место, рядом со мной`;
              },
            },
          },
        },
        scales: {
          x: {
            title: {
              display: true,
              text: "Секунды до соперника",
              color: "#66747c",
            },
            ticks: {
              callback(value) {
                const seconds = Number(value);
                return formatSignedDuration(seconds);
              },
              maxTicksLimit: 10,
            },
            grid: {
              color: "rgba(102,116,124,0.10)",
            },
          },
          y: {
            title: {
              display: true,
              text: "Место",
              color: "#66747c",
            },
            ticks: {
              stepSize: 1,
            },
            grid: {
              color: "rgba(102,116,124,0.10)",
            },
          },
        },
      },
    });
  }

  function renderLegend(result) {
    if (!zonesContainer) {
      return;
    }
    zonesContainer.innerHTML = "";
    result.bands.forEach((band) => {
      const card = document.createElement("div");
      card.className = "reachability-zone-card";
      card.style.borderLeftColor = band.color.border;
      const placeLabel = summarizePlaces(band.points);
      card.innerHTML = `
        <div class="reachability-zone-title">${band.color.label}</div>
        <div class="reachability-zone-places">${placeLabel || "Нет соперников"}</div>
        <div class="reachability-zone-range">${formatSignedDuration(band.from)} – ${formatSignedDuration(band.to)}</div>
      `;
      zonesContainer.appendChild(card);
    });
  }

  function buildZones(rawPoints) {
    const values = rawPoints.map((point) => point.x_seconds);
    const classCount = Math.min(4, Math.max(1, values.length));
    const breaks = jenks(values, classCount);
    const colors = [
      {fill: "rgba(99,153,34,0.11)", border: "#639922", label: "Сейчас реально"},
      {fill: "rgba(55,138,221,0.10)", border: "#378ADD", label: "Работа над техникой"},
      {fill: "rgba(186,117,23,0.10)", border: "#BA7517", label: "Серьёзная работа"},
      {fill: "rgba(224,75,74,0.09)", border: "#E24B4A", label: "Другой уровень"},
    ].slice(0, Math.max(1, breaks.length - 1));

    const bands = [];
    for (let index = 0; index < breaks.length - 1; index += 1) {
      const from = breaks[index];
      const to = breaks[index + 1];
      const color = colors[index] || colors[colors.length - 1];
      const isLastBand = index === breaks.length - 2;
      bands.push({
        from,
        to,
        color,
        points: rawPoints.filter((point) => {
          if (point.x_seconds < from) {
            return false;
          }
          return isLastBand ? point.x_seconds <= to : point.x_seconds < to;
        }),
      });
    }

    return {breaks, bands};
  }

  function summarizePlaces(pointsInBand) {
    const places = pointsInBand
      .filter((point) => !point.is_self)
      .map((point) => point.place)
      .filter((place) => Number.isFinite(place));
    if (!places.length) {
      return "";
    }
    const min = Math.min(...places);
    const max = Math.max(...places);
    return min === max ? `Место ${min}` : `Места ${min}–${max}`;
  }

  function jenks(values, numClasses) {
    const sorted = [...values].sort((left, right) => left - right);
    if (!sorted.length) {
      return [0, 0];
    }
    const n = sorted.length;
    const classCount = Math.min(Math.max(numClasses, 1), n);
    const mat1 = Array.from({length: n + 1}, () => new Array(classCount + 1).fill(0));
    const mat2 = Array.from({length: n + 1}, () => new Array(classCount + 1).fill(Infinity));
    for (let i = 1; i <= classCount; i += 1) {
      mat1[1][i] = 1;
      mat2[1][i] = 0;
    }
    for (let j = 2; j <= n; j += 1) {
      mat2[j][1] = Infinity;
    }

    for (let j = 2; j <= n; j += 1) {
      let sum = 0;
      let sumSquares = 0;
      let weight = 0;
      let ssd = 0;
      for (let m = 1; m <= j; m += 1) {
        const index = j - m + 1;
        const value = sorted[index - 1];
        weight += 1;
        sum += value;
        sumSquares += value * value;
        ssd = sumSquares - (sum * sum) / weight;
        for (let k = 2; k <= classCount; k += 1) {
          if (mat2[j][k] >= ssd + mat2[index - 1][k - 1]) {
            mat1[j][k] = index;
            mat2[j][k] = ssd + mat2[index - 1][k - 1];
          }
        }
      }
      mat1[j][1] = 1;
      mat2[j][1] = ssd;
    }

    const breaks = new Array(classCount + 1);
    breaks[0] = sorted[0];
    breaks[classCount] = sorted[n - 1];
    let k = n;
    for (let j = classCount; j >= 2; j -= 1) {
      const id = mat1[k][j] - 2;
      breaks[j - 1] = sorted[id];
      k = mat1[k][j] - 1;
    }
    return breaks;
  }

  function formatSignedDuration(seconds) {
    const value = Math.trunc(Number(seconds) || 0);
    const sign = value < 0 ? "-" : "";
    return `${sign}${formatDuration(Math.abs(value))}`;
  }

  function formatDuration(seconds) {
    const total = Math.max(Math.trunc(Number(seconds) || 0), 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const rest = total % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
    }
    return `${minutes}:${String(rest).padStart(2, "0")}`;
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
