/* Starts each [data-chart] SVG's entrance animation (site/assets/charts.css)
 * once 30% of it is on screen. Without IntersectionObserver, all start at
 * once. No dependencies, no modules. */
(function () {
  "use strict";

  function start() {
    var charts = Array.prototype.slice.call(document.querySelectorAll("[data-chart]"));
    if (!("IntersectionObserver" in window)) {
      charts.forEach(function (chart) {
        chart.classList.add("play");
      });
      return;
    }
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.3) {
            entry.target.classList.add("play");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.3 }
    );
    charts.forEach(function (chart) {
      observer.observe(chart);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
