"use strict";

// Full screen belongs to this page and the app navigates inside the frame, so page loads never end it.
(() => {
  const frame = document.getElementById("app");
  const enter = document.getElementById("enter");
  const target = new URL(new URLSearchParams(location.search).get("to") || "/", location.origin);
  frame.src = target.origin === location.origin ? target.pathname + target.search : "/";

  const sync = () => { enter.hidden = Boolean(document.fullscreenElement); };
  document.getElementById("enter-button").addEventListener("click", () => {
    document.documentElement.requestFullscreen().catch(() => {});
  });
  document.getElementById("leave").addEventListener("click", (event) => {
    event.preventDefault();
    const inner = frame.contentWindow.location;
    location.assign(inner.pathname + inner.search);
  });
  frame.addEventListener("load", () => { document.title = frame.contentDocument.title || "Your Turn"; });
  document.addEventListener("fullscreenchange", sync);
  sync();
})();
