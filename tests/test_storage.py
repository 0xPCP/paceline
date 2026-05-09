"""
Unit tests for app/storage.py.

LocalStorage tests use a real temporary directory.
SpacesStorage tests use moto to mock the S3/Spaces API — no real AWS calls.
"""
import io
import os
import pytest

from app.storage import LocalStorage, SpacesStorage, get_storage


# ── LocalStorage ───────────────────────────────────────────────────────────────

class TestLocalStorage:
    def test_save_creates_file(self, tmp_path):
        s = LocalStorage()
        key = os.path.join('ride_media', '1', 'photo.jpg')
        s.save(key, b'JPEGDATA', upload_folder=str(tmp_path))
        assert (tmp_path / 'ride_media' / '1' / 'photo.jpg').read_bytes() == b'JPEGDATA'

    def test_save_creates_intermediate_dirs(self, tmp_path):
        s = LocalStorage()
        key = os.path.join('deep', 'nested', 'dir', 'photo.jpg')
        s.save(key, b'bytes', upload_folder=str(tmp_path))
        assert (tmp_path / 'deep' / 'nested' / 'dir' / 'photo.jpg').exists()

    def test_delete_removes_file(self, tmp_path):
        s = LocalStorage()
        key = os.path.join('ride_media', '1', 'photo.jpg')
        dest = tmp_path / 'ride_media' / '1' / 'photo.jpg'
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b'data')
        s.delete(key, upload_folder=str(tmp_path))
        assert not dest.exists()

    def test_delete_missing_file_does_not_raise(self, tmp_path):
        s = LocalStorage()
        s.delete('nonexistent/path.jpg', upload_folder=str(tmp_path))  # should not raise

    def test_serve_returns_response(self, app, tmp_path):
        s = LocalStorage()
        ride_dir = tmp_path / 'ride_media' / '99'
        ride_dir.mkdir(parents=True)
        (ride_dir / 'test.jpg').write_bytes(b'\xff\xd8\xff')  # minimal JPEG header

        with app.test_request_context('/'):
            resp = s.serve(
                key=os.path.join('ride_media', '99', 'test.jpg'),
                upload_folder=str(tmp_path),
            )
        # Flask test client wraps this; just verify it looks like a response
        assert resp.status_code == 200


# ── SpacesStorage (moto mock) ──────────────────────────────────────────────────

@pytest.fixture
def spaces_bucket():
    """Create a fake S3 bucket via moto."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        client = boto3.client(
            's3',
            region_name='us-east-1',
            endpoint_url=None,
            aws_access_key_id='test',
            aws_secret_access_key='test',
        )
        client.create_bucket(Bucket='test-bucket')
        yield client, 'test-bucket'


@pytest.fixture
def spaces_storage():
    """SpacesStorage instance backed by moto."""
    from moto import mock_aws
    import boto3

    with mock_aws():
        client = boto3.client(
            's3',
            region_name='us-east-1',
            endpoint_url=None,
            aws_access_key_id='test',
            aws_secret_access_key='test',
        )
        client.create_bucket(Bucket='test-bucket')

        storage = SpacesStorage(
            bucket='test-bucket',
            region='us-east-1',
            endpoint=None,
            access_key='test',
            secret_key='test',
        )
        # Swap the internal client so it uses the moto-patched one
        storage._client = client
        yield storage, client


class TestSpacesStorage:
    def test_save_puts_object(self, spaces_storage):
        storage, client = spaces_storage
        storage.save('ride_media/1/photo.jpg', b'JPEGDATA')
        body = client.get_object(Bucket='test-bucket', Key='ride_media/1/photo.jpg')['Body'].read()
        assert body == b'JPEGDATA'

    def test_delete_removes_object(self, spaces_storage):
        storage, client = spaces_storage
        client.put_object(Bucket='test-bucket', Key='ride_media/1/photo.jpg', Body=b'data')
        storage.delete('ride_media/1/photo.jpg')
        objs = client.list_objects_v2(Bucket='test-bucket').get('Contents', [])
        assert not any(o['Key'] == 'ride_media/1/photo.jpg' for o in objs)

    def test_delete_missing_object_does_not_raise(self, spaces_storage):
        storage, _ = spaces_storage
        storage.delete('does/not/exist.jpg')  # should not raise

    def test_serve_private_returns_presigned_redirect(self, app, spaces_storage):
        storage, client = spaces_storage
        client.put_object(Bucket='test-bucket', Key='ride_media/1/photo.jpg', Body=b'data')
        with app.test_request_context('/'):
            resp = storage.serve('ride_media/1/photo.jpg', is_private=True)
        assert resp.status_code == 302
        loc = resp.headers.get('Location', '')
        assert 'test-bucket' in loc or 'photo.jpg' in loc

    def test_serve_public_no_cdn_returns_presigned(self, app, spaces_storage):
        storage, client = spaces_storage
        # No public_base_url set on this storage — still falls back to pre-signed
        client.put_object(Bucket='test-bucket', Key='ride_media/1/photo.jpg', Body=b'data')
        with app.test_request_context('/'):
            resp = storage.serve('ride_media/1/photo.jpg', is_private=False)
        assert resp.status_code == 302
        loc = resp.headers.get('Location', '')
        assert 'test-bucket' in loc or 'photo.jpg' in loc

    def test_serve_public_with_cdn_returns_cdn_url(self, app):
        """Public club + CDN configured → redirect to CDN URL, no pre-signed call."""
        from moto import mock_aws
        import boto3
        with mock_aws():
            client = boto3.client('s3', region_name='us-east-1',
                                  aws_access_key_id='test', aws_secret_access_key='test')
            client.create_bucket(Bucket='test-bucket')
            from app.storage import SpacesStorage
            storage = SpacesStorage(
                bucket='test-bucket', region='us-east-1', endpoint=None,
                access_key='test', secret_key='test',
                public_base_url='https://cdn.example.com',
            )
            storage._client = client
            with app.test_request_context('/'):
                resp = storage.serve('ride_media/1/photo.jpg', is_private=False)
            assert resp.status_code == 302
            assert resp.headers['Location'] == 'https://cdn.example.com/ride_media/1/photo.jpg'

    def test_serve_private_with_cdn_still_uses_presigned(self, app):
        """Private club + CDN configured → must still use pre-signed, not CDN."""
        from moto import mock_aws
        import boto3
        with mock_aws():
            client = boto3.client('s3', region_name='us-east-1',
                                  aws_access_key_id='test', aws_secret_access_key='test')
            client.create_bucket(Bucket='test-bucket')
            client.put_object(Bucket='test-bucket', Key='ride_media/2/secret.jpg', Body=b'x')
            from app.storage import SpacesStorage
            storage = SpacesStorage(
                bucket='test-bucket', region='us-east-1', endpoint=None,
                access_key='test', secret_key='test',
                public_base_url='https://cdn.example.com',
            )
            storage._client = client
            with app.test_request_context('/'):
                resp = storage.serve('ride_media/2/secret.jpg', is_private=True)
            assert resp.status_code == 302
            loc = resp.headers['Location']
            assert 'cdn.example.com' not in loc

    def test_delete_prefix_removes_all_matching(self, spaces_storage):
        storage, client = spaces_storage
        for i in range(3):
            client.put_object(Bucket='test-bucket', Key=f'ride_media/5/img{i}.jpg', Body=b'x')
        client.put_object(Bucket='test-bucket', Key='ride_media/6/other.jpg', Body=b'y')

        deleted = storage.delete_prefix('ride_media/5/')
        assert deleted == 3
        objs = client.list_objects_v2(Bucket='test-bucket').get('Contents', [])
        keys = [o['Key'] for o in objs]
        assert 'ride_media/6/other.jpg' in keys
        assert not any(k.startswith('ride_media/5/') for k in keys)

    def test_delete_prefix_empty_prefix_returns_zero(self, spaces_storage):
        storage, _ = spaces_storage
        count = storage.delete_prefix('no/such/prefix/')
        assert count == 0


# ── get_storage selects correct backend ───────────────────────────────────────

class TestGetStorage:
    def test_returns_local_when_no_spaces_bucket(self, app):
        app.config['SPACES_BUCKET'] = ''
        with app.app_context():
            s = get_storage()
        assert isinstance(s, LocalStorage)

    def test_returns_spaces_when_bucket_configured(self, app):
        from moto import mock_aws
        import boto3

        app.config['SPACES_BUCKET'] = 'my-bucket'
        app.config['SPACES_REGION'] = 'us-east-1'
        app.config['SPACES_ENDPOINT'] = ''
        app.config['SPACES_ACCESS_KEY'] = 'key'
        app.config['SPACES_SECRET_KEY'] = 'secret'

        with mock_aws():
            with app.app_context():
                s = get_storage()
        assert isinstance(s, SpacesStorage)
