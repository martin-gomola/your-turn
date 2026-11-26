const getUv = {
  have: [],
  brew: ['brew install uv'],
  script: ['curl -LsSf https://astral.sh/uv/install.sh | sh'],
};
// One command per line, in the order to run them. `install` comes last because it starts the inbox and keeps the terminal.
// PyPI through uv is the one promoted path; Nix stays documented in the README only.
export function installation({uv = 'have', doctor = false, autostart = false} = {}) {
  if (!Object.hasOwn(getUv, uv)) throw Error('Unknown uv choice');
  if (typeof doctor !== 'boolean' || typeof autostart !== 'boolean') throw Error('Invalid option');
  const run = autostart ? 'your-turn' : 'uvx your-turn@latest';
  return [
    ...getUv[uv],
    ...(autostart ? ['uv tool install your-turn@latest'] : []),
    ...(doctor ? [`${run} doctor`] : []),
    ...(autostart ? ['your-turn autostart enable'] : []),
    `${run} install`,
  ].join('\n');
}

if (typeof document !== 'undefined') {
  const byId = id => document.getElementById(id);

  function syncThemeToggle() {
    const dark = document.documentElement.dataset.theme === 'dark';
    const label = `Switch to ${dark ? 'light' : 'dark'} theme`;
    byId('theme-toggle').setAttribute('aria-label', label);
    byId('theme-toggle').title = label;
    byId('theme-toggle').querySelector('svg').innerHTML = dark
      ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>'
      : '<path d="M20.5 15.5A8.5 8.5 0 0 1 8.5 3.5a8.5 8.5 0 1 0 12 12Z"/>';
  }
  byId('theme-toggle').addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch {}
    syncThemeToggle();
  });
  syncThemeToggle();

  // Product view tabs (Inbox / Deck / Launcher) with roving tabindex and keyboard support.
  const tabs = [...document.querySelectorAll('.view-tab')];
  const caption = byId('showcase-caption');
  function selectTab(nextTab, {focus = false} = {}) {
    tabs.forEach(tab => {
      const active = tab === nextTab;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      const panel = byId(tab.getAttribute('aria-controls'));
      if (panel) {
        panel.hidden = !active;
        if (active && caption && panel.dataset.caption) caption.textContent = panel.dataset.caption;
      }
    });
    if (focus) nextTab.focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', event => {
      if (event.key === 'ArrowRight') { event.preventDefault(); selectTab(tabs[(index + 1) % tabs.length], {focus: true}); }
      else if (event.key === 'ArrowLeft') { event.preventDefault(); selectTab(tabs[(index - 1 + tabs.length) % tabs.length], {focus: true}); }
      else if (event.key === 'Home') { event.preventDefault(); selectTab(tabs[0], {focus: true}); }
      else if (event.key === 'End') { event.preventDefault(); selectTab(tabs[tabs.length - 1], {focus: true}); }
    });
  });

  let resetCopy;
  // One span per line so CSS can draw the $ prompt; tokens get colours. textContent stays the commands.
  function paint(target, commands) {
    target.replaceChildren(...commands.split('\n').flatMap((line, index) => {
      const row = document.createElement('span'); row.className = 'line';
      line.split(/(\s+)/).forEach((token, position) => {
        if (!token.trim()) { row.append(token); return; }
        const kind = position === 0 ? 'cmd' : /^https?:|^\|$/.test(token) ? 'muted' : token.startsWith('your-turn') ? 'repo' : token.startsWith('-') ? 'flag' : 'arg';
        const span = document.createElement('span'); span.className = `tok-${kind}`; span.textContent = token; row.append(span);
      });
      return index ? ['\n', row] : [row];
    }));
  }

  const value = name => document.querySelector(`input[name="${name}"]:checked`)?.value;
  function render() {
    clearTimeout(resetCopy);
    byId('copy').textContent = 'Copy commands';
    byId('copy').removeAttribute('data-copied');
    byId('status').textContent = '';
    const options = {uv: value('uv'), doctor: byId('doctor').checked, autostart: byId('autostart').checked};
    paint(byId('commands'), installation(options));
    byId('uv-note').hidden = options.uv === 'have';
    byId('autostart-note').hidden = !options.autostart;
    const runNote = byId('run-note');
    if (runNote) {
      runNote.innerHTML = options.autostart
        ? 'Paste in a terminal, restart your agent apps, and open <a href="http://localhost:8787">localhost:8787</a>. Future Codex sessions reuse the background inbox.'
        : 'Paste in a terminal, restart your agent apps, and open <a href="http://localhost:8787">localhost:8787</a>. Keep the terminal open; Ctrl+C stops the inbox.';
    }
  }
  document.querySelector('.choices').addEventListener('change', render);

  byId('copy').addEventListener('click', async () => {
    const command = byId('commands').textContent;
    try {
      await navigator.clipboard.writeText(command);
      if (byId('commands').textContent !== command) return;
      clearTimeout(resetCopy);
      byId('copy').textContent = '✓ Copied to clipboard';
      byId('copy').dataset.copied = '';
      resetCopy = setTimeout(() => { byId('copy').textContent = 'Copy commands'; byId('copy').removeAttribute('data-copied'); }, 1800);
      byId('status').textContent = 'Commands copied. Paste them in your terminal.';
    } catch {
      if (byId('commands').textContent !== command) return;
      clearTimeout(resetCopy);
      byId('copy').textContent = 'Copy manually';
      const selection = getSelection(); const range = document.createRange();
      range.selectNodeContents(byId('commands'));
      selection.removeAllRanges(); selection.addRange(range);
      byId('status').textContent = 'Clipboard unavailable. Copy the selected commands manually.';
    }
  });
  render();

  // The footer names the release the commands install. A failed lookup leaves it hidden rather than guessing.
  fetch('https://pypi.org/pypi/your-turn/json')
    .then((response) => response.ok ? response.json() : Promise.reject())
    .then(({info}) => {
      if (!/^\d+\.\d+\.\d+/.test(info?.version || '')) return;
      byId('version').textContent = `v${info.version} on PyPI`;
      byId('version').href = `https://pypi.org/project/your-turn/${info.version}/`;
      byId('version').hidden = false;
    })
    .catch(() => {});
}
