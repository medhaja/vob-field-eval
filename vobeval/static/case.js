(function () {
  const doc = document.querySelector(".doc");
  function focusKey(key, scroll) {
    document.querySelectorAll(".src.focus, .fcell.focus").forEach((el) => el.classList.remove("focus"));
    const src = document.getElementById("src-" + key);
    const cell = document.querySelector('.fcell[data-key="' + key + '"]');
    if (src) {
      src.classList.add("focus");
      if (scroll) {
        const top = src.offsetTop - doc.offsetTop - doc.clientHeight / 3;
        doc.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      }
    }
    if (cell) cell.classList.add("focus");
  }
  document.querySelectorAll(".fcell").forEach((cell) => {
    cell.addEventListener("mouseenter", () => focusKey(cell.dataset.key, true));
    cell.querySelector("input").addEventListener("focus", () => focusKey(cell.dataset.key, true));
  });
  document.querySelectorAll(".src").forEach((m) => {
    m.addEventListener("click", () => {
      focusKey(m.dataset.key, false);
      const input = document.querySelector('.fcell[data-key="' + m.dataset.key + '"] input');
      if (input) input.focus({ preventScroll: false });
    });
  });
  document.querySelectorAll(".key-link").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      focusKey(a.dataset.key, true);
      const input = document.querySelector('.fcell[data-key="' + a.dataset.key + '"] input');
      if (input) input.focus();
    });
  });
  const reveal = document.getElementById("reveal-gold");
  if (reveal) {
    reveal.addEventListener("change", () => document.body.classList.toggle("show-gold", reveal.checked));
  }
})();
