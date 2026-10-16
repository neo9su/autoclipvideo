"""Offline, bounded Qwen video experiment. No production imports or write access."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import time

from audit_wig_visual import verify_snapshot

MODEL = 'mlx-community/Qwen3-VL-2B-Instruct-4bit'
REVISION = '9c4f5209e57b31f4b9dfba735de3fb983739c9cc'
RELATIONS = {'visually_matching_rewear', 'different_style_or_color', 'no_wear_change', 'put_on_only', 'remove_only', 'uncertain'}
PROMPT = '''观看这一段连续的假发直播视频，只跟踪真实主播，不把手机里的照片当主播。比较开始和结束时的发色、刘海、长度、卷直程度，并观察中间摘下和戴上的过程。黑色贴头的头发或发网是未佩戴状态，不能当作另一款黑色假发。梳理、扎发或光线变化本身不算换款。假发离开画面要记录identity_gap=true；外观一致不代表实物或SKU已确认。看不清前后发型就回答uncertain。
仅输出一个简短JSON，不要Markdown。relation只能选：visually_matching_rewear（前后外观一致且有摘下、未佩戴、戴回完整过程）、different_style_or_color（前后发型或颜色明显不同）、no_wear_change、put_on_only、remove_only、uncertain。
字段：relation；before和after（实际看到的发型，各20字以内）；events（最多4个关键动作，按顺序，每项含start_s、end_s、action、evidence；时间为片段内秒数；action只能是remove、put_on、unworn、occluded或display）；identity_gap（布尔）；reason（40字以内）。不能虚构没看到的动作。'''
GENERATION = dict(temperature=0.7, top_p=0.8, top_k=20, presence_penalty=1.5)



def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read_cases(path):
    path = Path(path).resolve(strict=True)
    cases = json.loads(path.read_text())['samples']
    if not 1 <= len(cases) <= 8:
        raise ValueError('select 1–8 explicit clips')
    seen = set()
    for c in cases:
        if c['id'] in seen:
            raise ValueError('duplicate sample id')
        seen.add(c['id'])
        file = (path.parent / c['video']).resolve(strict=True)
        if not file.is_relative_to(path.parent):
            raise ValueError('clip escapes manifest directory')
        if not 0 < c['duration_s'] <= 150 or c['source_start_s'] < 0:
            raise ValueError('clip duration/source time out of bounds')
        if digest(file) != c['sha256']:
            raise ValueError('clip checksum mismatch')
        if c.get('expected') not in RELATIONS:
            raise ValueError('missing explicit human label, including uncertain')
        c['_path'] = str(file)
    return cases


def parse_observation(raw, duration):
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    try:
        d = json.loads(text)
        if not isinstance(d, dict) or d.get('relation') not in RELATIONS:
            raise ValueError('invalid relation')
        if type(d.get('identity_gap')) is not bool:
            raise ValueError('missing explicit identity uncertainty')
        for k in ['before', 'after', 'reason']:
            if not isinstance(d.get(k), str):
                raise ValueError('missing description')
        if not isinstance(d.get('events'), list):
            raise ValueError('missing event timeline')
        prior = -1
        for event in d['events']:
            start, end = event['start_s'], event['end_s']
            if type(start) not in (int, float) or type(end) not in (int, float) or not (0 <= start <= end <= duration):
                raise ValueError('event outside clip')
            if start < prior:
                raise ValueError('events not in time order')
            prior = start
            if event['action'] not in {'remove', 'put_on', 'unworn', 'occluded', 'display'} or not isinstance(event.get('evidence'), str):
                raise ValueError('invalid event')
        if d['relation'] == 'visually_matching_rewear':
            actions = [event['action'] for event in d['events']]
            try:
                removed = actions.index('remove')
                unworn = actions.index('unworn', removed + 1)
                actions.index('put_on', unworn + 1)
            except ValueError:
                raise ValueError('same-style rewear requires ordered remove/unworn/put_on evidence')
        return d, None
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return {'relation':'uncertain'}, str(exc)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--model-dir', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--fps', type=float, choices=[1.0, 2.0], default=1.0)
    p.add_argument('--max-frames', type=int, choices=[32, 64, 128], default=128)
    a = p.parse_args()
    script_sha256 = digest(__file__)
    cases = read_cases(a.manifest)
    root = verify_snapshot(a.model_dir, MODEL, REVISION)
    # Reserve before model import; duplicate runs cannot replace prior evidence.
    with Path(a.output).open('x', encoding='utf-8') as report, Path(a.output + '.progress.jsonl').open('x', encoding='utf-8') as progress:
        import mlx.core as mx
        from mlx_vlm import load, generate
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_video, VideoSampling
        mx.set_memory_limit(6 * 1024**3)
        mx.set_cache_limit(256 * 1024**2)
        mx.reset_peak_memory()
        mx.random.seed(0)
        started = time.monotonic()
        model, processor = load(str(root), trust_remote_code=False)
        if getattr(processor, 'video_processor', None) is None:
            raise RuntimeError('native video processor required; no silent still-frame fallback')
        model_peak = mx.get_peak_memory()
        results = []
        print('Fixed 4bit model loaded', flush=True)
        for case in cases:
            mx.clear_cache()
            mx.reset_peak_memory()
            t = time.monotonic()
            frames, metadata = load_video(case['_path'], VideoSampling(fps=a.fps, min_frames=4, max_frames=a.max_frames, frame_factor=2))
            actual_duration = metadata.duration or metadata.total_num_frames / metadata.fps
            if abs(actual_duration-case['duration_s']) > 0.6:
                raise ValueError('decoded duration differs from approved manifest')
            # This runtime treats video max_pixels as a whole-clip budget.
            # Scale by actual sampled count, avoiding tiny frames on long clips.
            processor.video_processor.max_pixels = len(frames) * 256 * 256
            processor.video_processor.min_pixels = len(frames) * 32 * 32
            prompt = apply_chat_template(processor, model.config, PROMPT, video=case['_path'], fps=metadata.sampled_fps, max_pixels=256*256)
            answer = generate(model, processor, prompt, video=[frames], video_metadata=[asdict(metadata)], fps=metadata.sampled_fps, max_pixels=256*256, max_tokens=500, verbose=False, **GENERATION)
            parsed, error = parse_observation(answer.text, actual_duration)
            result = {k:v for k,v in case.items() if k != '_path'}
            result.update(raw=answer.text, observation=parsed, parse_error=error,
                prompt_tokens=answer.prompt_tokens, generation_tokens=answer.generation_tokens, finish_reason=answer.finish_reason,
                sampled_frames=len(metadata.frames_indices), sampled_timestamps_s=metadata.timestamps,
                video_pixel_budget=len(frames)*256*256,
                elapsed_seconds=round(time.monotonic()-t,2), mlx_peak_bytes=mx.get_peak_memory(),
                approval='review_required', eligible_for_render=False, sku_verified=False)
            # Human labels never enter the model prompt. A parse failure is no success.
            result['matches_human_label'] = error is None and parsed['relation'] == case['expected']
            results.append(result)
            progress.write(json.dumps(result, ensure_ascii=False) + '\n')
            progress.flush()
            print(case['id'], parsed['relation'], 'seconds',result['elapsed_seconds'],'peak_bytes',result['mlx_peak_bytes'], flush=True)
            del frames, answer
        data = dict(script_sha256=script_sha256, manifest_sha256=digest(a.manifest), generation=GENERATION, seed=0, model=MODEL, revision=REVISION, runtime='mlx-vlm 0.7.8, Apple Metal 4bit',
            hardware_memory_kind='Apple unified memory; not NVIDIA CUDA VRAM',
            model_load_peak_bytes=model_peak, process_peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            total_seconds=round(time.monotonic()-started,2), prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest(),
            visual_verified=False, sku_verified=False, eligible_for_render=False, results=results)
        json.dump(data, report, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()
