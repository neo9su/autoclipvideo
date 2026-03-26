<template>
  <div class="app">
    <header class="header">
      <div class="header-inner">
        <h1>抖音直播录制系统</h1>
        <nav>
          <button :class="['nav-btn', page === 'dashboard' && 'active']" @click="page = 'dashboard'">监控面板</button>
          <button :class="['nav-btn', page === 'history' && 'active']" @click="page = 'history'">录像历史</button>
          <button :class="['nav-btn', page === 'upload' && 'active']" @click="page = 'upload'">上传剪辑</button>
          <button :class="['nav-btn', page === 'queue' && 'active']" @click="page = 'queue'">作业队列</button>
          <button :class="['nav-btn', page === 'groups' && 'active']" @click="page = 'groups'">分组管理</button>
          <button :class="['nav-btn', page === 'clips' && 'active']" @click="page = 'clips'">剪辑文件</button>
          <button :class="['nav-btn', page === 'products' && 'active']" @click="page = 'products'">商品库</button>
          <button :class="['nav-btn', page === 'publish' && 'active']" @click="page = 'publish'">发布</button>
        </nav>
        <!-- Stream login status -->
        <div class="stream-login" @click="showLoginPopup = true" :title="loginStatusTitle">
          <span :class="['login-dot', loginStatus.logged_in ? 'online' : 'offline', loginStatus.refreshing ? 'refreshing' : '']"></span>
          <span class="login-label">{{ loginStatus.logged_in ? '原画录播' : '低画质' }}</span>
        </div>
        <!-- Login popup -->
        <div v-if="showLoginPopup" class="login-popup-mask" @click.self="showLoginPopup = false">
          <div class="login-popup">
            <div class="login-popup-title">录播登录状态</div>
            <div class="login-popup-info">
              <div class="info-row">
                <span class="info-label">画质</span>
                <span :class="['info-value', loginStatus.logged_in ? 'good' : 'bad']">
                  {{ loginStatus.logged_in ? 'ORIGIN（原画）' : 'LD1（低画质 422p）' }}
                </span>
              </div>
              <div class="info-row" v-if="loginStatus.cookie_file">
                <span class="info-label">Cookie 文件</span>
                <span class="info-value">{{ loginStatus.cookie_file }}</span>
              </div>
              <div class="info-row" v-if="loginStatus.file_age_hours !== null">
                <span class="info-label">Cookie 更新</span>
                <span :class="['info-value', loginStatus.file_age_hours > 72 ? 'bad' : 'good']">
                  {{ loginStatus.file_age_hours }} 小时前
                </span>
              </div>
              <div class="info-row" v-if="!loginStatus.logged_in">
                <span class="info-label">说明</span>
                <span class="info-value bad">未登录导致录像画质为 422p，点击下方按钮重新登录</span>
              </div>
            </div>
            <div class="login-popup-actions">
              <button class="login-refresh-btn" @click="doLogin" :disabled="loginStatus.refreshing || loginRefreshing">
                {{ loginStatus.refreshing || loginRefreshing ? '登录浏览器已打开…' : '刷新登录（打开浏览器）' }}
              </button>
              <button class="login-close-btn" @click="showLoginPopup = false">关闭</button>
            </div>
          </div>
        </div>
      </div>
    </header>
    <GpuBanner />
    <main class="main">
      <Dashboard v-if="page === 'dashboard'" />
      <History v-else-if="page === 'history'" />
      <Groups v-else-if="page === 'groups'" />
      <Clips v-else-if="page === 'clips'" />
      <Upload v-else-if="page === 'upload'" />
      <Products v-else-if="page === 'products'" />
      <Publish v-else-if="page === 'publish'" />
      <ClipQueue v-else-if="page === 'queue'" />
    </main>
    <div class="toast-container">
      <div v-for="t in toasts" :key="t.id" :class="['toast', t.type]">{{ t.message }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Dashboard from './views/Dashboard.vue'
import History from './views/History.vue'
import Groups from './views/Groups.vue'
import Clips from './views/Clips.vue'
import Upload from './views/Upload.vue'
import Products from './views/Products.vue'
import Publish from './views/Publish.vue'
import ClipQueue from './views/ClipQueue.vue'
import GpuBanner from './components/GpuBanner.vue'
import { useToast } from './composables/toast.js'

const page = ref('dashboard')
const { toasts } = useToast()

// Stream login status
const loginStatus = ref({ logged_in: false, quality: 'LD1', file_age_hours: null, refreshing: false })
const showLoginPopup = ref(false)
const loginRefreshing = ref(false)

const loginStatusTitle = computed(() => {
  if (loginStatus.value.logged_in) {
    return `原画录播已登录，Cookie ${loginStatus.value.file_age_hours}h前更新`
  }
  return '录播未登录，当前画质为 422p（低画质）'
})

async function fetchLoginStatus() {
  try {
    const r = await fetch('/api/stream-login/status')
    if (r.ok) loginStatus.value = await r.json()
  } catch {}
}

async function doLogin() {
  loginRefreshing.value = true
  try {
    const r = await fetch('/api/stream-login/refresh', { method: 'POST' })
    const d = await r.json()
    if (d.ok) {
      // Poll until refreshing is done or cookies appear
      const poll = setInterval(async () => {
        await fetchLoginStatus()
        if (!loginStatus.value.refreshing && loginStatus.value.logged_in) {
          clearInterval(poll)
          loginRefreshing.value = false
        }
      }, 3000)
      setTimeout(() => { clearInterval(poll); loginRefreshing.value = false }, 310000)
    } else {
      alert(d.msg)
      loginRefreshing.value = false
    }
  } catch { loginRefreshing.value = false }
}

let loginTimer
onMounted(() => {
  fetchLoginStatus()
  loginTimer = setInterval(fetchLoginStatus, 60000)
})
onUnmounted(() => clearInterval(loginTimer))
</script>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f0f; color: #e0e0e0; }
.app { min-height: 100vh; }
.header { background: #1a1a1a; border-bottom: 1px solid #333; padding: 0 24px; }
.header-inner { max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; height: 56px; }
.header h1 { font-size: 18px; font-weight: 600; color: #fff; }
nav { display: flex; gap: 8px; }
.nav-btn { background: none; border: none; color: #999; cursor: pointer; padding: 6px 16px; border-radius: 6px; font-size: 14px; transition: all 0.2s; }
.nav-btn:hover { background: #333; color: #fff; }
.nav-btn.active { background: #fe2c55; color: #fff; }
.stream-login { display: flex; align-items: center; gap: 6px; cursor: pointer; padding: 5px 10px; border-radius: 6px; border: 1px solid #333; margin-left: 12px; }
.stream-login:hover { border-color: #555; background: #222; }
.login-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.login-dot.online { background: #34d399; }
.login-dot.offline { background: #fe2c55; }
.login-dot.refreshing { background: #f59e0b; animation: pulse 1s infinite; }
.login-label { font-size: 12px; color: #ccc; white-space: nowrap; }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.4 } }
.login-popup-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 300; display: flex; align-items: flex-start; justify-content: flex-end; padding-top: 56px; padding-right: 24px; }
.login-popup { background: #1e1e1e; border: 1px solid #333; border-radius: 10px; padding: 20px; width: 320px; }
.login-popup-title { font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 14px; }
.info-row { display: flex; gap: 10px; margin-bottom: 8px; font-size: 13px; }
.info-label { color: #888; width: 80px; flex-shrink: 0; }
.info-value { color: #ccc; }
.info-value.good { color: #34d399; }
.info-value.bad { color: #fe2c55; }
.login-popup-actions { margin-top: 16px; display: flex; gap: 8px; }
.login-refresh-btn { flex: 1; padding: 8px; background: #fe2c55; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
.login-refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.login-close-btn { padding: 8px 14px; background: #333; color: #ccc; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
.main { max-width: 1200px; margin: 0 auto; padding: 24px; }
.toast-container { position: fixed; bottom: 24px; right: 24px; display: flex; flex-direction: column; gap: 8px; z-index: 200; }
.toast { padding: 10px 18px; border-radius: 8px; font-size: 13px; color: #fff; max-width: 320px; animation: toast-in 0.2s ease; }
.toast.info    { background: #2a2a2a; border: 1px solid #444; }
.toast.success { background: rgba(52,211,153,0.2); border: 1px solid rgba(52,211,153,0.4); color: #34d399; }
.toast.error   { background: rgba(254,44,85,0.2);  border: 1px solid rgba(254,44,85,0.4);  color: #fe2c55; }
@keyframes toast-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
</style>
