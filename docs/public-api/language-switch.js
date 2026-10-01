// Keep readers on the same topic when both editions contain the page.
// A Chinese-only field reference falls back to the English overview.
document.addEventListener("click", async (event) => {
  const link = event.target.closest("a.md-select__link[hreflang]");
  const source = window.location.pathname.match(/^\/(en|zh)\/(.*)$/);
  if (!link || !source) return;

  const target = link.getAttribute("hreflang");
  if (target !== "en" && target !== "zh") return;
  event.preventDefault();
  event.stopImmediatePropagation();

  const candidate = `/${target}/${source[2]}`;
  const fallback = `/${target}/`;
  if (candidate === fallback) {
    window.location.assign(fallback);
    return;
  }
  try {
    const response = await fetch(candidate, { method: "HEAD", cache: "no-store" });
    window.location.assign(response.ok ? candidate : fallback);
  } catch (_) {
    window.location.assign(fallback);
  }
}, true);
