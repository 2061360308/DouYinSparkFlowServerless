import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

function load(file, dependencies) {
  const source = readFileSync(new URL(file, import.meta.url), 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports = {}
  vm.runInNewContext(js, { exports, require: name => dependencies[name] ?? {}, setTimeout })
  return exports
}

test('installation API uses authenticated HTTP rather than simulated success', async () => {
  const calls = []
  const http = { post: async (path, body) => { calls.push({ path, body }); return { stackId: 'real-stack' } } }
  const api = load('../src/api/install.ts', { './console.http': { http } })
  const body = { region: 'cn-hangzhou', stackName: 'test', credentials: {}, parameters: {} }
  const result = await api.deployStack(body)
  assert.equal(result.stackId, 'real-stack')
  assert.equal(calls[0].path, '/api/install/deploy')
  await api.getDeployStatus('real-stack')
  assert.equal(calls[1].path, '/api/install/refresh')
})

function routing(state, installation) {
  let guard
  const router = { beforeEach: fn => { guard = fn }, currentRoute: { value: {} }, replace() {} }
  let calls = 0
  let source = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
  source = source.replaceAll('import.meta.env.BASE_URL', "'/'")
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const dependencies = {
    'vue-router': { createRouter: () => router, createWebHistory() {} },
    '../api/console.http': { setUnauthorizedHandler() {} },
    '../composables/useAuth': { useAuth: () => ({ state, refresh: async () => {}, clear() {} }) },
    '../composables/useInstallState': { getInstallStatus: async () => { calls++; return installation } },
  }
  vm.runInNewContext(js, { exports: {}, require: name => dependencies[name] })
  return { run: to => guard(to), calls: () => calls }
}

test('uninstalled admin is directed to install, but password change takes priority', async () => {
  const state = { ready: true, user: {}, isAdmin: true, mustChangePassword: false }
  const route = routing(state, { needsInstall: true })
  assert.equal((await route.run({ name: 'dashboard', meta: { requiresAuth: true } })).name, 'install')
  state.mustChangePassword = true
  assert.equal((await route.run({ name: 'install', meta: { requiresAuth: true, requiresAdmin: true } })).name, 'change-password')
})

test('non-admin does not query admin installation status', async () => {
  const route = routing({ ready: true, user: {}, isAdmin: false }, { needsInstall: true })
  assert.equal(await route.run({ name: 'dashboard', meta: { requiresAuth: true } }), true)
  assert.equal(route.calls(), 0)
})
