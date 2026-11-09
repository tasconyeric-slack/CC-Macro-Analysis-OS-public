// Crosshair + tooltip for server-rendered line charts. Data comes from the
// <script type="application/json" data-for="..."> block next to each SVG.
document.querySelectorAll("svg.chart").forEach(function (svg) {
  var holder = document.querySelector('script[data-for="' + svg.id + '"]');
  if (!holder) return;
  var d = JSON.parse(holder.textContent);
  var card = svg.closest(".chartcard") || svg.parentElement;
  var cross = svg.querySelector(".cross");
  var tip = document.createElement("div");
  tip.className = "tip";
  tip.hidden = true;
  card.appendChild(tip);
  function move(evt) {
    var pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    var p = pt.matrixTransform(svg.getScreenCTM().inverse());
    var best = 0;
    for (var i = 1; i < d.x.length; i++) if (Math.abs(d.x[i] - p.x) < Math.abs(d.x[best] - p.x)) best = i;
    cross.setAttribute("x1", d.x[best]); cross.setAttribute("x2", d.x[best]);
    cross.setAttribute("y1", d.top); cross.setAttribute("y2", d.bottom);
    cross.setAttribute("visibility", "visible");
    var screen = svg.createSVGPoint();
    screen.x = d.x[best]; screen.y = d.y[best];
    var s = screen.matrixTransform(svg.getScreenCTM());
    var c = card.getBoundingClientRect();
    tip.style.left = (s.x - c.left) + "px";
    tip.style.top = (s.y - c.top) + "px";
    tip.textContent = d.labels[best] + "  ·  " + d.values[best] + (d.details && d.details[best] ? " · " + d.details[best] : "");
    tip.hidden = false;
  }
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerleave", function () { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
});
