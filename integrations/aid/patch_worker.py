"""Build a reviewable AID worker patch; does not deploy or access a GPU host."""
WRAPPER='''
# Fixed, scheduler-owned legacy clip protocol; base modes remain unchanged.
from legacy_clip_worker import validate as _validate_legacy_clip, execute as _execute_legacy_clip
_base_validated_request = validated_request
_base_execute = execute

def validated_request(job):
    request = (job.get("payload") or {}).get("qianchuanRenderRequest") or {}
    if request.get("renderMode") == "legacy_clip_v1":
        return _validate_legacy_clip(job)
    return _base_validated_request(job)

def execute(request, job_file, cancel_file):
    if request.get("renderMode") == "legacy_clip_v1":
        return _execute_legacy_clip(request, job_file, cancel_file, run, probe)
    return _base_execute(request, job_file, cancel_file)

'''
def patch(source):
    if '_validate_legacy_clip' in source:raise ValueError('Already patched')
    marker='if __name__ == "__main__":'
    if source.count(marker)!=1:raise ValueError('Worker entry point drift')
    result=source.replace(marker,WRAPPER+marker,1);compile(result,'worker.py','exec');return result
