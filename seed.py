"""
Cycling Clubs App — development seed data.
Run inside the container: python seed.py

Creates 3 clubs with realistic ride schedules, users, memberships, waivers, and signups.
"""
from datetime import date, time, datetime, timezone
from app import create_app
from app.extensions import db, bcrypt
from app.models import (User, Club, ClubMembership, ClubAdmin, ClubWaiver,
                         WaiverSignature, Ride, RideSignup, UserRideInvite,
                         ClubSponsor, ClubPost)

app = create_app()

with app.app_context():
    # ── Wipe existing data (dev only) ─────────────────────────────────────────
    db.drop_all()
    db.create_all()
    print("Schema reset.")

    # ── Users ─────────────────────────────────────────────────────────────────
    pw = bcrypt.generate_password_hash('password123').decode()

    superadmin = User(username='superadmin', email='admin@cyclingclub.dev',      password_hash=pw, is_admin=True)
    phil       = User(username='phil',       email='phil@pcp.dev',               password_hash=pw, zip_code='20148', address='Ashburn, VA')
    testadmin  = User(username='testadmin',  email='test@pcp.dev',               password_hash=bcrypt.generate_password_hash('password').decode())
    jsmith     = User(username='jsmith',     email='john.smith@example.com',     password_hash=pw, zip_code='20191')
    mbaker     = User(username='mbaker',     email='mary.baker@example.com',     password_hash=pw, zip_code='20190')
    twheels    = User(username='twheels',    email='tom.wheels@example.com',     password_hash=pw, zip_code='20194')
    kroller    = User(username='kroller',    email='kate.roller@example.com',    password_hash=pw, zip_code='22030')
    dkeller    = User(username='dkeller',    email='dave.keller@example.com',    password_hash=pw, zip_code='20191')
    smartin    = User(username='smartin',    email='sarah.martin@example.com',   password_hash=pw, zip_code='20170')
    # NVCC users
    nvcc_admin = User(username='nvcc_admin', email='admin@nvcc.dev',             password_hash=pw)
    arider     = User(username='arider',     email='alex.rider@example.com',     password_hash=pw, zip_code='22101')
    bclimber   = User(username='bclimber',   email='beth.climber@example.com',   password_hash=pw, zip_code='22102')
    # Artemis users
    art_admin  = User(username='art_admin',  email='admin@artemis.dev',          password_hash=pw)
    cspinner   = User(username='cspinner',   email='claire.spin@example.com',    password_hash=pw, zip_code='22201')

    all_users = [superadmin, phil, testadmin, jsmith, mbaker, twheels, kroller, dkeller, smartin,
                 nvcc_admin, arider, bclimber, art_admin, cspinner]
    db.session.add_all(all_users)
    db.session.commit()
    print(f"Created {len(all_users)} users")

    # ── Clubs ─────────────────────────────────────────────────────────────────
    rbc = Club(
        slug='rbc',
        name='Reston Bike Club',
        tagline="Northern Virginia's premier road cycling community since 1972",
        description=(
            'One of the largest cycling clubs in Northern Virginia. '
            'Weekly rides for all levels — Tuesday Worlds to leisurely Sunday spins. '
            'Home of the annual Ken Thompson Reston Century.\n\n'
            'Founded in 1972, RBC welcomes cyclists of all abilities. '
            'We ride rain or shine and believe cycling is best done together.'
        ),
        website='https://restonbikeclub.org',
        contact_email='info@restonbikeclub.org',
        banner_url='https://images.unsplash.com/photo-1541625602330-2277a4c46182?w=1400&q=80',
        address='Hunterwoods Shopping Center, 2324 Hunter Mill Rd',
        city='Reston', state='VA', zip_code='20191',
        lat=38.9376, lng=-77.3476,
        facebook_url='https://facebook.com/restonbikeclub',
        instagram_url='https://instagram.com/restonbikeclub',
        newsletter_url='https://restonbikeclub.org/newsletter',
        theme_preset='forest',
        theme_primary='#2d6a4f',
        theme_accent='#e76f51',
        safety_guidelines=(
            'Always wear a properly fitted helmet — no exceptions.\n'
            'Obey all traffic laws and stop at red lights and stop signs.\n'
            'Call out hazards: "Car back!", "Car up!", "Hole!", "Stopping!".\n'
            'No earbuds or headphones while riding in a group.\n'
            'Carry ID, phone, emergency cash, and a basic repair kit.\n'
            'Ride predictably: no sudden moves, signal turns, and hold your line.'
        ),
        is_verified=True,
        is_hidden=False,
    )
    nvcc = Club(
        slug='nvcc',
        name='Northern Virginia Cycling Club',
        tagline='Fast-paced road and gravel in the DC suburbs — no excuses, no shortcuts',
        description=(
            'Fast-paced road and gravel club based in McLean and the DC suburbs. '
            'Known for challenging Saturday hammerfests and weeknight criterium training.'
        ),
        website='https://example.com/nvcc',
        banner_url='https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=1400&q=80',
        contact_email='info@nvcc.dev',
        address='McLean Community Center, 1234 Ingleside Ave',
        city='McLean', state='VA', zip_code='22101',
        lat=38.9339, lng=-77.1773,
        is_private=True,
        require_membership=True,
        join_approval='manual',
        theme_preset='ocean',
        theme_primary='#1565c0',
        theme_accent='#f39c12',
        is_verified=True,
        is_hidden=False,
    )
    artemis = Club(
        slug='artemis',
        name='Artemis Cycling — Women\'s Club',
        tagline="Northern Virginia's women's cycling club — every pace, every level, every ride",
        description=(
            'Northern Virginia\'s premier women\'s cycling club. '
            'Supportive, no-drop rides for all fitness levels plus structured training for racers.'
        ),
        website='https://example.com/artemis',
        banner_url='https://images.unsplash.com/photo-1571188654248-7a89213915f7?w=1400&q=80',
        contact_email='info@artemis.dev',
        address='Ballston Common, 4238 Wilson Blvd',
        city='Arlington', state='VA', zip_code='22203',
        lat=38.8820, lng=-77.1128,
        theme_preset='berry',
        theme_primary='#6c3483',
        theme_accent='#e74c3c',
    )

    db.session.add_all([rbc, nvcc, artemis])
    db.session.commit()
    print("Created 3 clubs: rbc, nvcc, artemis")

    # ── Club admins ───────────────────────────────────────────────────────────
    db.session.add_all([
        ClubAdmin(user_id=dkeller.id,    club_id=rbc.id,     role='admin'),
        ClubAdmin(user_id=testadmin.id,  club_id=rbc.id,     role='admin'),   # test@pcp.dev
        ClubAdmin(user_id=nvcc_admin.id, club_id=nvcc.id,    role='admin'),
        ClubAdmin(user_id=art_admin.id,  club_id=artemis.id, role='admin'),
        # Phil can manage rides at RBC but not settings
        ClubAdmin(user_id=phil.id,       club_id=rbc.id,     role='ride_manager'),
    ])
    db.session.commit()

    # ── Club memberships ──────────────────────────────────────────────────────
    def join(club, *users, status='active'):
        for u in users:
            db.session.add(ClubMembership(user_id=u.id, club_id=club.id, status=status))

    join(rbc,     phil, testadmin, jsmith, mbaker, twheels, kroller, dkeller, smartin)
    join(nvcc,    arider, bclimber, dkeller)       # active NVCC members
    join(nvcc,    phil, status='pending')           # phil pending on manual-approval club
    join(artemis, mbaker, kroller, smartin, cspinner, bclimber)
    db.session.commit()
    print("Created club memberships")

    # ── Club waivers ──────────────────────────────────────────────────────────
    yr = date.today().year

    rbc_waiver = ClubWaiver(
        club_id=rbc.id, year=yr,
        title=f'Reston Bike Club {yr} Liability Waiver & Rules',
        body=(
            'By signing this waiver I acknowledge that cycling involves risk of injury or death. '
            'I release the Reston Bike Club, its officers, and ride leaders from all liability. '
            'I agree to wear a helmet on all club rides, obey all traffic laws, '
            'and follow the ride leader\'s instructions. '
            'I confirm that my bicycle is in safe, road-worthy condition.'
        ),
    )
    nvcc_waiver = ClubWaiver(
        club_id=nvcc.id, year=yr,
        title=f'NVCC {yr} Participation Agreement',
        body=(
            'Participation in NVCC rides is at my own risk. '
            'I release NVCC from liability for any injury, loss, or damage sustained during club activities. '
            'I agree to ride predictably, call out hazards, and never overlap wheels on group rides. '
            'Helmets are mandatory. No earbuds in both ears.'
        ),
    )
    artemis_waiver = ClubWaiver(
        club_id=artemis.id, year=yr,
        title=f'Artemis Cycling {yr} Rider Agreement',
        body=(
            'I understand that cycling carries inherent risks. '
            'I release Artemis Cycling from all liability related to club rides and events. '
            'I agree to uphold the club\'s code of conduct: be supportive, no one gets dropped intentionally, '
            'helmets required, and always ride with a buddy on solo training rides.'
        ),
    )
    db.session.add_all([rbc_waiver, nvcc_waiver, artemis_waiver])
    db.session.commit()
    print("Created club waivers")

    # Phil has signed RBC waiver; most others haven't (to test the gate)
    db.session.add(WaiverSignature(user_id=phil.id, club_id=rbc.id,
                                   waiver_id=rbc_waiver.id, year=yr))
    db.session.add(WaiverSignature(user_id=dkeller.id, club_id=rbc.id,
                                   waiver_id=rbc_waiver.id, year=yr))
    db.session.add(WaiverSignature(user_id=arider.id, club_id=nvcc.id,
                                   waiver_id=nvcc_waiver.id, year=yr))
    db.session.commit()
    print("Created waiver signatures")

    # ── RBC Sponsors ──────────────────────────────────────────────────────────
    db.session.add_all([
        ClubSponsor(
            club_id=rbc.id,
            name='The Bike Lane',
            logo_url='https://placehold.co/200x80/1a1a2e/ffffff?text=The+Bike+Lane',
            website='https://thebikelane.com',
            display_order=1,
        ),
        ClubSponsor(
            club_id=rbc.id,
            name="Conte's Bike Shop",
            logo_url='https://placehold.co/200x80/c0392b/ffffff?text=Conte%27s+Bikes',
            website='https://contesbike.com',
            display_order=2,
        ),
        ClubSponsor(
            club_id=rbc.id,
            name='Reston Town Center',
            logo_url='https://placehold.co/200x80/2c3e50/ffffff?text=Reston+Town+Center',
            website='https://restontowncenter.com',
            display_order=3,
        ),
        ClubSponsor(
            club_id=rbc.id,
            name='Spokes Etc.',
            logo_url='https://placehold.co/200x80/27ae60/ffffff?text=Spokes+Etc.',
            website='https://spokesetc.com',
            display_order=4,
        ),
    ])
    db.session.commit()
    print("Created RBC sponsors")

    # ── RBC News Posts ────────────────────────────────────────────────────────
    db.session.add_all([
        ClubPost(
            club_id=rbc.id,
            author_id=testadmin.id,
            title='Welcome to the 2026 Season!',
            body=(
                'The 2026 ride season is officially underway! '
                'We kicked off with a fantastic Season Opener on April 6th — '
                'great weather, great legs, and great company.\n\n'
                'A few reminders as we ramp up:\n\n'
                '- **Waivers** must be signed before your first ride. '
                'Check your profile to confirm yours is on file.\n'
                '- **New ride leaders** are always welcome — '
                'reach out to any admin if you\'re interested.\n'
                '- Our **Tuesday Worlds** group is averaging 24+ mph this year. '
                'The Wednesday Recovery ride is a no-drop option at 16 mph.'
            ),
            published_at=datetime(2026, 4, 7, 9, 0, tzinfo=timezone.utc),
        ),
        ClubPost(
            club_id=rbc.id,
            author_id=testadmin.id,
            title='Ken Thompson Reston Century — Registration Open',
            body=(
                '### Save the Date: September 20, 2026\n\n'
                'Registration is now open for the **Ken Thompson Reston Century**, '
                'our flagship annual event. This year we\'re offering:\n\n'
                '- 25-mile family route\n'
                '- 50-mile metric century\n'
                '- 100-mile full century with 5,200 ft of climbing\n\n'
                'Early-bird pricing is available through June 30th. '
                'Club members receive a $10 discount — use code **RBC2026** at checkout.\n\n'
                'Volunteers are also needed for SAG support, rest stops, and finish-line crew. '
                'Sign up at the front desk at any club ride.'
            ),
            published_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        ),
        ClubPost(
            club_id=rbc.id,
            author_id=dkeller.id,
            title='New: Wednesday Evening Gravel Ride',
            body=(
                'Starting **May 14th**, we\'re launching a weekly Wednesday evening gravel ride '
                'from the Reston Town Center parking garage at 6:00 PM.\n\n'
                'The route is approximately 28 miles with 1,800 ft of climbing on '
                'packed gravel and doubletrack trails through the Potomac Heritage Trail system. '
                'B-pace, no-drop.\n\n'
                'Recommended: gravel or CX bike, tubeless tires. '
                'Helmets required. Lights required (it will be getting dark on the way back).'
            ),
            published_at=datetime(2026, 5, 8, 14, 0, tzinfo=timezone.utc),
        ),
    ])
    db.session.commit()
    print("Created RBC news posts")

    # ── RBC Rides ─────────────────────────────────────────────────────────────
    HUNTERWOODS  = 'Hunterwoods Shopping Center, 2324 Hunter Mill Rd, Reston, VA'
    ARTSPACE     = 'ArtSpace Parking Lot, 635 Herndon Pkwy, Herndon, VA'
    BIKE_LANE    = 'The Bike Lane, 11943 Lake Newport Rd, Reston, VA'
    LAKE_NEWPORT = 'Lake Newport Lake House, 1100 Lake Newport Rd, Reston, VA'

    # Real public RBC/NoVA RideWithGPS routes
    RWGPS_TUE_WORLDS  = 'https://ridewithgps.com/routes/35103917'
    RWGPS_TUE_B       = 'https://ridewithgps.com/routes/35758396'
    RWGPS_WED_RAMBLE  = 'https://ridewithgps.com/routes/45147'
    RWGPS_THU_B       = 'https://ridewithgps.com/routes/34495154'
    RWGPS_WOMENS_THU  = 'https://ridewithgps.com/routes/33309426'
    RWGPS_SAT_A_LEESB = 'https://ridewithgps.com/routes/31848563'
    RWGPS_SAT_B_LEESB = 'https://ridewithgps.com/routes/248407'
    RWGPS_SAT_C       = 'https://ridewithgps.com/routes/32400962'
    RWGPS_MIDDLEBURG  = 'https://ridewithgps.com/routes/39485933'
    RWGPS_GOOSE_CREEK = 'https://ridewithgps.com/routes/31799369'
    RWGPS_CENTURY_100 = 'https://ridewithgps.com/routes/16172906'
    RWGPS_SUNDAY_EASY = 'https://ridewithgps.com/routes/33309467'
    RWGPS_SPRING_KICK = 'https://ridewithgps.com/routes/12422327'

    rbc_rides = [
        # Past rides
        Ride(club_id=rbc.id, title='Tuesday Worlds — A Group',
             date=date(2026, 4, 14), time=time(17, 0), meeting_location=HUNTERWOODS,
             distance_miles=38, elevation_feet=2100, pace_category='A', ride_type='road',
             ride_leader='Dave K.', route_url=RWGPS_TUE_WORLDS,
             description='Fast no-mercy Tuesday worlds.'),
        Ride(club_id=rbc.id, title='Tuesday Evening — B Group',
             date=date(2026, 4, 14), time=time(17, 0), meeting_location=HUNTERWOODS,
             distance_miles=28, elevation_feet=1350, pace_category='B', ride_type='road',
             ride_leader='Tom R.', route_url=RWGPS_TUE_B,
             description='Rolling route through Great Falls. Regroup at the top of difficult climbs.'),
        Ride(club_id=rbc.id, title='Thursday Evening — B/C Group',
             date=date(2026, 4, 16), time=time(17, 0), meeting_location=ARTSPACE,
             distance_miles=30, elevation_feet=1500, pace_category='B', ride_type='road',
             ride_leader='Sarah M.', route_url=RWGPS_THU_B),
        Ride(club_id=rbc.id, title='Saturday Club Ride — A Group',
             date=date(2026, 4, 18), time=time(8, 0), meeting_location=HUNTERWOODS,
             distance_miles=58, elevation_feet=3400, pace_category='A', ride_type='road',
             ride_leader='Dave K.', route_url=RWGPS_MIDDLEBURG,
             description='Middleburg loop. Long day in the saddle — bring two full bottles and a snack.'),
        Ride(club_id=rbc.id, title='Saturday Club Ride — C Group',
             date=date(2026, 4, 18), time=time(8, 30), meeting_location=HUNTERWOODS,
             distance_miles=38, elevation_feet=1900, pace_category='C', ride_type='road',
             ride_leader='Linda H.', route_url=RWGPS_SAT_C),
        # Week 1: Apr 21–27
        Ride(club_id=rbc.id, title='Tuesday Worlds — A Group',
             date=date(2026, 4, 21), time=time(17, 0), meeting_location=HUNTERWOODS,
             distance_miles=38, elevation_feet=2100, pace_category='A', ride_type='road',
             ride_leader='Dave K.', route_url=RWGPS_TUE_WORLDS),
        Ride(club_id=rbc.id, title='Tuesday Evening — B Group',
             date=date(2026, 4, 21), time=time(17, 0), meeting_location=HUNTERWOODS,
             distance_miles=28, elevation_feet=1350, pace_category='B', ride_type='road',
             ride_leader='Tom R.', route_url=RWGPS_TUE_B,
             description='No-drop ride. Regroup at the top of hills.'),
        Ride(club_id=rbc.id, title='Wednesday Morning Ramble',
             date=date(2026, 4, 22), time=time(10, 0), meeting_location=BIKE_LANE,
             distance_miles=25, elevation_feet=900, pace_category='C', ride_type='social',
             ride_leader='Linda H.', route_url=RWGPS_WED_RAMBLE,
             description='Mid-week social spin. Coffee stop at the turnaround is highly likely.'),
        Ride(club_id=rbc.id, title='Thursday Evening — B Group',
             date=date(2026, 4, 23), time=time(17, 0), meeting_location=ARTSPACE,
             distance_miles=30, elevation_feet=1500, pace_category='B', ride_type='road',
             ride_leader='Mark W.', route_url=RWGPS_THU_B),
        Ride(club_id=rbc.id, title="Women's Thursday Ride",
             date=date(2026, 4, 23), time=time(18, 0), meeting_location=LAKE_NEWPORT,
             distance_miles=18, elevation_feet=600, pace_category='D', ride_type='social',
             ride_leader='Jennifer L.', route_url=RWGPS_WOMENS_THU,
             description='All-women, all-paces welcome. No one gets dropped.'),
        Ride(club_id=rbc.id, title='Saturday A Ride to Leesburg & Back',
             date=date(2026, 4, 25), time=time(8, 0), meeting_location=HUNTERWOODS,
             distance_miles=55, elevation_feet=3200, pace_category='A', ride_type='road',
             ride_leader='Dave K.', route_url=RWGPS_SAT_A_LEESB,
             description='Double loop through Loudoun County back roads.'),
        Ride(club_id=rbc.id, title='Saturday B Ride to Leesburg & Back',
             date=date(2026, 4, 25), time=time(8, 30), meeting_location=HUNTERWOODS,
             distance_miles=38, elevation_feet=1800, pace_category='B', ride_type='road',
             ride_leader='Susan P.', route_url=RWGPS_SAT_B_LEESB),
        Ride(club_id=rbc.id, title='RBC Spring Kickoff Ride',
             date=date(2026, 4, 26), time=time(9, 0), meeting_location=BIKE_LANE,
             distance_miles=26, elevation_feet=750, pace_category='D', ride_type='social',
             ride_leader='Bob N.', route_url=RWGPS_SPRING_KICK,
             description='Annual season opener. Recovery-pace loop, post-ride coffee, new members welcome.'),
        # Week 2
        Ride(club_id=rbc.id, title='Tuesday Worlds — A Group',
             date=date(2026, 4, 28), time=time(17, 0), meeting_location=HUNTERWOODS,
             distance_miles=38, elevation_feet=2100, pace_category='A', ride_type='road',
             ride_leader='Dave K.'),
        Ride(club_id=rbc.id, title='Tuesday Evening — B Group',
             date=date(2026, 4, 28), time=time(17, 0), meeting_location=HUNTERWOODS,
             distance_miles=28, elevation_feet=1350, pace_category='B', ride_type='road',
             ride_leader='Tom R.'),
        Ride(club_id=rbc.id, title='Wednesday Morning Ramble',
             date=date(2026, 4, 29), time=time(10, 0), meeting_location=BIKE_LANE,
             distance_miles=22, elevation_feet=800, pace_category='C', ride_type='social',
             ride_leader='Linda H.'),
        Ride(club_id=rbc.id, title='Thursday Evening — B Group',
             date=date(2026, 4, 30), time=time(17, 0), meeting_location=ARTSPACE,
             distance_miles=32, elevation_feet=1600, pace_category='B', ride_type='road',
             ride_leader='Mark W.'),
        Ride(club_id=rbc.id, title="Women's Thursday Ride",
             date=date(2026, 4, 30), time=time(18, 0), meeting_location=LAKE_NEWPORT,
             distance_miles=18, elevation_feet=600, pace_category='D', ride_type='social',
             ride_leader='Jennifer L.'),
        Ride(club_id=rbc.id, title='Saturday Club Ride — A Group',
             date=date(2026, 5, 2), time=time(8, 0), meeting_location=HUNTERWOODS,
             distance_miles=62, elevation_feet=3800, pace_category='A', ride_type='road',
             ride_leader='Chris T.', route_url=RWGPS_GOOSE_CREEK,
             description='Goose Creek loop. 62 miles of Loudoun grind.'),
        Ride(club_id=rbc.id, title='Saturday Club Ride — C/D',
             date=date(2026, 5, 2), time=time(8, 30), meeting_location=HUNTERWOODS,
             distance_miles=30, elevation_feet=1100, pace_category='C', ride_type='road',
             ride_leader='Susan P.', route_url=RWGPS_SAT_C),
        # Week 3
        Ride(club_id=rbc.id, title='Tuesday Worlds — A Group',
             date=date(2026, 5, 5), time=time(17, 0), meeting_location=HUNTERWOODS,
             distance_miles=40, elevation_feet=2200, pace_category='A', ride_type='road',
             ride_leader='Dave K.', route_url=RWGPS_TUE_WORLDS),
        Ride(club_id=rbc.id, title='Tuesday Evening — B Group',
             date=date(2026, 5, 5), time=time(17, 0), meeting_location=HUNTERWOODS,
             distance_miles=28, elevation_feet=1350, pace_category='B', ride_type='road',
             ride_leader='Tom R.', route_url=RWGPS_TUE_B),
        Ride(club_id=rbc.id, title='Wednesday Morning Ramble',
             date=date(2026, 5, 6), time=time(10, 0), meeting_location=BIKE_LANE,
             distance_miles=25, elevation_feet=900, pace_category='C', ride_type='social',
             ride_leader='Linda H.', route_url=RWGPS_WED_RAMBLE),
        Ride(club_id=rbc.id, title='Thursday Evening — B Group',
             date=date(2026, 5, 7), time=time(17, 0), meeting_location=ARTSPACE,
             distance_miles=30, elevation_feet=1500, pace_category='B', ride_type='road',
             ride_leader='Mark W.', route_url=RWGPS_THU_B),
        Ride(club_id=rbc.id, title="Women's Thursday Ride",
             date=date(2026, 5, 7), time=time(18, 0), meeting_location=LAKE_NEWPORT,
             distance_miles=18, elevation_feet=600, pace_category='D', ride_type='social',
             ride_leader='Jennifer L.', route_url=RWGPS_WOMENS_THU),
        Ride(club_id=rbc.id, title='Saturday Club Ride — A/B',
             date=date(2026, 5, 9), time=time(8, 0), meeting_location=HUNTERWOODS,
             distance_miles=50, elevation_feet=2900, pace_category='A', ride_type='road',
             ride_leader='Dave K.',
             description='W&OD out and Loudoun back roads return.'),
        # Special event
        Ride(club_id=rbc.id, title='43rd Ken Thompson Reston Century',
             date=date(2026, 8, 23), time=time(7, 0), meeting_location=HUNTERWOODS,
             distance_miles=100, elevation_feet=5800, pace_category='A', ride_type='event',
             ride_leader='RBC Board', route_url=RWGPS_CENTURY_100,
             description=(
                 'The flagship RBC event — 43 years running. '
                 'Multiple route options: 25, 50, 75, and 100 miles. '
                 'SAG support, rest stops, and post-ride celebration.'
             )),
    ]

    # ── NVCC Rides ────────────────────────────────────────────────────────────
    MCLEAN_CC    = 'McLean Community Center, 1234 Ingleside Ave, McLean, VA'
    GREAT_FALLS  = 'Great Falls Park Entrance, Georgetown Pike, Great Falls, VA'

    nvcc_rides = [
        Ride(club_id=nvcc.id, title='Thursday Night Worlds',
             date=date(2026, 4, 23), time=time(18, 0), meeting_location=MCLEAN_CC,
             distance_miles=32, elevation_feet=1800, pace_category='A', ride_type='road',
             ride_leader='Alex R.',
             description='Fast hammerfest on the Chain Bridge loop. No drop — just no mercy.'),
        Ride(club_id=nvcc.id, title='Saturday Great Falls Hammerfest',
             date=date(2026, 4, 25), time=time(7, 30), meeting_location=MCLEAN_CC,
             distance_miles=60, elevation_feet=4200, pace_category='A', ride_type='road',
             ride_leader='Beth C.',
             description='The signature NVCC ride. Plan for 3+ hours.'),
        Ride(club_id=nvcc.id, title='Sunday Recovery Spin',
             date=date(2026, 4, 26), time=time(9, 0), meeting_location=GREAT_FALLS,
             distance_miles=28, elevation_feet=900, pace_category='C', ride_type='social',
             ride_leader='Alex R.',
             description='Easy legs after Saturday. Coffee stop guaranteed.'),
        Ride(club_id=nvcc.id, title='Thursday Night Worlds',
             date=date(2026, 4, 30), time=time(18, 0), meeting_location=MCLEAN_CC,
             distance_miles=32, elevation_feet=1800, pace_category='A', ride_type='road',
             ride_leader='Alex R.'),
        Ride(club_id=nvcc.id, title='Saturday Great Falls Hammerfest',
             date=date(2026, 5, 2), time=time(7, 30), meeting_location=MCLEAN_CC,
             distance_miles=65, elevation_feet=4500, pace_category='A', ride_type='road',
             ride_leader='Beth C.',
             description='Extended loop this week — Potomac Heritage Trail connection.'),
        Ride(club_id=nvcc.id, title='Thursday Night Worlds',
             date=date(2026, 5, 7), time=time(18, 0), meeting_location=MCLEAN_CC,
             distance_miles=32, elevation_feet=1800, pace_category='A', ride_type='road',
             ride_leader='Alex R.'),
    ]

    # ── Artemis Rides ─────────────────────────────────────────────────────────
    BALLSTON     = 'Ballston Common, 4238 Wilson Blvd, Arlington, VA'
    ROSSLYN      = 'Rosslyn Metro, 1700 N Moore St, Arlington, VA'

    artemis_rides = [
        Ride(club_id=artemis.id, title='Tuesday Empowerment Ride',
             date=date(2026, 4, 22), time=time(18, 30), meeting_location=BALLSTON,
             distance_miles=20, elevation_feet=700, pace_category='C', ride_type='social',
             ride_leader='Claire S.',
             description='All paces welcome. Supportive group, we regroup at every light.'),
        Ride(club_id=artemis.id, title='Saturday Training Ride — Intermediate',
             date=date(2026, 4, 25), time=time(8, 0), meeting_location=ROSSLYN,
             distance_miles=42, elevation_feet=2100, pace_category='B', ride_type='training',
             ride_leader='Beth C.',
             description='Mount Vernon trail out, back roads return. Skills focus: paceline.'),
        Ride(club_id=artemis.id, title='Saturday Training Ride — Advanced',
             date=date(2026, 4, 25), time=time(8, 0), meeting_location=ROSSLYN,
             distance_miles=55, elevation_feet=3100, pace_category='A', ride_type='training',
             ride_leader='Claire S.',
             description='Race prep ride. Bring race legs.'),
        Ride(club_id=artemis.id, title='Tuesday Empowerment Ride',
             date=date(2026, 4, 29), time=time(18, 30), meeting_location=BALLSTON,
             distance_miles=20, elevation_feet=700, pace_category='C', ride_type='social',
             ride_leader='Claire S.'),
        Ride(club_id=artemis.id, title='Saturday Training Ride — Intermediate',
             date=date(2026, 5, 2), time=time(8, 0), meeting_location=ROSSLYN,
             distance_miles=40, elevation_feet=2000, pace_category='B', ride_type='training',
             ride_leader='Beth C.'),
        Ride(club_id=artemis.id, title='New Rider Orientation Ride',
             date=date(2026, 5, 3), time=time(10, 0), meeting_location=BALLSTON,
             distance_miles=12, elevation_feet=300, pace_category='D', ride_type='social',
             ride_leader='Claire S.',
             description='Never ridden in a group before? This is for you. Max 12mph, fully no-drop.'),
    ]

    all_rides = rbc_rides + nvcc_rides + artemis_rides
    db.session.add_all(all_rides)
    db.session.commit()
    print(f"Created {len(all_rides)} rides ({len(rbc_rides)} RBC, {len(nvcc_rides)} NVCC, {len(artemis_rides)} Artemis)")

    # ── Signups ───────────────────────────────────────────────────────────────
    def signup(ride, *users):
        for u in users:
            db.session.add(RideSignup(ride_id=ride.id, user_id=u.id))

    # RBC past rides
    signup(rbc_rides[0],  dkeller, phil, smartin)
    signup(rbc_rides[1],  jsmith, mbaker, twheels)
    signup(rbc_rides[2],  phil, jsmith, twheels)
    signup(rbc_rides[3],  dkeller, phil, jsmith)
    signup(rbc_rides[4],  mbaker, kroller, twheels)

    # RBC upcoming
    signup(rbc_rides[5],  dkeller, phil)
    signup(rbc_rides[6],  jsmith, mbaker, twheels, smartin)
    signup(rbc_rides[7],  mbaker, kroller, smartin)
    signup(rbc_rides[8],  phil, jsmith, twheels)
    signup(rbc_rides[9],  mbaker, kroller)
    signup(rbc_rides[10], dkeller, phil, jsmith)
    signup(rbc_rides[11], mbaker, twheels, kroller)
    signup(rbc_rides[25], dkeller, phil, jsmith, smartin)  # Century

    # NVCC
    signup(nvcc_rides[0], arider, bclimber, phil)
    signup(nvcc_rides[1], arider, bclimber)
    signup(nvcc_rides[2], arider, phil)

    # Artemis
    signup(artemis_rides[0], mbaker, kroller, cspinner, bclimber)
    signup(artemis_rides[1], kroller, bclimber)
    signup(artemis_rides[2], cspinner)

    db.session.commit()
    print("Created signups")

    # ── User-owned rides ──────────────────────────────────────────────────────
    from datetime import timedelta
    today = date.today()
    next_sat = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    next_sun = next_sat + timedelta(days=1)
    next_fri = next_sat - timedelta(days=1)

    # Phil's public ride — anyone can join
    phil_public = Ride(
        owner_id=phil.id, club_id=None, is_private=False,
        title='Saturday Gravel Grinder w/ Phil',
        date=next_sat, time=time(8, 0),
        meeting_location='Algonkian Regional Park, 47001 Fairway Dr, Sterling, VA',
        distance_miles=42, elevation_feet=2200,
        pace_category='B', ride_type='gravel',
        ride_leader='phil',
        route_url='https://ridewithgps.com/routes/31799369',
        description='Dirt roads and W&OD connector. Gravel bikes recommended but hybrid OK.',
    )

    # Phil's private ride — invite-only
    phil_private = Ride(
        owner_id=phil.id, club_id=None, is_private=True,
        title='Phil\'s Secret Hammerfest (private)',
        date=next_sun, time=time(7, 30),
        meeting_location='Starbucks on Broad St, Ashburn, VA',
        distance_miles=65, elevation_feet=4000,
        pace_category='A', ride_type='road',
        ride_leader='phil',
        description='Private fast group. Invite only.',
    )

    # jsmith's public ride
    jsmith_ride = Ride(
        owner_id=jsmith.id, club_id=None, is_private=False,
        title='Friday Evening Spin',
        date=next_fri, time=time(18, 0),
        meeting_location='Lake Fairfax Park, 1400 Lake Fairfax Dr, Reston, VA',
        distance_miles=22, elevation_feet=700,
        pace_category='C', ride_type='social',
        ride_leader='jsmith',
        description='Easy end-of-week ride. All paces welcome.',
    )

    db.session.add_all([phil_public, phil_private, jsmith_ride])
    db.session.flush()

    # Auto-signup owners
    db.session.add_all([
        RideSignup(ride_id=phil_public.id,  user_id=phil.id),
        RideSignup(ride_id=phil_private.id, user_id=phil.id),
        RideSignup(ride_id=jsmith_ride.id,  user_id=jsmith.id),
    ])

    # mbaker has accepted an invitation to Phil's private ride
    mb_invite = UserRideInvite(ride_id=phil_private.id, user_id=mbaker.id, status='accepted')
    db.session.add(mb_invite)
    db.session.add(RideSignup(ride_id=phil_private.id, user_id=mbaker.id))

    # kroller has requested access to Phil's private ride (pending)
    db.session.add(UserRideInvite(ride_id=phil_private.id, user_id=kroller.id, status='requested'))

    # twheels is signed up for Phil's public ride
    db.session.add(RideSignup(ride_id=phil_public.id, user_id=twheels.id))

    db.session.commit()
    print("Created 3 user-owned rides (2 for phil, 1 for jsmith)")

    print("\nSeed complete!")
    print("\nLogin credentials (all use password: password123 unless noted):")
    print("  superadmin@cyclingclub.dev  — global superadmin")
    print("  test@pcp.dev / password     — RBC club admin (testing account)")
    print("  phil@pcp.dev                — RBC member + NVCC pending + 2 personal rides")
    print("  dave.keller@...             — RBC club admin")
    print("  admin@nvcc.dev              — NVCC club admin (manual-approval)")
    print("  admin@artemis.dev           — Artemis club admin")
    print("  john.smith@...              — RBC member + 1 personal ride")
    print("  mary.baker@...              — RBC + Artemis member, invited to Phil's private ride")
