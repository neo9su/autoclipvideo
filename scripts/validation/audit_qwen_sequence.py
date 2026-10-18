"""Replay saved Qwen sequence JSON without GPU/model/production access."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.wig_sequence_evidence import analyze_sequence


def audit(path):
    data = path.read_bytes()
    saved = json.loads(data)
    cases = []
    for case in saved.get('cases', []):
        parsed = case.get('parsed')
        if isinstance(parsed, dict) and isinstance(parsed.get('frames'), list):
            cases.append({'case': case['name'], 'audit': analyze_sequence(parsed['frames'])})
    return {'input_sha256': hashlib.sha256(data).hexdigest(), 'cases': cases,
            'case_count': len(cases), 'issue_count': sum(c['audit']['issue_count'] for c in cases),
            'scope': 'saved_model_output_consistency_not_visual_accuracy', 'gpu_calls': 0,
            'production_modified': False}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path);p.add_argument('output', type=Path);a=p.parse_args()
    result=audit(a.input)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({'case_count':result['case_count'], 'issue_count':result['issue_count'], 'gpu_calls':0}))
