from datetime import datetime, timezone

from app.extensions import db
from app.models import AdminAuditLog, PlatformPost
from tests.conftest import login


def test_homepage_shows_published_platform_posts(client, db):
    post = PlatformPost(
        title='New route tools',
        summary='Feature updates for club ride leaders.',
        body='Paceline now has better route tools.',
        is_published=True,
        published_at=datetime.now(timezone.utc),
    )
    db.session.add(post)
    db.session.commit()

    resp = client.get('/')

    assert resp.status_code == 200
    assert b'Latest from Paceline' in resp.data
    assert b'New route tools' in resp.data
    assert b'Feature updates for club ride leaders.' in resp.data


def test_homepage_hides_draft_platform_posts(client, db):
    db.session.add(PlatformPost(
        title='Draft update',
        body='Not ready yet.',
        is_published=False,
    ))
    db.session.commit()

    resp = client.get('/')

    assert resp.status_code == 200
    assert b'Draft update' not in resp.data


def test_platform_news_detail_has_no_comment_form(client, db):
    post = PlatformPost(
        title='Product update',
        body='This post should not have comments.',
        is_published=True,
    )
    db.session.add(post)
    db.session.commit()

    resp = client.get(f'/news/{post.id}')

    assert resp.status_code == 200
    assert b'Product update' in resp.data
    assert b'Post Comment' not in resp.data


def test_regular_user_cannot_manage_platform_posts(client, regular_user):
    login(client, regular_user.email)
    resp = client.get('/admin/platform-posts/')
    assert resp.status_code == 403


def test_superadmin_can_create_platform_post(client, db, admin_user):
    login(client, admin_user.email)

    resp = client.post('/admin/platform-posts/new', data={
        'title': 'Feature launch',
        'summary': 'A short launch note.',
        'body': 'The full launch note.',
        'is_published': 'y',
    }, follow_redirects=True)

    assert resp.status_code == 200
    post = PlatformPost.query.filter_by(title='Feature launch').first()
    assert post is not None
    assert post.author_id == admin_user.id
    assert post.is_published is True
    assert AdminAuditLog.query.filter_by(action='create_platform_post').first() is not None


def test_superadmin_can_update_and_delete_platform_post(client, db, admin_user):
    post = PlatformPost(title='Old title', body='Old body', is_published=True)
    db.session.add(post)
    db.session.commit()

    login(client, admin_user.email)
    resp = client.post(f'/admin/platform-posts/{post.id}/edit', data={
        'title': 'Updated title',
        'summary': '',
        'body': 'Updated body',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(post)
    assert post.title == 'Updated title'
    assert post.is_published is False

    post_id = post.id
    resp = client.post(f'/admin/platform-posts/{post_id}/delete', follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(PlatformPost, post_id) is None
