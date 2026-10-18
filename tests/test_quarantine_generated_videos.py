import os
from datetime import datetime,timezone
import pytest
from scripts.quarantine_generated_videos import preview,apply,restore


def test_only_old_generated_files_move_and_restore(tmp_path):
    root=tmp_path/'recordings';root.mkdir()
    names=['merged_1_假发_20260401_120000.mp4','merged_2_假发_20261001_120000.mp4','1_20260401_120000_000.mp4','merged_3_保护_20260401_120000.mp4']
    for n in names:
        p=root/n;p.write_bytes(n.encode());os.utime(p,(1775000000,1775000000))
    rows=preview({'root':root},datetime(2026,7,18,tzinfo=timezone.utc).timestamp(),[names[3]])
    assert [os.path.basename(r['source']) for r in rows]==[names[0]]
    batch=tmp_path/'batch';apply(rows,batch)
    assert not (root/names[0]).exists() and (root/names[2]).exists()
    restore(batch/'manifest.json');assert (root/names[0]).exists()


def test_restore_does_not_overwrite_new_video(tmp_path):
    root=tmp_path/'r';root.mkdir();p=root/'merged_1_x_20260401_120000.mp4';p.write_bytes(b'old');os.utime(p,(1775000000,1775000000))
    rows=preview({'root':root},1784332800,[]);batch=tmp_path/'batch';apply(rows,batch);p.write_bytes(b'new')
    with pytest.raises(ValueError):restore(batch/'manifest.json')
    assert p.read_bytes()==b'new'
