import { computed, ref } from 'vue'

const activeRequests = ref(0)
const pendingRequests = new Map()

export const isLoading = computed(() => activeRequests.value > 0)

export function beginRequest() {
  activeRequests.value += 1
}

export function endRequest() {
  activeRequests.value = Math.max(0, activeRequests.value - 1)
}

export function dedupeRequest(key, request) {
  const existing = pendingRequests.get(key)
  if (existing) return existing
  const promise = request().finally(() => pendingRequests.delete(key))
  pendingRequests.set(key, promise)
  return promise
}
