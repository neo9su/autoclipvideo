import { createApp, h } from 'vue'
import HistoryLibrary from './views/HistoryLibrary.vue'
import './style.css'
createApp({render:()=>h('main',{class:'main'},[
  h('a',{href:'/frontend/',style:'display:inline-block;margin:20px 0;color:#ff4167'},'← 返回录制系统'),
  h(HistoryLibrary)
])}).mount('#history-library')
