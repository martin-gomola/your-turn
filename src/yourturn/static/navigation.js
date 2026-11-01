"use strict";

// Tag only the split-inbox → same-chat navigation; other page transitions keep their own motion.
(() => {
  const markCollapse = (event, from, to) => {
    if (!event.viewTransition || !to || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const source = from ? new URL(from) : null, target = new URL(to);
    // The chat-only route carries its originating split view even when activation.from is unavailable.
    const open = source ? source.searchParams.get("open") : target.searchParams.get("returnOpen");
    if (!open || target.searchParams.get("thread") !== open || (source &&
        (source.origin !== target.origin || source.pathname !== target.pathname || source.searchParams.has("thread")))) return;
    event.viewTransition.types.delete("page");
    event.viewTransition.types.add("hide-inbox");
    document.documentElement.dataset.sidebarNavigation = "hide";
  };
  addEventListener("pageswap", (event) => markCollapse(event, location.href, event.activation?.entry?.url));
  addEventListener("pagereveal", (event) => {
    delete document.documentElement.dataset.sidebarNavigation;
    markCollapse(event, globalThis.navigation?.activation?.from?.url, location.href);
  });
})();
