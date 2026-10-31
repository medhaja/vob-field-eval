(function () {
  const data = JSON.parse(document.getElementById("sweep-data").textContent);
  const v = data.v;
  const points = data.sweeps[v];
  const baseline = data.baselines[v];
  const slider = document.getElementById("t");
  const out = document.getElementById("t-out");
  const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";
  let chart = null;

  function pointAt(t) {
    return points.reduce((best, p) => (Math.abs(p.threshold - t) < Math.abs(best.threshold - t) ? p : best), points[0]);
  }

  function update() {
    const t = parseFloat(slider.value);
    const p = pointAt(t);
    out.textContent = t.toFixed(2);
    document.getElementById("m-auto").textContent = pct(p.automation_rate, 0);
    document.getElementById("m-auto-n").textContent = p.auto_cases + " cases need no person";
    document.getElementById("m-esc").textContent = pct(p.escaped_error_rate);
    document.getElementById("m-caught").textContent = pct(p.errors_caught, 0);
    document.getElementById("m-staff").textContent = p.review_per_day;
    document.getElementById("queue-link").href = "/queue?v=" + v + "&t=" + t.toFixed(2);
    document.querySelectorAll("[data-version-link]").forEach((a) => {
      a.href = "/threshold?v=" + a.dataset.versionLink + "&t=" + t.toFixed(2);
    });
    document.querySelectorAll("#sweep-table tr[data-t]").forEach((tr) => {
      tr.classList.toggle("current", Math.abs(parseFloat(tr.dataset.t) - t) < 1e-6);
    });
    history.replaceState(null, "", "/threshold?v=" + v + "&t=" + t.toFixed(2));
    if (chart) {
      const idx = points.indexOf(p);
      chart.data.datasets.forEach((ds) => {
        if (ds.marker) ds.pointRadius = points.map((_, i) => (i === idx ? 6 : 0));
      });
      chart.update("none");
    }
  }

  document.getElementById("baseline-note").textContent =
    "Without routing (everything auto-approved), " + pct(baseline.escaped_error_rate) +
    " of cases would go out with at least one wrong field.";

  function draw() {
    if (!window.Chart) return; // chart library unavailable offline; numbers above still update
    const labels = points.map((p) => p.threshold.toFixed(2));
    chart = new Chart(document.getElementById("sweep"), {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Auto-approved", data: points.map((p) => 100 * p.automation_rate), borderColor: "#0e7490",
            backgroundColor: "#0e7490", borderWidth: 2, tension: 0.25, marker: true, pointRadius: 0 },
          { label: "Escaped errors", data: points.map((p) => 100 * p.escaped_error_rate), borderColor: "#c2410c",
            backgroundColor: "#c2410c", borderWidth: 2, tension: 0.25, marker: true, pointRadius: 0 },
          { label: "Escaped errors with no routing", data: points.map(() => 100 * baseline.escaped_error_rate),
            borderColor: "#a1a1aa", borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { min: 0, max: 100, ticks: { callback: (x) => x + "%" }, grid: { color: "#f0f0f2" } },
          x: { title: { display: true, text: "Confidence threshold" }, grid: { display: false } },
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, usePointStyle: true } },
          tooltip: { callbacks: { label: (c) => c.dataset.label + ": " + c.parsed.y.toFixed(1) + "%" } },
        },
      },
    });
    update();
  }

  slider.addEventListener("input", update);
  update();
  if (window.Chart) draw(); else window.addEventListener("load", draw);
})();
