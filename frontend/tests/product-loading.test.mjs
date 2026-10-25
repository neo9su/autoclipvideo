import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source = fs.readFileSync(new URL('../src/views/Products.vue', import.meta.url), 'utf8')
const body = source.match(/async function loadProducts\(\) \{[\s\S]*?\n\}/)[0]
const products = { value: [{ id: 7 }] }, productsLoading = { value: true }, productsError = { value: '' }
let response = [{ id: 8 }], error = null
const context = { products, productsLoading, productsError, Array, Error,
  getProducts: async () => { if (error) throw error; return response }, showToast() {} }
vm.createContext(context)
vm.runInContext(body, context)
await context.loadProducts()
assert.equal(products.value[0].id, 8)
assert.equal(productsLoading.value, false)
error = Error('offline')
await context.loadProducts()
assert.equal(products.value[0].id, 8, 'failed refresh preserves existing products')
assert.match(productsError.value, /加载失败/)
assert.equal(productsLoading.value, false)
error = null; response = { detail: 'invalid' }
await context.loadProducts()
assert.equal(products.value[0].id, 8, 'invalid response cannot replace products')
response = []
await context.loadProducts()
assert.equal(productsError.value, '')
assert.equal(products.value.length, 0, 'successful empty response remains distinguishable')
let ran = false
context.onMounted = fn => { context.mount = fn }
context.getRooms = async () => { throw Error('room request failed') }
context.loadProducts = async () => { ran = true }
vm.runInContext(source.match(/onMounted\(\(\) => \{[\s\S]*?\n\}\)/)[0], context)
context.mount()
await new Promise(resolve => setImmediate(resolve))
assert.equal(ran, true, 'room failure must not block product loading')
console.log('Product loading checks passed: success, failure, invalid data, empty, independent rooms')
if (process.argv[2]) {
  const live = fs.readFileSync(process.argv[2], 'utf8')
  const load = live.match(/let productLoading=z\(!0\),productError=z\(``\);async function T\(\)\{[\s\S]*?finally\{productLoading.value=!1\}\}/)[0]
  const c = { z: value => ({value}), i:{value:[{id:9}]}, ss:async()=>{throw Error('offline')}, r(){}, Array, Error }
  vm.createContext(c);vm.runInContext(load,c)
  await c.T()
  assert.equal(c.i.value[0].id,9)
  assert.equal(vm.runInContext('productLoading.value',c),false)
  assert.match(vm.runInContext('productError.value',c),/加载失败/)
  console.log('Production bundle error recovery check passed')
}
