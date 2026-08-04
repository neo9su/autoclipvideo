# Issue #16 千川投流独立试跑证据

- 试跑范围：单个小样本，未批量触发
- 任务接口：`POST /api/v2/qianchuan/generate`
- 任务 ID：`group_id=5130`
- 样本分组：`夺回人生 黑茶色`
- 商品匹配：商品记录 `18`，夺回人生/免发网/大波浪
- 匹配分：`0.763`，阈值 `0.58`
- 脚本：5 个场景，目标时长 18 秒
- 关键步骤：商品强匹配 → 千川脚本生成 → 配音 → 镜头匹配 → 视频合成 → 质量探测
- 最终状态：`2`（成功）
- 生成视频：`director_output_1785592798.mp4`
- 视频属性：21.226 秒，1080×1920，H.264/YUV420P，AAC，25 fps
- 质量探测：`ok=true`，解码通过，无错误；仅提示 fps 为 25 而非接近 30
- 预览截图：`qianchuan_issue16_preview.jpg`

## 运行证据

```json
{
  "group_id": 5130,
  "status": 2,
  "score": 0.763,
  "script_scene_count": 5,
  "matched_segment_count": 2,
  "final_video": "director_output_1785592798.mp4",
  "quality": {
    "ok": true,
    "duration": 21.226009,
    "width": 1080,
    "height": 1920,
    "video_codec": "h264",
    "audio_codec": "aac",
    "fps": 25.0,
    "decode_ok": true,
    "errors": []
  }
}
```

> 说明：运行过程中只提交了这一条 `group_id=5130` 请求；没有调用批量触发脚本。
