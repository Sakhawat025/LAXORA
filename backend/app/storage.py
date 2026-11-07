"""Private file storage. All callers must authorize access before reading files."""
import logging
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit
import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

UPLOAD_DIR = Path(os.getenv('UPLOAD_DIR', './uploads')).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 10 * 1024 * 1024

def key(name):
    if not re.fullmatch(r'[a-f0-9]{32}(?:\.jpg)?', name):
        raise HTTPException(400, 'Invalid stored file name')
    return name

def enabled():
    backend = os.getenv('STORAGE_BACKEND', 'local').strip().lower()
    if backend not in ('local', 'supabase'):
        raise RuntimeError('STORAGE_BACKEND must be local or supabase')
    return backend == 'supabase'

def settings():
    url = os.getenv('SUPABASE_URL', '').strip().rstrip('/')
    secret = os.getenv('SUPABASE_SECRET_KEY', '').strip()
    bucket = os.getenv('SUPABASE_STORAGE_BUCKET', 'laxora-files').strip()
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise HTTPException(503, 'Set SUPABASE_URL to the HTTPS project URL')
    if not secret or secret.startswith('sb_publishable_'):
        raise HTTPException(503, 'Configure a backend Supabase secret key')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', bucket):
        raise HTTPException(503, 'Invalid storage bucket configuration')
    headers = {'apikey': secret}
    # New sb_secret keys are not JWTs. Only legacy service-role JWTs use Bearer.
    if secret.startswith('eyJ'):
        headers['Authorization'] = 'Bearer ' + secret
    return url + '/storage/v1', bucket, headers

def request(method, path, **kwargs):
    base, bucket, headers = settings()
    headers.update(kwargs.pop('headers', {}))
    try:
        response = httpx.request(method, base + path.replace('{bucket}', quote(bucket, safe='')), headers=headers, timeout=45, follow_redirects=False, **kwargs)
    except httpx.RequestError:
        raise HTTPException(503, 'File storage is temporarily unavailable') from None
    return response

def missing(response):
    if response.status_code == 404:
        return True
    # Supabase can report missing objects with HTTP 400 and JSON statusCode 404.
    if response.status_code == 400:
        try:
            body = response.json()
            return str(body.get('statusCode')) == '404' or body.get('code') in ('NoSuchKey', 'NoSuchObject')
        except (ValueError, AttributeError):
            pass
    return False

def check_bucket():
    response = request('GET', '/bucket/{bucket}')
    if response.status_code != 200:
        raise HTTPException(503, 'Cannot access storage bucket; check URL, secret key and bucket name')
    try:
        info = response.json()
        if info.get('public') is not False:
            raise HTTPException(503, 'Storage bucket must be private: turn Public bucket OFF')
    except ValueError:
        raise HTTPException(503, 'Invalid storage bucket response') from None
    return info

def remote_read(name):
    response = request('GET', '/object/{bucket}/' + key(name))
    if missing(response):
        raise HTTPException(404, 'File unavailable')
    if response.status_code != 200:
        raise HTTPException(503, 'Unable to download file from storage')
    if len(response.content) > MAX_FILE_SIZE:
        raise HTTPException(503, 'Stored file exceeds maximum size')
    return response.content

def remote_write(name, content, mime):
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, 'Maximum file size is 10 MB')
    check_bucket()
    response = request('POST', '/object/{bucket}/' + key(name), content=content, headers={'Content-Type': mime, 'x-upsert': 'false'})
    if response.status_code not in (200, 201):
        raise HTTPException(503, 'Unable to upload file; check bucket size and MIME settings')

def write(name, content, mime):
    if enabled():
        remote_write(name, content, mime)
    else:
        (UPLOAD_DIR / key(name)).write_bytes(content)

def delete(name):
    if not name:
        return
    if enabled():
        response = request('DELETE', '/object/{bucket}', json={'prefixes': [key(name)]})
        if response.status_code not in (200, 204) and not missing(response):
            raise HTTPException(503, 'Unable to delete file from storage')
    else:
        (UPLOAD_DIR / key(name)).unlink(missing_ok=True)

def cleanup(name):
    # A committed profile change must not appear to fail because old-file cleanup failed.
    try:
        delete(name)
    except Exception:
        logging.getLogger(__name__).warning('Unused file cleanup failed; retry during storage maintenance')

def download(name, mime, filename=None):
    key(name)
    if enabled():
        headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
        if filename:
            headers['Content-Disposition'] = "attachment; filename*=UTF-8''" + quote(filename, safe='')
        return Response(remote_read(name), media_type=mime, headers=headers)
    path = UPLOAD_DIR / name
    if not path.is_file():
        raise HTTPException(404, 'File unavailable')
    return FileResponse(path, media_type=mime, filename=filename, content_disposition_type='attachment', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
