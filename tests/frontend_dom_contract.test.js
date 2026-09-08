'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');

test('Action Queue browser shell exposes persistent review controls', () => {
  for (const id of ['viewMode', 'queueControls', 'minProbability', 'minSamples', 'marketTypeFilter', 'newOnly', 'queueSummary']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `missing #${id}`);
  }
  assert.match(html, /data-view="queue"/);
  assert.match(html, /action-queue\.js/);
});

test('ticker detail includes an accessible four-VWAP state map mount', () => {
  assert.match(html, /id="stateMap"/);
  assert.match(html, /aria-label="Close to rolling VWAP state map"/);
});

test('inline browser application parses as JavaScript', () => {
  const inlineScripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .filter(match => match[1].trim())
    .map(match => match[1]);
  assert.equal(inlineScripts.length, 1);
  assert.doesNotThrow(() => new vm.Script(inlineScripts[0], { filename: 'static/index.html:inline' }));
});

test('existing scanner capabilities remain present', () => {
  for (const id of ['periods', 'positions', 'historyFilter', 'capFilters', 'watchFilter', 'favoriteFilter', 'alertFilter', 'trackerToggle', 'notificationToggle', 'themeToggle']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `regressed #${id}`);
  }
  assert.match(html, /lightweight-charts\.standalone\.production\.js/);
  assert.match(html, /market-kind/);
});
