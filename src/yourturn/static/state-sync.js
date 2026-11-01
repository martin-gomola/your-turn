"use strict";

(() => {
  const KEY = "your-turn:inbox-state:v2";
  const empty = () => ({ seen: {}, dismissed: {}, dismissed_at: {} });
  function clean(raw) {
    const state = empty();
    for (const name of Object.keys(state)) {
      for (const [key, value] of Object.entries(raw?.[name] || {})) {
        if (!/^(codex|claude|cursor):[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(key)) continue;
        if (name === "dismissed_at" ? Number.isSafeInteger(value) && value >= 0
          : typeof value === "string" || (name === "dismissed" && value === null)) state[name][key] = value;
      }
    }
    return state;
  }
  function merge(target, source) {
    for (const [key, value] of Object.entries(source.seen)) {
      target.seen[key] = value > (target.seen[key] || "") ? value : target.seen[key] || "";
    }
    for (const [key, value] of Object.entries(source.dismissed)) {
      const stamp = source.dismissed_at[key] || 0, previous = target.dismissed_at[key] || 0;
      if (!Object.hasOwn(target.dismissed, key) || stamp > previous ||
          (stamp === previous && (value === null || (target.dismissed[key] !== null && value > target.dismissed[key])))) {
        target.dismissed[key] = value;
        target.dismissed_at[key] = stamp;
      }
    }
  }

  window.YourTurnState = class {
    constructor() {
      this.data = empty();
      this.remote = empty();
      this.ready = false;
      this.sending = false;
      this.known = null;
      this.readBackup();
    }
    readBackup() {
      try { merge(this.data, clean(JSON.parse(localStorage.getItem(KEY)))); } catch { /* Storage may be unavailable. */ }
      this.prune();
    }
    prune() {
      if (!this.known) return;
      for (const state of [this.data, this.remote]) {
        for (const values of Object.values(state)) {
          for (const key of Object.keys(values)) if (!this.known.has(key)) delete values[key];
        }
      }
    }
    retain(keys) {
      this.known = new Set(keys);
      this.prune();
      this.persist();
      return this.flush();
    }
    persist() {
      // Merge other tabs before writing, and serialize consistently to avoid storage-event loops.
      this.readBackup();
      try {
        const serialized = JSON.stringify(Object.fromEntries(Object.entries(this.data).map(([name, values]) =>
          [name, Object.fromEntries(Object.entries(values).sort(([a], [b]) => a.localeCompare(b)))])));
        if (localStorage.getItem(KEY) !== serialized) localStorage.setItem(KEY, serialized);
      } catch { /* Server sync still works. */ }
    }
    save(change) {
      this.readBackup();
      const update = clean(change);
      for (const key of Object.keys(update.dismissed)) {
        update.dismissed_at[key] = Math.max(Date.now(), (this.data.dismissed_at[key] || 0) + 1);
      }
      merge(this.data, update);
      this.persist();
      return this.flush();
    }
    receive(snapshot) {
      this.remote = clean(snapshot);
      merge(this.data, this.remote);
      this.prune();
      // A server still running the old protocol must restart before accepting versioned backups.
      this.ready = Object.hasOwn(snapshot, "dismissed_at");
      this.persist();
      return this.flush();
    }
    async flush() {
      if (!this.ready || !this.known || this.sending) return;
      const change = empty();
      for (const [key, value] of Object.entries(this.data.seen)) {
        if (value > (this.remote.seen[key] || "")) change.seen[key] = value;
      }
      for (const [key, value] of Object.entries(this.data.dismissed)) {
        const stamp = this.data.dismissed_at[key] || 0, previous = this.remote.dismissed_at[key] || 0;
        if (!Object.hasOwn(this.remote.dismissed, key) || stamp > previous ||
            (stamp === previous && this.remote.dismissed[key] !== null &&
              (value === null || value > this.remote.dismissed[key]))) {
          change.dismissed[key] = value;
          change.dismissed_at[key] = stamp;
        }
      }
      if (!Object.keys(change.seen).length && !Object.keys(change.dismissed).length) return;
      this.sending = true;
      let saved = false;
      try {
        const response = await fetch("/api/state", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(change), signal: AbortSignal.timeout(5000) });
        if (response.ok) { merge(this.remote, change); saved = true; }
      } catch { /* Keep the local copy and retry on reconnect, online, or the next timer tick. */ }
      finally { this.sending = false; }
      if (saved) return this.flush();
    }
  };
  window.YourTurnState.storageKey = KEY;
})();
