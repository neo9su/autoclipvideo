import importlib.util,sqlite3
from pathlib import Path
p=Path(__file__).parents[1]/'backend/clip_retry_sources.py';s=importlib.util.spec_from_file_location('retry',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_room_subfolder_video_and_root_srt(tmp_path):
    room=tmp_path/'1';room.mkdir();video=room/'recording.mp4';video.write_bytes(b'media');srt=tmp_path/'recording.srt';srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n口播')
    assert m.resolve_retry_files('recording.mp4',lambda _:str(video),lambda _:str(srt))==(str(video),str(srt),None)
def test_empty_or_missing_material_not_admitted(tmp_path):
    video=tmp_path/'v.mp4';video.write_bytes(b'media');srt=tmp_path/'v.srt';srt.touch()
    assert m.resolve_retry_files('v.mp4',lambda _:str(video),lambda _:str(srt))[2]
    assert m.resolve_retry_files('v.mp4',lambda _:None,lambda _:str(srt))[2]
def test_failed_claim_cannot_happen_twice():
    db=sqlite3.connect(':memory:');db.executescript('create table recordings(id,clipped,local_deleted,transcribed,clip_error);insert into recordings values(1,-1,0,2,"failure");')
    sql='UPDATE recordings SET clipped = 0, clip_error = NULL WHERE id = ? AND clipped = -1 AND local_deleted = 0 AND transcribed = 2'
    assert db.execute(sql,(1,)).rowcount==1
    assert db.execute(sql,(1,)).rowcount==0
