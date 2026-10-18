"""Build auditable single-hairstyle archive plans, never cut ambiguous footage."""
import hashlib
import json
from pathlib import Path
from wig_catalog_names import hairstyle_name, mention_evidence
from wig_preprocess import build_asset_name, extract_features, normalize


def build_archive_plan(recording_id, source_path, boundaries, products):
    """Keep catalogue candidates distinct; display names do not imply SKU identity."""
    plans = []
    for index, boundary in enumerate(boundaries):
        start = float(boundary.get('start_sec') or 0)
        end = float(boundary.get('end_sec') or 0)
        if start < 0 or end <= start:
            continue
        spoken = str(boundary.get('wig') or '')
        evidence = str(boundary.get('current_evidence') or '')
        candidates = []
        for product in products:
            name = hairstyle_name(product.get('product_name') or '')
            if not name:
                continue
            # Resolve exact names/components, not generic hairstyle similarity.
            import re
            aliases = [normalize(a) for a in re.split('[&＆]',name) if len(normalize(a))>=2]
            observed = normalize(spoken)
            if observed not in aliases and observed != normalize(name):
                continue
            hit = mention_evidence(evidence,name)
            if hit['current']:
                candidates.append({'catalogue_id':product['id'],'hairstyle_name':name,
                                   'product_id':product.get('product_id'),'product_url':product.get('product_url')})
        color = boundary.get('color') or ''
        features = boundary.get('features') or []
        # Features here are reported observations; catalogue prose alone does
        # not establish the visible colour or hairstyle.
        identity_names = {c['hairstyle_name'] for c in candidates}
        name = next(iter(identity_names)) if len(identity_names)==1 else ''
        if not name:
            name = build_asset_name('',color,features)
        segment_id = hashlib.sha256(f'{recording_id}:{source_path}:{start:.3f}:{end:.3f}'.encode()).hexdigest()[:24]
        folder = build_asset_name(name,color,features)
        verified = boundary.get('visual_verified') is True and bool(boundary.get('visual_style_signature'))
        ready = bool(candidates) and len(identity_names)==1 and verified and boundary.get('identity_confirmed') is True
        plans.append({'segment_id':segment_id,'recording_id':recording_id,'source_path':str(source_path),
            'start_sec':start,'end_sec':end,'hairstyle_name':name,'color':color,'features':features,
            'catalogue_candidates':candidates,'spoken_evidence':evidence,
            'visual_style_signature':boundary.get('visual_style_signature'),
            'status':'ready' if ready else 'needs_evidence',
            'relative_output':str(Path(folder)/(folder+'_'+segment_id+'.mp4'))})
    # Overlapping assignments to different styles cannot both be rendered.
    for i, a in enumerate(plans):
        for b in plans[i+1:]:
            if min(a['end_sec'],b['end_sec'])>max(a['start_sec'],b['start_sec']):
                a['status']=b['status']='overlap_review'
    return {'recording_id':recording_id,'source_path':str(source_path),'segments':plans,
            'ready_count':sum(p['status']=='ready' for p in plans),'time_basis':'original_video_seconds'}
