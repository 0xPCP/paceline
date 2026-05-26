from datetime import datetime, timezone

from app.extensions import db
from app.models import AdminAuditLog, Club, PlatformPost
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
    assert b'Paceline now has better route tools.' in resp.data


def test_homepage_expands_latest_platform_post_and_summarizes_older_posts(client, db):
    db.session.add(PlatformPost(
        title='Older update',
        summary='Older summary.',
        body='Older full body should stay behind the link.',
        is_published=True,
        published_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    ))
    db.session.add(PlatformPost(
        title='Newest update',
        summary='Newest summary.',
        body='Newest full body is visible by default.\n\n- First visible item\n- Second visible item',
        is_published=True,
        published_at=datetime(2026, 5, 26, tzinfo=timezone.utc),
    ))
    db.session.commit()

    resp = client.get('/')

    assert resp.status_code == 200
    assert b'platform-news-card-expanded' in resp.data
    assert b'Newest full body is visible by default.' in resp.data
    assert b'First visible item' in resp.data
    assert b'Older summary.' in resp.data
    assert b'Older full body should stay behind the link.' not in resp.data


def test_homepage_orders_news_after_featured_clubs(client, db):
    db.session.add(Club(
        slug='landing-club',
        name='Landing Club',
        is_hidden=False,
        is_active=True,
    ))
    db.session.add(PlatformPost(
        title='Homepage update',
        body='News body.',
        is_published=True,
        published_at=datetime.now(timezone.utc),
    ))
    db.session.commit()

    html = client.get('/').data.decode()

    assert 'How It Works' in html
    assert 'Featured Clubs' in html
    assert 'Latest from Paceline' in html
    assert html.index('How It Works') < html.index('Featured Clubs')
    assert html.index('Featured Clubs') < html.index('Latest from Paceline')


def test_homepage_uses_regular_clubs_until_ten_featured_exist(client, db):
    for i in range(9):
        db.session.add(Club(
            slug=f'featured-{i}',
            name=f'Featured {i}',
            is_hidden=False,
            is_active=True,
            is_featured=True,
            featured_rank=i + 1,
        ))
    db.session.add(Club(
        slug='fallback-visible',
        name='Fallback Visible',
        is_hidden=False,
        is_active=True,
    ))
    db.session.commit()

    html = client.get('/').data.decode()

    assert 'Featured Clubs' in html
    assert 'Fallback Visible' in html


def test_homepage_uses_featured_clubs_when_ten_exist(client, db):
    for i in range(10):
        db.session.add(Club(
            slug=f'featured-{i}',
            name=f'Featured {i}',
            is_hidden=False,
            is_active=True,
            is_featured=True,
            featured_rank=10 - i,
        ))
    db.session.add(Club(
        slug='regular-visible',
        name='Regular Visible',
        is_hidden=False,
        is_active=True,
    ))
    db.session.commit()

    html = client.get('/').data.decode()

    assert 'Featured Clubs' in html
    assert 'Regular Visible' not in html
    assert html.index('Featured 9') < html.index('Featured 0')


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


def test_superadmin_can_feature_club_for_homepage(client, db, admin_user):
    club = Club(slug='feature-me', name='Feature Me', is_hidden=False)
    db.session.add(club)
    db.session.commit()
    login(client, admin_user.email)

    resp = client.post(f'/admin/clubs/{club.id}/feature', data={
        'is_featured': '1',
        'featured_rank': '3',
    }, follow_redirects=True)

    assert resp.status_code == 200
    db.session.refresh(club)
    assert club.is_featured is True
    assert club.featured_rank == 3
    assert AdminAuditLog.query.filter_by(action='update_featured_club').first() is not None


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
