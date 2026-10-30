"""Replay saved Qwen sequence JSON without GPU/model/production access."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from backend.wig_sequence_evidence import analyze_sequence, attach_catalogue_evidence
from wig_transcript_evidence import parse_srt


def audit(path, *, srt=None, products=None):
    data = path.read_bytes()
    saved = json.loads(data)
    cases = []
    for case in saved.get('cases', []):
        parsed = case.get('parsed')
        if isinstance(parsed, dict) and isinstance(parsed.get('frames'), list):
            sequence = analyze_sequence(parsed['frames'])
            if srt is not None:
                sequence = attach_catalogue_evidence(sequence, parse_srt(srt), products)
            cases.append({'case': case['name'], 'audit': sequence})
    return {'input_sha256': hashlib.sha256(data).hexdigest(), 'cases': cases,
            'case_count': len(cases), 'issue_count': sum(c['audit']['issue_count'] for c in cases),
            'scope': 'saved_model_output_consistency_not_visual_accuracy', 'gpu_calls': 0,
            'production_modified': False,
            'subtitle_sha256': hashlib.sha256(srt.encode()).hexdigest() if srt is not None else None,
            'catalogue_sha256': hashlib.sha256(json.dumps(products, ensure_ascii=False, sort_keys=True).encode()).hexdigest() if products is not None else None}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path);p.add_argument('output', type=Path)
    p.add_argument('--srt', type=Path);p.add_argument('--catalogue', type=Path);a=p.parse_args()
    if bool(a.srt) != bool(a.catalogue):p.error('--srt and --catalogue must be supplied together')
    result=audit(a.input, srt=a.srt.read_text(encoding='utf-8-sig') if a.srt else None,
                 products=json.loads(a.catalogue.read_text(encoding='utf-8')) if a.catalogue else None)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({'case_count':result['case_count'], 'issue_count':result['issue_count'], 'gpu_calls':0}))
