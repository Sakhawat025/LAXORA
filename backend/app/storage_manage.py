"""Run inside the API container: python -m app.storage_manage check|migrate."""
import argparse
import hashlib
from fastapi import HTTPException
from sqlalchemy import select
from . import storage
from .database import SessionLocal
from .models import User, Credential, VerificationDocument

def migrate():
    storage.check_bucket()
    with SessionLocal() as db:
        files = {name: 'image/jpeg' for name in db.scalars(select(User.avatar)) if name}
        for model in (Credential, VerificationDocument):
            for row in db.scalars(select(model)):
                files[row.stored_name] = row.mime
    verified = 0
    for name, mime in files.items():
        path = storage.UPLOAD_DIR / storage.key(name)
        try:
            remote = storage.remote_read(name)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            if not path.is_file():
                raise HTTPException(409, 'A referenced file is missing locally and remotely; migration stopped')
            storage.remote_write(name, path.read_bytes(), mime)
            remote = storage.remote_read(name)
        if path.is_file() and hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(remote).digest():
            raise HTTPException(409, 'A file checksum differs; nothing was overwritten. Migration stopped')
        verified += 1
    print(f'Migration complete: {verified} referenced files verified. Local files retained.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'migrate'])
    args = parser.parse_args()
    try:
        if args.action == 'check':
            storage.check_bucket()
            print('Supabase connection OK. Bucket is private.')
        else:
            migrate()
    except HTTPException as exc:
        parser.exit(1, f'Storage check failed: {exc.detail}\n')

if __name__ == '__main__':
    main()
