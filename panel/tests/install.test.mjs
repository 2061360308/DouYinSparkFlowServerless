import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'
import { computed } from 'vue'
import { buildParameters, DEFAULT_SPEC, memoryBounds } from '../src/install/fields.ts'

test('deployment parameters reject invalid or cleared function specifications', () => {
  for (const patch of [
    { Cpu: 0.05 }, { Cpu: 0.41 }, { Cpu: Infinity },
    { MemorySize: 1537 }, { MemorySize: 8192 }, { MemorySize: null },
    { TaskMemorySize: 64 }, { TaskCpu: 0.01 },
    { FunctionTimeout: null }, { FunctionTimeout: 1.5 },
    { TaskFunctionTimeout: 0 }, { DiskSize: 123 },
  ]) {
    assert.throws(() => buildParameters({ ...DEFAULT_SPEC, ...patch }), JSON.stringify(patch))
  }
  assert.equal(buildParameters(DEFAULT_SPEC).MemorySize, '1536')
  assert.equal(buildParameters({ ...DEFAULT_SPEC, Cpu: 0.4 }).Cpu, '0.4')
})

test('memory bounds do not invent capacity below the browser memory floor', () => {
  const bounds = memoryBounds(0.05)
  assert.ok(bounds.max <= 0.05 * 4096)
  assert.ok(bounds.min > bounds.max)
})

function deferred() {
  let resolve
  const promise = new Promise(r => { resolve = r })
  return { promise, resolve }
}
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }

// Execute the real component setup; replace only lifecycle, clock and API boundaries.
function mountDeploy(api, phase = 'idle') {
  const source = readFileSync(new URL('../src/install/steps/StepDeploy.vue', import.meta.url), 'utf8')
  const script = parse(source).descriptor.scriptSetup.content
  const js = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const store = {
    region: 'cn-hangzhou', stackName: 'test', credentials: {}, spec: { ...DEFAULT_SPEC },
    deploy: { phase, stackId: '', status: '', events: [], outputs: null, error: '' },
  }
  let mounted, unmounted, nextId = 0
  const timers = new Map()
  const schedule = (fn, repeat) => { const id = ++nextId; timers.set(id, { fn, repeat }); return id }
  vm.runInNewContext(js, {
    exports: {},
    require(name) {
      if (name === 'vue') return { computed, onMounted: fn => { mounted = fn }, onUnmounted: fn => { unmounted = fn } }
      if (name.endsWith('useInstallForm')) return { useInstallStore: () => store }
      if (name.endsWith('fields')) return { buildParameters }
      if (name.endsWith('api/install')) return api
      throw new Error(`Unexpected dependency: ${name}`)
    },
    setTimeout: fn => schedule(fn, false), setInterval: fn => schedule(fn, true),
    clearTimeout: id => timers.delete(id), clearInterval: id => timers.delete(id),
  })
  mounted()
  return {
    store, timers, unmount: () => unmounted(),
    tick() { for (const [id, timer] of [...timers]) { if (!timer.repeat) timers.delete(id); timer.fn() } },
  }
}

test('leaving during stack creation prevents polling and stale state updates', async () => {
  const creation = deferred()
  let calls = 0
  const page = mountDeploy({ deployStack: () => creation.promise, getDeployStatus: async () => { calls++; return { status: 'CREATE_IN_PROGRESS', events: [] } } })
  page.unmount()
  creation.resolve({ stackId: 'late' })
  await flush()
  assert.equal(calls, 0)
  assert.equal(page.store.deploy.stackId, '')
  assert.equal(page.timers.size, 0)
})

test('restored deployment queries the saved request without creating again', async () => {
  let creates = 0
  const page = mountDeploy({
    deployStack: async () => { creates++; return { stackId: 'duplicate' } },
    getDeployStatus: async () => ({ status: 'CREATE_COMPLETE', events: [], outputs: { FunctionName: 'restored' } }),
  }, 'deploying')
  await flush()
  assert.equal(creates, 0)
  assert.equal(page.store.deploy.phase, 'success')
  assert.equal(page.store.deploy.outputs.FunctionName, 'restored')
})

test('slow status queries never overlap and unmounted responses are ignored', async () => {
  const pending = deferred()
  let calls = 0
  const page = mountDeploy({
    deployStack: async () => ({ stackId: 's1' }),
    getDeployStatus: () => ++calls === 1 ? Promise.resolve({ status: 'CREATE_IN_PROGRESS', events: [] }) : pending.promise,
  })
  await flush()
  page.tick()
  page.tick()
  assert.equal(calls, 2)
  page.unmount()
  pending.resolve({ status: 'CREATE_COMPLETE', events: [], outputs: { FunctionName: 'late' } })
  await flush()
  assert.equal(page.store.deploy.phase, 'deploying')
  assert.equal(page.timers.size, 0)
})

test('successful polling publishes outputs and stops scheduling', async () => {
  let calls = 0
  const outputs = { FunctionName: 'browser', TriggerUrlInternet: 'https://example.test' }
  const page = mountDeploy({
    deployStack: async () => ({ stackId: 's1' }),
    getDeployStatus: async () => ++calls === 1
      ? { status: 'CREATE_IN_PROGRESS', events: [] }
      : { status: 'CREATE_COMPLETE', events: [], outputs },
  })
  await flush()
  assert.equal(page.store.deploy.phase, 'deploying')
  page.tick()
  await flush()
  assert.equal(page.store.deploy.phase, 'success')
  assert.deepEqual(page.store.deploy.outputs, outputs)
  assert.equal(page.timers.size, 0)
})

test('failed polling shows the resource failure and stops scheduling', async () => {
  const page = mountDeploy({
    deployStack: async () => ({ stackId: 's1' }),
    getDeployStatus: async () => ({ status: 'CREATE_FAILED', statusReason: 'quota exceeded', events: [] }),
  })
  await flush()
  assert.equal(page.store.deploy.phase, 'error')
  assert.equal(page.store.deploy.error, 'quota exceeded')
  assert.equal(page.timers.size, 0)
})

test('a rejected request after unmount cannot overwrite the next page state', async () => {
  let reject
  const pending = new Promise((_, r) => { reject = r })
  const page = mountDeploy({ deployStack: () => pending })
  page.unmount()
  reject(new Error('late failure'))
  await flush()
  assert.equal(page.store.deploy.error, '')
  assert.equal(page.timers.size, 0)
})
