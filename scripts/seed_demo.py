"""Reset and seed the isolated Paceline demo database.

This script is destructive by design and must only run in a demo deployment.
It refuses to run unless PACELINE_DEMO_MODE=true and --yes are both provided.
"""
import argparse
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from app.extensions import bcrypt, db
from app.models import (Club, ClubAdmin, ClubMembership, ClubPost, ClubWaiver,
                        Ride, RideSignup, User, WaiverSignature)


def _pw(value='password123'):
    return bcrypt.generate_password_hash(value).decode()


def _ride(club, title, days_from_now, start, miles, pace, leader, location, **kwargs):
    return Ride(
        club_id=club.id,
        title=title,
        date=date.today() + timedelta(days=days_from_now),
        time=start,
        meeting_location=location,
        distance_miles=miles,
        pace_category=pace,
        ride_leader=leader,
        **kwargs,
    )


def seed_demo_database(confirm=False):
    demo_mode = (
        os.environ.get('PACELINE_DEMO_MODE')
        or os.environ.get('DEMO_MODE')
        or 'false'
    ).lower() == 'true'
    if not demo_mode:
        raise RuntimeError('Refusing to reset data because PACELINE_DEMO_MODE is not true.')
    if not confirm:
        raise RuntimeError('Refusing to reset data without --yes confirmation.')

    app = create_app()
    with app.app_context():
        if not app.config.get('DEMO_MODE'):
            raise RuntimeError('Refusing to reset data because PACELINE_DEMO_MODE is not true.')

        db.drop_all()
        db.create_all()

        superadmin = User(
            username='demo_superadmin',
            email='phil@pcp.dev',
            password_hash=_pw(),
            is_admin=True,
            zip_code='20148',
        )
        ava = User(username='ava_owner', email='ava.owner@example.com', password_hash=_pw(), zip_code='20191')
        noah = User(username='noah_rides', email='noah.rides@example.com', password_hash=_pw(), zip_code='22201')
        mia = User(username='mia_member', email='mia.member@example.com', password_hash=_pw(), zip_code='22101')
        leo = User(username='leo_gravel', email='leo.gravel@example.com', password_hash=_pw(), zip_code='20175')
        zoe = User(username='zoe_new', email='zoe.new@example.com', password_hash=_pw(), zip_code='20001')
        db.session.add_all([superadmin, ava, noah, mia, leo, zoe])
        db.session.commit()

        potomac = Club(
            slug='potomac-pedalers-demo',
            name='Potomac Pedalers Demo Club',
            tagline='A fictional all-paces cycling club for showcasing Paceline',
            description=(
                'A friendly fictional club with weekly road rides, member-only routes, '
                'ride leaders, waivers, and a full calendar for demo purposes.'
            ),
            website='https://example.com/potomac-pedalers',
            contact_email='hello@example.com',
            address='Fictional Community Center, 100 Market Street',
            city='Reston',
            state='VA',
            zip_code='20191',
            lat=38.9586,
            lng=-77.3570,
            banner_url='https://images.unsplash.com/photo-1541625602330-2277a4c46182?w=1400&q=80',
            theme_preset='forest',
            theme_primary='#2d6a4f',
            theme_accent='#e76f51',
            require_membership=True,
            join_approval='auto',
            owner_id=ava.id,
            safety_guidelines=(
                'Helmets are required. Ride predictably, call out hazards, and regroup '
                'at marked stops. Demo content is fictional.'
            ),
        )
        capital = Club(
            slug='capital-gravel-demo',
            name='Capital Gravel Collective Demo',
            tagline='Fictional gravel rides, clinics, and weekend adventures',
            description=(
                'A fictional gravel-focused club showing how Paceline can support '
                'mixed-terrain rides, private details, and club updates.'
            ),
            website='https://example.com/capital-gravel',
            contact_email='gravel@example.com',
            address='Fictional Trailhead, 42 Canal Road',
            city='Leesburg',
            state='VA',
            zip_code='20175',
            lat=39.1157,
            lng=-77.5636,
            is_private=True,
            require_membership=True,
            join_approval='manual',
            banner_url='https://images.unsplash.com/photo-1511994298241-608e28f14fde?w=1400&q=80',
            theme_preset='crimson',
            theme_primary='#7b2d26',
            theme_accent='#3498db',
            owner_id=leo.id,
        )
        river = Club(
            slug='river-city-cycling-demo',
            name='River City Cycling Demo',
            tagline='Fictional beginner-friendly rides near the city',
            description='A fictional public club with approachable rides and simple signup flows.',
            city='Washington',
            state='DC',
            zip_code='20001',
            lat=38.9072,
            lng=-77.0369,
            banner_url='https://images.unsplash.com/photo-1517649763962-0c623066013b?w=1400&q=80',
            theme_preset='ocean',
            theme_primary='#1565c0',
            theme_accent='#f39c12',
            owner_id=noah.id,
        )
        db.session.add_all([potomac, capital, river])
        db.session.commit()

        db.session.add_all([
            ClubAdmin(user_id=ava.id, club_id=potomac.id, role='admin'),
            ClubAdmin(user_id=noah.id, club_id=potomac.id, role='ride_manager'),
            ClubAdmin(user_id=leo.id, club_id=capital.id, role='admin'),
            ClubAdmin(user_id=noah.id, club_id=river.id, role='admin'),
            ClubMembership(user_id=ava.id, club_id=potomac.id, status='active'),
            ClubMembership(user_id=noah.id, club_id=potomac.id, status='active'),
            ClubMembership(user_id=mia.id, club_id=potomac.id, status='active'),
            ClubMembership(user_id=zoe.id, club_id=potomac.id, status='pending'),
            ClubMembership(user_id=leo.id, club_id=capital.id, status='active'),
            ClubMembership(user_id=mia.id, club_id=capital.id, status='active'),
            ClubMembership(user_id=zoe.id, club_id=capital.id, status='pending'),
            ClubMembership(user_id=noah.id, club_id=river.id, status='active'),
            ClubMembership(user_id=zoe.id, club_id=river.id, status='active'),
        ])
        db.session.commit()

        year = date.today().year
        waiver = ClubWaiver(
            club_id=potomac.id,
            year=year,
            title=f'Potomac Pedalers Demo {year} Waiver',
            body='Fictional demo waiver. Riders agree to wear a helmet and ride safely.',
        )
        db.session.add(waiver)
        db.session.commit()
        db.session.add_all([
            WaiverSignature(user_id=ava.id, club_id=potomac.id, waiver_id=waiver.id, year=year),
            WaiverSignature(user_id=mia.id, club_id=potomac.id, waiver_id=waiver.id, year=year),
        ])

        rides = [
            _ride(potomac, 'Tuesday Tempo Demo Ride', 2, time(18, 0), 32, 'B', 'Noah R.',
                  'Fictional Community Center, Reston, VA', elevation_feet=1450,
                  ride_type='road', max_riders=24,
                  route_url='https://ridewithgps.com/routes/35758396',
                  description='Steady B pace with regroup points after major climbs.',
                  garmin_groupride_code='A1B2C3'),
            _ride(potomac, 'Saturday All-Paces Demo Rollout', 5, time(8, 30), 45, 'C', 'Ava P.',
                  'Fictional Community Center, Reston, VA', elevation_feet=2100,
                  ride_type='road', max_riders=40,
                  route_url='https://ridewithgps.com/routes/33309467',
                  description='Separate A/B/C groups leave from the same location.'),
            _ride(capital, 'Gravel Skills Clinic Demo', 6, time(9, 0), 28, 'C', 'Leo G.',
                  'Fictional Trailhead, Leesburg, VA', elevation_feet=1800,
                  ride_type='gravel', max_riders=18,
                  description='Fictional private-club clinic with a short skills session.'),
            _ride(river, 'Beginner Coffee Spin Demo', 3, time(10, 0), 16, 'D', 'Noah R.',
                  'Fictional Plaza, Washington, DC', elevation_feet=400,
                  ride_type='social', max_riders=20,
                  description='No-drop social ride ending near a coffee shop.'),
            _ride(river, 'After Work City Loop Demo', 8, time(17, 45), 22, 'C', 'Zoe N.',
                  'Fictional Plaza, Washington, DC', elevation_feet=650,
                  ride_type='road', max_riders=22),
        ]
        db.session.add_all(rides)
        db.session.commit()

        db.session.add_all([
            RideSignup(ride_id=rides[0].id, user_id=ava.id),
            RideSignup(ride_id=rides[0].id, user_id=mia.id),
            RideSignup(ride_id=rides[1].id, user_id=ava.id),
            RideSignup(ride_id=rides[1].id, user_id=noah.id),
            RideSignup(ride_id=rides[2].id, user_id=leo.id),
            RideSignup(ride_id=rides[3].id, user_id=zoe.id),
        ])

        db.session.add_all([
            ClubPost(
                club_id=potomac.id,
                author_id=ava.id,
                title='Demo season kickoff',
                body='This fictional post shows how clubs can publish updates for members.',
                published_at=datetime.now(timezone.utc),
            ),
            ClubPost(
                club_id=capital.id,
                author_id=leo.id,
                title='Private gravel route preview',
                body='This fictional update demonstrates member-only club communication.',
                published_at=datetime.now(timezone.utc),
            ),
        ])
        db.session.commit()

        print('Demo database reset complete.')
        print('Created 3 fictional clubs, 6 users, 5 upcoming rides, and sample admin/member data.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--yes', action='store_true', help='confirm destructive demo reset')
    args = parser.parse_args()
    seed_demo_database(confirm=args.yes)


if __name__ == '__main__':
    main()
