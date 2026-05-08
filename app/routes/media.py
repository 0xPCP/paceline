"""
Post-ride media sharing routes.

Strategy summary — see docs/media_strategy.md for full details.
- Photos: JPEG/PNG/WebP, ≤5 MB input, resized to MEDIA_MAX_WIDTH_PX on ingest.
- Videos: External links only (YouTube, Strava, Vimeo). No server storage.
- Limits: MEDIA_MAX_PHOTOS_PER_USER_RIDE per user per ride,
          MEDIA_MAX_PHOTOS_PER_RIDE total per ride.
- Expiry: Files auto-deleted MEDIA_EXPIRY_DAYS days after ride date (scheduler job).
- Visibility: Only shown after ride.date has passed. Private club content
              requires active membership to serve.
"""
import os
import uuid
import logging
from datetime import date

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort, current_app, send_from_directory)
from flask_login import login_required, current_user

from ..extensions import db
from ..models import Club, Ride, RideMedia
from ..security import is_allowed_video_link

logger = logging.getLogger(__name__)

media_bp = Blueprint('media', __name__)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

def _get_club_or_404(slug):
    return Club.query.filter_by(slug=slug, is_active=True).first_or_404()


def _ride_or_404(club, ride_id):
    return Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()


def _can_view_media(club):
    """Media on private clubs is gated behind active membership."""
    if not club.is_private:
        return True
    return current_user.is_authenticated and current_user.is_active_member_of(club)


def _save_photo(file, ride_id):
    """Resize uploaded image to max width, compress to ≤2 MB, save as JPEG."""
    try:
        from PIL import Image
    except ImportError:
        abort(500, 'Pillow not installed — photo uploads unavailable')
    import io

    max_width = current_app.config.get('MEDIA_MAX_WIDTH_PX', 1200)
    max_bytes = 2 * 1024 * 1024
    upload_root = current_app.config['UPLOAD_FOLDER']
    ride_dir = os.path.join(upload_root, 'ride_media', str(ride_id))
    os.makedirs(ride_dir, exist_ok=True)

    filename = f'{uuid.uuid4().hex}.jpg'
    dest = os.path.join(ride_dir, filename)

    file.stream.seek(0)
    img = Image.open(file.stream)
    img = img.convert('RGB')
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)

    for quality in (85, 75, 65, 55):
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=quality, optimize=True, progressive=True)
        if buf.tell() <= max_bytes:
            break

    with open(dest, 'wb') as fh:
        fh.write(buf.getvalue())

    return os.path.join('ride_media', str(ride_id), filename)


# ── File serve ─────────────────────────────────────────────────────────────────

@media_bp.route('/media/ride/<int:ride_id>/<filename>')
def serve_photo(ride_id, filename):
    """Serve a ride photo. Enforces private-club access control."""
    ride = Ride.query.get_or_404(ride_id)
    club = Club.query.get_or_404(ride.club_id)
    if not _can_view_media(club):
        abort(403)
    upload_root = current_app.config['UPLOAD_FOLDER']
    ride_dir = os.path.join(upload_root, 'ride_media', str(ride_id))
    return send_from_directory(ride_dir, filename)


# ── Photo upload ───────────────────────────────────────────────────────────────

@media_bp.route('/clubs/<slug>/rides/<int:ride_id>/media/photo', methods=['POST'])
@login_required
def upload_photo(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = _ride_or_404(club, ride_id)

    if ride.date > date.today():
        flash('Photos can only be shared after the ride has taken place.', 'warning')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')

    if club.is_private and not current_user.is_active_member_of(club):
        abort(403)

    max_per_user = current_app.config.get('MEDIA_MAX_PHOTOS_PER_USER_RIDE', 5)
    max_per_ride = current_app.config.get('MEDIA_MAX_PHOTOS_PER_RIDE', 30)

    user_count = RideMedia.query.filter_by(
        ride_id=ride.id, user_id=current_user.id, media_type='photo'
    ).count()
    if user_count >= max_per_user:
        flash(f'You can share at most {max_per_user} photos per ride.', 'warning')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')

    ride_count = RideMedia.query.filter_by(ride_id=ride.id, media_type='photo').count()
    if ride_count >= max_per_ride:
        flash(f'This ride has reached the {max_per_ride}-photo limit.', 'warning')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')

    file = request.files.get('photo')
    if not file or not file.filename:
        flash('No file selected.', 'danger')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        flash('Only JPEG, PNG, and WebP images are allowed.', 'danger')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')

    caption = request.form.get('caption', '').strip()[:300] or None

    try:
        rel_path = _save_photo(file, ride.id)
    except Exception as exc:
        logger.error('Photo upload failed for ride %d: %s', ride.id, exc)
        flash('Upload failed — please try again.', 'danger')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')

    db.session.add(RideMedia(
        ride_id=ride.id,
        user_id=current_user.id,
        media_type='photo',
        file_path=rel_path,
        caption=caption,
    ))
    db.session.commit()
    flash('Photo shared!', 'success')
    return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')


# ── Video link ─────────────────────────────────────────────────────────────────

@media_bp.route('/clubs/<slug>/rides/<int:ride_id>/media/video', methods=['POST'])
@login_required
def add_video_link(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = _ride_or_404(club, ride_id)

    if ride.date > date.today():
        flash('Videos can only be shared after the ride has taken place.', 'warning')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')

    if club.is_private and not current_user.is_active_member_of(club):
        abort(403)

    url = request.form.get('url', '').strip()
    if not url:
        flash('Please provide a video URL.', 'danger')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')
    if not is_allowed_video_link(url):
        flash('Only YouTube, Vimeo, and Strava activity links are accepted.', 'danger')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')

    caption = request.form.get('caption', '').strip()[:300] or None

    db.session.add(RideMedia(
        ride_id=ride.id,
        user_id=current_user.id,
        media_type='video_link',
        url=url[:500],
        caption=caption,
    ))
    db.session.commit()
    flash('Video link shared!', 'success')
    return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')


# ── Delete ─────────────────────────────────────────────────────────────────────

@media_bp.route('/clubs/<slug>/rides/<int:ride_id>/media/<int:media_id>/delete', methods=['POST'])
@login_required
def delete_media(slug, ride_id, media_id):
    club = _get_club_or_404(slug)
    ride = _ride_or_404(club, ride_id)
    item = RideMedia.query.filter_by(id=media_id, ride_id=ride.id).first_or_404()

    if item.user_id != current_user.id and not current_user.can_manage_rides(club):
        abort(403)

    if item.file_path:
        full = os.path.join(current_app.config['UPLOAD_FOLDER'], item.file_path)
        try:
            os.remove(full)
        except OSError:
            pass

    db.session.delete(item)
    db.session.commit()
    flash('Media removed.', 'info')
    return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#media')
