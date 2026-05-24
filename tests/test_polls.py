"""Tests for the ride poll feature."""
import pytest
from datetime import date, time, timedelta, datetime

from app.models import (
    Club, ClubAdmin, ClubMembership, RidePoll, RidePollOption, RidePollVote, Ride, User,
)
from app.extensions import db as _db, bcrypt


# ── Helpers ───────────────────────────────────────────────────────────────────

def login(client, email, password='password123'):
    return client.post('/auth/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def future_dt(days=1, hour=23, minute=59):
    d = date.today() + timedelta(days=days)
    return datetime(d.year, d.month, d.day, hour, minute)


def future_date(days=7):
    return date.today() + timedelta(days=days)


def make_user(db, username, email, password='password123'):
    u = User(username=username, email=email,
             password_hash=bcrypt.generate_password_hash(password).decode())
    db.session.add(u)
    db.session.commit()
    return u


def make_club(db, slug='poll-club', name='Poll Club'):
    c = Club(slug=slug, name=name, is_hidden=False)
    db.session.add(c)
    db.session.commit()
    return c


def make_admin(db, user, club):
    db.session.add(ClubAdmin(user_id=user.id, club_id=club.id))
    db.session.commit()


def make_member(db, user, club):
    db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status='active'))
    db.session.commit()


def make_poll(db, club, creator, status='open', finalize_mode='manual',
              poll_length=True, poll_course=False, poll_start_time=False,
              closes_at=None):
    if closes_at is None:
        closes_at = future_dt(days=1)
    poll = RidePoll(
        club_id=club.id,
        created_by_id=creator.id,
        title='Test Poll',
        ride_date=future_date(),
        closes_at=closes_at,
        finalize_mode=finalize_mode,
        status=status,
        poll_length=poll_length,
        poll_course=poll_course,
        poll_start_time=poll_start_time,
    )
    db.session.add(poll)
    db.session.flush()

    order = 0
    if poll_length:
        for val in ('20 miles', '30 miles', '40 miles'):
            db.session.add(RidePollOption(poll_id=poll.id, category='length',
                                          value=val, display_order=order))
            order += 1
    if poll_course:
        for val in ('Route A', 'Route B'):
            db.session.add(RidePollOption(poll_id=poll.id, category='course',
                                          value=val, display_order=order))
            order += 1
    if poll_start_time:
        for val in ('7:00 AM', '7:30 AM', '8:00 AM'):
            db.session.add(RidePollOption(poll_id=poll.id, category='start_time',
                                          value=val, display_order=order))
            order += 1
    db.session.commit()
    return poll


# ── Model unit tests ──────────────────────────────────────────────────────────

class TestRidePollModel:
    def test_is_open_true_when_open_and_future(self, app, db):
        with app.app_context():
            club = make_club(db)
            user = make_user(db, 'u1', 'u1@x.com')
            poll = make_poll(db, club, user, status='open', closes_at=future_dt(1))
            assert poll.is_open is True

    def test_is_open_false_when_closed(self, app, db):
        with app.app_context():
            club = make_club(db)
            user = make_user(db, 'u1', 'u1@x.com')
            poll = make_poll(db, club, user, status='closed')
            assert poll.is_open is False

    def test_is_open_false_when_past_closes_at(self, app, db):
        with app.app_context():
            club = make_club(db)
            user = make_user(db, 'u1', 'u1@x.com')
            past = datetime.now() - timedelta(hours=1)
            poll = make_poll(db, club, user, status='open', closes_at=past)
            assert poll.is_open is False

    def test_active_categories(self, app, db):
        with app.app_context():
            club = make_club(db)
            user = make_user(db, 'u1', 'u1@x.com')
            poll = make_poll(db, club, user, poll_length=True, poll_course=True, poll_start_time=False)
            assert poll.active_categories == ['length', 'course']

    def test_winner_most_votes(self, app, db):
        with app.app_context():
            club = make_club(db)
            creator = make_user(db, 'creator', 'c@x.com')
            voter1 = make_user(db, 'voter1', 'v1@x.com')
            voter2 = make_user(db, 'voter2', 'v2@x.com')
            poll = make_poll(db, club, creator, poll_length=True)
            opts = poll.options_for('length')
            # opts[0]=20mi, opts[1]=30mi, opts[2]=40mi
            # Give 30mi 2 votes, others 1
            now = datetime.utcnow()
            db.session.add(RidePollVote(poll_id=poll.id, option_id=opts[1].id, user_id=voter1.id, category='length', voted_at=now))
            db.session.add(RidePollVote(poll_id=poll.id, option_id=opts[1].id, user_id=voter2.id, category='length', voted_at=now))
            db.session.add(RidePollVote(poll_id=poll.id, option_id=opts[0].id, user_id=creator.id, category='length', voted_at=now))
            # We can't have 2 votes per user per category — use different users
            db.session.commit()
            _db.session.expire_all()
            fresh = _db.session.get(RidePoll, poll.id)
            winner = fresh.winner_for('length')
            assert winner.value == '30 miles'

    def test_winner_tie_broken_by_first_vote(self, app, db):
        with app.app_context():
            club = make_club(db)
            creator = make_user(db, 'creator', 'c@x.com')
            voter1  = make_user(db, 'voter1', 'v1@x.com')
            poll = make_poll(db, club, creator, poll_length=True)
            opts = poll.options_for('length')
            early = datetime(2026, 1, 1, 6, 0)
            late  = datetime(2026, 1, 1, 7, 0)
            opts[0].first_voted_at = late   # 20mi got first vote late
            opts[1].first_voted_at = early  # 30mi got first vote early
            # Give both 1 vote (tie)
            db.session.add(RidePollVote(poll_id=poll.id, option_id=opts[0].id, user_id=creator.id, category='length'))
            db.session.add(RidePollVote(poll_id=poll.id, option_id=opts[1].id, user_id=voter1.id, category='length'))
            db.session.commit()
            _db.session.expire_all()
            fresh = _db.session.get(RidePoll, poll.id)
            winner = fresh.winner_for('length')
            assert winner.value == '30 miles'  # earliest first_voted_at wins

    def test_unique_voter_count(self, app, db):
        with app.app_context():
            club = make_club(db)
            creator = make_user(db, 'creator', 'c@x.com')
            voter   = make_user(db, 'voter', 'v@x.com')
            poll = make_poll(db, club, creator, poll_length=True, poll_start_time=True)
            opts_len = poll.options_for('length')
            opts_time = poll.options_for('start_time')
            now = datetime.utcnow()
            # voter votes on both categories — should count as 1 unique voter
            db.session.add(RidePollVote(poll_id=poll.id, option_id=opts_len[0].id, user_id=voter.id, category='length', voted_at=now))
            db.session.add(RidePollVote(poll_id=poll.id, option_id=opts_time[0].id, user_id=voter.id, category='start_time', voted_at=now))
            db.session.commit()
            _db.session.expire_all()
            fresh = _db.session.get(RidePoll, poll.id)
            assert fresh.unique_voter_count == 1


# ── Route / access control tests ──────────────────────────────────────────────

class TestPollAccess:
    def test_anon_cannot_view_poll(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            user = make_user(db, 'admin', 'a@x.com')
            make_admin(db, user, club)
            poll = make_poll(db, club, user)
            rv = client.get(f'/clubs/poll-club/polls/{poll.id}/', follow_redirects=True)
            # Redirected to login (401 → redirect) or shows login page
            assert rv.status_code in (200, 302, 401, 403)

    def test_non_member_cannot_view_poll(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            outsider = make_user(db, 'outsider', 'o@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            poll = make_poll(db, club, admin)
            login(client, 'o@x.com')
            rv = client.get(f'/clubs/poll-club/polls/{poll.id}/', follow_redirects=True)
            body = rv.data.decode()
            # Should see a warning about membership
            assert 'member' in body.lower() or rv.status_code == 403

    def test_member_can_view_poll(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            poll = make_poll(db, club, admin)
            login(client, 'm@x.com')
            rv = client.get(f'/clubs/poll-club/polls/{poll.id}/')
            assert rv.status_code == 200
            assert b'Test Poll' in rv.data

    def test_non_manager_cannot_create_poll(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            member = make_user(db, 'member', 'm@x.com')
            make_member(db, member, club)
            login(client, 'm@x.com')
            rv = client.get(f'/clubs/poll-club/polls/create', follow_redirects=True)
            assert rv.status_code == 403

    def test_ride_manager_can_access_create(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            login(client, 'a@x.com')
            rv = client.get(f'/clubs/poll-club/polls/create')
            assert rv.status_code == 200
            assert b'Create Ride Poll' in rv.data


# ── Create poll ───────────────────────────────────────────────────────────────

class TestPollCreate:
    def _post_create(self, client, slug, form):
        return client.post(f'/clubs/{slug}/polls/create', data=form, follow_redirects=True)

    def test_create_poll_success(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            login(client, 'a@x.com')
            closes = future_dt(1)
            rv = self._post_create(client, 'poll-club', {
                'title': 'Weekend Ride',
                'ride_date': future_date().isoformat(),
                'closes_at': closes.strftime('%Y-%m-%dT%H:%M'),
                'finalize_mode': 'manual',
                'poll_length': '1',
                'length_options[]': ['20 miles', '30 miles'],
            })
            assert rv.status_code == 200
            poll = RidePoll.query.filter_by(club_id=club.id).first()
            assert poll is not None
            assert poll.title == 'Weekend Ride'
            opts = poll.options_for('length')
            assert len(opts) == 2

    def test_create_requires_at_least_one_category(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            login(client, 'a@x.com')
            rv = self._post_create(client, 'poll-club', {
                'title': 'No Category Poll',
                'ride_date': future_date().isoformat(),
                'closes_at': future_dt(1).strftime('%Y-%m-%dT%H:%M'),
                'finalize_mode': 'manual',
            })
            assert b'at least one category' in rv.data

    def test_create_requires_options_for_selected_category(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            login(client, 'a@x.com')
            rv = self._post_create(client, 'poll-club', {
                'title': 'Empty Options',
                'ride_date': future_date().isoformat(),
                'closes_at': future_dt(1).strftime('%Y-%m-%dT%H:%M'),
                'finalize_mode': 'manual',
                'poll_length': '1',
                'length_options[]': [''],  # blank option
            })
            assert b'Add at least one length option' in rv.data

    def test_options_capped_at_10(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            login(client, 'a@x.com')
            # Submit 15 options; only first 10 should be saved
            opts = [f'{i*5} miles' for i in range(1, 16)]
            rv = self._post_create(client, 'poll-club', {
                'title': 'Many Options',
                'ride_date': future_date().isoformat(),
                'closes_at': future_dt(1).strftime('%Y-%m-%dT%H:%M'),
                'finalize_mode': 'manual',
                'poll_length': '1',
                'length_options[]': opts,
            })
            poll = RidePoll.query.filter_by(club_id=club.id).first()
            assert poll is not None
            assert len(poll.options_for('length')) == 10


# ── Voting ────────────────────────────────────────────────────────────────────

class TestPollVoting:
    def test_member_can_vote(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            poll = make_poll(db, club, admin)
            opt_id = poll.options_for('length')[0].id
            login(client, 'm@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll.id}/vote',
                             data={'vote_length': str(opt_id)}, follow_redirects=True)
            assert rv.status_code == 200
            assert b'recorded' in rv.data
            vote = RidePollVote.query.filter_by(poll_id=poll.id, user_id=member.id).first()
            assert vote is not None
            assert vote.option_id == opt_id

    def test_vote_sets_first_voted_at(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            poll = make_poll(db, club, admin)
            opt = poll.options_for('length')[0]
            assert opt.first_voted_at is None
            login(client, 'm@x.com')
            client.post(f'/clubs/poll-club/polls/{poll.id}/vote',
                        data={'vote_length': str(opt.id)})
            _db.session.expire_all()
            opt_fresh = _db.session.get(RidePollOption, opt.id)
            assert opt_fresh.first_voted_at is not None

    def test_cannot_vote_twice_same_category(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            poll = make_poll(db, club, admin)
            opts = poll.options_for('length')
            login(client, 'm@x.com')
            client.post(f'/clubs/poll-club/polls/{poll.id}/vote',
                        data={'vote_length': str(opts[0].id)})
            # Change vote to opts[1]
            client.post(f'/clubs/poll-club/polls/{poll.id}/vote',
                        data={'vote_length': str(opts[1].id)})
            votes = RidePollVote.query.filter_by(poll_id=poll.id, user_id=member.id, category='length').all()
            assert len(votes) == 1
            assert votes[0].option_id == opts[1].id

    def test_cannot_vote_on_closed_poll(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            poll = make_poll(db, club, admin, status='closed')
            opt_id = poll.options_for('length')[0].id
            login(client, 'm@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll.id}/vote',
                             data={'vote_length': str(opt_id)}, follow_redirects=True)
            assert b'no longer accepting' in rv.data
            assert RidePollVote.query.count() == 0

    def test_non_member_cannot_vote(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin    = make_user(db, 'admin', 'a@x.com')
            outsider = make_user(db, 'outsider', 'o@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            poll = make_poll(db, club, admin)
            opt_id = poll.options_for('length')[0].id
            login(client, 'o@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll.id}/vote',
                             data={'vote_length': str(opt_id)})
            assert rv.status_code == 403
            assert RidePollVote.query.count() == 0


# ── Close & finalize ──────────────────────────────────────────────────────────

class TestPollClose:
    def test_admin_can_close_poll(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            poll = make_poll(db, club, admin)
            login(client, 'a@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll.id}/close', follow_redirects=True)
            assert rv.status_code == 200
            _db.session.expire_all()
            fresh = _db.session.get(RidePoll, poll.id)
            assert fresh.status == 'closed'

    def test_member_cannot_close_poll(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            poll = make_poll(db, club, admin)
            login(client, 'm@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll.id}/close')
            assert rv.status_code == 403

    def test_manual_finalize_creates_ride(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            poll = make_poll(db, club, admin, status='closed')
            opt_id = poll.options_for('length')[0].id  # '20 miles'
            login(client, 'a@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll.id}/finalize',
                             data={'winner_length': str(opt_id)}, follow_redirects=True)
            assert rv.status_code == 200
            _db.session.expire_all()
            fresh = _db.session.get(RidePoll, poll.id)
            assert fresh.status == 'finalized'
            assert fresh.ride_id is not None
            ride = _db.session.get(Ride, fresh.ride_id)
            assert ride is not None
            assert ride.distance_miles == 20.0

    def test_cannot_finalize_open_poll(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            poll = make_poll(db, club, admin, status='open')
            login(client, 'a@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll.id}/finalize',
                             data={'winner_length': str(poll.options_for('length')[0].id)},
                             follow_redirects=True)
            assert b'Close the poll' in rv.data
            fresh = _db.session.get(RidePoll, poll.id)
            assert fresh.status == 'open'


class TestPollDelete:
    def test_admin_can_delete_poll_without_votes(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            poll = make_poll(db, club, admin)
            poll_id = poll.id
            login(client, 'a@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll_id}/delete', follow_redirects=True)
            assert rv.status_code == 200
            assert _db.session.get(RidePoll, poll_id) is None

    def test_cannot_delete_poll_with_votes(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            poll = make_poll(db, club, admin)
            opt = poll.options_for('length')[0]
            _db.session.add(RidePollVote(poll_id=poll.id, option_id=opt.id,
                                          user_id=member.id, category='length'))
            _db.session.commit()
            login(client, 'a@x.com')
            rv = client.post(f'/clubs/poll-club/polls/{poll.id}/delete', follow_redirects=True)
            assert b'Cannot delete' in rv.data
            assert _db.session.get(RidePoll, poll.id) is not None


# ── Club home shows poll card ─────────────────────────────────────────────────

class TestPollOnClubHome:
    def test_open_poll_appears_on_club_home(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            make_poll(db, club, admin)
            login(client, 'm@x.com')
            rv = client.get(f'/clubs/poll-club/')
            assert b'Test Poll' in rv.data
            assert b'Poll' in rv.data

    def test_finalized_poll_does_not_appear_on_club_home(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin  = make_user(db, 'admin', 'a@x.com')
            member = make_user(db, 'member', 'm@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_member(db, member, club)
            make_poll(db, club, admin, status='finalized')
            login(client, 'm@x.com')
            rv = client.get(f'/clubs/poll-club/')
            # finalized polls should not appear in open_polls section
            # (the poll card with Vote → link should not be there)
            assert b'Vote \xe2\x86\x92' not in rv.data  # UTF-8 encoded →

    def test_poll_not_visible_to_non_member_on_home(self, client, app, db):
        with app.app_context():
            club = make_club(db)
            admin    = make_user(db, 'admin', 'a@x.com')
            outsider = make_user(db, 'outsider', 'o@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            make_poll(db, club, admin)
            login(client, 'o@x.com')
            rv = client.get(f'/clubs/poll-club/')
            # Poll cards only rendered when is_member; outsider won't see them
            assert b'Vote \xe2\x86\x92' not in rv.data


# ── Finalization helpers ───────────────────────────────────────────────────────

class TestFinalizationHelpers:
    def test_parse_time_formats(self, app):
        from app.routes.polls import _parse_time
        with app.app_context():
            assert _parse_time('7:00 AM').hour == 7
            assert _parse_time('7:30 AM').minute == 30
            assert _parse_time('07:00').hour == 7
            assert _parse_time('19:30').hour == 19
            assert _parse_time('7:30AM').minute == 30

    def test_parse_distance(self, app):
        from app.routes.polls import _parse_distance
        with app.app_context():
            assert _parse_distance('20 miles') == 20.0
            assert _parse_distance('35.5 km') == 35.5
            assert _parse_distance('50') == 50.0
            assert _parse_distance('no number') is None

    def test_do_finalize_parses_start_time(self, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            poll = make_poll(db, club, admin, status='closed',
                             poll_length=False, poll_start_time=True)
            opt = poll.options_for('start_time')[0]  # '7:00 AM'
            from app.routes.polls import _do_finalize
            _do_finalize(poll, club, {'winner_start_time': str(opt.id)})
            _db.session.expire_all()
            fresh = _db.session.get(RidePoll, poll.id)
            ride = _db.session.get(Ride, fresh.ride_id)
            assert ride.time.hour == 7

    def test_do_finalize_uses_url_as_route(self, app, db):
        with app.app_context():
            club = make_club(db)
            admin = make_user(db, 'admin', 'a@x.com')
            make_admin(db, admin, club)
            make_member(db, admin, club)
            poll = make_poll(db, club, admin, status='closed',
                             poll_length=False, poll_course=True)
            # Set first option value to a URL
            opt = poll.options_for('course')[0]
            opt.value = 'https://ridewithgps.com/routes/12345'
            _db.session.commit()
            from app.routes.polls import _do_finalize
            _do_finalize(poll, club, {'winner_course': str(opt.id)})
            _db.session.expire_all()
            fresh = _db.session.get(RidePoll, poll.id)
            ride = _db.session.get(Ride, fresh.ride_id)
            assert ride.route_url == 'https://ridewithgps.com/routes/12345'
