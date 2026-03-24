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
import { ref } from 'vue'
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
.main { max-width: 1200px; margin: 0 auto; padding: 24px; }
.toast-container { position: fixed; bottom: 24px; right: 24px; display: flex; flex-direction: column; gap: 8px; z-index: 200; }
.toast { padding: 10px 18px; border-radius: 8px; font-size: 13px; color: #fff; max-width: 320px; animation: toast-in 0.2s ease; }
.toast.info    { background: #2a2a2a; border: 1px solid #444; }
.toast.success { background: rgba(52,211,153,0.2); border: 1px solid rgba(52,211,153,0.4); color: #34d399; }
.toast.error   { background: rgba(254,44,85,0.2);  border: 1px solid rgba(254,44,85,0.4);  color: #fe2c55; }
@keyframes toast-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
</style>
