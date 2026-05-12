"""Tests for the embeddable club ride widget."""
import pytest
from datetime import date, time, timedelta
from app.models import Club, Ride


# ── Helpers ───────────────────────────────────────────────────────────────────

def _login(client, email, password='password123'):
    return client.post('/auth/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _make_ride(db, club, days_ahead=3, title='Morning Ride', pace='B',
               distance=30.0, cancelled=False):
    ride = Ride(
        club_id=club.id,
        title=title,
        date=date.today() + timedelta(days=days_ahead),
        time=time(7, 0),
        meeting_location='Main St & Elm Ave',
        pace_category=pace,
        distance_miles=distance,
        is_cancelled=cancelled,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestEmbedRoute:

    def test_embed_returns_200_for_public_club(self, client, sample_club):
        """Embed page is publicly accessible — no login required."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert resp.status_code == 200

    def test_embed_shows_upcoming_rides(self, client, db, sample_club):
        """Rides in the next 30 days appear in the widget."""
        ride = _make_ride(db, sample_club, days_ahead=5, title='Club Century')
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert b'Club Century' in resp.data

    def test_embed_hides_cancelled_rides(self, client, db, sample_club):
        """Cancelled rides do not appear in the widget."""
        _make_ride(db, sample_club, title='Cancelled Ride', cancelled=True)
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert b'Cancelled Ride' not in resp.data

    def test_embed_hides_past_rides(self, client, db, sample_club):
        """Rides in the past are not shown."""
        past_ride = Ride(
            club_id=sample_club.id,
            title='Old Ride',
            date=date.today() - timedelta(days=1),
            time=time(7, 0),
            meeting_location='Old Spot',
            pace_category='B',
            distance_miles=25.0,
            is_cancelled=False,
        )
        db.session.add(past_ride)
        db.session.commit()
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert b'Old Ride' not in resp.data

    def test_embed_hides_rides_beyond_30_days(self, client, db, sample_club):
        """Rides more than 30 days out are not shown."""
        far_ride = Ride(
            club_id=sample_club.id,
            title='Far Future Ride',
            date=date.today() + timedelta(days=45),
            time=time(8, 0),
            meeting_location='Far Away',
            pace_category='C',
            distance_miles=20.0,
            is_cancelled=False,
        )
        db.session.add(far_ride)
        db.session.commit()
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert b'Far Future Ride' not in resp.data

    def test_embed_ride_links_to_paceline(self, client, db, sample_club):
        """Each ride links to the Paceline ride detail page."""
        ride = _make_ride(db, sample_club, title='Link Test Ride')
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        expected_path = f'/clubs/{sample_club.slug}/rides/{ride.id}'
        assert expected_path.encode() in resp.data

    def test_embed_contains_club_name(self, client, sample_club):
        """Club name appears in the widget header."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert sample_club.name.encode() in resp.data

    def test_embed_has_powered_by_paceline(self, client, sample_club):
        """Widget includes 'Powered by Paceline' attribution."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert b'Powered by Paceline' in resp.data

    def test_embed_has_no_main_nav(self, client, sample_club):
        """Embed page does not include the main site navigation."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        html = resp.data.decode()
        # Base navbar contains the main nav brand; embed page should not have it
        assert 'navbar' not in html.lower()

    def test_embed_shows_empty_state(self, client, sample_club):
        """When there are no upcoming rides, a helpful message is shown."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert b'No upcoming rides' in resp.data

    def test_embed_404_for_hidden_club(self, client, db):
        """Embed returns 404 for a hidden (not yet public) club."""
        hidden = Club(
            slug='hidden-club',
            name='Hidden Club',
            is_hidden=True,
        )
        db.session.add(hidden)
        db.session.commit()
        resp = client.get('/clubs/hidden-club/embed')
        assert resp.status_code == 404

    def test_embed_404_for_inactive_club(self, client, db):
        """Embed returns 404 for an inactive club."""
        inactive = Club(
            slug='inactive-club',
            name='Inactive Club',
            is_hidden=False,
            is_active=False,
        )
        db.session.add(inactive)
        db.session.commit()
        resp = client.get('/clubs/inactive-club/embed')
        assert resp.status_code == 404

    def test_embed_shows_pace_for_rides(self, client, db, sample_club):
        """Pace category appears in the widget for each ride."""
        _make_ride(db, sample_club, pace='A', title='Fast Ride')
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        html = resp.data.decode()
        assert 'pace-A' in html

    def test_embed_multiple_rides_ordered_by_date(self, client, db, sample_club):
        """Multiple rides appear in ascending date order."""
        _make_ride(db, sample_club, days_ahead=10, title='Later Ride')
        _make_ride(db, sample_club, days_ahead=2, title='Earlier Ride')
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        html = resp.data.decode()
        earlier_pos = html.index('Earlier Ride')
        later_pos = html.index('Later Ride')
        assert earlier_pos < later_pos

    def test_embed_is_standalone_html_document(self, client, sample_club):
        """Embed page is a complete HTML document (not a fragment)."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        html = resp.data.decode()
        assert '<!DOCTYPE html>' in html
        assert '<html' in html
        assert '</html>' in html

    def test_embed_has_no_x_frame_options(self, client, sample_club):
        """Embed response must not send X-Frame-Options so external sites can iframe it."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert 'X-Frame-Options' not in resp.headers

    def test_embed_club_name_is_a_link(self, client, sample_club):
        """Club name in the embed header links to the club homepage."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        html = resp.data.decode()
        assert f'/clubs/{sample_club.slug}/' in html
        assert 'ew-header-name' in html
        # The name element should be an anchor tag
        assert f'href' in html and 'ew-header-name' in html


class TestEmbedCodeInAdminSettings:

    def test_admin_settings_contains_embed_section(self, client, db, club_admin_user, sample_club):
        """Embed section appears in club admin settings."""
        _login(client, club_admin_user.email)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert resp.status_code == 200
        assert b'Embed Ride Widget' in resp.data

    def test_admin_settings_embed_url_contains_club_slug(
            self, client, db, club_admin_user, sample_club):
        """The embed code shown to admins references the correct club slug."""
        _login(client, club_admin_user.email)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert f'/clubs/{sample_club.slug}/embed'.encode() in resp.data

    def test_admin_settings_embed_code_uses_full_page_friendly_height(
            self, client, db, club_admin_user, sample_club):
        """Default embed code should not make the redesigned cards feel cramped."""
        _login(client, club_admin_user.email)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert b'height="650"' in resp.data
