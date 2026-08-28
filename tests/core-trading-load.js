'use strict';

const fs = require('fs');

const baseUrl = process.env.LOAD_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.LOAD_LOCATION || 'CORE_STRESS';
const maker = process.env.LOAD_MAKER || 'stressmaker';
const taker = process.env.LOAD_TAKER || 'stresstaker';
const orders = Number(process.env.LOAD_ORDERS || 1000);
const concurrency = Number(process.env.LOAD_CONCURRENCY || 16);
const settleMs = Number(process.env.LOAD_SETTLE_MS || 10000);
const output = process.env.LOAD_OUTPUT || '/artifacts/core-trading-load.json';
const runId = process.env.LOAD_RUN_ID || `${Date.now()}`;

if (!Number.isInteger(orders) || orders < 1) throw new Error('LOAD_ORDERS must be a positive integer');
if (!Number.isInteger(concurrency) || concurrency < 1) throw new Error('LOAD_CONCURRENCY must be a positive integer');

const endpoint = `${baseUrl.replace(/\/$/, '')}/httpapi/`;

function percentile(values, ratio) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * ratio) - 1)];
}

async function invoke(method, content) {
  const started = process.hrtime.bigint();
  let response;
  let body = '';
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ serverName: 'OrderSvr', method, content })
    });
    body = await response.text();
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
    let value;
    try { value = JSON.parse(body); } catch (_) { value = {}; }
    return { ok: response.ok && Number(value.code) === 0, httpStatus: response.status, code: value.code,
      msg: value.msg || '', elapsedMs, body };
  } catch (error) {
    return { ok: false, httpStatus: 0, code: 'NETWORK', msg: error.message,
      elapsedMs: Number(process.hrtime.bigint() - started) / 1e6, body };
  }
}

function orderContent(user, side, price, clOrdID) {
  return {
    OCType: 'OPEN', OrderQty: '0.0001', OrdType: 'Limit', ClOrdID: clOrdID,
    Terminal: 'API', AlgoName: 'cross', Side: side, Price: String(price), UserID: user,
    MarketIndicator: '4', TimeInForce: 'GTC', SecurityID: 'BTCUSDT', Location: location
  };
}

async function runConcurrent(name, total, factory) {
  let next = 0;
  const results = new Array(total);
  const started = process.hrtime.bigint();
  async function worker() {
    while (true) {
      const index = next++;
      if (index >= total) return;
      results[index] = await factory(index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, total) }, worker));
  const wallMs = Number(process.hrtime.bigint() - started) / 1e6;
  const latencies = results.map(item => item.elapsedMs);
  const failures = results.filter(item => !item.ok);
  return {
    name, total, success: total - failures.length, failed: failures.length, wallMs,
    throughput: total * 1000 / wallMs,
    latencyMs: { min: Math.min(...latencies), p50: percentile(latencies, 0.50),
      p95: percentile(latencies, 0.95), p99: percentile(latencies, 0.99), max: Math.max(...latencies) },
    failureSamples: failures.slice(0, 10).map(item => ({ code: item.code, status: item.httpStatus, msg: item.msg,
      body: item.body.slice(0, 300) }))
  };
}

async function cancelAll(user) {
  return invoke('cancelAllOrder', {
    UserID: user, SecurityID: 'BTCUSDT', MarketIndicator: '4', AlgoName: 'cross', Location: location
  });
}

async function main() {
  const phases = [];
  phases.push(await runConcurrent('resting-order-place', orders, index =>
    invoke('placeOrder', orderContent(maker, 'Sell', '90000', `LOAD-${runId}-REST-${index}`))));
  await new Promise(resolve => setTimeout(resolve, settleMs));

  const cancelStarted = process.hrtime.bigint();
  const cancelResult = await cancelAll(maker);
  phases.push({ name: 'mass-cancel', total: 1, success: cancelResult.ok ? 1 : 0,
    failed: cancelResult.ok ? 0 : 1, wallMs: Number(process.hrtime.bigint() - cancelStarted) / 1e6,
    throughput: 0, latencyMs: { p50: cancelResult.elapsedMs, p95: cancelResult.elapsedMs,
      p99: cancelResult.elapsedMs, max: cancelResult.elapsedMs },
    failureSamples: cancelResult.ok ? [] : [{ code: cancelResult.code, msg: cancelResult.msg }] });

  phases.push(await runConcurrent('maker-place', orders, index =>
    invoke('placeOrder', orderContent(maker, 'Sell', '60000', `LOAD-${runId}-MAKER-${index}`))));
  await new Promise(resolve => setTimeout(resolve, settleMs));
  phases.push(await runConcurrent('taker-match', orders, index =>
    invoke('placeOrder', orderContent(taker, 'Buy', '60000', `LOAD-${runId}-TAKER-${index}`))));

  const summary = {
    runId, generatedAt: new Date().toISOString(), endpoint, location, maker, taker, orders, concurrency, phases,
    passed: phases.every(phase => phase.failed === 0)
  };
  fs.writeFileSync(output, `${JSON.stringify(summary, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
  if (!summary.passed) process.exitCode = 2;
}

main().catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
