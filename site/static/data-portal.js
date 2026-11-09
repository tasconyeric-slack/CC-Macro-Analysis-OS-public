// All curves are rendered at build time. Range selection never calls a network API.
document.querySelectorAll('.data-metric').forEach(function (card) {
  card.querySelectorAll('[data-range]').forEach(function (button) {
    button.addEventListener('click', function () {
      card.querySelectorAll('[data-range]').forEach(function (b) {
        b.setAttribute('aria-pressed', String(b === button));
      });
      card.querySelectorAll('[data-range-plot]').forEach(function (plot) {
        plot.hidden = plot.dataset.rangePlot !== button.dataset.range;
      });
    });
  });
});
