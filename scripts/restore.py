"""Restore a backup into the running local Docker stack. Explicit confirmation required."""
import argparse
import subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('backup',type=Path)
p.add_argument('--confirm-replace-data',action='store_true')
a=p.parse_args();root=Path(__file__).resolve().parents[1]
if not a.confirm_replace_data:raise SystemExit('This replaces current data. Add --confirm-replace-data after checking the backup.')
backup=a.backup.resolve()
if not (backup/'database.dump').is_file() or not (backup/'documents.tar').is_file():raise SystemExit('Both database.dump and documents.tar are required')
def run(args,**kw):return subprocess.run(['docker','compose']+args,cwd=root,check=True,**kw)
run(['stop','web','api'])
try:
    with (backup/'database.dump').open('rb') as f:
        run(['exec','-T','db','pg_restore','-U','laxora','-d','laxora','--clean','--if-exists','--no-owner','--exit-on-error'],stdin=f)
    # The application is stopped, so no new uploads can race the restore.
    with (backup/'documents.tar').open('rb') as f:
        run(['run','--rm','-T','--no-deps','api','sh','-c','find /app/uploads -mindepth 1 -maxdepth 1 -type f -delete && tar -C /app/uploads -xf -'],stdin=f)
except Exception:
    print('Restore failed; web and API remain stopped. Inspect the failure before restarting.')
    raise
run(['up','-d','api','web'])
print('Restore completed.')
