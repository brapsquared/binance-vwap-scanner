'use strict';

// Browser QA harness. Start Chromium/Brave with --remote-debugging-port=9228,
// then run: node tests/run_frontend_browser_qa.js http://127.0.0.1:9228 http://127.0.0.1:8798

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const cdpBase = process.argv[2] || 'http://127.0.0.1:9228';
const appUrl = process.argv[3] || 'http://127.0.0.1:8798';
const outputDir = process.argv[4] || os.tmpdir();

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const assert = (condition, message) => { if (!condition) throw new Error(message); };

async function main() {
  const target = await fetch(`${cdpBase}/json/new?${encodeURIComponent(appUrl)}`, { method: 'PUT' }).then(response => {
    if (!response.ok) throw new Error(`CDP target creation failed: ${response.status}`);
    return response.json();
  });
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  const pending = new Map();
  const exceptions = [];
  let id = 0;
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      return message.error ? reject(new Error(message.error.message)) : resolve(message.result);
    }
    if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails.text);
  };
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = () => reject(new Error('CDP WebSocket connection failed'));
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id;
    pending.set(requestId, { resolve, reject });
    socket.send(JSON.stringify({ id: requestId, method, params }));
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const screenshot = async name => {
    const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    const destination = path.join(outputDir, name);
    fs.writeFileSync(destination, Buffer.from(result.data, 'base64'));
    return destination;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: appUrl });
  await wait(1200);
  await evaluate(`localStorage.clear(); localStorage.setItem('vwap-prefs', JSON.stringify({view:'queue',minProbability:0.5,minSamples:0,marketType:'all',newOnly:false,period:'365'})); location.reload()`);
  await wait(1500);

  const desktop = await evaluate(`(() => ({
    queueVisible: !document.querySelector('#queueControls').hidden,
    scannerHidden: document.querySelector('#scannerControls').hidden,
    queueRows: [...document.querySelectorAll('#rows tr[data-symbol]')].map(row => row.dataset.symbol),
    stateNodes: document.querySelectorAll('#stateMap .state-node').length,
    summary: document.querySelector('#queueSummary').textContent,
    perpTagged: document.querySelector('#rows [data-symbol="BETAUSDT"] .market-kind')?.textContent,
    chartPresent: !!document.querySelector('#chart canvas'),
  }))()`);
  assert(desktop.queueVisible && desktop.scannerHidden, 'Action Queue view did not replace scanner controls');
  assert(desktop.queueRows.join(',') === 'ALPHAUSDT,BETAUSDT', `unexpected queue order: ${desktop.queueRows}`);
  assert(desktop.stateNodes === 5, `expected five state-map nodes, got ${desktop.stateNodes}`);
  assert(desktop.perpTagged === 'PERP', 'perp-only market tag is missing');
  assert(desktop.chartPresent, 'existing chart did not render');
  const desktopShot = await screenshot('vwap-action-queue-desktop.png');

  await evaluate(`document.querySelector('#rows tr[data-symbol="BETAUSDT"]').click()`);
  await wait(700);
  const viewed = await evaluate(`(() => ({
    ids: JSON.parse(localStorage.getItem('vwap-viewed-queue') || '[]'),
    stillNew: !!document.querySelector('#rows tr[data-symbol="BETAUSDT"] .new-dot'),
    detailTicker: document.querySelector('.ticker')?.textContent,
  }))()`);
  assert(viewed.ids.includes('BETA:watching:2026-09-07'), 'mark-viewed identity was not persisted');
  assert(!viewed.stillNew, 'viewed row still renders as unviewed');
  assert(viewed.detailTicker.includes('BETA'), 'selected ticker detail did not update');

  await evaluate(`const input=document.querySelector('#minSamples'); input.value='200'; input.dispatchEvent(new Event('change',{bubbles:true}))`);
  const filtered = await evaluate(`[...document.querySelectorAll('#rows tr[data-symbol]')].map(row => row.dataset.symbol)`);
  assert(filtered.join(',') === 'ALPHAUSDT', `sample threshold did not filter queue: ${filtered}`);

  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await wait(300);
  const mobile = await evaluate(`(() => ({
    viewport: [innerWidth, innerHeight],
    scopeHidden: getComputedStyle(document.querySelector('#queueHead .hide-mobile')).display === 'none',
    controlsWidth: Math.round(document.querySelector('#queueControls').getBoundingClientRect().width),
    bodyWidth: document.body.scrollWidth,
  }))()`);
  assert(mobile.viewport[0] === 390, `mobile viewport did not apply: ${mobile.viewport}`);
  assert(mobile.scopeHidden, 'mobile queue did not hide compact scope column');
  assert(mobile.bodyWidth <= 390, `mobile page overflows horizontally: ${mobile.bodyWidth}px`);
  const mobileShot = await screenshot('vwap-action-queue-mobile.png');

  assert(exceptions.length === 0, `browser exceptions: ${exceptions.join('; ')}`);
  socket.close();
  console.log(JSON.stringify({ desktop, viewed, filtered, mobile, screenshots: [desktopShot, mobileShot] }, null, 2));
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
