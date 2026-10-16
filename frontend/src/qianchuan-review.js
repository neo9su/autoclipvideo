export const qianchuanStatusMap = {
  0: { label: '未生成', className: 'idle', hint: '千川结果尚未生成，请先生成/重试千川版。' },
  1: { label: '生成中', className: 'running', hint: '正在生成千川投流版，请勿重复提交。' },
  2: { label: '已完成', className: 'done', hint: '千川投流版已生成，可预览或下载。' },
  '-1': { label: '普通失败', className: 'failed', hint: '生成失败，可查看错误摘要后重试。' },
  '-2': { label: '商品不匹配', className: 'blocked', hint: '商品/颜色/镜头匹配不足，已拒绝生成。' },
  '-3': { label: '质量失败', className: 'failed', hint: '质量检测不通过，请调整素材后重试。' },
  '-4': { label: '编码/探测失败', className: 'failed', hint: '视频编码或质量探测失败，可重试或检查素材。' },
  '-5': { label: '款式一致性待审核', className: 'blocked', hint: '已暂停自动生成。核实款式、颜色和商品后重新检查；检查通过不代表画面已审核。' },
}

const reasons = {
  ambiguous_group_identity: '分组款式或颜色不明确',
  multiple_group_products: '分组包含多个商品简称',
  no_recording_evidence: '没有已转录的候选录像',
  missing_room: '缺少房间信息', room_mismatch: '录像来自其他房间',
  missing_recording_identity: '录像缺少款式或颜色',
  recording_identity_conflict: '录像款式或颜色与目标冲突',
  multiple_products_in_recording: '录像提及多个商品',
  product_name_conflict: '录像商品简称与目标不同',
  different_recording_products: '候选录像对应不同商品',
}

export function identityReviewItems(group) {
  let review = group.qianchuan_review
  if (typeof review === 'string') {
    try { review = JSON.parse(review) } catch { return ['审核证据无法读取，请重新检查'] }
  }
  return (review?.identity?.issues || []).slice(0, 10).map(issue => {
    const source = issue.recording_id != null ? `录像 #${issue.recording_id}：` : ''
    const expected = (issue.expected || []).join('、')
    const observed = (issue.observed || []).join('、')
    return `${source}${reasons[issue.code] || '需核实款式证据'}${expected ? `；目标：${expected}` : ''}${observed ? `；识别：${observed}` : ''}`
  })
}
