(function () {
  const card = document.querySelector(".error-reasons-card");
  if (!card) {
    return;
  }

  const stats = parseJson(card.dataset.errorReasons, {});
  const tabs = Array.from(card.querySelectorAll("[data-error-reasons-tab]"));
  const sections = {
    top: card.querySelector("#error-reasons-top"),
    trend: card.querySelector("#error-reasons-trend"),
  };
  let chart = null;

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.errorReasonsTab));
  });

  renderLegend();

  function activateTab(name) {
    tabs.forEach((tab) => {
      const isActive = tab.dataset.errorReasonsTab === name;
      tab.classList.toggle("active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    Object.entries(sections).forEach(([sectionName, section]) => {
      if (!section) {
        return;
      }
      const isActive = sectionName === name;
      section.classList.toggle("active", isActive);
      section.hidden = !isActive;
    });
    if (name === "trend") {
      renderChart();
    }
  }

  function renderChart() {
    if (chart || !window.Chart || !stats.dates?.length || !stats.reasons?.length) {
      return;
    }
    const canvas = card.querySelector("#error-reasons-chart");
    if (!canvas) {
      return;
    }
    chart = new window.Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: stats.dates,
        datasets: stats.reasons.map((reason, index) => ({
          label: reason.label,
          data: reason.trend,
          borderColor: reason.color,
          backgroundColor: `${reason.color}22`,
          borderWidth: index === 0 ? 2.5 : 1.5,
          pointRadius: 4,
          tension: 0.3,
          fill: false,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: {display: false},
          tooltip: {mode: "index", intersect: false},
        },
        scales: {
          x: {
            grid: {color: "rgba(102, 116, 124, 0.12)"},
            ticks: {font: {size: 12}},
          },
          y: {
            min: 0,
            ticks: {stepSize: 1, font: {size: 12}},
            grid: {color: "rgba(102, 116, 124, 0.12)"},
          },
        },
      },
    });
  }

  function renderLegend() {
    const legend = card.querySelector(".error-reasons-legend");
    if (!legend || !stats.reasons?.length) {
      return;
    }
    legend.replaceChildren(
      ...stats.reasons.map((reason) => {
        const item = document.createElement("span");
        item.className = "error-reasons-legend-item";

        const dot = document.createElement("span");
        dot.className = "error-reasons-legend-dot";
        dot.style.background = reason.color;

        item.append(dot, document.createTextNode(reason.label));
        return item;
      })
    );
  }

  function parseJson(value, fallback) {
    try {
      return value ? JSON.parse(value) : fallback;
    } catch (_error) {
      return fallback;
    }
  }
})();
