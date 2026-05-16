(function () {
  const card = document.querySelector(".race-positions-card");
  if (!card || !window.Chart) {
    return;
  }

  const stats = parseJson(card.dataset.racePositions, {});
  const points = Array.isArray(stats.points) ? stats.points : [];
  const canvas = card.querySelector("#race-positions-chart");
  if (!canvas || !points.length) {
    return;
  }

  new window.Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels: points.map((point) => point.date_label),
      datasets: [{
        label: "Позиция",
        data: points.map((point) => point.position_ratio),
        borderColor: "#0f6b4f",
        backgroundColor: "#0f6b4f22",
        borderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 5,
        tension: 0.25,
        fill: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: {display: false},
        tooltip: {
          callbacks: {
            title(items) {
              const point = points[items[0]?.dataIndex ?? 0];
              return point?.training_title || "";
            },
            label(item) {
              const point = points[item.dataIndex];
              const total = point.participant_count ? ` из ${point.participant_count}` : "";
              const group = point.group_name ? ` · ${point.group_name}` : "";
              return `${point.place} место${total}${group}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: {color: "rgba(102, 116, 124, 0.12)"},
          ticks: {font: {size: 12}},
        },
        y: {
          reverse: true,
          min: 0,
          max: 1,
          ticks: {
            stepSize: 0.25,
            font: {size: 12},
            callback(value) {
              return `${Math.round(Number(value) * 100)}%`;
            },
          },
          grid: {color: "rgba(102, 116, 124, 0.12)"},
        },
      },
    },
  });

  function parseJson(value, fallback) {
    try {
      return value ? JSON.parse(value) : fallback;
    } catch (_error) {
      return fallback;
    }
  }
})();
