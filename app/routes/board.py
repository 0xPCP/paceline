"""
Club board routes — member-only post board on the club home page.

Access: active members only.
Media: up to 3 photos per post, stored under uploads/board_media/<post_id>/.
       Same Pillow pipeline and 90-day expiry as ride media.
Notifications: fire-and-forget email to subscribers on each new post,
               post author on each reply, and mentioned users via @username.
"""
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import current_user, login_required

from ..extensions import db
from ..models import (Club, ClubBoardMedia, ClubBoardPost, ClubBoardReaction,
                      ClubBoardReply, ClubBoardSubscription)
from ..utils import process_photo_bg

logger = logging.getLogger(__name__)

board_bp = Blueprint('board', __name__)

BOARD_PAGE_SIZE = 15
BOARD_MAX_PHOTOS = 3
BOARD_MAX_AGE_DAYS = 365
_MENTION_RE = re.compile(r'@([A-Za-z0-9_]{2,50})')


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_club(slug):
    return Club.query.filter_by(slug=slug).first_or_404()


def _require_member(club):
    if not current_user.is_authenticated or not current_user.is_active_member_of(club):
        abort(403)


def _read_image_bytes(file):
    """Read file stream into bytes on the request thread. Returns bytes or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    import io as _io
    file.stream.seek(0)
    img_bytes = file.stream.read()
    try:
        Image.open(_io.BytesIO(img_bytes)).verify()
    except Exception:
        return None
    return img_bytes


def _board_query(club_id, before_post=None):
    """Return a query for board posts, newest first, capped at BOARD_MAX_AGE_DAYS."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=BOARD_MAX_AGE_DAYS)
    q = (ClubBoardPost.query
         .filter_by(club_id=club_id)
         .filter(ClubBoardPost.created_at >= cutoff)
         .order_by(ClubBoardPost.is_pinned.desc(),
                   ClubBoardPost.created_at.desc()))
    if before_post:
        q = q.filter(ClubBoardPost.created_at < before_post.created_at)
    return q


def _notify_subscribers(app, post_id):
    """Background thread: email all club subscribers except the author."""
    with app.app_context():
        from ..email import send_board_post_notification
        post = db.session.get(ClubBoardPost, post_id)
        if not post:
            return
        subs = (ClubBoardSubscription.query
                .filter_by(club_id=post.club_id)
                .filter(ClubBoardSubscription.user_id != post.author_id)
                .all())
        for sub in subs:
            try:
                send_board_post_notification(post, sub.user)
            except Exception as exc:
                logger.warning('Board notification failed for user %d: %s', sub.user_id, exc)


def _notify_reply_author(app, reply_id):
    """Background thread: email the post author when someone replies (not themselves)."""
    with app.app_context():
        from ..email import send_reply_notification
        reply = db.session.get(ClubBoardReply, reply_id)
        if not reply or not reply.post:
            return
        if reply.author_id == reply.post.author_id:
            return
        try:
            send_reply_notification(reply)
        except Exception as exc:
            logger.warning('Reply notification failed for reply %d: %s', reply_id, exc)


def _notify_mentions(app, body, club_id, author_id, post_id):
    """Background thread: email any @mentioned active club members."""
    with app.app_context():
        from ..models import User, ClubMembership
        from ..email import send_mention_notification
        usernames = set(_MENTION_RE.findall(body))
        if not usernames:
            return
        post = db.session.get(ClubBoardPost, post_id)
        if not post:
            return
        author = db.session.get(User, author_id)
        users = User.query.filter(User.username.in_(usernames)).all()
        member_ids = {m.user_id for m in
                      ClubMembership.query.filter_by(club_id=club_id, status='active').all()}
        for user in users:
            if user.id in member_ids and user.id != author_id:
                try:
                    send_mention_notification(user, author, post, body)
                except Exception as exc:
                    logger.warning('Mention notification failed for user %d: %s', user.id, exc)


# ── Routes ─────────────────────────────────────────────────────────────────────

@board_bp.route('/clubs/<slug>/board/', methods=['GET', 'POST'])
@login_required
def board(slug):
    club = _get_club(slug)
    _require_member(club)

    if request.method == 'POST':
        body = request.form.get('body', '').strip()
        if not body:
            flash('Post cannot be empty.', 'warning')
            return redirect(url_for('board.board', slug=slug))

        post = ClubBoardPost(club_id=club.id, author_id=current_user.id, body=body)
        db.session.add(post)
        db.session.flush()

        photos = request.files.getlist('photos')
        saved = 0
        pending_threads = []
        for f in photos:
            if saved >= BOARD_MAX_PHOTOS:
                break
            if f and f.filename:
                img_bytes = _read_image_bytes(f)
                if img_bytes is None:
                    continue
                max_width = current_app.config.get('MEDIA_MAX_WIDTH_PX', 1200)
                upload_root = current_app.config['UPLOAD_FOLDER']
                filename = f'{uuid.uuid4().hex}.jpg'
                rel = os.path.join('board_media', str(post.id), filename)
                dest = os.path.join(upload_root, 'board_media', str(post.id), filename)
                db.session.add(ClubBoardMedia(post_id=post.id, file_path=rel))
                pending_threads.append((img_bytes, dest, max_width))
                saved += 1

        db.session.commit()
        app = current_app._get_current_object()
        threading.Thread(target=_notify_subscribers, args=(app, post.id), daemon=True).start()
        threading.Thread(target=_notify_mentions,
                         args=(app, body, club.id, current_user.id, post.id),
                         daemon=True).start()
        for img_bytes, dest, max_width in pending_threads:
            threading.Thread(
                target=process_photo_bg,
                args=(img_bytes, dest, max_width, 2 * 1024 * 1024),
                daemon=True,
            ).start()

        flash('Post shared with the club.', 'success')
        return redirect(url_for('board.board', slug=slug) + '#board-top')

    before_id = request.args.get('before', type=int)
    before_post = db.session.get(ClubBoardPost, before_id) if before_id else None

    posts = _board_query(club.id, before_post).limit(BOARD_PAGE_SIZE + 1).all()
    has_more = len(posts) > BOARD_PAGE_SIZE
    posts = posts[:BOARD_PAGE_SIZE]

    is_subscribed = ClubBoardSubscription.query.filter_by(
        club_id=club.id, user_id=current_user.id).first() is not None
    is_admin = current_user.can_manage_content(club)

    return render_template(
        'clubs/board.html',
        club=club,
        posts=posts,
        has_more=has_more,
        oldest_id=posts[-1].id if posts else None,
        is_subscribed=is_subscribed,
        is_admin=is_admin,
        before_id=before_id,
    )


@board_bp.route('/clubs/<slug>/board/<int:post_id>/delete', methods=['POST'])
@login_required
def board_delete(slug, post_id):
    club = _get_club(slug)
    _require_member(club)
    post = ClubBoardPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()

    if post.author_id != current_user.id and not current_user.can_manage_content(club):
        abort(403)

    upload_root = current_app.config.get('UPLOAD_FOLDER', '')
    for m in post.media:
        if m.file_path and upload_root:
            try:
                os.remove(os.path.join(upload_root, m.file_path))
            except OSError:
                pass

    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'success')
    return redirect(request.referrer or url_for('board.board', slug=slug))


@board_bp.route('/clubs/<slug>/board/<int:post_id>/pin', methods=['POST'])
@login_required
def board_pin(slug, post_id):
    club = _get_club(slug)
    if not current_user.can_manage_content(club):
        abort(403)
    post = ClubBoardPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()
    post.is_pinned = not post.is_pinned
    db.session.commit()
    return redirect(request.referrer or url_for('board.board', slug=slug))


@board_bp.route('/clubs/<slug>/board/<int:post_id>/react', methods=['POST'])
@login_required
def board_react(slug, post_id):
    club = _get_club(slug)
    _require_member(club)
    post = ClubBoardPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()

    data = request.get_json(silent=True) or {}
    reaction_type = data.get('reaction') or request.form.get('reaction', '')
    if reaction_type not in ('like', 'dislike'):
        return jsonify({'error': 'invalid reaction'}), 400

    existing = ClubBoardReaction.query.filter_by(
        post_id=post_id, user_id=current_user.id).first()

    if existing:
        if existing.reaction == reaction_type:
            db.session.delete(existing)
            user_reaction = None
        else:
            existing.reaction = reaction_type
            user_reaction = reaction_type
    else:
        db.session.add(ClubBoardReaction(
            post_id=post_id, user_id=current_user.id, reaction=reaction_type))
        user_reaction = reaction_type

    db.session.commit()

    like_count = ClubBoardReaction.query.filter_by(post_id=post_id, reaction='like').count()
    dislike_count = ClubBoardReaction.query.filter_by(post_id=post_id, reaction='dislike').count()

    return jsonify({
        'like_count': like_count,
        'dislike_count': dislike_count,
        'user_reaction': user_reaction,
    })


@board_bp.route('/clubs/<slug>/board/<int:post_id>/reply', methods=['POST'])
@login_required
def board_reply(slug, post_id):
    club = _get_club(slug)
    _require_member(club)
    post = ClubBoardPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()

    body = request.form.get('body', '').strip()
    if not body:
        flash('Reply cannot be empty.', 'warning')
        return redirect(url_for('board.board', slug=slug) + f'#post-{post_id}')

    reply = ClubBoardReply(post_id=post_id, author_id=current_user.id, body=body)
    db.session.add(reply)
    db.session.commit()

    app = current_app._get_current_object()
    threading.Thread(target=_notify_reply_author, args=(app, reply.id), daemon=True).start()
    threading.Thread(target=_notify_mentions,
                     args=(app, body, club.id, current_user.id, post_id),
                     daemon=True).start()

    return redirect(url_for('board.board', slug=slug) + f'#post-{post_id}')


@board_bp.route('/clubs/<slug>/board/<int:post_id>/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def board_reply_delete(slug, post_id, reply_id):
    club = _get_club(slug)
    _require_member(club)
    reply = ClubBoardReply.query.filter_by(id=reply_id, post_id=post_id).first_or_404()
    # Verify the post belongs to this club
    ClubBoardPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()

    if reply.author_id != current_user.id and not current_user.can_manage_content(club):
        abort(403)

    db.session.delete(reply)
    db.session.commit()
    return redirect(url_for('board.board', slug=slug) + f'#post-{post_id}')


@board_bp.route('/clubs/<slug>/board/subscribe', methods=['POST'])
@login_required
def board_subscribe(slug):
    club = _get_club(slug)
    _require_member(club)

    existing = ClubBoardSubscription.query.filter_by(
        club_id=club.id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        flash('You will no longer receive board notifications.', 'info')
    else:
        db.session.add(ClubBoardSubscription(club_id=club.id, user_id=current_user.id))
        flash("You'll get an email when someone posts on the board.", 'success')
    db.session.commit()
    return redirect(request.referrer or url_for('board.board', slug=slug))


@board_bp.route('/media/board/<int:post_id>/<filename>')
@login_required
def serve_board_media(post_id, filename):
    post = db.session.get(ClubBoardPost, post_id)
    if post is None:
        abort(404)
    if not current_user.is_active_member_of(post.club):
        abort(403)
    upload_root = current_app.config['UPLOAD_FOLDER']
    post_dir = os.path.join(upload_root, 'board_media', str(post_id))
    return send_from_directory(post_dir, filename)
