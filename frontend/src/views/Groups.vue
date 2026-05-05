<template>
  <div>
    <div class="toolbar">
      <h2>分组管理</h2>
      <div class="toolbar-actions">
        <button class="btn-primary" @click="openCreateGroupModal">+ 新建分组</button>
        <button class="btn-custom" @click="openCustomGroupModal">+ 自定义分组</button>
        <button v-if="suggestions.length > 0" class="btn-action orange btn-sm" @click="showSuggestions = true">
          规则建议 ({{ suggestions.length }})
        </button>
      </div>
    </div>

    <div v-if="groups.length === 0" class="empty-tip">
      暂无分组。录像完成转录和剪辑后，系统会自动按款式/颜色分组。
    </div>

    <div class="groups-list">
      <div v-for="g in groups" :key="g.id" :class="['group-card', g.is_custom && 'group-card-custom']">
        <!-- Group header -->
        <div class="group-header">
          <div class="group-meta">
            <div class="group-label">{{ g.label }}</div>
            <div class="group-sub">
              <span v-if="!g.is_custom" class="tag">{{ g.room_name }}</span>
              <span v-else class="tag" style="background:rgba(251,146,60,0.15);color:#c2540a;">自定义</span>
              <span class="tag date-tag">{{ g.created_at ? g.created_at.slice(0, 10) : '' }}</span>
              <span class="tag" v-if="g.wig_model">{{ g.wig_model }}</span>
              <span class="tag color" v-if="g.wig_color">{{ g.wig_color }}</span>
              <span v-if="g.published_count > 0" class="tag published-tag">已发布 {{ g.published_count }} 次</span>
              
              <!-- 发布版本选择器 -->
              <div class="mode-selector">
                <select
                  :value="g.publish_versions || 'both'"
                  @change="setPublishVersions(g, $event.target.value)"
                  class="mode-select"
                  title="发布时使用哪个版本"
                >
                  <option value="both">📤 全部版本</option>
                  <option value="director">🎬 导演版</option>
                  <option value="classic">📹 经典版</option>
                  <option value="creative">✍️ 自编版</option>
                </select>
              </div>
            </div>
          </div>
          <div class="group-stats">
            <span class="stat-item">{{ g.ready_count }} / {{ g.clip_count }} 条剪辑</span>
            <button class="btn-edit" @click="openEditGroupModal(g)" title="编辑分组">✎</button>
            <button class="btn-del" @click="doDeleteGroup(g)" title="删除分组">✕</button>
          </div>
          <div class="group-actions">
            <!-- 三模式触发按钮 -->
            <button
              v-if="g.classic_status !== 1 && g.director_status !== 1 && (g.creative_status || 0) !== 1"
              class="btn-action"
              :disabled="g.ready_count === 0"
              @click="doMerge(g)">
              {{ (g.classic_status === 2 || g.director_status === 2 || g.creative_status === 2) ? '↺ 重新合并' : '剪辑并合并' }}
            </button>
            <button v-else class="btn-action yellow" disabled>处理中…</button>
            <!-- 经典版结果 -->
            <template v-if="g.classic_status === 2">
              <button class="btn-action teal" style="margin-right:2px" @click="openClassicPreview(g)">▶ 经典版</button>
              <a :href="`${apiBase}/api/groups/${g.id}/download`" class="btn-action teal" title="经典版下载">↓</a>
            </template>
            <span v-else-if="g.classic_status === 1" class="badge yellow">经典版处理中…</span>
            <span v-else-if="g.classic_status === -1" class="badge red">经典版失败</span>
            <!-- 自编版结果 -->
            <template v-if="g.creative_status === 2">
              <button class="btn-action green" style="margin-right:2px" @click="openCreativePreview(g)">▶ 自编版</button>
              <a :href="`${apiBase}/api/groups/${g.id}/creative-download`" class="btn-action green" title="自编版下载">↓</a>
            </template>
            <span v-else-if="(g.creative_status || 0) === 1" class="badge yellow">自编版处理中…</span>
            <span v-else-if="g.creative_status === -1" class="badge red">自编版失败</span>
            <!-- 重剪 -->
            <button
              v-if="g.clip_count > 0"
              class="btn-action orange"
              :disabled="reclipAllId === g.id"
              @click="doReclipAll(g)"
              title="重置所有剪辑并重新生成">
              {{ reclipAllId === g.id ? '重剪中…' : '↺ 全部重剪' }}
            </button>
            <button class="btn-sm" @click="toggleDetail(g.id)">
              {{ openId === g.id ? '收起' : '查看详情' }}
            </button>
          </div>
        </div>

        <!-- 导演模式操作面板（始终显示） -->
        <div class="director-panel">
          <!-- Vibe 选择器 -->
          <div class="vibe-selector">
            <span class="vibe-label">风格</span>
            <select :value="g.vibe || 'trendy'" @change="setVibe(g, $event.target.value)" class="vibe-select">
              <option value="trendy">🔥 爆款型</option>
              <option value="emotional">💛 情感型</option>
              <option value="lifestyle">☕ 生活型</option>
              <option value="luxury">✨ 高端型</option>
              <option value="contrast">⚡ 反差型</option>
              <option value="creative">✍️ 自编文案</option>
            </select>
            <span class="vibe-hint">{{ vibeHints[g.vibe || 'trendy'] }}</span>
          </div>
          <div class="director-steps">
            <div class="director-step">
              <span class="step-num">1</span>
              <button
                class="btn-director"
                :disabled="directorBusy[g.id] === 'script'"
                @click="generateDirectorScript(g)">
                {{ directorBusy[g.id] === 'script' ? '生成中…' : (g.director_script ? '↺ 重新生成脚本' : '生成脚本') }}
              </button>
              <span v-if="g.director_script" class="step-done">✓ 脚本已生成</span>
            </div>
            <div class="director-step">
              <span class="step-num">2</span>
              <button
                class="btn-director"
                :disabled="directorBusy[g.id] === 'voice'"
                @click="generateVoiceover(g)">
                {{ directorBusy[g.id] === 'voice' ? '合成中…' : (g.director_audio_path ? '↺ 重新生成配音' : '生成配音') }}
              </button>
              <span v-if="g.director_audio_path" class="step-done">✓ 配音已生成</span>
            </div>
            <div class="director-step">
              <span class="step-num">3</span>
              <button
                class="btn-director"
                :disabled="directorBusy[g.id] === 'video'"
                @click="composeDirectorVideo(g)">
                {{ directorBusy[g.id] === 'video' ? '合成中…' : (g.director_final_video ? '↺ 重新合成' : '合成视频') }}
              </button>
              <span v-if="g.director_final_video" class="step-done">✓ 视频已生成</span>
              <button v-if="g.director_final_video" class="btn-action purple" style="margin-left:8px" @click="openDirectorPreview(g)">▶ 预览</button>
              <a v-if="g.director_final_video" :href="`${apiBase}/api/groups/${g.id}/director-download`" class="btn-action purple" style="margin-left:4px">↓ 下载</a>
            </div>
          </div>
          <div v-if="g.director_error" class="director-error">⚠ {{ g.director_error }}</div>
        </div>

        <!-- 封面生成面板 -->
        <div class="cover-panel" v-if="g.classic_status === 2 || g.director_status === 2 || g.creative_status === 2">
          <div class="cover-panel-header">
            <span class="cover-panel-title">封面</span>
            <button
              class="btn-sm btn-cover-gen"
              :disabled="coverGenerating[g.id]"
              @click="generateCovers(g)">
              {{ coverGenerating[g.id] ? '生成中…' : (g.cover_candidates ? '↺ 重新生成' : '生成封面') }}
            </button>
            <span v-if="g.selected_cover" class="cover-selected-hint">✓ 已选封面</span>
          </div>
          <!-- 3张候选图 -->
          <div v-if="g.cover_candidates" class="cover-candidates">
            <div
              v-for="(cv, idx) in parseCandidates(g.cover_candidates)"
              :key="idx"
              :class="['cover-candidate', g.selected_cover === cv && 'cover-candidate-selected']"
              @click="selectCover(g, cv)">
              <img :src="`${apiBase}/api/groups/${g.id}/cover/${cv}?t=${coverBust[g.id] || pageLoadTs}`"
                   class="cover-img"
                   @error="e => e.target.src=''" />
              <div class="cover-scheme-label">{{ coverSchemeLabel(idx) }}</div>
              <div v-if="g.selected_cover === cv" class="cover-check">✓</div>
              <button class="cover-preview-btn" @click.stop="openCoverPreview(g, cv, idx)" title="预览大图">⤢</button>
            </div>
          </div>
        </div>

        <!-- Custom group upload -->
        <div v-if="g.is_custom" class="custom-upload-row">
          <label :for="`upload-${g.id}`" class="btn-upload-label">+ 上传视频</label>
          <input :id="`upload-${g.id}`" type="file" accept="video/mp4,video/*" class="hidden-file-input"
                 @change="e => doUploadVideo(g.id, e)" />
          <span v-if="uploadingId === g.id" class="uploading-hint">上传中…</span>
        </div>

        <!-- Merge status -->
        <div v-if="g.merge_status === -1" class="merge-error">
          上次合并失败
          <button v-if="g.merge_error" class="btn-error-detail" @click.stop="showMergeError(g)">查看原因</button>
        </div>

        <!-- Quality issue warning -->
        <div v-if="g.quality_issue" class="quality-issue-bar">
          <span class="quality-issue-icon">⚠️</span>
          <span class="quality-issue-text">发布质量检测不通过：{{ g.quality_issue }}</span>
          <button class="btn-action red btn-sm" style="margin-left:auto" @click="doMerge(g)">↺ 重新剪辑后合并</button>
        </div>

        <!-- Detail: recordings in group -->
        <div v-if="openId === g.id && detail">
          <div class="detail-loading" v-if="detailLoading">加载中…</div>
          <table v-else class="detail-table">
            <thead>
              <tr>
                <th></th>
                <th>文件名</th>
                <th>内容摘要</th>
                <th>标签</th>
                <th>处理状态</th>
                <th>移至分组</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in detail.recordings" :key="r.id">
                <td class="thumb-cell">
                  <img v-if="r.clipped === 2"
                       :src="getThumbnailUrl(r.id)"
                       class="thumb-img"
                       @error="e => e.target.style.display='none'" />
                  <div v-else class="thumb-placeholder"></div>
                </td>
                <td class="filename">{{ r.filename }}</td>
                <td>{{ r.session_label || '—' }}</td>
                <td>
                  <span v-if="r.has_tryon" class="tag">试戴</span>
                  <span v-if="r.has_promotion" class="tag promo">促销</span>
                </td>
                <td class="status-cell">
                  <!-- failed states -->
                  <span v-if="r.transcribed === -1" class="badge red" :title="r.transcribe_error || ''">转录失败</span>
                  <span v-else-if="r.clipped === -1" class="badge red">剪辑失败</span>
                  <!-- done -->
                  <span v-else-if="r.clipped === 2" class="clip-done-row">
                    <button class="badge-btn purple" @click="openPreview(r)">▶ 预览</button>
                    <a :href="`${apiBase}/api/recordings/${r.id}/clip`" class="badge purple">↓</a>
                    <button class="badge-btn orange" @click="openReclip(r)">↺ 重剪</button>
                    <button class="badge-btn teal" @click="openReview(r)" :title="r.review_status ? '已审核（再次审核）' : '人工审核片段'">{{ r.review_status ? '✓审' : '审核' }}</button>
                  </span>
                  <!-- pending (no active progress) -->
                  <span v-else-if="r.transcribed === 0 && !progressMap[r.id]" class="badge dim">待转录</span>
                  <span v-else-if="r.transcribed === 2 && r.clipped === 0 && !progressMap[r.id]" class="badge dim">待剪辑</span>
                  <!-- in-progress with progress bar -->
                  <div v-else-if="progressMap[r.id]" class="progress-wrap">
                    <div class="progress-label">
                      <span class="progress-msg">{{ progressMap[r.id].msg }}</span>
                      <span class="progress-pct">{{ progressMap[r.id].pct }}%</span>
                    </div>
                    <div class="progress-bar-bg">
                      <div class="progress-bar-fill" :style="{ width: progressMap[r.id].pct + '%' }"></div>
                    </div>
                    <div v-if="progressMap[r.id].eta_seconds != null" class="progress-eta">
                      {{ formatEta(progressMap[r.id].eta_seconds) }}
                    </div>
                  </div>
                  <!-- fallback in-progress without data yet -->
                  <span v-else-if="r.transcribed === 1" class="badge yellow">转录中…</span>
                  <span v-else-if="r.clipped === 1" class="badge yellow">剪辑中…</span>
                </td>
                <td>
                  <select class="reassign-select"
                          :value="r.group_id"
                          @change="doReassign(r.id, $event.target.value)">
                    <option value="">— 不分组 —</option>
                    <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.label }}</option>
                  </select>
                </td>
              </tr>
              <tr v-if="detail.recordings.length === 0">
                <td colspan="6" class="empty">此分组暂无录像</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- Group Create / Edit Modal -->
  <div v-if="groupModal" class="modal-backdrop" @click.self="groupModal = null">
    <div class="modal">
      <div class="modal-header">
        <span>{{ groupModal.mode === 'create' ? '新建分组' : '编辑分组' }}</span>
        <button class="modal-close" @click="groupModal = null">✕</button>
      </div>
      <div class="modal-field" v-if="groupModal.mode === 'create'">
        <label>直播间</label>
        <select v-model="groupModal.room_id" class="modal-input">
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
      </div>
      <div class="modal-field">
        <label>分组标签</label>
        <input v-model="groupModal.label" class="modal-input" placeholder="例：大波浪 自然黑" />
      </div>
      <div class="modal-field">
        <label>款式 <span class="field-hint">可留空</span></label>
        <input v-model="groupModal.wig_model" class="modal-input" placeholder="例：大波浪卷发" />
      </div>
      <div class="modal-field">
        <label>颜色 <span class="field-hint">可留空</span></label>
        <input v-model="groupModal.wig_color" class="modal-input" placeholder="例：自然黑" />
      </div>
      <div class="modal-field">
        <label>批量导入视频 <span class="field-hint">可选 — 每行一个 .mp4 文件路径</span></label>
        <textarea
          v-model="groupModal.importPaths"
          class="modal-input"
          rows="4"
          placeholder="/Users/claw/work/douyin-recorder/recordings/video1.mp4&#10;/Users/claw/work/douyin-recorder/recordings/video2.mp4"
        ></textarea>
        <div v-if="importPreviewCount > 0" class="import-preview">已填入 {{ importPreviewCount }} 个路径</div>
      </div>
      <div class="modal-footer">
        <button class="btn-action" @click="groupModal = null">取消</button>
        <button class="btn-action purple" :disabled="groupModalSaving || !groupModal.label.trim()" @click="saveGroupModal">
          {{ groupModalSaving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>

  <!-- Video Preview Modal -->
  <div v-if="previewRec" class="modal-backdrop" @click.self="closePreview">
    <div class="preview-modal">
      <div class="preview-header">
        <span class="preview-title">{{ previewRec.filename }}</span>
        <button class="modal-close" @click="closePreview">✕</button>
      </div>
      <video
        :src="`${apiBase}/api/recordings/${previewRec.id}/clip`"
        controls
        autoplay
        class="preview-video"
        @error="previewError = true"
      ></video>
      <div v-if="previewError" class="preview-err">视频加载失败</div>
      <div class="preview-footer">
        <a :href="`${apiBase}/api/recordings/${previewRec.id}/clip`" class="btn-action purple" download>下载</a>
      </div>
    </div>
  </div>

  <!-- Classic Video Preview Modal -->
  <div v-if="classicPreviewGroup" class="modal-backdrop" @click.self="closeClassicPreview">
    <div class="preview-modal">
      <div class="preview-header">
        <span class="preview-title">经典版 · {{ classicPreviewGroup.label }}</span>
        <button class="modal-close" @click="closeClassicPreview">✕</button>
      </div>
      <video
        :src="`${apiBase}/api/groups/${classicPreviewGroup.id}/download`"
        controls
        autoplay
        class="preview-video"
        @error="classicPreviewError = true"
      ></video>
      <div v-if="classicPreviewError" class="preview-err">视频加载失败</div>
      <div class="preview-footer">
        <a :href="`${apiBase}/api/groups/${classicPreviewGroup.id}/download`" class="btn-action teal" download>↓ 下载</a>
      </div>
    </div>
  </div>

  <!-- Director Video Preview Modal -->
  <div v-if="directorPreviewGroup" class="modal-backdrop" @click.self="closeDirectorPreview">
    <div class="preview-modal">
      <div class="preview-header">
        <span class="preview-title">导演模式 · {{ directorPreviewGroup.label }}</span>
        <button class="modal-close" @click="closeDirectorPreview">✕</button>
      </div>
      <video
        :src="`${apiBase}/api/groups/${directorPreviewGroup.id}/director-download`"
        controls
        autoplay
        class="preview-video"
        @error="directorPreviewError = true"
      ></video>
      <div v-if="directorPreviewError" class="preview-err">视频加载失败</div>
      <div class="preview-footer">
        <a :href="`${apiBase}/api/groups/${directorPreviewGroup.id}/director-download`" class="btn-action purple" download>↓ 下载</a>
      </div>
    </div>
  </div>

  <!-- Creative Video Preview Modal -->
  <div v-if="creativePreviewGroup" class="modal-backdrop" @click.self="closeCreativePreview">
    <div class="preview-modal">
      <div class="preview-header">
        <span class="preview-title">自编版 · {{ creativePreviewGroup.label }}</span>
        <button class="modal-close" @click="closeCreativePreview">✕</button>
      </div>
      <video
        :src="`${apiBase}/api/groups/${creativePreviewGroup.id}/creative-download`"
        controls
        autoplay
        class="preview-video"
        @error="creativePreviewError = true"
      ></video>
      <div v-if="creativePreviewError" class="preview-err">视频加载失败</div>
      <div class="preview-footer">
        <a :href="`${apiBase}/api/groups/${creativePreviewGroup.id}/creative-download`" class="btn-action green" download>↓ 下载</a>
      </div>
    </div>
  </div>

  <!-- Cover Preview Modal -->
  <div v-if="coverPreview" class="modal-backdrop" @click.self="coverPreview = null">
    <div class="cover-preview-modal">
      <div class="cover-preview-header">
        <span class="cover-preview-title">{{ coverPreview.label }} · {{ coverSchemeLabel(coverPreview.idx) }}</span>
        <div class="cover-preview-actions">
          <button
            :class="['btn-action', coverPreview.selected ? 'teal' : 'yellow']"
            @click="selectCoverFromPreview">
            {{ coverPreview.selected ? '✓ 已选定' : '选用此封面' }}
          </button>
          <a :href="`${apiBase}/api/groups/${coverPreview.groupId}/cover/${coverPreview.cv}?t=${coverBust[coverPreview.groupId] || pageLoadTs}`"
             class="btn-action purple" download title="下载封面图">↓ 下载</a>
          <button class="modal-close" @click="coverPreview = null">✕</button>
        </div>
      </div>
      <div class="cover-preview-body">
        <button class="cover-nav cover-nav-prev" @click="coverNavStep(-1)" :disabled="coverPreview.idx === 0">‹</button>
        <img
          :src="`${apiBase}/api/groups/${coverPreview.groupId}/cover/${coverPreview.cv}?t=${coverBust[coverPreview.groupId] || pageLoadTs}`"
          class="cover-preview-img"
        />
        <button class="cover-nav cover-nav-next" @click="coverNavStep(1)" :disabled="coverPreview.idx === coverPreview.total - 1">›</button>
      </div>
      <div class="cover-preview-dots">
        <span
          v-for="i in coverPreview.total" :key="i"
          :class="['cover-dot', i - 1 === coverPreview.idx && 'cover-dot-active']"
          @click="coverNavTo(i - 1)">
        </span>
      </div>
    </div>
  </div>

  <!-- Re-clip Feedback Modal -->
  <div v-if="reclipModal" class="modal-backdrop" @click.self="!reclipSaving && (reclipModal = null)">
    <div class="modal">
      <!-- Success state -->
      <template v-if="reclipModal.submitted">
        <div class="reclip-success">
          <div class="reclip-success-icon">✓</div>
          <div class="reclip-success-title">视频重剪已加入队列</div>
          <div class="reclip-success-sub">
            {{ reclipModal.feedback.trim() ? 'AI 正在分析你的反馈，将优化片段选取策略' : '将使用不同片段组合重新生成' }}
          </div>
        </div>
        <div class="modal-footer" style="justify-content:center">
          <button class="btn-action purple" @click="reclipModal = null">知道了</button>
        </div>
      </template>
      <!-- Input state -->
      <template v-else>
        <div class="modal-header">
          <span>↺ 重新剪辑</span>
          <button class="modal-close" @click="reclipModal = null">✕</button>
        </div>
        <div class="modal-field">
          <label>不满意的原因 <span class="field-hint">可留空，填写后 AI 会针对性优化</span></label>
          <textarea
            v-model="reclipModal.feedback"
            class="modal-input"
            rows="4"
            placeholder="例：选的片段太短，没有突出促销信息；或：视频内容跳跃太厉害，希望更连贯…"
          ></textarea>
        </div>
        <div class="reclip-hint">
          <span v-if="reclipModal.feedback.trim()">✦ AI 将根据你的反馈调整片段选取策略</span>
          <span v-else>留空则直接重新生成（使用不同的片段组合）</span>
        </div>
        <div class="modal-footer">
          <button class="btn-action" @click="reclipModal = null">取消</button>
          <button class="btn-action purple" :disabled="reclipSaving" @click="doReclip">
            {{ reclipSaving ? '提交中…' : '确认重新剪辑' }}
          </button>
        </div>
      </template>
    </div>
  </div>

  <!-- Custom Group Create Modal -->
  <div v-if="customModal" class="modal-backdrop" @click.self="customModal = null">
    <div class="modal modal-custom">
      <div class="modal-header">
        <span>新建自定义分组</span>
        <button class="modal-close" @click="customModal = null">✕</button>
      </div>
      <div class="modal-field">
        <label>分组标签 *</label>
        <input v-model="customModal.label" class="modal-input" placeholder="例：大波浪 自然黑" />
      </div>
      <div class="modal-field">
        <label>款式 <span class="field-hint">可留空</span></label>
        <input v-model="customModal.wig_model" class="modal-input" placeholder="例：大波浪卷发" />
      </div>
      <div class="modal-field">
        <label>颜色 <span class="field-hint">可留空</span></label>
        <input v-model="customModal.wig_color" class="modal-input" placeholder="例：自然黑" />
      </div>
      <div class="modal-footer">
        <button class="btn-action" @click="customModal = null">取消</button>
        <button class="btn-action orange" :disabled="customModalSaving || !customModal.label.trim()" @click="saveCustomModal">
          {{ customModalSaving ? '创建中…' : '创建' }}
        </button>
      </div>
    </div>
  </div>

  <!-- Merge error detail modal -->
  <div v-if="mergeErrorGroup" class="modal-overlay" @click.self="mergeErrorGroup = null">
    <div class="modal-box">
      <div class="modal-title">合并失败原因 — {{ mergeErrorGroup.label }}</div>
      <pre class="error-pre">{{ mergeErrorGroup.merge_error || '无详细信息' }}</pre>
      <button class="btn-action" style="margin-top:12px" @click="mergeErrorGroup = null">关闭</button>
    </div>
  </div>

  <!-- Human Review Modal -->
  <div v-if="reviewModal" class="modal-backdrop" @click.self="!reviewSaving && (reviewModal = null)">
    <div class="modal review-modal">
      <div class="modal-header">
        <span>审核片段 · {{ reviewModal.rec.filename }}</span>
        <button class="modal-close" @click="reviewModal = null">✕</button>
      </div>
      <div v-if="reviewLoading" class="review-loading">加载中…</div>
      <template v-else-if="reviewModal.segs">
        <div class="review-hint">
          勾选要保留的片段（算法选中的已预选）。取消勾选 = 告诉系统该关键词不重要；手动勾选未选中片段 = 告诉系统遗漏了。
        </div>
        <div class="review-segments">
          <div
            v-for="seg in reviewModal.segs"
            :key="seg.idx"
            :class="['review-seg', reviewModal.selected.has(seg.idx) && 'review-seg-selected', !seg.valid && 'review-seg-invalid']"
            @click="toggleSeg(seg.idx)"
          >
            <div class="review-seg-check">{{ reviewModal.selected.has(seg.idx) ? '☑' : '☐' }}</div>
            <div class="review-seg-body">
              <div class="review-seg-time">{{ fmtSec(seg.start) }} – {{ fmtSec(seg.end) }}</div>
              <div class="review-seg-text">{{ seg.text }}</div>
              <div class="review-seg-meta">
                <span class="review-score">{{ seg.score > 0 ? '+' + seg.score : seg.score }}</span>
                <span v-if="seg.category" class="review-cat">{{ seg.category }}</span>
                <span v-if="!seg.valid" class="review-invalid-mark">过滤</span>
              </div>
            </div>
          </div>
        </div>
        <div class="review-summary">
          已选 {{ reviewModal.selected.size }} / {{ reviewModal.segs.length }} 段
          <span v-if="reviewModal.algoIdxs.size">
            （算法选 {{ reviewModal.algoIdxs.size }} 段，
            你新增 {{ reviewModal_added.length }}，删除 {{ reviewModal_removed.length }}）
          </span>
        </div>
      </template>
      <div class="modal-footer">
        <button class="btn-action" @click="reviewModal = null">取消</button>
        <button class="btn-action purple" :disabled="reviewSaving || reviewLoading || !reviewModal.segs" @click="submitReview">
          {{ reviewSaving ? '提交中…' : '提交审核' }}
        </button>
      </div>
    </div>
  </div>

  <!-- Rule Suggestions Panel (shown when there are pending suggestions) -->
  <div v-if="showSuggestions" class="modal-backdrop" @click.self="showSuggestions = false">
    <div class="modal suggestions-modal">
      <div class="modal-header">
        <span>规则建议审核</span>
        <button class="modal-close" @click="showSuggestions = false">✕</button>
      </div>
      <div v-if="suggestions.length === 0" class="review-hint">暂无待审核建议</div>
      <div v-else class="suggestions-list">
        <div v-for="s in suggestions" :key="s.id" class="suggestion-item">
          <div class="sug-kw">{{ s.keyword }}</div>
          <div class="sug-reason">{{ s.reason }}</div>
          <div class="sug-score">{{ s.current_score }} → {{ s.suggested_score }}</div>
          <div class="sug-actions">
            <button class="btn-action purple btn-sm" @click="acceptSuggestion(s.id)">接受</button>
            <button class="btn-action btn-sm" @click="rejectSuggestion(s.id)">忽略</button>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn-action" @click="showSuggestions = false">关闭</button>
      </div>
    </div>
  </div>

</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getGroups, getGroup, getRooms, mergeGroup, retryModes, createGroup, updateGroup, reassignRecording, importGroupVideos, createWS, getThumbnailUrl, createCustomGroup, uploadCustomGroupVideo, deleteGroup, getProcessingProgress, reclipRecording, reclipGroupAll } from '../api.js'
import { useToast } from '../composables/toast.js'

const groups = ref([])
const rooms = ref([])
const openId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''
let ws = null

const { show } = useToast()

// Group create/edit modal: { mode: 'create'|'edit', id?, room_id, label, wig_model, wig_color, importPaths }
const groupModal = ref(null)
const groupModalSaving = ref(false)

// Custom group modal
const customModal = ref(null)
const customModalSaving = ref(false)
const uploadingId = ref(null)

// Processing progress: { [recording_id]: { pct, msg, eta_seconds, phase } }
const progressMap = ref({})
let progressTimer = null

// Merge error detail
const mergeErrorGroup = ref(null)
function showMergeError(g) { mergeErrorGroup.value = g }

// Video preview
const previewRec = ref(null)
const previewError = ref(false)
function openPreview(r) { previewRec.value = r; previewError.value = false }
function closePreview() { previewRec.value = null }

// Classic video preview
const classicPreviewGroup = ref(null)
const classicPreviewError = ref(false)
function openClassicPreview(g) { classicPreviewGroup.value = g; classicPreviewError.value = false }
function closeClassicPreview() { classicPreviewGroup.value = null }

// Director video preview
const directorPreviewGroup = ref(null)
const directorPreviewError = ref(false)
function openDirectorPreview(g) { directorPreviewGroup.value = g; directorPreviewError.value = false }
function closeDirectorPreview() { directorPreviewGroup.value = null }

// Creative video preview
const creativePreviewGroup = ref(null)
const creativePreviewError = ref(false)
function openCreativePreview(g) { creativePreviewGroup.value = g; creativePreviewError.value = false }
function closeCreativePreview() { creativePreviewGroup.value = null }

// Re-clip (single recording)
const reclipModal = ref(null)
const reclipSaving = ref(false)
function openReclip(r) { reclipModal.value = { rec: r, feedback: '' } }

// Director mode busy state: { [groupId]: 'script' | 'voice' | 'video' | null }
const directorBusy = ref({})

const vibeHints = {
  trendy:    '快节奏·强钩子·追热点',
  emotional: '情感共鸣·讲故事·引共情',
  lifestyle: 'GRWM·日常感·接地气',
  luxury:    '品质感·精致·仪式感',
  contrast:  '反差感·意外·强对比',
  creative:  '自由创作·编造卖点·催单节奏',
}

// Cover generation
const pageLoadTs = Date.now()           // bust cover URLs on every page load
const coverGenerating = ref({})
const coverBust = ref({})   // per-group cache-bust timestamp
const coverPreview = ref(null)   // { groupId, cv, idx, total, candidates, label, selected }
const COVER_SCHEME_LABELS = ['发量直接翻倍', '换个发型像换脸', '细软塌救星']

function parseCandidates(json) {
  try { return JSON.parse(json) } catch { return [] }
}

function coverSchemeLabel(idx) {
  return COVER_SCHEME_LABELS[idx] ?? `方案${idx + 1}`
}

function openCoverPreview(g, cv, idx) {
  const candidates = parseCandidates(g.cover_candidates)
  coverPreview.value = {
    groupId: g.id,
    cv,
    idx,
    total: candidates.length,
    candidates,
    label: g.label,
    selected: g.selected_cover === cv,
    _group: g,
  }
}

function coverNavStep(delta) {
  const p = coverPreview.value
  if (!p) return
  const newIdx = Math.max(0, Math.min(p.total - 1, p.idx + delta))
  const newCv = p.candidates[newIdx]
  coverPreview.value = { ...p, idx: newIdx, cv: newCv, selected: p._group.selected_cover === newCv }
}

function coverNavTo(idx) {
  const p = coverPreview.value
  if (!p) return
  const newCv = p.candidates[idx]
  coverPreview.value = { ...p, idx, cv: newCv, selected: p._group.selected_cover === newCv }
}

async function selectCoverFromPreview() {
  const p = coverPreview.value
  if (!p) return
  await selectCover(p._group, p.cv)
  coverPreview.value = { ...p, selected: true }
}

async function generateCovers(g) {
  coverGenerating.value[g.id] = true
  try {
    const resp = await fetch(`${apiBase}/api/groups/${g.id}/generate-covers`, { method: 'POST' })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || '封面生成失败')
    }
    const result = await resp.json()
    coverBust.value[g.id] = Date.now()
    show(`已生成 ${result.covers.length} 张封面候选`, 'success')
    await load()
  } catch (e) {
    show(e.message || '封面生成失败', 'error')
  } finally {
    coverGenerating.value[g.id] = false
  }
}

async function selectCover(g, coverPath) {
  try {
    const resp = await fetch(`${apiBase}/api/groups/${g.id}/select-cover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cover: coverPath }),
    })
    if (!resp.ok) throw new Error('选择失败')
    g.selected_cover = coverPath
    show('封面已选定', 'success')
  } catch (e) {
    show(e.message || '封面选择失败', 'error')
  }
}

// Re-clip all recordings in a group
const reclipAllId = ref(null)
async function doReclipAll(g) {
  if (!confirm(`将重置「${g.label}」分组内所有剪辑并重新生成（共 ${g.clip_count} 条录像）。确认吗？`)) return
  reclipAllId.value = g.id
  try {
    const result = await reclipGroupAll(g.id)
    show(`已提交 ${result.queued.length} / ${result.total} 条录像重新剪辑`, 'success')
    await load()
    if (openId.value === g.id) detail.value = await getGroup(g.id)
  } catch (e) {
    show(e.message || '全部重剪失败', 'error')
  } finally {
    reclipAllId.value = null
  }
}
async function doReclip() {
  if (!reclipModal.value) return
  reclipSaving.value = true
  const { rec, feedback } = reclipModal.value
  try {
    await reclipRecording(rec.id, feedback)
    reclipModal.value.submitted = true  // switch to success state
    if (openId.value) getGroup(openId.value).then(d => { detail.value = d })
  } catch (e) {
    show(e.message || '操作失败', 'error')
  } finally {
    reclipSaving.value = false
  }
}

const importPreviewCount = computed(() => {
  const txt = groupModal.value?.importPaths || ''
  return txt.split('\n').map(p => p.trim()).filter(p => p.endsWith('.mp4')).length
})

async function load() {
  ;[groups.value, rooms.value] = await Promise.all([getGroups(), getRooms()])
  if (openId.value) {
    detail.value = await getGroup(openId.value)
  }
}

async function toggleDetail(id) {
  if (openId.value === id) {
    openId.value = null
    detail.value = null
    stopProgressPolling()
    return
  }
  openId.value = id
  detailLoading.value = true
  detail.value = null
  detail.value = await getGroup(id)
  detailLoading.value = false
  startProgressPolling()
}

function startProgressPolling() {
  stopProgressPolling()
  const poll = async () => {
    progressMap.value = await getProcessingProgress()
  }
  poll()
  progressTimer = setInterval(poll, 8000)
}

function stopProgressPolling() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
}

function formatEta(seconds) {
  if (seconds == null || seconds < 0) return ''
  if (seconds < 60) return `约 ${seconds}秒`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `约 ${m}分${s > 0 ? s + '秒' : ''}`
}

async function doMerge(g) {
  try {
    await mergeGroup(g.id)
    show('合并任务已提交', 'info')
    await load()
  } catch (e) {
    show(e.message || '合并失败', 'error')
  }
}

async function doRetryModes(g) {
  try {
    await retryModes(g.id)
    show('导演+自编任务已提交', 'info')
    await load()
  } catch (e) {
    show(e.message || '任务提交失败', 'error')
  }
}

function openCreateGroupModal() {
  groupModal.value = {
    mode: 'create',
    room_id: rooms.value[0]?.id ?? '',
    label: '',
    wig_model: '',
    wig_color: '',
    importPaths: '',
  }
}

function openEditGroupModal(g) {
  groupModal.value = {
    mode: 'edit',
    id: g.id,
    room_id: g.room_id,
    label: g.label,
    wig_model: g.wig_model || '',
    wig_color: g.wig_color || '',
    importPaths: '',
  }
}

async function saveGroupModal() {
  const m = groupModal.value
  if (!m || !m.label.trim()) return
  groupModalSaving.value = true
  try {
    const body = { label: m.label.trim(), wig_model: m.wig_model.trim() || null, wig_color: m.wig_color.trim() || null }
    let groupId
    if (m.mode === 'create') {
      const created = await createGroup({ ...body, room_id: Number(m.room_id) })
      groupId = created.id
    } else {
      await updateGroup(m.id, body)
      groupId = m.id
    }
    if (m.importPaths?.trim()) {
      const paths = m.importPaths.split('\n').map(p => p.trim()).filter(Boolean)
      const result = await importGroupVideos(groupId, paths)
      show(`已导入 ${result.imported} 个视频${result.skipped.length ? `，${result.skipped.length} 个跳过` : ''}`, 'success')
    }
    groupModal.value = null
    await load()
  } catch (e) {
    show(e.message || '保存失败', 'error')
  } finally {
    groupModalSaving.value = false
  }
}

async function doDeleteGroup(g) {
  if (!confirm(`删除分组「${g.label}」？录像文件不会被删除，仅解除关联。`)) return
  try {
    await deleteGroup(g.id)
    if (openId.value === g.id) { openId.value = null; detail.value = null }
    await load()
    show('分组已删除', 'info')
  } catch (e) {
    show(e.message || '删除失败', 'error')
  }
}

async function setPublishVersions(group, versions) {
  group.publish_versions = versions
  try {
    const response = await fetch(`${apiBase}/api/groups/${group.id}/publish-versions`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ publish_versions: versions })
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || '设置失败')
    }
    const labels = { both: '两个版本', director: '导演版', classic: '经典版' }
    show(`发布版本已设为：${labels[versions] || versions}`, 'success')
  } catch (e) {
    show(e.message || '设置发布版本失败', 'error')
    await load()
  }
}

async function setVibe(group, vibe) {
  group.vibe = vibe
  try {
    await fetch(`${apiBase}/api/v2/director/set-vibe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: group.id, vibe })
    })
  } catch (e) {
    // best-effort — vibe is still held in local group object for current session
  }
}

async function generateDirectorScript(group) {
  directorBusy.value[group.id] = 'script'
  group.director_error = null
  try {
    const response = await fetch(`${apiBase}/api/v2/director/generate-script`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: group.id, script_type: 'balanced', vibe: group.vibe || 'trendy' })
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || '脚本生成失败')
    }
    const result = await response.json()
    if (!result.success) throw new Error('脚本生成返回失败状态')
    show(result.fallback ? '已生成备用脚本（Claude暂时不可用）' : '脚本生成成功', result.fallback ? 'warning' : 'success')
    await load()
  } catch (e) {
    group.director_error = e.message || '脚本生成失败'
    show(group.director_error, 'error')
  } finally {
    directorBusy.value[group.id] = null
  }
}

async function generateVoiceover(group) {
  directorBusy.value[group.id] = 'voice'
  group.director_error = null
  try {
    const response = await fetch(`${apiBase}/api/v2/director/generate-voiceover?group_id=${group.id}`, {
      method: 'POST'
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || '配音生成失败')
    }
    const result = await response.json()
    if (!result.success) throw new Error(result.error || '配音生成失败')
    show(`配音生成成功，时长 ${Math.round(result.total_duration)} 秒`, 'success')
    await load()
  } catch (e) {
    group.director_error = e.message || '配音生成失败'
    show(group.director_error, 'error')
  } finally {
    directorBusy.value[group.id] = null
  }
}

async function composeDirectorVideo(group) {
  directorBusy.value[group.id] = 'video'
  group.director_error = null
  const style = group.vibe || 'trendy'
  try {
    const response = await fetch(`${apiBase}/api/v2/director/compose-video?group_id=${group.id}&video_style=${style}`, {
      method: 'POST'
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || '合成失败')
    }
    // 后台任务已启动，busy 状态由 director_done / director_error WS 事件清除
    show('合成已启动，完成后自动通知', 'info')
  } catch (e) {
    // 校验失败（同步错误），立刻清除 busy
    directorBusy.value[group.id] = null
    group.director_error = e.message || '视频合成失败'
    show(group.director_error, 'error')
  }
}

function openCustomGroupModal() {
  customModal.value = { label: '', wig_model: '', wig_color: '' }
}

async function saveCustomModal() {
  const m = customModal.value
  if (!m || !m.label.trim()) return
  customModalSaving.value = true
  try {
    await createCustomGroup({ label: m.label.trim(), wig_model: m.wig_model.trim() || null, wig_color: m.wig_color.trim() || null })
    customModal.value = null
    show('自定义分组已创建', 'success')
    await load()
  } catch (e) {
    show(e.message || '创建失败', 'error')
  } finally {
    customModalSaving.value = false
  }
}

async function doUploadVideo(groupId, event) {
  const file = event.target.files?.[0]
  if (!file) return
  uploadingId.value = groupId
  try {
    await uploadCustomGroupVideo(groupId, file)
    show(`已上传 ${file.name}，正在处理…`, 'success')
    await load()
  } catch (e) {
    show(e.message || '上传失败', 'error')
  } finally {
    uploadingId.value = null
    event.target.value = ''
  }
}

async function doReassign(recordingId, newGroupId) {
  try {
    await reassignRecording(recordingId, newGroupId ? Number(newGroupId) : null)
    await load()
  } catch (e) {
    show(e.message || '移动失败', 'error')
  }
}

onMounted(() => {
  load()
  loadSuggestions()
  ws = createWS((msg) => {
    if (msg.type === 'merged') {
      show('视频合并完成', 'success')
      load()
    } else if (['transcribed', 'clipped'].includes(msg.type)) {
      load()
      if (openId.value) getProcessingProgress().then(p => { progressMap.value = p })
    } else if (msg.type === 'clip_progress' && msg.recording_id != null) {
      progressMap.value = {
        ...progressMap.value,
        [msg.recording_id]: { pct: msg.pct, msg: msg.msg, eta_seconds: msg.eta_seconds, phase: msg.phase ?? '' }
      }
    } else if (msg.type === 'director_done') {
      directorBusy.value[msg.group_id] = null
      const n = msg.matched_count ? `，匹配 ${msg.matched_count} 个片段` : ''
      show(`导演视频合成完成${n}`, 'success')
      load()
    } else if (msg.type === 'director_error') {
      directorBusy.value[msg.group_id] = null
      show(msg.error || '合成失败', 'error')
      load()
    } else if (msg.type === 'director_voice_done') {
      show('配音生成完成', 'success')
      load()
    }
  })
  // Poll every 15s for merge status updates
  const t = setInterval(load, 15000)
  onUnmounted(() => clearInterval(t))
})

// ── Human Review ─────────────────────────────────────────────────────────────

const reviewModal = ref(null)  // { rec, segs, selected: Set, algoIdxs: Set }
const reviewLoading = ref(false)
const reviewSaving = ref(false)
const suggestions = ref([])
const showSuggestions = ref(false)

function fmtSec(sec) {
  const m = Math.floor(sec / 60)
  const s = (sec % 60).toFixed(1).padStart(4, '0')
  return `${m}:${s}`
}

async function openReview(r) {
  reviewModal.value = { rec: r, segs: null, selected: new Set(), algoIdxs: new Set() }
  reviewLoading.value = true
  try {
    const res = await fetch(`${apiBase}/api/recordings/${r.id}/review-candidates`)
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    const segs = data.all_segs || []

    // Pre-select algo-selected segments from prev_review if available
    let algoIdxs = new Set()
    let prevSelected = new Set()
    if (data.prev_review) {
      algoIdxs = new Set(data.prev_review.algo_segments || [])
      prevSelected = new Set(data.prev_review.user_segments || [])
    } else {
      // No prior review — pre-select top-scored valid segments (algo's likely picks)
      // We sort by score descending and take top ~30%
      const valid = segs.filter(s => s.valid && s.score > 0).sort((a, b) => b.score - a.score)
      const topN = Math.max(1, Math.ceil(valid.length * 0.3))
      algoIdxs = new Set(valid.slice(0, topN).map(s => s.idx))
      prevSelected = new Set(algoIdxs)
    }

    reviewModal.value = { rec: r, segs, selected: new Set(prevSelected), algoIdxs }
  } catch (e) {
    show(e.message || '加载失败', 'error')
    reviewModal.value = null
  } finally {
    reviewLoading.value = false
  }
}

function toggleSeg(idx) {
  const m = reviewModal.value
  if (!m) return
  if (m.selected.has(idx)) m.selected.delete(idx)
  else m.selected.add(idx)
  // Trigger reactivity
  reviewModal.value = { ...m, selected: new Set(m.selected) }
}

const reviewModal_added = computed(() => {
  const m = reviewModal.value
  if (!m || !m.algoIdxs) return []
  return [...m.selected].filter(i => !m.algoIdxs.has(i))
})

const reviewModal_removed = computed(() => {
  const m = reviewModal.value
  if (!m || !m.algoIdxs) return []
  return [...m.algoIdxs].filter(i => !m.selected.has(i))
})

async function submitReview() {
  const m = reviewModal.value
  if (!m || !m.segs) return
  reviewSaving.value = true
  try {
    const algoArr = [...m.algoIdxs]
    const userArr = [...m.selected]
    const added = userArr.filter(i => !m.algoIdxs.has(i))
    const removed = algoArr.filter(i => !m.selected.has(i))
    const userSegsFull = m.segs.filter(s => added.includes(s.idx))

    const res = await fetch(`${apiBase}/api/recordings/${m.rec.id}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        algo_segments: algoArr,
        user_segments: userArr,
        user_added: added,
        user_removed: removed,
        user_segments_full: userSegsFull,
      })
    })
    if (!res.ok) throw new Error((await res.json()).detail || '提交失败')
    show('审核已提交，系统正在学习', 'success')
    reviewModal.value = null
    // Refresh suggestions after submit
    await loadSuggestions()
    // Update the recording's review_status in detail
    if (openId.value) detail.value = await getGroup(openId.value)
  } catch (e) {
    show(e.message || '提交失败', 'error')
  } finally {
    reviewSaving.value = false
  }
}

async function loadSuggestions() {
  try {
    const res = await fetch(`${apiBase}/api/rule-suggestions`)
    if (res.ok) suggestions.value = await res.json()
  } catch (e) { /* best effort */ }
}

async function acceptSuggestion(id) {
  try {
    const res = await fetch(`${apiBase}/api/rule-suggestions/${id}/accept`, { method: 'POST' })
    if (!res.ok) throw new Error((await res.json()).detail || '操作失败')
    show('规则已接受并生效', 'success')
    await loadSuggestions()
  } catch (e) { show(e.message || '操作失败', 'error') }
}

async function rejectSuggestion(id) {
  try {
    const res = await fetch(`${apiBase}/api/rule-suggestions/${id}/reject`, { method: 'POST' })
    if (!res.ok) throw new Error((await res.json()).detail || '操作失败')
    show('建议已忽略', 'info')
    await loadSuggestions()
  } catch (e) { show(e.message || '操作失败', 'error') }
}

onUnmounted(() => { ws?.close(); stopProgressPolling() })
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }
.toolbar-actions { display: flex; gap: 8px; }
.btn-primary { background: #fe2c55; color: #fff; border: none; padding: 7px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-primary:hover { background: #e0203d; }
.btn-custom { background: rgba(251,146,60,0.15); color: #fb923c; border: 1px solid rgba(251,146,60,0.4); padding: 7px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-custom:hover { background: rgba(251,146,60,0.25); }
.btn-edit { background: none; border: none; color: #555; cursor: pointer; font-size: 15px; padding: 0 4px; margin-left: 8px; }
.btn-edit:hover { color: #ccc; }
.btn-del { background: none; border: none; color: #555; cursor: pointer; font-size: 13px; padding: 0 4px; margin-left: 2px; }
.btn-del:hover { color: #fe2c55; }
.group-card-custom .btn-del { color: #aaa; }
.group-card-custom .btn-del:hover { color: #c0392b; }
.empty-tip { color: #444; text-align: center; padding: 60px; }
.groups-list { display: flex; flex-direction: column; gap: 12px; }
.group-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 18px; }
.group-card-custom { background: #f5f3ef; border: 2px solid #fb923c; color: #1a1a1a; }
.group-card-custom .group-label { color: #111; }
.group-card-custom .group-stats { color: #555; }
.group-card-custom .tag { background: #e8e4dc; color: #555; }
.group-card-custom .btn-sm { background: #e8e4dc; border-color: #ccc; color: #333; }
.group-card-custom .btn-sm:hover { background: #ddd; }
.group-card-custom .merge-error { color: #c0392b; }
.group-card-custom .detail-table th { color: #777; }
.group-card-custom .detail-table td { border-color: #e0dbd0; }
.group-card-custom .filename { color: #666; }
.group-card-custom .reassign-select { background: #f0ece4; border-color: #ccc; color: #333; }
.custom-upload-row { display: flex; align-items: center; gap: 8px; padding: 8px 0 0; }
.btn-upload-label { background: rgba(251,146,60,0.12); color: #c2540a; border: 1px solid rgba(251,146,60,0.4); padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.btn-upload-label:hover { background: rgba(251,146,60,0.22); }
.hidden-file-input { display: none; }
.uploading-hint { font-size: 12px; color: #fb923c; }
.group-header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.group-meta { flex: 1; }
.group-label { font-size: 16px; font-weight: 600; margin-bottom: 6px; }
.group-sub { display: flex; gap: 6px; flex-wrap: wrap; }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #2a2a2a; color: #999; }
.tag.color { background: rgba(251,191,36,0.12); color: #fbbf24; }
.tag.promo { background: rgba(254,44,85,0.12); color: #fe2c55; }
.tag.date-tag { background: rgba(148,163,184,0.2); color: #cbd5e1; }

/* 模式选择器样式 */
.mode-selector { margin-top: 4px; }
.mode-select {
  background: #1a1a1a;
  border: 1px solid #444;
  color: #ccc;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  min-width: 120px;
}
.mode-select:hover {
  border-color: #666;
}
.mode-select:focus {
  outline: none;
  border-color: #8b5cf6;
  box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.1);
}
.group-stats { font-size: 13px; color: #666; white-space: nowrap; }
.stat-item { margin-right: 12px; }
.group-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.btn-action { background: #2a2a2a; border: 1px solid #444; color: #ccc; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; text-decoration: none; display: inline-block; }
.btn-action:hover:not(:disabled) { background: #333; color: #fff; }
.btn-action:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-action.purple { background: rgba(168,85,247,0.15); color: #c084fc; border-color: rgba(168,85,247,0.3); }
.btn-action.yellow { background: rgba(251,191,36,0.12); color: #fbbf24; border-color: transparent; }
.btn-action.teal { background: rgba(45,212,191,0.12); color: #2dd4bf; border-color: rgba(45,212,191,0.3); }
.btn-action.green { background: rgba(34,197,94,0.12); color: #22c55e; border-color: rgba(34,197,94,0.3); }
.btn-action.red { background: rgba(254,44,85,0.12); color: #fe2c55; border-color: rgba(254,44,85,0.3); }
.btn-action.orange { background: rgba(251,146,60,0.15); color: #c2540a; border-color: rgba(251,146,60,0.4); }
.btn-sm { background: #222; border: 1px solid #333; color: #888; padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.btn-sm:hover { background: #2a2a2a; color: #ccc; }
.merge-error { font-size: 12px; color: #fe2c55; margin-top: 8px; display: flex; align-items: center; gap: 8px; }
.btn-error-detail { background: none; border: 1px solid rgba(254,44,85,0.4); color: #fe2c55; border-radius: 4px; padding: 1px 7px; font-size: 11px; cursor: pointer; }
.btn-error-detail:hover { background: rgba(254,44,85,0.1); }
.modal-box { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 20px; max-width: 560px; width: 90%; }
.modal-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: #fe2c55; }
.error-pre { background: #111; border: 1px solid #2a2a2a; border-radius: 6px; padding: 12px; font-size: 11px; color: #f87171; white-space: pre-wrap; word-break: break-all; max-height: 300px; overflow-y: auto; margin: 0; }
.quality-issue-bar { display: flex; align-items: center; gap: 8px; margin-top: 10px; background: rgba(251,146,60,0.08); border: 1px solid rgba(251,146,60,0.3); border-radius: 8px; padding: 8px 12px; }
.quality-issue-icon { font-size: 14px; flex-shrink: 0; }
.quality-issue-text { font-size: 12px; color: #fb923c; flex: 1; line-height: 1.4; }
.detail-loading { text-align: center; color: #555; padding: 20px; }
.detail-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 16px; }
.detail-table th { text-align: left; padding: 8px 12px; color: #555; border-bottom: 1px solid #222; }
.detail-table td { padding: 10px 12px; border-bottom: 1px solid #1e1e1e; }
.filename { font-family: monospace; color: #888; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; text-decoration: none; display: inline-block; }
.badge.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge.yellow { background: rgba(251,191,36,0.12); color: #fbbf24; }
.badge.dim { background: #2a2a2a; color: #555; }
.badge.red { background: rgba(254,44,85,0.15); color: #fe2c55; }
.status-cell { min-width: 140px; }
.progress-wrap { display: flex; flex-direction: column; gap: 3px; }
.progress-label { display: flex; justify-content: space-between; font-size: 11px; }
.progress-msg { color: #aaa; }
.progress-pct { color: #ccc; font-weight: 600; }
.progress-bar-bg { height: 5px; background: #2a2a2a; border-radius: 3px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #a855f7, #7c3aed); border-radius: 3px; transition: width 0.4s ease; }
.progress-eta { font-size: 10px; color: #666; }
.group-card-custom .progress-bar-bg { background: #ddd; }
.group-card-custom .progress-msg { color: #666; }
.group-card-custom .progress-pct { color: #333; }
.group-card-custom .progress-eta { color: #999; }
.empty { text-align: center; color: #444; padding: 20px; }
.reassign-select { background: #1a1a1a; border: 1px solid #333; color: #888; padding: 3px 6px; border-radius: 4px; font-size: 11px; cursor: pointer; max-width: 130px; }
.reassign-select:focus { outline: none; border-color: #555; }
.thumb-cell { width: 70px; padding: 6px 12px; }
.thumb-img { width: 60px; height: 34px; object-fit: cover; border-radius: 4px; display: block; }
.thumb-placeholder { width: 60px; height: 34px; background: #111; border-radius: 4px; }
/* Publish Modal */
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 24px; width: 480px; max-width: 92vw; }
.modal-header { display: flex; justify-content: space-between; align-items: center; font-size: 15px; font-weight: 600; margin-bottom: 20px; }
.modal-close { background: none; border: none; color: #666; font-size: 16px; cursor: pointer; padding: 0; }
.modal-close:hover { color: #ccc; }
.modal-loading { text-align: center; color: #666; padding: 30px 0; }
.modal-field { margin-bottom: 16px; }
.modal-field label { display: block; font-size: 12px; color: #888; margin-bottom: 6px; }
.field-hint { color: #555; margin-left: 4px; }
.modal-input { width: 100%; background: #111; border: 1px solid #333; color: #ccc; border-radius: 6px; padding: 8px 10px; font-size: 13px; box-sizing: border-box; resize: vertical; font-family: inherit; }
.modal-input:focus { outline: none; border-color: #555; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.import-preview { font-size: 11px; color: #34d399; margin-top: 4px; }
.modal-custom { background: #f5f3ef; border-color: #fb923c; color: #1a1a1a; }
.modal-custom .modal-header { color: #1a1a1a; }
.modal-custom .modal-field label { color: #555; }
.modal-custom .modal-input { background: #fff; border-color: #ccc; color: #1a1a1a; }
.modal-custom .modal-input:focus { border-color: #fb923c; }
.modal-custom .modal-close { color: #888; }
.published-tag { background: rgba(52,211,153,0.12); color: #34d399; }
.clip-done-row { display: inline-flex; align-items: center; gap: 4px; }
.badge-btn { font-size: 11px; padding: 2px 8px; border-radius: 10px; cursor: pointer; border: none; background: rgba(168,85,247,0.15); color: #c084fc; }
.badge-btn:hover { background: rgba(168,85,247,0.28); }
.badge-btn.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge-btn.orange { background: rgba(251,146,60,0.15); color: #fb923c; }
.badge-btn.orange:hover { background: rgba(251,146,60,0.28); }
.reclip-hint { font-size: 11px; color: #666; margin: -8px 0 12px; padding: 0 2px; }
.reclip-success { text-align: center; padding: 28px 16px 20px; }
.reclip-success-icon { font-size: 36px; color: #34d399; margin-bottom: 12px; }
.reclip-success-title { font-size: 16px; font-weight: 600; color: #ccc; margin-bottom: 8px; }
.reclip-success-sub { font-size: 13px; color: #666; line-height: 1.6; }
.preview-modal { background: #111; border: 1px solid #333; border-radius: 12px; width: min(860px, 94vw); max-height: 90vh; display: flex; flex-direction: column; overflow: hidden; }
.preview-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid #222; font-size: 13px; color: #aaa; gap: 12px; }
.preview-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: monospace; font-size: 12px; }
.preview-video { width: 100%; max-height: 70vh; background: #000; display: block; }
.preview-err { text-align: center; color: #fe2c55; padding: 20px; }
.preview-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid #222; }
.director-panel { padding: 10px 16px; background: rgba(99,102,241,0.07); border-top: 1px solid rgba(99,102,241,0.2); border-bottom: 1px solid rgba(99,102,241,0.2); }
.retry-modes-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; padding: 8px 10px; background: rgba(99,102,241,0.12); border-radius: 6px; border: 1px solid rgba(99,102,241,0.3); }
.btn-retry-modes { padding: 6px 14px; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; white-space: nowrap; }
.btn-retry-modes:hover { opacity: 0.85; }
.retry-hint { font-size: 11px; color: #a5b4fc; }
.vibe-selector { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.vibe-label { font-size: 11px; color: #a5b4fc; font-weight: 600; }
.vibe-select { padding: 3px 8px; font-size: 12px; border-radius: 6px; border: 1px solid rgba(99,102,241,0.4); background: rgba(99,102,241,0.15); color: #e0e7ff; cursor: pointer; }
.vibe-hint { font-size: 11px; color: #818cf8; font-style: italic; }
.director-steps { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.director-step { display: flex; align-items: center; gap: 6px; }
.step-num { width: 20px; height: 20px; border-radius: 50%; background: rgba(99,102,241,0.3); color: #a5b4fc; font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.btn-director { padding: 5px 12px; font-size: 12px; border-radius: 6px; border: 1px solid rgba(99,102,241,0.4); background: rgba(99,102,241,0.15); color: #a5b4fc; cursor: pointer; white-space: nowrap; }
.btn-director:hover:not(:disabled) { background: rgba(99,102,241,0.3); }
.btn-director:disabled { opacity: 0.4; cursor: not-allowed; }
.step-done { font-size: 11px; color: #6ee7b7; white-space: nowrap; }
.director-error { margin-top: 6px; font-size: 11px; color: #f87171; }
/* Review modal */
.review-modal { width: 680px; max-width: 95vw; max-height: 90vh; display: flex; flex-direction: column; }
.review-loading { text-align: center; color: #666; padding: 30px 0; flex: 1; }
.review-hint { font-size: 11px; color: #888; margin-bottom: 12px; line-height: 1.6; background: rgba(99,102,241,0.06); border-radius: 6px; padding: 8px 10px; border: 1px solid rgba(99,102,241,0.15); }
.review-segments { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; max-height: 50vh; padding-right: 4px; }
.review-seg { display: flex; gap: 10px; padding: 8px 10px; border-radius: 6px; border: 1px solid #2a2a2a; cursor: pointer; transition: border-color 0.15s, background 0.15s; }
.review-seg:hover { border-color: #444; background: rgba(255,255,255,0.02); }
.review-seg-selected { border-color: rgba(168,85,247,0.6); background: rgba(168,85,247,0.08); }
.review-seg-invalid { opacity: 0.4; }
.review-seg-check { font-size: 14px; color: #c084fc; width: 16px; flex-shrink: 0; padding-top: 1px; }
.review-seg-body { flex: 1; min-width: 0; }
.review-seg-time { font-size: 10px; color: #555; font-family: monospace; margin-bottom: 2px; }
.review-seg-text { font-size: 12px; color: #ccc; line-height: 1.5; word-break: break-all; }
.review-seg-meta { display: flex; gap: 6px; margin-top: 4px; flex-wrap: wrap; }
.review-score { font-size: 10px; background: rgba(250,204,21,0.12); color: #fcd34d; border-radius: 4px; padding: 1px 5px; }
.review-cat { font-size: 10px; background: rgba(99,102,241,0.12); color: #818cf8; border-radius: 4px; padding: 1px 5px; }
.review-invalid-mark { font-size: 10px; background: rgba(254,44,85,0.12); color: #f87171; border-radius: 4px; padding: 1px 5px; }
.review-summary { margin-top: 10px; font-size: 11px; color: #888; padding: 6px 10px; background: #111; border-radius: 6px; }
.badge-btn.teal { background: rgba(20,184,166,0.15); color: #2dd4bf; }
.badge-btn.teal:hover { background: rgba(20,184,166,0.28); }
/* Rule suggestions panel */
.suggestions-modal { width: 560px; max-width: 95vw; max-height: 85vh; display: flex; flex-direction: column; }
.suggestions-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.suggestion-item { padding: 12px; border: 1px solid #2a2a2a; border-radius: 8px; background: #111; }
.sug-kw { font-size: 13px; font-weight: 600; color: #a78bfa; margin-bottom: 4px; }
.sug-reason { font-size: 11px; color: #888; margin-bottom: 6px; line-height: 1.5; }
.sug-score { font-size: 11px; color: #fcd34d; margin-bottom: 8px; font-family: monospace; }
.sug-actions { display: flex; gap: 8px; }
/* Cover panel */
.cover-panel { padding: 10px 16px; background: rgba(245,158,11,0.06); border-top: 1px solid rgba(245,158,11,0.18); }
.cover-panel-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.cover-panel-title { font-size: 12px; font-weight: 700; color: #fbbf24; }
.btn-cover-gen { padding: 4px 12px; font-size: 12px; border-radius: 6px; border: 1px solid rgba(245,158,11,0.4); background: rgba(245,158,11,0.15); color: #fbbf24; cursor: pointer; white-space: nowrap; }
.btn-cover-gen:hover:not(:disabled) { background: rgba(245,158,11,0.3); }
.btn-cover-gen:disabled { opacity: 0.4; cursor: not-allowed; }
.cover-selected-hint { font-size: 11px; color: #6ee7b7; }
.cover-candidates { display: flex; gap: 12px; flex-wrap: wrap; }
.cover-candidate { position: relative; cursor: pointer; border: 2px solid #333; border-radius: 8px; overflow: hidden; transition: border-color 0.15s; }
.cover-candidate:hover { border-color: #fbbf24; }
.cover-candidate-selected { border-color: #fbbf24; box-shadow: 0 0 0 2px rgba(245,158,11,0.4); }
.cover-img { width: 120px; height: 213px; object-fit: cover; display: block; image-rendering: -webkit-optimize-contrast; image-rendering: crisp-edges; }
.cover-scheme-label { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.7); color: #fbbf24; font-size: 10px; text-align: center; padding: 3px 4px; font-weight: 600; }
.cover-check { position: absolute; top: 4px; right: 4px; width: 18px; height: 18px; border-radius: 50%; background: #fbbf24; color: #000; font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.cover-preview-btn { position: absolute; top: 4px; left: 4px; width: 20px; height: 20px; border-radius: 4px; background: rgba(0,0,0,0.6); color: #fff; border: none; cursor: pointer; font-size: 12px; display: flex; align-items: center; justify-content: center; opacity: 0; transition: opacity 0.15s; padding: 0; }
.cover-candidate:hover .cover-preview-btn { opacity: 1; }
/* Cover preview modal */
.cover-preview-modal { background: #111; border: 1px solid #333; border-radius: 12px; width: min(480px, 95vw); display: flex; flex-direction: column; overflow: hidden; }
.cover-preview-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid #222; gap: 10px; }
.cover-preview-title { font-size: 13px; color: #aaa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.cover-preview-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.cover-preview-body { display: flex; align-items: center; justify-content: center; background: #000; position: relative; padding: 0 40px; }
.cover-preview-img { width: 100%; max-width: 360px; max-height: 70vh; object-fit: contain; display: block; }
.cover-nav { position: absolute; top: 50%; transform: translateY(-50%); width: 36px; height: 36px; border-radius: 50%; background: rgba(255,255,255,0.12); border: none; color: #fff; font-size: 22px; cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 2; transition: background 0.15s; }
.cover-nav:hover:not(:disabled) { background: rgba(255,255,255,0.25); }
.cover-nav:disabled { opacity: 0.2; cursor: default; }
.cover-nav-prev { left: 6px; }
.cover-nav-next { right: 6px; }
.cover-preview-dots { display: flex; justify-content: center; gap: 8px; padding: 12px; }
.cover-dot { width: 8px; height: 8px; border-radius: 50%; background: #444; cursor: pointer; transition: background 0.15s; }
.cover-dot-active { background: #fbbf24; }
</style>
