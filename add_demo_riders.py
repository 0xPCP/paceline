"""
Add demo riders to an existing database (production-safe — does NOT wipe data).

Run locally against production:
  DATABASE_URL="postgresql://..." python add_demo_riders.py

Creates 4 clearly-labelled demo accounts, makes them RBC members, signs them
up for upcoming RBC rides, and creates accepted friendships with testadmin so
the "Friends Riding Soon" feed is populated for demo purposes.
"""
from datetime import date, timedelta
from app import create_app
from app.extensions import db, bcrypt
from app.models import User, Club, ClubMembership, Ride, RideSignup, UserFriend

app = create_app()

DEMO_TAG = '[Demo Account]'
FRIEND_OF = 'phil'        # the demo account that will see "Friends Riding Soon"
CLUB_SLUG = 'paceline-demo'

DEMO_USERS = [
    dict(username='alex_demo',   email='alex.demo@demo.paceline.club',
         bio=f'{DEMO_TAG} Alex — weekend warrior, loves long Saturday rides',
         zip_code='20148'),
    dict(username='jordan_demo', email='jordan.demo@demo.paceline.club',
         bio=f'{DEMO_TAG} Jordan — gravel enthusiast and Tuesday Worlds regular',
         zip_code='20191'),
    dict(username='casey_demo',  email='casey.demo@demo.paceline.club',
         bio=f'{DEMO_TAG} Casey — B-group staple, never misses a Wednesday ramble',
         zip_code='20194'),
    dict(username='riley_demo',  email='riley.demo@demo.paceline.club',
         bio=f'{DEMO_TAG} Riley — new to the club, signed up for everything',
         zip_code='22030'),
]

with app.app_context():
    pw = bcrypt.generate_password_hash('DemoRider2026!').decode()

    club = Club.query.filter_by(slug=CLUB_SLUG).first()
    if not club:
        print(f"ERROR: no club with slug '{CLUB_SLUG}' found — check CLUB_SLUG.")
        exit(1)

    anchor = User.query.filter_by(username=FRIEND_OF).first()
    if not anchor:
        print(f"ERROR: user '{FRIEND_OF}' not found — check FRIEND_OF.")
        exit(1)

    today = date.today()

    # Upcoming rides in this club (next 30 days)
    upcoming = (Ride.query
                .filter_by(club_id=club.id)
                .filter(Ride.date >= today)
                .filter(Ride.date <= today + timedelta(days=30))
                .order_by(Ride.date, Ride.time)
                .all())

    if not upcoming:
        print("WARNING: no upcoming rides in the next 30 days for this club.")

    created_users = []
    for spec in DEMO_USERS:
        existing = User.query.filter_by(username=spec['username']).first()
        if existing:
            print(f"  skip {spec['username']} — already exists")
            created_users.append(existing)
            continue

        u = User(
            username=spec['username'],
            email=spec['email'],
            password_hash=pw,
            bio=spec.get('bio'),
            zip_code=spec.get('zip_code'),
            profile_is_public=True,   # public so anyone can find + friend them
        )
        db.session.add(u)
        db.session.flush()

        # Club membership
        if not ClubMembership.query.filter_by(user_id=u.id, club_id=club.id).first():
            db.session.add(ClubMembership(user_id=u.id, club_id=club.id, status='active'))

        # Accepted friendship with anchor user
        if not anchor.friend_request_row(u):
            db.session.add(UserFriend(
                requester_id=anchor.id,
                addressee_id=u.id,
                status='accepted',
                follow_rides=True,
            ))

        created_users.append(u)
        print(f"  created {spec['username']}")

    db.session.flush()

    # Ensure existing demo users are members and friends
    for u in created_users:
        if not ClubMembership.query.filter_by(user_id=u.id, club_id=club.id).first():
            db.session.add(ClubMembership(user_id=u.id, club_id=club.id, status='active'))
        if not anchor.friend_request_row(u):
            db.session.add(UserFriend(
                requester_id=anchor.id,
                addressee_id=u.id,
                status='accepted',
                follow_rides=True,
            ))

    db.session.flush()

    # Sign demo riders up for upcoming rides — stagger so the feed looks natural
    # alex  → rides[0], rides[3]
    # jordan → rides[0], rides[1]
    # casey → rides[1], rides[2]
    # riley → rides[2], rides[3]
    assignments = []
    if len(upcoming) >= 1:
        assignments += [(created_users[0], upcoming[0]), (created_users[1], upcoming[0])]
    if len(upcoming) >= 2:
        assignments += [(created_users[1], upcoming[1]), (created_users[2], upcoming[1])]
    if len(upcoming) >= 3:
        assignments += [(created_users[2], upcoming[2]), (created_users[3], upcoming[2])]
    if len(upcoming) >= 4:
        assignments += [(created_users[0], upcoming[3]), (created_users[3], upcoming[3])]

    for u, ride in assignments:
        already = RideSignup.query.filter_by(ride_id=ride.id, user_id=u.id).first()
        if not already:
            db.session.add(RideSignup(ride_id=ride.id, user_id=u.id))
            print(f"  signed up {u.username} → {ride.title} ({ride.date})")

    db.session.commit()
    print("\nDone. Demo riders added/verified.")
    print(f"  Log in as {FRIEND_OF} and visit your profile to see 'Friends Riding Soon'.")
    print("  Demo account password: DemoRider2026!")
