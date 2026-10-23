"""Original-time subtitle evidence; mentions are never visual identity proofs."""
import math
import re
import unicodedata
from wig_catalog_names import hairstyle_name, mention_evidence

TIME = re.compile(r'(\d{1,3}):([0-5]\d):([0-5]\d)[,.](\d{3})')


def seconds(value):
    match = TIME.fullmatch(value.strip())
    if not match:
        raise ValueError('Invalid subtitle timestamp')
    h, m, s, ms = map(int, match.groups())
    return h*3600+m*60+s+ms/1000


def parse_srt(text):
    cues = []
    for block in re.split(r'\n\s*\n', (text or '').replace('\r\n', '\n').lstrip('\ufeff').strip()):
        lines = block.splitlines()
        index = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if index is None:
            continue
        try:
            left, right = lines[index].split('-->', 1)
            start, end = seconds(left), seconds(right.strip().split()[0])
        except (ValueError, IndexError):
            continue
        content = ''.join(lines[index+1:]).strip()
        if end > start and content:
            cues.append({'start_sec': start, 'end_sec': end, 'text': content})
    return sorted(cues, key=lambda c: (c['start_sec'], c['end_sec']))


def plain(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', str(value or '')).casefold() if c.isalnum())


def corroborate_quote(cues, quote, name, start, end):
    """Require an actual local quote and its full surrounding spoken context."""
    if not all(math.isfinite(x) for x in (start, end)) or end <= start:
        return {'verified': False, 'reason': 'invalid_source_window', 'cues': []}
    wanted = plain(quote)
    if not wanted:
        return {'verified': False, 'reason': 'missing_quote', 'cues': []}
    # No sparse concatenation across long pauses or source-window boundaries.
    local = [c for c in cues if c['start_sec'] >= start and c['end_sec'] <= end]
    for i in range(len(local)):
        chain = []
        for c in local[i:i+8]:
            if chain and c['start_sec']-chain[-1]['end_sec'] > 1:
                break
            chain.append(c)
            spoken = ''.join(x['text'] for x in chain)
            if wanted in plain(spoken):
                # Include adjacent original context to catch a question,
                # comparison or negation omitted from the model's quote.
                lo, hi = chain[0]['start_sec'], chain[-1]['end_sec']
                context = ''.join(x['text'] for x in cues if x['end_sec'] >= lo-1 and x['start_sec'] <= hi+1)
                hit = mention_evidence(context, name)
                return {'verified': hit['current'], 'reason': hit['reason'], 'cues': chain,
                        'context': context}
    return {'verified': False, 'reason': 'quote_not_in_source_window', 'cues': []}


def catalogue_mentions(cues, products):
    """List every local catalogue mention with time, without asserting boundaries."""
    names = {}
    for product in products:
        name = hairstyle_name(product.get('product_name'))
        if name:
            names.setdefault(name, []).append(product['id'])
    hits = []
    for i, cue in enumerate(cues):
        # Resolve aliases after neutral transcription, never prompt ASR with names.
        for name, ids in names.items():
            aliases = [a for a in re.split(r'[&＆]', name) if len(a) >= 2]
            if not any(a in cue['text'] for a in aliases):
                continue
            context = ''.join(c['text'] for c in cues[max(0,i-1):i+2]
                              if c['end_sec'] >= cue['start_sec']-1 and c['start_sec'] <= cue['end_sec']+1)
            evidence = mention_evidence(context, name)
            hits.append({**cue, 'hairstyle_name': name, 'catalogue_ids': ids,
                         'current_assertion': evidence['current'], 'reason': evidence['reason'],
                         'context': context, 'visual_verified': False})
    return hits
