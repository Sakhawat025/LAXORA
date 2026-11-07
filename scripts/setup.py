"""Cross-platform first-run setup. Never overwrites existing secrets."""
from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
path=root/'.env'
if path.exists():
    print('.env already exists; left unchanged.')
else:
    path.write_text('POSTGRES_PASSWORD='+secrets.token_hex(24)+'\nJWT_SECRET='+secrets.token_hex(48)+'\nALLOWED_ORIGINS=http://localhost:3000\nCOOKIE_SECURE=false\n')
    path.chmod(0o600)
    print('Created .env with unique secrets. Next: docker compose up --build -d')
