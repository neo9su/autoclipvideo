<template>
  <div class="app">
    <header class="header">
      <div class="header-inner">
        <h1>抖音直播录制系统</h1>
        <nav>
          <button :class="['nav-btn', page === 'dashboard' && 'active']" @click="page = 'dashboard'">监控面板</button>
          <button :class="['nav-btn', page === 'history' && 'active']" @click="page = 'history'">录像历史</button>
          <button :class="['nav-btn', page === 'groups' && 'active']" @click="page = 'groups'">分组管理</button>
        </nav>
      </div>
    </header>
    <main class="main">
      <Dashboard v-if="page === 'dashboard'" />
      <History v-else-if="page === 'history'" />
      <Groups v-else />
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import Dashboard from './views/Dashboard.vue'
import History from './views/History.vue'
import Groups from './views/Groups.vue'
const page = ref('dashboard')
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
</style>
