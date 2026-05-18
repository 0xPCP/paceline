"""
Media storage abstraction.

Two backends selected at app startup:

  LocalStorage (default)
    Files live at UPLOAD_FOLDER/<key> on the host filesystem.
    serve() calls Flask's send_from_directory.

  SpacesStorage (when SPACES_BUCKET is set)
    Files are PUT to DigitalOcean Spaces (S3-compatible) under the bucket key.

    Serving strategy:
      - Public clubs + SPACES_PUBLIC_BASE_URL set → 302 to CDN URL (permanent,
        cacheable, no Flask round-trip after the first request).
      - Private clubs OR no CDN URL configured → 302 to a short-lived pre-signed
        URL (TTL: PRESIGN_TTL seconds). Access control runs in Flask first, so
        the URL is only vended to authorised users.

Call get_storage(app) inside a request or app context to get the active backend.
All callers go through the same three methods: save(), delete(), serve().
"""
import os
import logging

from flask import send_from_directory, redirect, abort

logger = logging.getLogger(__name__)

_PRESIGN_TTL = 300  # seconds — pre-signed URL lifetime for Spaces


class LocalStorage:
    """Store files on the host filesystem under UPLOAD_FOLDER."""

    def _folder(self, upload_folder):
        if upload_folder:
            return upload_folder
        from flask import current_app
        return current_app.config.get('UPLOAD_FOLDER', 'uploads')

    def save(self, key: str, data: bytes, upload_folder: str = None, **_) -> None:
        dest = os.path.join(self._folder(upload_folder), key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as fh:
            fh.write(data)

    def delete(self, key: str, upload_folder: str = None, **_) -> None:
        path = os.path.join(self._folder(upload_folder), key)
        try:
            os.remove(path)
        except OSError:
            pass

    def serve(self, key: str, upload_folder: str = None, **_):
        """Return a Flask response streaming the file from disk."""
        folder = self._folder(upload_folder)
        directory = os.path.join(folder, os.path.dirname(key))
        filename = os.path.basename(key)
        return send_from_directory(directory, filename)


class SpacesStorage:
    """Store files in DigitalOcean Spaces (S3-compatible object storage)."""

    def __init__(self, bucket: str, region: str, endpoint: str,
                 access_key: str, secret_key: str, public_base_url: str = ''):
        import boto3
        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip('/')
        self._client = boto3.client(
            's3',
            region_name=region,
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def save(self, key: str, data: bytes, acl: str = 'private', **_) -> None:
        kwargs = dict(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType='image/jpeg',
        )
        if acl:
            kwargs['ACL'] = acl
        self._client.put_object(**kwargs)

    def delete(self, key: str, **_) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            logger.warning('Spaces delete failed for %s: %s', key, exc)

    def serve(self, key: str, is_private: bool = True, **_):
        """
        Redirect the browser to the file.

        Public club + CDN URL configured: permanent CDN redirect (cacheable).
        Private club or no CDN URL: short-lived pre-signed URL (authorised only).
        """
        if not is_private and self._public_base_url:
            return redirect(f'{self._public_base_url}/{key}', code=302)
        try:
            url = self._client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self._bucket, 'Key': key},
                ExpiresIn=_PRESIGN_TTL,
            )
        except Exception as exc:
            logger.error('Failed to generate pre-signed URL for %s: %s', key, exc)
            abort(500)
        return redirect(url, code=302)

    def delete_prefix(self, prefix: str) -> int:
        """Delete all objects whose keys start with prefix. Returns deleted count."""
        deleted = 0
        paginator = self._client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            objects = [{'Key': obj['Key']} for obj in page.get('Contents', [])]
            if objects:
                self._client.delete_objects(
                    Bucket=self._bucket,
                    Delete={'Objects': objects, 'Quiet': True},
                )
                deleted += len(objects)
        return deleted


def get_storage(app=None):
    """
    Return the active storage backend for the given app (or current_app).

    Reads config once per call — lightweight enough for per-request use.
    """
    from flask import current_app
    flask_app = app if app is not None else current_app._get_current_object()
    cfg = flask_app.config

    bucket = cfg.get('SPACES_BUCKET', '').strip()
    if bucket:
        return SpacesStorage(
            bucket=bucket,
            region=cfg.get('SPACES_REGION', 'nyc3'),
            endpoint=cfg.get('SPACES_ENDPOINT', ''),
            access_key=cfg.get('SPACES_ACCESS_KEY', ''),
            secret_key=cfg.get('SPACES_SECRET_KEY', ''),
            public_base_url=cfg.get('SPACES_PUBLIC_BASE_URL', ''),
        )
    return LocalStorage()
