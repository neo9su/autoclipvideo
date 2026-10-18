"""Audit sampled model observations; never certify wig/SKU identity or cut media."""
import math
import re

VERSION = 'wig-sequence-evidence-v1'
_STATES = {'wearing', 'no_wig', 'hair_net', 'putting_on', 'taking_off',
           'holding_only', 'occluded', 'uncertain'}
_UNCERTAIN = re.compile(r'无法确认|不能确认|无法判断|不确定|不能确定|cannot (?:confirm|determine)|uncertain', re.I)
_FINISHED = re.compile(r'取下假发后|摘下假发后|摘掉假发后|已(?:经)?(?:摘下|取下|摘掉)')


def analyze_sequence(frames, *, max_gap_seconds=2):
    """Keep head/held-item evidence separate; sparse equal looks never imply rewear.

    An unresolved reason/state conflict is marked uncertain, never guessed into
    no_wig. Candidate runs cover observed timestamps only, not unobserved edges.
    """
    if not math.isfinite(max_gap_seconds) or max_gap_seconds <= 0:
        raise ValueError('Invalid maximum sample gap')
    rows = []
    for frame in frames:
        raw = dict(frame)
        try:
            t = float(raw['time_sec'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Invalid source timestamp') from None
        if not math.isfinite(t) or t < 0:
            raise ValueError('Invalid source timestamp')
        state = raw.get('state')
        issues = []
        if state not in _STATES:
            issues.append('unknown_state')
        reason = str(raw.get('reason') or '')
        if state == 'wearing' and _UNCERTAIN.search(reason):
            issues.append('state_reason_uncertainty_conflict')
        if state == 'taking_off' and _FINISHED.search(reason):
            issues.append('action_completion_conflict')
        if raw.get('head_visible') is not True:
            issues.append('head_not_confirmed_visible')
        effective = 'uncertain' if issues else state
        # Holding a wig does not establish what is on the head.
        head_state = 'uncertain' if effective == 'holding_only' else effective
        rows.append({'time_sec': t, 'raw': raw, 'reported_state': state,
                     'head_state': head_state, 'issues': issues,
                     'held_wig_reported': raw.get('detached_wig_visible') is True or state == 'holding_only',
                     'product_features': {k: raw[k] for k in ('color', 'bangs', 'length', 'hair_arrangement')
                                          if k in raw} if head_state == 'wearing' else {}})
    rows.sort(key=lambda r: r['time_sec'])
    # Contradictory duplicate timestamps must not create zero-length episodes.
    if any(a['time_sec'] == b['time_sec'] for a, b in zip(rows, rows[1:])):
        raise ValueError('Duplicate source timestamp; audit each model case separately')
    runs, gaps, events = [], [], []
    current = None
    previous = None
    for row in rows:
        t, state = row['time_sec'], row['head_state']
        gap = previous is not None and t - previous['time_sec'] > max_gap_seconds
        if gap:
            gaps.append({'start_sec': previous['time_sec'], 'end_sec': t, 'reason': 'unsampled_identity_gap'})
        if previous and not gap and state != previous['head_state']:
            events.append({'start_sec': previous['time_sec'], 'end_sec': t,
                           'from_state': previous['head_state'], 'to_state': state,
                           'evidence': 'sampled_model_state_change_not_confirmed_physical_action'})
        if state != 'wearing' or gap:
            current = None
        if state == 'wearing':
            if current is None:
                current = {'first_observed_sec': t, 'last_observed_sec': t, 'sample_count': 0,
                           'visual_verified': False, 'sku_verified': False}
                runs.append(current)
            current['last_observed_sec'] = t
            current['sample_count'] += 1
        previous = row
    return {'version': VERSION, 'observations': rows, 'wearing_candidate_runs': runs,
            'sampled_state_changes': events, 'identity_gaps': gaps,
            'issue_count': sum(len(r['issues']) for r in rows),
            'same_object_rewear': 'unverified', 'sku_verified': False,
            'eligible_for_render': False, 'read_only': True}
