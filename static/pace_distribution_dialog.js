(function () {
  const workspace = document.querySelector("#race-result-workspace");
  const button = document.querySelector("#open-pace-distribution-btn");
  const modal = document.querySelector("#pace-distribution-modal");
  const closeButton = document.querySelector("#pace-distribution-close");
  const subtitle = document.querySelector("#pace-distribution-subtitle");
  const statsContainer = document.querySelector("#pace-distribution-stats");
  const chartCanvas = document.querySelector("#pace-distribution-chart");
  const scatterCanvas = document.querySelector("#pace-distribution-scatter");

  if (!workspace || !button || !modal || !closeButton || !chartCanvas || !scatterCanvas || !window.Chart) {
    return;
  }

  const data = parseJson(workspace.dataset.paceDistribution, {});
  const points = Array.isArray(data.points) ? data.points : [];
  const buckets = Array.isArray(data.buckets) ? data.buckets : [];
  let distributionChart = null;
  let scatterChart = null;

  button.addEventListener("click", openModal);
  closeButton.addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.matches("[data-close-pace-distribution]")) {
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
    if (!distributionChart) {
      renderDialog();
    } else {
      requestAnimationFrame(() => {
        distributionChart.resize();
        scatterChart.resize();
        distributionChart.update("none");
        scatterChart.update("none");
      });
    }
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
  }

  function renderDialog() {
    if (subtitle) {
      subtitle.textContent = [data.leader_name, `${data.split_count || points.length} сплитов`].filter(Boolean).join(" · ");
    }
    renderStats();
    renderDistributionChart();
    renderScatterChart();
  }

  function renderStats() {
    if (!statsContainer) {
      return;
    }
    const stats = [
      ["Минимум", data.min, "fast"],
      ["Средний", data.mean, "normal"],
      ["Медиана", data.median, "normal"],
      ["Максимум", data.max, "slow"],
    ];
    statsContainer.replaceChildren(...stats.map(([label, value, tone]) => {
      const card = document.createElement("div");
      card.className = "pace-distribution-stat";
      const caption = document.createElement("span");
      caption.textContent = label;
      const number = document.createElement("strong");
      number.className = `pace-distribution-stat-${tone}`;
      number.textContent = formatPace(value);
      card.append(caption, number);
      return card;
    }));
  }

  function renderDistributionChart() {
    const ctx = chartCanvas.getContext("2d");
    const meanMedianPlugin = {
      id: "paceMeanMedianLines",
      afterDraw(chart) {
        const {ctx, chartArea} = chart;
        const min = buckets[0]?.from;
        const max = buckets[buckets.length - 1]?.to;
        if (!chartArea || min === undefined || max === undefined || max <= min) {
          return;
        }
        [
          [data.mean, "#0f6b4f", []],
          [data.median, "#b46a12", [4, 4]],
        ].forEach(([value, color, dash]) => {
          const ratio = (Number(value) - min) / (max - min);
          const x = chartArea.left + ratio * (chartArea.right - chartArea.left);
          ctx.save();
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;
          ctx.setLineDash(dash);
          ctx.beginPath();
          ctx.moveTo(x, chartArea.top);
          ctx.lineTo(x, chartArea.bottom);
          ctx.stroke();
          ctx.restore();
        });
      },
    };

    distributionChart = new window.Chart(ctx, {
      type: "bar",
      plugins: [meanMedianPlugin],
      data: {
        labels: buckets.map((bucket) => formatPace(bucket.from)),
        datasets: [{
          data: buckets.map((bucket) => bucket.count),
          backgroundColor: buckets.map((bucket) => toneColor(bucket.tone)),
          borderWidth: 0,
          barPercentage: 0.9,
          categoryPercentage: 1,
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
                const bucket = buckets[items[0]?.dataIndex ?? 0];
                return `Темп ${formatPace(bucket.from)}-${formatPace(bucket.to)}`;
              },
              label(item) {
                return `Сплитов: ${item.raw}`;
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              maxTicksLimit: 8,
            },
            grid: {color: "rgba(102,116,124,0.10)"},
          },
          y: {
            min: 0,
            ticks: {stepSize: 1},
            grid: {color: "rgba(102,116,124,0.10)"},
          },
        },
      },
    });
  }

  function renderScatterChart() {
    scatterChart = new window.Chart(scatterCanvas.getContext("2d"), {
      type: "scatter",
      data: {
        datasets: [{
          data: points.map((point) => ({x: point.pace_seconds, y: 1, label: point.label, tone: point.tone})),
          backgroundColor: points.map((point) => toneColor(point.tone)),
          borderColor: "#ffffff",
          borderWidth: 1.5,
          pointRadius: 7,
          pointHoverRadius: 9,
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
              label(context) {
                return `Сплит ${context.raw.label}: ${formatPace(context.parsed.x)}`;
              },
            },
          },
        },
        scales: {
          x: {
            min: buckets[0]?.from,
            max: buckets[buckets.length - 1]?.to,
            ticks: {
              callback: formatPace,
              maxTicksLimit: 8,
            },
            grid: {color: "rgba(102,116,124,0.10)"},
          },
          y: {display: false, min: 0, max: 2},
        },
      },
    });
  }

  function toneColor(tone) {
    if (tone === "fast") {
      return "#0f6b4f";
    }
    if (tone === "slow") {
      return "#c63d3d";
    }
    return "#267bc6";
  }

  function formatPace(value) {
    const total = Math.max(Math.round(Number(value) || 0), 0);
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function parseJson(value, fallback) {
    try {
      return value ? JSON.parse(value) : fallback;
    } catch (_error) {
      return fallback;
    }
  }
})();
