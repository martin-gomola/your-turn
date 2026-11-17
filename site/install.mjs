const getUv = {
  have: [],
  brew: ['brew install uv'],
  script: ['curl -LsSf https://astral.sh/uv/install.sh | sh'],
};
// One command per line, in the order to run them. `install` comes last because it starts the inbox and keeps the terminal.
// PyPI through uv is the one promoted path; Nix stays documented in the README only.
export function installation({uv = 'have', doctor = true, autostart = false} = {}) {
  if (!Object.hasOwn(getUv, uv)) throw Error('Unknown uv choice');
  if (typeof doctor !== 'boolean' || typeof autostart !== 'boolean') throw Error('Invalid option');
  const run = autostart ? 'your-turn' : 'uvx your-turn@latest';
  return [
    ...getUv[uv],
    ...(autostart ? ['uv tool install your-turn'] : []),
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
      : '<path d="M20.5 15.5A8.5 8.5 0 0 1 8.5 3.5 8.5 8.5 0 1 0 20.5 15.5Z"/>';
  }
  byId('theme-toggle').addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch {}
    syncThemeToggle();
  });
  syncThemeToggle();
  let resetCopy;
  const value = name => document.querySelector(`input[name="${name}"]:checked`)?.value;
  function render() {
    clearTimeout(resetCopy);
    byId('copy').textContent = 'Copy commands';
    byId('status').textContent = '';
    const options = {uv: value('uv'), doctor: byId('doctor').checked, autostart: byId('autostart').checked};
    byId('commands').textContent = installation(options);
    byId('summary').textContent = [
      options.doctor ? 'dry run first' : 'no dry run',
      options.autostart ? 'Codex autostart' : 'starts in this terminal',
    ].join(' · ');
    byId('uv-note').hidden = options.uv === 'have';
    byId('autostart-note').hidden = !options.autostart;
  }
  document.querySelector('.choices').addEventListener('change', render);
  byId('copy').addEventListener('click', async () => {
    const command = byId('commands').textContent;
    try {
      await navigator.clipboard.writeText(command);
      if (byId('commands').textContent !== command) return;
      clearTimeout(resetCopy);
      byId('copy').textContent = 'Copied';
      resetCopy = setTimeout(() => { byId('copy').textContent = 'Copy commands'; }, 2500);
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
