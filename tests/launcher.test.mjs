import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const controls = source.slice(source.indexOf('const deckLaunchPages ='), source.indexOf('$("deck-launcher").addEventListener'));

function setup(reduced = false) {
  const events = {}, scrolls = [], pages = [{ offsetLeft: 0 }, { offsetLeft: 816 }];
  const button = dataset => ({ dataset, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute(k) { delete this.attrs[k]; }, focus() { document.activeElement = this; } });
  const dots = [button({ launchPage: '0' }), button({ launchPage: '1' })];
  const document = { activeElement: null }, position = {};
  const apps = {
    clientWidth: 800, scrollLeft: 0, querySelectorAll: () => pages,
    addEventListener: (name, fn) => { events[name] = fn; },
    scrollTo(options) { scrolls.push(options); this.scrollLeft = options.left; },
    focus() { document.activeElement = this; },
  };
  const nav = {
    querySelectorAll: () => dots,
    addEventListener: (name, fn) => { events[`nav-${name}`] = fn; },
  };
  let resize, settle;
  vm.runInNewContext(controls, {
    deckLaunchApps: apps, document, calm: { matches: reduced },
    $: id => id === 'deck-launch-pagination' ? nav : position,
    ResizeObserver: class { constructor(fn) { resize = fn; } observe() {} },
    clearTimeout() {}, setTimeout(fn) { settle = fn; },
  });
  const key = key => {
    const event = { key, preventDefault() { this.defaultPrevented = true; } };
    events.keydown(event);
    return event;
  };
  return { apps, pages, dots, position, scrolls, document, key,
    resize: () => resize(), scroll: left => { apps.scrollLeft = left; events.scroll(); settle(); },
    click(control) { control.focus(); events['nav-click']({ target: { closest: () => control } }); },
  };
}

test('page controls bound navigation, keep one accessible page and retain keyboard focus', () => {
  const b = setup();
  assert.equal(b.pages[1].inert, true);
  b.click(b.dots[1]);
  assert.equal(b.pages[0].inert, true);
  assert.equal(b.pages[1].inert, false);
  assert.equal(b.dots[1].attrs['aria-current'], 'page');
  assert.equal(b.document.activeElement, b.dots[1]);
  assert.equal(b.position.textContent, 'Shortcuts page 2 of 2');
  assert.equal(b.key('ArrowRight').defaultPrevented, true);
  assert.equal(b.scrolls.at(-1).left, 816);
  b.key('Home');
  assert.equal(b.scrolls.at(-1).left, 0);
  assert.equal(b.key('Enter').defaultPrevented, undefined);
});

test('native scrolling and rotation keep the current page; reduced motion never animates', () => {
  const b = setup(true);
  b.scroll(816);
  assert.equal(b.dots[1].attrs['aria-current'], 'page');
  b.pages[1].offsetLeft = 416;
  b.resize();
  assert.equal(b.scrolls.at(-1).left, 416);
  assert.equal(b.scrolls.at(-1).behavior, 'instant');
  b.key('ArrowLeft');
  assert.equal(b.scrolls.at(-1).left, 0);
  assert.equal(b.scrolls.at(-1).behavior, 'instant');
});
