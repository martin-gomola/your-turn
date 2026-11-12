"use strict";

// Resolve header density before first paint, alongside appearance.
try {
  // Without a saved choice, shorter windows start compact so the first chats sit above the fold.
  const saved = localStorage.getItem("compact-header");
  document.documentElement.dataset.header = saved === "true" || (saved === null && innerHeight < 1100) ? "compact" : "full";
} catch {
  document.documentElement.dataset.header = "full";
}
// Deck shows unless it was turned off; its theme is Dark unless Warm was chosen.
try {
  document.documentElement.dataset.deckEnabled = String(localStorage.getItem("your-turn.deck.enabled") !== "false");
  const deckTheme = localStorage.getItem("your-turn.deck.theme");
  document.documentElement.dataset.deckTheme = deckTheme === "warm" ? "warm" : "dark";
} catch {
  document.documentElement.dataset.deckEnabled = "true";
  document.documentElement.dataset.deckTheme = "dark";
}

// Loaded without defer so the theme is set before first paint.
(() => {
  const system = matchMedia("(prefers-color-scheme: dark)");
  const stored = () => {
    try {
      return localStorage.getItem("theme");
    } catch {
      return null;
    }
  };
  let preference = stored();
  // A chat opened from Deck keeps Deck's dark surface whatever the saved appearance.
  const query = new URLSearchParams(location.search);
  const deckChat = query.has("thread") && query.get("view") === "deck";
  const apply = () => {
    const theme = preference;
    const dark = deckChat || theme === "dark" || (theme !== "light" && system.matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#151515" : "#fcfbfa");
    document.dispatchEvent(new Event("themechange"));
  };
  window.YourTurnTheme = {
    preference: () => preference === "light" || preference === "dark" ? preference : "system",
    set: (value) => {
      preference = value === "light" || value === "dark" ? value : null;
      let saved = true;
      try {
        if (preference) localStorage.setItem("theme", preference);
        else localStorage.removeItem("theme");
      } catch { saved = false; }
      apply();
      return saved;
    },
  };
  apply();
  system.addEventListener("change", apply);
  addEventListener("storage", (event) => {
    if (event.key === "theme" || event.key === null) { preference = stored(); apply(); }
  });
})();
