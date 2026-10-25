export function uploadPublishVideoRequest(url, file, onProgress, signal, XHR = XMLHttpRequest) {
  return new Promise((resolve, reject) => {
    const xhr = new XHR(), form = new FormData()
    form.append('file', file)
    xhr.open('POST', url)
    xhr.timeout = 30 * 60 * 1000
    const abort = () => xhr.abort()
    const finish = (action, value) => { signal?.removeEventListener('abort', abort); action(value) }
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded * 100 / event.total))
    }
    xhr.onload = () => {
      let data
      try { data = JSON.parse(xhr.responseText) } catch { /* Handle plain server failures below. */ }
      if (xhr.status >= 200 && xhr.status < 300 && data?.group?.id) finish(resolve, data)
      else finish(reject, new Error(typeof data?.detail === 'string' ? data.detail : `上传失败 (${xhr.status})`))
    }
    xhr.onerror = xhr.ontimeout = () => finish(reject, new Error('上传结果未确认，可重新选择同一文件重试；相同内容不会重复建分组'))
    xhr.onabort = () => finish(reject, new Error('上传已取消；当前文件结果如未确认，可重新选择同一文件重试'))
    if (signal?.aborted) return reject(new Error('上传已取消'))
    signal?.addEventListener('abort', abort, { once: true })
    xhr.send(form)
  })
}

export function createPublishVideoUploader(options) {
  const { ref } = options
  const busy = ref(false), status = ref(''), errors = ref([]), completed = ref([])
  let controller = null, cancelled = false
  async function uploadFiles(fileList) {
    if (busy.value || options.isBusy()) return
    const files = Array.from(fileList || [])
    if (!files.length) return
    busy.value = true; errors.value = []; completed.value = []; cancelled = false
    try {
      for (let index = 0; index < files.length; index++) {
        if (cancelled) break
        const file = files[index]
        if (!/\.(mp4|mov)$/i.test(file.name) || file.size > 1_000_000_000 || !file.size) {
          errors.value = [...errors.value, `${file.name}：请选择不超过1000MB的非空MP4/MOV视频`]
          continue
        }
        controller = new AbortController()
        const progress = percent => { status.value = `上传 ${index + 1}/${files.length}：${file.name} ${percent}%${percent === 100 ? '，正在校验入库…' : ''}` }
        progress(0)
        try {
          const result = await options.upload(file, progress, controller.signal)
          options.addGroup(result.group)
          completed.value = [...completed.value, { id: result.group.id, name: file.name, reused: result.reused }]
        } catch (error) {
          errors.value = [...errors.value, `${file.name}：${error.message || error}`]
        }
      }
      status.value = `已完成 ${completed.value.length}/${files.length} 个视频，上传成功的视频已选中，可继续编辑文案和挂车商品。`
    } finally { busy.value = false; controller = null }
  }
  function cancel() { cancelled = true; controller?.abort() }
  return { busy, status, errors, completed, uploadFiles, cancel }
}
