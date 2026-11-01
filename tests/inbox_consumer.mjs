// Reads `{rows, now}` on stdin and prints how app.js files each inbox row: its section and its tag's tooltip.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const slice = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));
const { rows, now } = JSON.parse(readFileSync(0, 'utf8'));
const context = vm.createContext({});
vm.runInContext([
  `Date.now = () => ${Number(now)};`,
  'const NEW_WINDOW_MS = 24 * 60 * 60 * 1000;',
  slice('const APP_NAME', 'const QUIET_NOTIFY_MS'),
  slice('function chatKey(chat)', 'function isChat('),
  'const shared = { seen: {}, dismissed: {} }; const seen = { get: (key) => shared.seen[key] || "" };',
  slice('function needsAttention(chat)', 'function chatSummary('),
  // Before `unknownNote`, every unknown row's tooltip was `unavailableNote`.
  'Object.assign(this, { sectionOf, attentionState, unknownNote: typeof unknownNote === "function" ? unknownNote : unavailableNote });',
].join('\n'), context);

const result = rows.map((chat) => ({
  key: chat.key,
  section: context.sectionOf(chat),
  state: context.attentionState(chat),
  tooltip: context.attentionState(chat) === 'unknown' ? context.unknownNote(chat) : '',
}));
process.stdout.write(JSON.stringify(result));
