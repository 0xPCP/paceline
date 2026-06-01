"""
Recurring ride instance generator.

A "recurring" ride has is_recurring=True and serves as the weekly template.
Instances are concrete Ride rows with recurrence_parent_id set and is_recurring=False.
Calling generate_instances() is idempotent — it skips dates that already have an instance.
"""
from datetime import date, timedelta
from .extensions import db
from .models import Ride

WEEKS_AHEAD = 8


def generate_instances(template: Ride, weeks: int = WEEKS_AHEAD) -> list[Ride]:
    """
    Create (or skip) one Ride instance per week for `weeks` weeks starting
    from the week after template.date, on the same weekday as template.date.
    Returns the list of newly created instances.
    """
    if not template.is_recurring or template.recurrence_parent_id is not None:
        return []

    # Build set of existing instance dates to avoid duplicates
    existing = {
        r.date for r in Ride.query.filter_by(recurrence_parent_id=template.id).all()
    }

    # Generate exactly `weeks` weekly instances starting the week after the template date
    created = []
    cursor = template.date + timedelta(weeks=1)
    end = template.date + timedelta(weeks=weeks)
    while cursor <= end:
        if cursor not in existing:
            instance = Ride(
                club_id=template.club_id,
                title=template.title,
                date=cursor,
                time=template.time,
                meeting_location=template.meeting_location,
                distance_miles=template.distance_miles,
                elevation_feet=template.elevation_feet,
                pace_category=template.pace_category,
                is_multi_pace=template.is_multi_pace,
                pace_categories=list(template.pace_categories) if template.pace_categories else None,
                ride_leader=template.ride_leader,
                route_url=template.route_url,
                description=template.description,
                is_recurring=False,
                recurrence_parent_id=template.id,
            )
            db.session.add(instance)
            created.append(instance)
        cursor += timedelta(weeks=1)

    if created:
        db.session.commit()
    return created


def delete_future_instances(template: Ride) -> int:
    """Delete all future instances of a recurring template (used before regenerating)."""
    today = date.today()
    future = Ride.query.filter(
        Ride.recurrence_parent_id == template.id,
        Ride.date >= today,
    ).all()
    for r in future:
        db.session.delete(r)
    db.session.commit()
    return len(future)
