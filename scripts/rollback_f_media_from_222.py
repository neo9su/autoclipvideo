"""Restore F media locally after stopping the F migration worker."""
from migrate_f_media_to_222 import worker
import rollback_c_media_from_222 as rollback

rollback.AUDIT, rollback.ROOT, rollback.DEST = worker.AUDIT, worker.ROOT, worker.DEST

if __name__ == '__main__':
    rollback.run()
