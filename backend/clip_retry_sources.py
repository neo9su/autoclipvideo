"""Resolve migrated retry inputs without assuming video and subtitles share a folder."""
import os

def resolve_retry_files(filename, recording_resolver, subtitle_resolver):
    video=recording_resolver(filename)
    if not video or not os.path.isfile(video):
        return None,None,'录像文件不存在或当前账号无法访问'
    # Prefer the exact sidecar, then the authoritative historical SRT resolver.
    sidecar=os.path.splitext(video)[0]+'.srt'
    if os.path.isfile(sidecar) and os.path.getsize(sidecar)>0:
        return video,sidecar,None
    for candidate in (video,filename):
        subtitle=subtitle_resolver(candidate)
        if subtitle and os.path.isfile(subtitle) and os.path.getsize(subtitle)>0:
            return video,subtitle,None
    return video,None,'字幕文件不存在或为空，需要先恢复转写'
