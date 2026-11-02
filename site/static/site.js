// Small progressive enhancements. The site works without this file: every language link already
// points at the equivalent page in the other language.
(function () {
  var KEY = "ccmacro.locale";

  // 1. Language switch: keep the #fragment so the reader lands on the same section, and remember
  //    an explicit choice so "/" can send them back to it.
  var links = document.querySelectorAll("a[data-lang]");
  function carryHash() {
    links.forEach(function (a) { a.href = a.getAttribute("data-base") + location.hash; });
  }
  links.forEach(function (a) {
    a.addEventListener("click", function () {
      carryHash();
      try { localStorage.setItem(KEY, a.getAttribute("data-lang")); } catch (e) { /* storage may be blocked */ }
    });
  });
  carryHash();
  window.addEventListener("hashchange", carryHash);

  // 2. A fragment that differs only in case (#h2 for #H2) still scrolls to its section.
  function matchFragment() {
    var raw = location.hash.slice(1);
    if (!raw) return;
    var id; try { id = decodeURIComponent(raw); } catch (e) { id = raw; }
    if (document.getElementById(id)) return;
    var low = id.toLowerCase(), hit = null, all = document.querySelectorAll("[id]");
    for (var i = 0; i < all.length && !hit; i++) if (all[i].id.toLowerCase() === low) hit = all[i];
    if (hit) hit.scrollIntoView();
  }
  matchFragment();
  window.addEventListener("hashchange", matchFragment);

  // 3. A fragment that points inside a closed <details> (a claim's lineage) opens it.
  function openTarget() {
    var el = location.hash.length > 1 && document.getElementById(decodeURIComponent(location.hash.slice(1)));
    for (var n = el; n; n = n.parentElement) if (n.tagName === "DETAILS") n.open = true;
  }
  openTarget();
  window.addEventListener("hashchange", openTarget);

  // 4. Print / save as PDF for the Deep Dive
  document.querySelectorAll("[data-print]").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });
})();
