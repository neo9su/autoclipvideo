"""Shadow diagnostic: separate visible head state from before/after appearance."""
import argparse
import json
from pathlib import Path
import resource
import time
from audit_wig_sequence import MODELS, GENERATION, digest, read_cases
from audit_wig_visual import verify_snapshot

FIELDS = {
 'head': {'hair_visible','close_fitting_or_net','occluded','uncertain'},
 'color': {'black','dark_brown','warm_brown','blonde','pink','grey','other','uncertain'},
 'bangs': {'full','curtain','side','none','uncertain'},
 'texture': {'straight','wavy','curly','uncertain'},
}
PROMPT = '''这三张完整画面按时间先后取自同一段连续视频：开始、中间、结束。只观察真实主播的头部，不观察手机屏幕内的人或手持假发。不推断SKU，不总结是否同款。逐张提取可见特征，遮挡就填uncertain。
只输出JSON：{"frames":[{"index":0,"head":"...","color":"...","bangs":"...","texture":"..."}, ...]}，必须恰好三项，index依次0、1、2。
head只能为hair_visible（明显披散的头发）、close_fitting_or_net（贴头短发或发网，不能确认真发）、occluded（被挡住）、uncertain。
color只能black、dark_brown、warm_brown、blonde、pink、grey、other、uncertain。
bangs只能full（齐刘海）、curtain（中分帘式刘海）、side（侧分）、none、uncertain。
texture只能straight（直）、wavy（波浪）、curly（明显卷曲）、uncertain。
head不是hair_visible时，color、bangs、texture全部填uncertain。不要把中间露出的黑色头部当作黑色商品。'''


def parse_frames(raw):
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('\n',1)[1].rsplit('```',1)[0].strip()
    try:
        frames = json.loads(text)['frames']
        if len(frames) != 3:
            raise ValueError('need exactly three ordered observations')
        for index, frame in enumerate(frames):
            if frame['index'] != index:
                raise ValueError('frame order mismatch')
            for field, allowed in FIELDS.items():
                if frame.get(field) not in allowed:
                    raise ValueError('invalid feature: '+field)
        return frames, None
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return None, str(exc)


def compare_appearance(frames):
    # This is evidence routing, not product/SKU approval or an action detector.
    result = dict(candidate='uncertain', reasons=[], requires_visual_review=True,
        eligible_for_render=False, sku_verified=False, physical_identity_verified=False)
    if frames is None:
        result['reasons'].append('invalid_observations')
        return result
    before, middle, after = frames
    if before['head'] != 'hair_visible' or after['head'] != 'hair_visible':
        result['reasons'].append('before_or_after_not_visible')
        return result
    fields = ('color','bangs','texture')
    # Middle-frame color is deliberately excluded: removal is not a new SKU.
    if any(before[f] == 'uncertain' or after[f] == 'uncertain' for f in fields):
        result['reasons'].append('before_or_after_features_unknown')
        return result
    differences = [f for f in fields if before[f] != after[f]]
    result['differences'] = differences
    if differences:
        result['candidate'] = 'different_visible_style'
    elif middle['head'] == 'close_fitting_or_net':
        result['candidate'] = 'matching_style_rewear_candidate'
        result['reasons'].append('three_states_do_not_prove_continuous_object_identity')
    elif middle['head'] == 'hair_visible':
        result['candidate'] = 'no_visible_style_change'
        result['reasons'].append('three_frames_cannot_exclude_intervening_switches')
    else:
        result['reasons'].append('middle_state_unknown')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True)
    p.add_argument('--model-dir',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    cases=read_cases(a.manifest)
    name,revision=MODELS['4b']
    root=verify_snapshot(a.model_dir,name,revision)
    with Path(a.output).open('x',encoding='utf-8') as report, Path(a.output+'.progress.jsonl').open('x',encoding='utf-8') as progress:
        import cv2
        from PIL import Image
        import mlx.core as mx
        from mlx_vlm import load,generate
        from mlx_vlm.prompt_utils import apply_chat_template
        mx.set_memory_limit(6*1024**3);mx.set_cache_limit(256*1024**2);mx.reset_peak_memory();mx.random.seed(0)
        model,processor=load(str(root),trust_remote_code=False)
        results=[]
        for c in cases:
            started=time.monotonic();mx.clear_cache();mx.reset_peak_memory()
            cap=cv2.VideoCapture(c['_path'])
            count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=cap.get(cv2.CAP_PROP_FPS)
            if not count or fps <= 0:raise ValueError('unreadable clip')
            indices=[0,count//2,count-1];images=[]
            try:
                for i in indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES,i);ok,frame=cap.read()
                    if not ok:raise ValueError('keyframe read failed')
                    images.append(Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)))
            finally:cap.release()
            prompt=apply_chat_template(processor,model.config,PROMPT,num_images=3)
            answer=generate(model,processor,prompt,image=images,max_pixels=512*512,max_tokens=500,verbose=False,**GENERATION)
            observations,error=parse_frames(answer.text)
            result=dict(id=c['id'], recording_id=c['recording_id'], source_start_s=c['source_start_s'],
                clip_sha256=c['sha256'], sampled_timestamps_s=[i/fps for i in indices],
                raw=answer.text, observations=observations, parse_error=error,
                policy=compare_appearance(observations), elapsed_seconds=round(time.monotonic()-started,2),
                mlx_peak_bytes=mx.get_peak_memory(), prompt_tokens=answer.prompt_tokens,generation_tokens=answer.generation_tokens)
            results.append(result);progress.write(json.dumps(result,ensure_ascii=False)+'\n');progress.flush()
            print(c['id'],result['policy']['candidate'],result['mlx_peak_bytes'],flush=True)
        json.dump(dict(model=name,revision=revision,script_sha256=digest(__file__),manifest_sha256=digest(a.manifest),
            generation=GENERATION,seed=0,scope='three sampled frames diagnostic, not continuous-motion verification',
            memory_kind='Apple unified memory, not CUDA VRAM',process_peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            results=results),report,ensure_ascii=False,indent=2)

if __name__=='__main__':main()
