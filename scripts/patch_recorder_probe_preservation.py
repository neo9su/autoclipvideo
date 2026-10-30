"""Protect original recordings when ffprobe cannot establish duration."""
OLD='''        duration = await probe_duration(filepath)
        if classify_duration(duration) != "accepted":'''
NEW='''        duration = await probe_duration(filepath)
        status = classify_duration(duration)
        if status == "duration_unavailable":
            logger.warning(
                "[%s] Preserving recording with unavailable duration: %s",
                self.room_name, filepath,
            )
            return False
        if status != "accepted":'''
def patch(source):
    if source.count(OLD)!=1:raise RuntimeError('Recorder finalization source drift')
    result=source.replace(OLD,NEW,1);compile(result,'recorder.py','exec');return result
