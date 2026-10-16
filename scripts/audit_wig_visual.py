"""Standalone shadow visual probe. Never imports production workers or approves clips."""
import argparse
import hashlib
import json
from pathlib import Path
import time

MODEL = 'HuggingFaceTB/SmolVLM-500M-Instruct'
REVISION = 'a7da5b986cb59b408707209984f360a5f4ad7e47'
QUESTIONS = {
    'people': 'How many people are visible? Describe each person by their position.',
    'hair': 'Describe the visible hair color, bangs and length of each person. If hidden, say unknown.',
    'wearing': 'Is there visible evidence that a person is wearing, putting on, removing, or holding a wig? Describe only visible evidence. If you cannot tell, say unknown.',
    'occlusion': 'Are heads or hair hidden by hands, a phone, or other objects? Describe what is hidden.',
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', action='append', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--cache-dir', required=True)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    a = p.parse_args()
    paths = [Path(x).resolve(strict=True) for x in a.image]
    if len(paths) > 12:
        p.error('at most 12 explicit images')
    out = Path(a.output)
    # Reserve a fresh output before expensive work; never overwrite prior evidence.
    with out.open('x', encoding='utf-8') as report:
        import torch
        from PIL import Image
        from transformers import AutoProcessor, AutoModelForImageTextToText
        torch.set_num_threads(2)
        if a.device == 'cuda':
            if not torch.cuda.is_available():
                raise RuntimeError('CUDA unavailable; no silent fallback')
            torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        processor = AutoProcessor.from_pretrained(MODEL, revision=REVISION, cache_dir=a.cache_dir, trust_remote_code=False)
        model = AutoModelForImageTextToText.from_pretrained(
            MODEL, revision=REVISION, cache_dir=a.cache_dir,
            torch_dtype=torch.float16 if a.device == 'cuda' else torch.float32,
            trust_remote_code=False, attn_implementation='eager',
        ).to(a.device).eval()
        results = []
        for path in paths:
            with Image.open(path) as source:
                image = source.convert('RGB')
            answers = {}
            for key, question in QUESTIONS.items():
                prompt = processor.apply_chat_template([{'role':'user','content':[{'type':'image'},{'type':'text','text':question}]}], add_generation_prompt=True)
                inputs = processor(text=prompt, images=[image], return_tensors='pt').to(a.device)
                if a.device == 'cuda':
                    inputs = inputs.to(dtype=torch.float16)
                with torch.inference_mode():
                    tokens = model.generate(**inputs, max_new_tokens=80, do_sample=False)
                answers[key] = processor.decode(tokens[0, inputs['input_ids'].shape[1]:], skip_special_tokens=True)
            results.append({'image':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'answers':answers,'approval':'review_required','eligible_for_render':False})
        result = {'model':MODEL,'revision':REVISION,'device':a.device,'elapsed_seconds':round(time.monotonic()-started,2), 'peak_allocated_bytes':torch.cuda.max_memory_allocated() if a.device=='cuda' else None, 'peak_reserved_bytes':torch.cuda.max_memory_reserved() if a.device=='cuda' else None,'visual_verified':False,'sku_verified':False,'results':results}
        json.dump(result, report, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()
