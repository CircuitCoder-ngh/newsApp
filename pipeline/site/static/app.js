// Filtering itself is pure CSS (see style.css); this only remembers the
// choices between visits and hides day headings left with nothing under them.
(() => {
  const KEY = "worldline-filters";
  const boxes = [...document.querySelectorAll(".filters input[type=checkbox]")];
  if (!boxes.length) return;

  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    for (const box of boxes) if (box.id in saved) box.checked = saved[box.id];
  } catch {}

  const shown = (el) => getComputedStyle(el).display !== "none";

  const sync = () => {
    let any = false;
    for (const day of document.querySelectorAll(".day")) {
      const visible = [...day.querySelectorAll(".entry")].some(shown);
      day.hidden = !visible;
      any ||= visible;
    }
    for (const card of document.querySelectorAll(".story-card")) any ||= shown(card);
    const empty = document.querySelector(".filtered-empty");
    if (empty) empty.hidden = any;
    try {
      localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(boxes.map((b) => [b.id, b.checked]))));
    } catch {}
  };

  for (const box of boxes) box.addEventListener("change", sync);
  sync();
})();
