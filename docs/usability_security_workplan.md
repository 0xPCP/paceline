# Usability and Security Improvement Workplan

Started: 2026-05-26

This document tracks the implementation order for the current usability,
feature, and security improvement batch. Work should proceed one item at a
time, with tests and help documentation updated as each item lands.

## Order of Work

1. **New-user onboarding checklist**
   - Add a dashboard checklist for location, profile photo, ride preferences,
     first club, and first ride signup.
   - Document in rider help and refresh screenshots.

2. **Profile page organization**
   - Split the profile page into clearer sections/tabs: account, notifications,
     privacy/recommendations, gear/bikes, and security.
   - Document in rider help and refresh screenshots.

3. **Empty states and filter recovery**
   - Improve no-results states on Discover, dashboard, clubs, and shop pages
     with clear next actions.
   - Document where relevant and refresh screenshots.

4. **Sticky mobile ride action**
   - Add a mobile sticky action bar for ride signup/join/dues/waiver actions.
   - Document in rider help and refresh screenshots.

5. **Club-admin setup checklist**
   - Add an admin checklist for new clubs: logo, first ride, invites/members,
     ride leaders, Stripe, and embed link.
   - Document in club-manager help and refresh screenshots.

6. **Pace help and New Rider Friendly surfacing**
   - Add pace guidance near filters and ride creation.
   - Promote New Rider Friendly on discovery and help pages.
   - Document in rider and club-manager help.

7. **Waitlist/reminder improvements**
   - Add rider-facing notification controls for similar rides or ride-capacity
     opportunities without creating noisy email volume.
   - Document in rider help.

8. **Club quality signals**
   - Surface verified, active, New Rider Friendly, Stripe-ready, and responsive
     indicators where they help riders choose clubs.
   - Document in rider and club-manager help.

9. **Club-admin analytics**
   - Add club-level views/signups/member growth/popular ride type stats for
     club admins.
   - Document in club-manager help.

10. **Public beta feedback prompt**
    - Add a low-friction feedback/report prompt on key pages.
    - Document in rider help.

11. **Email verification**
    - Verify direct-registration emails and email changes before trusting the
      address.
    - Document in rider help and security notes.

12. **Redis-capable rate limiting**
    - Configure Flask-Limiter to use Redis when `RATELIMIT_STORAGE_URI` is set
      and document production setup.

13. **Fresh auth for Stripe Connect**
    - Require fresh login for Stripe Connect/disconnect and checkout-affecting
      admin actions.

14. **Dependency/CVE scanning**
    - Add documented dependency audit workflow or CI job.

15. **Final verification**
    - Run focused tests, screenshot refresh, and deployment health checks.

## Progress

- [x] New-user onboarding checklist
- [x] Profile page organization
- [x] Empty states and filter recovery
- [x] Sticky mobile ride action
- [x] Club-admin setup checklist
- [x] Pace help and New Rider Friendly surfacing
- [x] Waitlist/reminder improvements
- [x] Club quality signals
- [x] Club-admin analytics
- [x] Public beta feedback prompt
- [x] Email verification
- [x] Redis-capable rate limiting
- [x] Fresh auth for Stripe Connect
- [x] Dependency/CVE scanning
- [ ] Final verification
