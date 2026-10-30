// Filters for the timeline, archive and stories lists. Each entry carries its
// topic and per-region outlet counts (data-eu="2" data-am="1" ...); an entry is
// shown when its topic is on and the outlets from the selected regions add up
// to at least the chosen minimum. Choices are remembered between visits.
(() => {
  const form = document.querySelector(".filters");
  if (!form) return;

  const KEY = "worldline-filters-v2";
  const topics = [...form.querySelectorAll("input[data-topic]")];
  const regions = [...form.querySelectorAll("input[data-region]")];
  const min = form.querySelector("#f-min");
  const count = form.querySelector(".filter-count");
  const reset = form.querySelector(".filter-reset");
  const empty = document.querySelector(".filtered-empty");
  const items = [...document.querySelectorAll(".entry, .story-card")];
  const noun = document.querySelector(".story-card") ? "stories" : "events";
  const defaultMin = min.querySelector("option[selected]").value;

  const state = () => ({
    topics: Object.fromEntries(topics.map((b) => [b.dataset.topic, b.checked])),
    regions: Object.fromEntries(regions.map((b) => [b.dataset.region, b.checked])),
    min: min.value,
  });

  const restore = (saved) => {
    for (const b of topics) b.checked = saved.topics?.[b.dataset.topic] ?? true;
    for (const b of regions) b.checked = saved.regions?.[b.dataset.region] ?? true;
    min.value = saved.min ?? defaultMin;
  };

  const apply = () => {
    const onTopics = new Set(topics.filter((b) => b.checked).map((b) => b.dataset.topic));
    const onRegions = regions.filter((b) => b.checked).map((b) => b.dataset.region);
    const need = Number(min.value);
    let shown = 0;

    for (const el of items) {
      const outlets = onRegions.reduce((sum, r) => sum + Number(el.dataset[r] || 0), 0);
      // A story whose every event came from one outlet is a loose grouping, not a
      // story several outlets followed; it only shows when the minimum is 1.
      const scattered = el.classList.contains("story-card") && el.classList.contains("single");
      const ok = onTopics.has(el.dataset.topic) && outlets >= need && !(scattered && need > 1);
      el.hidden = !ok;
      shown += ok;
    }
    for (const day of document.querySelectorAll(".day")) {
      day.hidden = !day.querySelector(".entry:not([hidden])");
    }
    for (const b of regions) document.documentElement.classList.toggle(`off-${b.dataset.region}`, !b.checked);

    count.textContent = `Showing ${shown} of ${items.length} ${noun}.`;
    if (empty) empty.hidden = shown > 0 || items.length === 0;
    const current = state();
    reset.hidden =
      current.min === defaultMin &&
      Object.values(current.topics).every(Boolean) &&
      Object.values(current.regions).every(Boolean);
    try {
      localStorage.setItem(KEY, JSON.stringify(current));
    } catch {}
  };

  try {
    restore(JSON.parse(localStorage.getItem(KEY) || "{}"));
  } catch {}

  form.addEventListener("change", apply);
  form.addEventListener("submit", (e) => e.preventDefault());
  reset.addEventListener("click", () => {
    restore({});
    apply();
  });

  form.hidden = false;
  document.documentElement.classList.add("filtered");
  apply();
})();
