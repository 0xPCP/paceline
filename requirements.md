# Cycling Clubs App — Requirements

## Vision

A multi-tenant web platform where any cycling club can host their presence, manage their ride calendar, and grow their membership. Users register once, join multiple clubs, and see all their upcoming rides in a single personalized home screen. The platform should make it effortless for a club admin to run a professional club without needing a separate website, payment processor, or email system.

Research across ~50 major US cycling clubs (NYCC, Cascade Bicycle Club, BTCNJ, DC Velo, Chicago Cycling Club, LA Wheelmen, Boulder Velo, etc.) and leading club management platforms (Cyql, RideWithGPS for Clubs, ClubExpress, RideStats) informed this requirements list.

---

## Status key

- ✅ Built — shipped and tested
- 🔨 In progress
- 📋 Planned — in the backlog
- 💡 Icebox — good idea, not yet scheduled

---

## User Features

### Account & Profile
- ✅ Register with email + password
- ✅ Profile: username, email, zip code (used for weather and club discovery)
- 📋 Emergency contact field (name + phone) — safety-critical; displayed to ride leader day-of
- 📋 Medical notes field (allergies, conditions) — opt-in; visible to ride leaders only
- 📋 Third-party OAuth login (Google / Microsoft)
- 📋 Gear inventory (for "What to Wear" recommendations)

### Home Screen
- ✅ Personalized dashboard showing all upcoming rides across every club the user has joined
- ✅ "What to Wear" weather widget for the user's saved zip code (Open-Meteo, no API key)
- 📋 Weekly ride digest email — automated Sunday morning preview of the week's rides at the user's clubs
- 📋 Ride history — "You've done 47 rides this year across 3 clubs"
- 📋 Personal mileage / elevation stats YTD

### Club Discovery
- ✅ Search clubs by name, city, state
- ✅ Find local clubs by zip code with radius filter (10 / 25 / 50 / 100 mi)
- ✅ Interactive map (Leaflet + OpenStreetMap) showing all club pins + upcoming ride counts
- 📋 Ride discovery across clubs — "All rides near my zip this weekend" regardless of club membership
- 📋 Filter rides by pace category, distance, date across all clubs

### Club Membership
- ✅ Join any club (all clubs are publicly discoverable on map and Find Clubs)
- ✅ Auto-approve mode: membership is active immediately on join
- ✅ Manual-approve mode: request goes pending; admin approves or rejects
- ✅ Pending state shown on club page: "Pending Approval"
- ✅ Leave club at any time
- 📋 Guest / trial ride — allow 2–3 rides without joining (configurable per club)
- 📋 Membership tiers: individual, family, student, senior (different dues amounts)
- 📋 Invite-by-email: admin sends a link that grants immediate membership

### Notifications
- ✅ Cancellation email when a signed-up ride is cancelled
- ✅ New ride notification when admin publishes a ride
- ✅ Ride reminder email (morning of the ride)
- 📋 Weekly digest email (Sunday preview of upcoming club rides)
- 📋 Membership approval/rejection email
- 📋 Membership renewal reminder ("Your membership expires in 30 days")
- 💡 SMS / push notifications for same-day cancellations
- 💡 Post-ride summary email ("16 riders completed Tuesday Worlds, avg 22.4 mph")

---

## Club Features

### Club Page (Public)
- ✅ Club name, description, logo, contact info, website link
- ✅ Club-branded header: custom primary color, accent color, banner image
- ✅ 6 preset color themes + custom color picker (wizard on creation, editable in settings)
- ✅ Upcoming rides preview (5 most recent) with weather chip
- ✅ Strava club activity feed (recent member rides)
- ✅ Private club badge + route hiding for non-members
- 📋 Club news / blog posts — admin-authored announcements with date
- 📋 Sponsor / partner logos section
- 📋 Club stats: founded year, member count, total rides hosted
- 📋 Ride leader roster (public: name + bio)
- 💡 Photo gallery — member-uploaded post-ride photos

### Club Calendar
- ✅ List view, week view, month view with navigation
- ✅ Pace category filter (A / B / C / D)
- ✅ Weather chip on each ride card
- 📋 Ride type / tag filter (road, gravel, social, training, event)
- 📋 Difficulty tag (flat, rolling, hilly, mountainous)
- 📋 Multi-group ride card — A + B + C groups on the same day displayed as one card with expand

### Ride Detail Page
- ✅ Full ride details: title, date/time, distance, elevation, pace, meeting location, description
- ✅ Ride leader name
- ✅ Weather forecast chip (Open-Meteo — within 7-day window)
- ✅ Rider sign-up / cancel signup
- ✅ Signed-up riders list (visible to authenticated users)
- ✅ RideWithGPS map embed
- ✅ Route URL (hidden from non-members on private clubs)
- ✅ GPX download (proxied from RideWithGPS; hidden from non-members on private clubs)
- ✅ Add to Calendar (.ics export — works with Google, Outlook, Apple Calendar)
- ✅ Video embed (YouTube / Vimeo)
- ✅ Cancellation banner + reason
- 📋 Ride cap (max riders) with waiting list
- 📋 Ride tags (gravel, road, social, training, night ride, etc.)
- 📋 Direct route send to Garmin / Wahoo device (via RideWithGPS API or device API)
- 📋 Ride comment thread — members ask questions, post updates before/after
- 📋 Post-ride report / write-up (admin-authored, links to photos)
- 💡 Real-time ride tracking (where is the group right now?) — safety use case

### Waivers
- ✅ Per-club digital waiver with checkbox acknowledgment
- ✅ Annual re-signing (expires each calendar year)
- ✅ Redirect to waiver before ride signup if unsigned
- ✅ Waiver status shown on club home page
- 📋 Per-event waivers — separate waiver for special events (night rides, gravel, crits)
- 📋 Minor / youth waiver requiring parent signature

### Membership Management (Admin)
- ✅ `require_membership` toggle — must join before ride signup
- ✅ `join_approval` — auto or manual approval mode
- ✅ Pending requests list with approve / reject on Team page
- ✅ Pending count badge on admin dashboard
- ✅ Add members manually (by username or email)
- ✅ Remove members
- 📋 Membership tiers with configurable dues amounts
- 📋 Online dues payment (Stripe) — annual membership fee
- 📋 Automatic renewal / recurring billing option
- 📋 Member renewal reminders (automated email 30 + 7 days before expiry)
- 📋 Membership lapse / grace period (configurable — 30-day grace after expiry)
- 📋 CSV export — full member list with join date, status, contact info
- 📋 Emergency contact visible to ride leaders day-of

### Ride Management (Admin)
- ✅ Create / edit / cancel rides with reason
- ✅ All ride fields: title, date, time, pace, distance, elevation, location, description, route URL, video URL
- ✅ Recurring rides (weekly template, generates 8 instances)
- ✅ Weather-based auto-cancel (configurable thresholds: rain %, wind mph, temp °F floor/ceiling)
- ✅ Ride management list with edit / delete
- 📋 Ride type / tag assignment (road, gravel, social, training, event)
- 📋 Ride cap (max riders field)
- 📋 Multi-group ride support — link A/B/C variants under one parent event
- 📋 Ride leader assignment from member roster
- 📋 Bulk ride import (CSV upload for season schedule)

### Team / Admin Roles
- ✅ `ClubAdmin.role`: `admin` (full access) | `ride_manager` (rides only, no settings/team)
- ✅ Add / remove admin team members by username or email
- ✅ Prevent self-removal if last full admin
- 📋 `treasurer` role — view financial reports, export member/dues data
- 📋 `content_editor` role — manage news posts and club description only
- 📋 Volunteer role for events (not a standing admin; one-time event access)

### Club Settings
- ✅ Basic info: name, description, city/state/zip, address, contact email, website
- ✅ Appearance: primary color, accent color, banner image, logo URL
- ✅ Membership: require_membership toggle, join_approval mode
- ✅ Strava: club ID for activity feed
- ✅ Weather auto-cancel: thresholds for rain, wind, temperature
- 📋 Privacy: is_private toggle (already model-level; needs settings UI)
- 📋 Dues: tier names, amounts, renewal period
- 📋 Guest passes: number of free guest rides allowed before join prompt
- 📋 Email preferences: which automated emails to send (digest, reminders, etc.)
- 💡 Custom domain: map clubname.com to their platform page

### Financial (Admin)
- 📋 Stripe integration for annual membership dues
- 📋 Membership tiers with different price points
- 📋 Payment history per member
- 📋 Treasurer dashboard: dues collected YTD, outstanding renewals
- 📋 CSV export: financial data for reporting
- 📋 Event registration payment (separate from membership dues)
- 💡 Merchandise store (jerseys, kits) — most clubs outsource; low priority

### Events (Annual / Special)
- 📋 Event pages distinct from weekly rides — centuries, gran fondos, crits, clinics
- 📋 Event registration with online payment
- 📋 Multiple route options per event (25 / 50 / 75 / 100 mi choices)
- 📋 Volunteer sign-up for SAG, rest stops, finish line
- 📋 Early bird / tiered pricing
- 📋 Discount / promo codes
- 📋 Post-event results / finisher list
- 💡 Timing integration (for timed events — RaceJoy, ChronoTrack)

### Member Engagement
- 📋 Club-wide mileage / elevation challenge ("Ride 5,000 miles as a club this year")
- 📋 Progress bar + leaderboard for challenge
- 📋 Personal stats: rides attended, miles, elevation YTD at this club
- 📋 Attendance history for ride leaders / admins
- 📋 "Most rides" / "Most miles" club awards
- 💡 Badges / achievements (gamification)
- 💡 Ride streaks

### Safety
- 📋 Emergency contact on member profile — visible to ride leader
- 📋 Ride leader first-aid certification field + expiry tracking
- 📋 QR code check-in at rides (phone scan, no paper sign-in sheets)
- 💡 Real-time group location sharing (opt-in, safety use case)

---

## Platform Features

### Multi-Club
- ✅ Multi-tenant data model from day one — every club has isolated data
- ✅ User can belong to multiple clubs simultaneously
- ✅ Home screen aggregates rides across all joined clubs
- 📋 Cross-club ride discovery — find rides near zip from any club, not just joined clubs
- 📋 Platform-level admin dashboard — superadmin sees all clubs, all stats

### API
- ✅ Internal endpoints for home screen ride aggregation (`/api/clubs/map-data`)
- 📋 Public JSON feed per club (for embedding ride calendar on external club website)
- 📋 Webhook: notify external systems on ride create/cancel/update

---

## Non-Functional Requirements

- All third-party services (weather, maps) must be self-hostable or free/open — no paid API keys for core features
- Every feature ships with a pytest test harness; all tests must pass before commit
- `pip-audit -r requirements.txt` must pass before every commit and the GitHub
  `Security Audit / dependency-audit` job must pass after every push
- Docker on TrueNAS Scale is the deployment target — `docker compose up -d --build`
- Multi-tenant from day one — club slugs are the isolation boundary
- Mobile-responsive UI on all pages (Bootstrap 5, tested at 390px width)
- No JavaScript framework dependency — server-rendered Jinja2 + vanilla JS for interactive elements
- Passwords hashed with bcrypt; CSRF on all forms
