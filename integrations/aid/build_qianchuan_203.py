"""Port the verified fixed renderer to a separate Windows/203 profile."""
import ast,copy
PROFILE='qianchuan-render-203'
FFMPEG=r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
FFPROBE=r'C:\ProgramData\chocolatey\bin\ffprobe.exe'
RUN='''def run(command: list[str], cancel_file: Path, deadline: float) -> None:
    import tempfile
    with tempfile.TemporaryFile() as diagnostics:
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=diagnostics,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        while process.poll() is None:
            if cancel_file.is_file() or time.monotonic() >= deadline:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                raise RuntimeError("Qianchuan render cancelled or timed out")
            time.sleep(0.5)
        if process.returncode != 0:
            diagnostics.seek(0, 2)
            diagnostics.seek(max(0, diagnostics.tell() - 4096))
            detail = diagnostics.read().decode("utf-8", "replace")[-600:]
            raise RuntimeError("FFmpeg render failed: " + detail)
'''

def worker(source):
    assert source.count('PROFILE = "qianchuan-render"')==1,'Worker profile drift'
    source=source.replace('PROFILE = "qianchuan-render"',f'PROFILE = "{PROFILE}"',1)
    assert source.count('FFMPEG = Path("/usr/bin/ffmpeg")')==1
    source=source.replace('FFMPEG = Path("/usr/bin/ffmpeg")','FFMPEG = Path('+repr(FFMPEG)+')')
    source=source.replace('FFPROBE = Path("/usr/bin/ffprobe")','FFPROBE = Path('+repr(FFPROBE)+')')
    assert source.count('"nodeId": "gpu-222"')==2
    source=source.replace('"nodeId": "gpu-222"','"nodeId": "gpu-203"')
    source=source.replace('deadline = started + 3600','deadline = started + 3500')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='run')
    lines=source.splitlines(keepends=True);lines[node.lineno-1:node.end_lineno]=(RUN+'\n').splitlines(keepends=True)
    result=''.join(lines);compile(result,'gpu_qianchuan_render_worker.py','exec');return result

def profile(original):
    value=copy.deepcopy(original)
    value.update(displayName='千川视频分析与重混（203）',allowedNodeIds=['gpu-203'],gpuIndices=[0],enabled=True)
    return value

def agent_profile():
    return dict(runCommand=[r'C:\Python313\python.exe',r'C:\ProgramData\AIDGpuScheduler\adapters\qianchuan-render-203\gpu_qianchuan_render_worker.py','{job_file}'],resultRequired=True,allowedProcessPatterns=[r'(?i)qianchuan-render-203[\\/]+gpu_qianchuan_render_worker\.py',r'(?i)ffmpeg\.exe.*AIDGpuScheduler[\\/]+spool[\\/]'])
