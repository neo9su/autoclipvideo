"""F-drive profile for the checksum-verified media relocation worker."""
from pathlib import Path
import migrate_c_media_to_222 as worker

worker.ROOT = Path('F:\\')
worker.AUDIT = Path(r'C:\Users\neo\douyin_backend\codex_rollbacks\f-media-to-222-20261024')
worker.DEST = Path(r'\\10.190.0.222\disk2\douyin-203-f-media')
worker.ROOTS = ['douyin_recordings', 'douyin-inputs']
worker.MEDIA_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.ts', '.flv', '.webm', '.m4v', '.avi', '.wav', '.mp3', '.m4a', '.aac', '.srt', '.ass', '.vtt', '.jpg', '.jpeg', '.png', '.webp'}
worker.EXCLUDED_DIRECTORIES = {'models', 'sfx', 'voice_refs', '_product_link_edits'}

if __name__ == '__main__':
    worker.run()
