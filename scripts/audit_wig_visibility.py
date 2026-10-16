"""CPU-only foreground-occlusion proposals over existing, hashed test clips.

Tilted parallel edges are only a rigid-object risk proposal, NOT proof of a
screen or of target identity. A negative result never certifies visibility.
"""
import argparse
import copy
import json
import math
from pathlib import Path
from audit_wig_sequence import digest, read_cases

POLICY = 'wig-foreground-risk-v1'


def tilted_border_pairs(lines, width, height, anchor=(0.5, 0.35)):
    """Find separated near-parallel tilted borders straddling a viewport prior.

    The anchor is a geometric prior for these fixed-camera diagnostics, not a
    detected/tracked presenter. Background perspective can produce false holds.
    """
    ax, ay = anchor[0] * width, anchor[1] * height
    borders=[]
    for line in lines:
        x1,y1,x2,y2=map(float,line)
        dx,dy=x2-x1,y2-y1
        length=math.hypot(dx,dy)
        if length < width*.4 or abs(dy) < 1:
            continue
        slope=dx/dy
        tilt=abs(math.degrees(math.atan(slope)))
        if not 5 <= tilt <= 25:
            continue
        margin=abs(dy)*.1
        if not min(y1,y2)-margin <= ay <= max(y1,y2)+margin:
            continue
        borders.append(dict(x=x1+(ay-y1)*slope, angle=math.degrees(math.atan(slope)),line=list(line)))
    for i,left in enumerate(borders):
        for right in borders[i+1:]:
            if abs(left['angle']-right['angle']) > 7:
                continue
            lo,hi=sorted([left['x'],right['x']])
            if lo < ax < hi and hi-lo >= width*.35:
                return [left['line'],right['line']]
    return []


def foreground_risk(image):
    import cv2
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,60,160)
    raw=cv2.HoughLinesP(edges,1,math.pi/180,60,minLineLength=image.shape[1]*.4,maxLineGap=20)
    lines=[] if raw is None else raw[:,0,:].tolist()
    pair=tilted_border_pairs(lines,image.shape[1],image.shape[0])
    return dict(risk_candidate=bool(pair),border_lines=pair,
        reason='large_tilted_foreground_borders' if pair else 'no_geometric_proposal',
        target_verified=False, screen_confirmed=False)


def apply_visibility_hold(prior, risks):
    result=copy.deepcopy(prior)
    result.update(target_verified=False, head_state_verified=False,
        requires_visual_review=True, eligible_for_render=False,
        physical_identity_verified=False, sku_verified=False)
    result.setdefault('reasons',[])
    if risks:
        result['previous_candidate']=result.get('candidate','uncertain')
        result['candidate']='uncertain'
        result['reasons'].append('foreground_occlusion_candidate_requires_target_review')
    else:
        result['reasons'].append('negative_geometry_does_not_verify_target_or_head_state')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True)
    p.add_argument('--feature-report',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    cases=read_cases(a.manifest)
    cached=json.loads(Path(a.feature_report).read_text())
    if cached['manifest_sha256'] != digest(a.manifest):
        p.error('cached feature report belongs to a different manifest')
    records={r['id']:r for r in cached['results']}
    if set(records) != {c['id'] for c in cases}:
        p.error('cached sample selection mismatch')
    with Path(a.output).open('x',encoding='utf-8') as out:
        import cv2
        cv2.setNumThreads(1)
        results=[]
        for case in cases:
            prior=records[case['id']]
            if prior['clip_sha256'] != case['sha256']:
                raise ValueError('cached feature clip checksum mismatch')
            cap=cv2.VideoCapture(case['_path'])
            fps=cap.get(cv2.CAP_PROP_FPS);n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if fps <= 0 or not n:
                cap.release();raise ValueError('unreadable clip')
            observations=[]
            # CPU proposals at approximately 1 fps; preserve actual indices/times.
            indices=sorted(set(range(0,n,max(1,round(fps))))|{n-1})
            try:
                for index in indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=cap.read()
                    if not ok:raise ValueError('CPU diagnostic frame read failed')
                    observations.append(dict(frame_index=index,timestamp_s=index/fps,**foreground_risk(image)))
            finally:cap.release()
            risks=[r for r in observations if r['risk_candidate']]
            results.append(dict(id=case['id'],clip_sha256=case['sha256'],
                observations=observations, risk_count=len(risks),
                policy=apply_visibility_hold(prior['policy'],risks)))
            print(case['id'],'risk frames',len(risks),'/',len(observations),flush=True)
        json.dump(dict(policy=POLICY,script_sha256=digest(__file__),
            source_report_sha256=digest(a.feature_report), manifest_sha256=digest(a.manifest),
            compute='CPU only; no model inference or GPU access',
            target_anchor_scope='fixed-camera viewport prior, not identity tracking',
            negative_result_certifies_nothing=True, results=results),out,ensure_ascii=False,indent=2)

if __name__=='__main__':main()
