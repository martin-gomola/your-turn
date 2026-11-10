import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const now = new Date().toISOString();

function inboxPolicy(dismissed = {}, seen = {}) {
  const context = vm.createContext({
    NEW_WINDOW_MS: 86400000, shared: { dismissed }, seen: { get: key => seen[key] || '' },
    chatKey: chat => chat.key, SECTIONS: ['waiting', 'working', 'new', 'earlier'].map(key => ({ key })),
    waitingSince: chat => chat.turn_ended_at || chat.updated_at,
  });
  vm.runInContext(source.slice(source.indexOf('function needsAttention('), source.indexOf('function chatSummary(')) +
    source.slice(source.indexOf('function groupChats('), source.indexOf('function quietFor(')) +
    '\nObject.assign(this, { groupChats, sectionOf, isNewResult, reminderDismissed });', context);
  return context;
}

function withDeck(policy, storage = {}) {
  policy.DECK_REVIEW_KEY = 'your-turn.deck.reviewed';
  policy.deckReviewed = new Map();
  policy.readPreference = key => storage[key] || null;
  policy.localStorage = { setItem: (key, value) => { storage[key] = value; } };
  vm.runInContext(source.slice(source.indexOf('function deckOrder('), source.indexOf('function latestQuota(')) +
    source.slice(source.indexOf('function readDeckReviews('), source.indexOf('if (deckView && !threadId) window.addEventListener("storage"')) +
    '\ndeckReviewed = readDeckReviews(); Object.assign(this, { deckGroups, deckSectionOf, setDeckReview });', policy);
  return policy;
}

test('Inbox fresh results ignore Deck review markers in shared reminder state', () => {
  const chat = { key: 'codex:result', status: 'done', turn_ended_at: now, updated_at: now, outcome: 'Completed' };
  const policy = inboxPolicy({ [chat.key]: `reviewed:${now}` });
  assert.equal(policy.isNewResult(chat), true);
  assert.equal(policy.groupChats([chat]).get('new').length, 1);
  assert.equal(policy.groupChats([chat]).get('earlier').length, 0);
});

test('Inbox running tasks stay Working with absent, cleared, reviewed or stale reminder markers', () => {
  const chat = { key: 'codex:running', status: 'working', working_since: now, updated_at: now };
  for (const marker of [undefined, `cleared:${now}`, `reviewed:${now}`, 'old-request']) {
    const policy = inboxPolicy(marker === undefined ? {} : { [chat.key]: marker });
    assert.equal(policy.groupChats([chat]).get('working').length, 1, marker);
    assert.equal(policy.groupChats([chat]).get('earlier').length, 0, marker);
  }
});

test('Inbox reminder dismissal and seen results retain their original classification', () => {
  const request = { key: 'codex:request', status: 'done', needs_you: true, attention_key: 'request-1', updated_at: now, turn_ended_at: now };
  assert.equal(inboxPolicy().sectionOf(request), 'waiting');
  assert.equal(inboxPolicy({ [request.key]: 'request-1' }).sectionOf(request), 'earlier');
  assert.equal(inboxPolicy({ [request.key]: 'request-1' }).sectionOf({ ...request, attention_key: 'request-2' }), 'waiting');
  assert.equal(inboxPolicy({ [request.key]: 'request-1' }).sectionOf({ ...request, status: 'working' }), 'working');
  const done = { key: 'codex:seen', status: 'done', updated_at: now, turn_ended_at: now, outcome: 'Done' };
  assert.equal(inboxPolicy({}, { [done.key]: now }).sectionOf(done), 'earlier');
});

test('Deck review and Undo are view-local and never mutate Inbox reminder or seen state', () => {
  const chat = { key: 'codex:result', status: 'done', turn_ended_at: now, updated_at: now, outcome: 'Completed' };
  const dismissed = {}, seen = {}, storage = {};
  const policy = withDeck(inboxPolicy(dismissed, seen), storage);
  policy.setDeckReview(chat.key, now);
  assert.deepEqual(dismissed, {});
  assert.deepEqual(seen, {});
  assert.deepEqual(Object.keys(storage), ['your-turn.deck.reviewed']);
  assert.equal(policy.groupChats([chat]).get('new').length, 1);
  assert.equal(policy.deckGroups([chat]).get('new').length, 0);
  assert.equal(policy.deckGroups([chat]).get('earlier').length, 1);
  const reloaded = withDeck(inboxPolicy(dismissed, seen), storage);
  assert.equal(reloaded.deckSectionOf(chat), 'earlier');
  reloaded.setDeckReview(chat.key, null);
  assert.equal(reloaded.deckSectionOf(chat), 'new');
  assert.equal(reloaded.sectionOf(chat), 'new');
  assert.deepEqual(dismissed, {});
});

test('legacy Deck markers affect only Deck, and never reclassify a running task', () => {
  const chat = { key:'codex:legacy', status:'done', turn_ended_at:now, updated_at:now, outcome:'Completed' };
  const dismissed = { [chat.key]:`reviewed:${now}` };
  const policy = withDeck(inboxPolicy(dismissed));
  assert.equal(policy.sectionOf(chat), 'new');
  assert.equal(policy.deckSectionOf(chat), 'earlier');
  assert.equal(policy.deckGroups([{...chat,status:'working'}]).get('working').length, 1);
  policy.setDeckReview(chat.key, null);
  assert.equal(policy.deckSectionOf(chat), 'new');
  assert.equal(dismissed[chat.key], `reviewed:${now}`, 'legacy shared state is not rewritten');
});

test('a quiet Working chat set aside on Deck moves to Earlier until it writes again', () => {
  const chat = { key:'claude:stale', status:'working', quiet:true, updated_at:now };
  const policy = withDeck(inboxPolicy());
  policy.setDeckReview(chat.key, `quiet:${now}`);
  assert.equal(policy.deckSectionOf(chat), 'earlier');
  assert.equal(policy.deckGroups([chat]).get('working').length, 0);
  assert.equal(policy.sectionOf(chat), 'working', 'Inbox still shows it working');
  assert.equal(policy.deckSectionOf({...chat, updated_at:'2099-01-01T00:00:00Z'}), 'working');
});

test('invalid Deck browser storage cannot affect Inbox classification', () => {
  const policy = withDeck(inboxPolicy(), { 'your-turn.deck.reviewed':'not-json' });
  const chat = { key:'codex:running',status:'working',updated_at:now };
  assert.equal(policy.sectionOf(chat), 'working');
  assert.equal(policy.deckSectionOf(chat), 'working');
});
