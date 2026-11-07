"""Back up DB and uploaded credentials. Run from the project root; Docker required."""
import subprocess
from pathlib import Path
from datetime import datetime,timezone
root=Path(__file__).resolve().parents[1]
dest=root/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
dest.mkdir(parents=True,exist_ok=False)
with (dest/'database.dump').open('wb') as f:
    subprocess.run(['docker','compose','exec','-T','db','pg_dump','-U','laxora','-d','laxora','-Fc'],cwd=root,stdout=f,check=True)
with (dest/'documents.tar').open('wb') as f:
    subprocess.run(['docker','compose','exec','-T','api','tar','-C','/app/uploads','-cf','-','.'],cwd=root,stdout=f,check=True)
print('Backup written to',dest)
