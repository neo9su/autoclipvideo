"""Bounded, request-scoped file checks for network-backed publish pickers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class GroupArtifactSnapshot:
    """Keep real file checks, deduplicate paths and cap concurrent SMB requests."""

    def __init__(self, versions, candidate_paths=None, values=None):
        if candidate_paths is None:
            from video_path_resolver import _candidate_paths
            candidate_paths = _candidate_paths
        self.versions = set(versions)
        self.candidate_paths = candidate_paths
        self.results = {}
        if values is not None:
            unique = list(dict.fromkeys(str(v) for v in values if v))
            # Network-backed is_file calls are I/O-bound. No GPU/media work here.
            with ThreadPoolExecutor(max_workers=8, thread_name_prefix='group-files') as pool:
                self.results.update(zip(unique, pool.map(self._probe, unique)))

    def _probe(self, value):
        inaccessible = False
        for candidate in self.candidate_paths(value):
            candidate = Path(candidate)
            try:
                if candidate.is_file():
                    return str(candidate), 'ready'
            except OSError:
                # A missing/offline/denied item must not hide every other group.
                inaccessible = True
        return None, 'access_error' if inaccessible else 'stale_path'

    def resolve(self, value, version):
        if not value:
            return None, 'not_generated'
        if version not in self.versions:
            return None, 'invalid_version'
        key = str(value)
        if key not in self.results:
            self.results[key] = self._probe(key)
        return self.results[key]
