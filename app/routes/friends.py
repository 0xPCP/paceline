from flask import Blueprint, redirect, url_for, flash, abort, request
from flask_login import current_user, login_required
from ..extensions import db
from ..models import User, UserFriend

friends_bp = Blueprint('friends', __name__)


@friends_bp.route('/users/<username>/friend-request', methods=['POST'])
@login_required
def send_request(username):
    other = User.query.filter_by(username=username).first_or_404()
    if other.id == current_user.id:
        flash('You cannot send a friend request to yourself.', 'danger')
        return redirect(url_for('main.public_profile', username=username))

    follow_rides = request.form.get('follow_rides') == '1'
    existing = current_user.friend_request_row(other)
    if existing:
        if existing.status == 'accepted':
            flash('You are already friends.', 'info')
        elif existing.status == 'pending':
            flash('Friend request already sent.', 'info')
        elif existing.status == 'declined':
            existing.requester_id = current_user.id
            existing.addressee_id = other.id
            existing.status = 'pending'
            existing.follow_rides = follow_rides
            db.session.commit()
            flash(f'Friend request sent to @{username}.', 'success')
        return redirect(url_for('main.public_profile', username=username))

    row = UserFriend(requester_id=current_user.id, addressee_id=other.id,
                     status='pending', follow_rides=follow_rides)
    db.session.add(row)
    db.session.commit()
    flash(f'Friend request sent to @{username}.', 'success')
    return redirect(url_for('main.public_profile', username=username))


@friends_bp.route('/friends/<int:request_id>/accept', methods=['POST'])
@login_required
def accept_request(request_id):
    row = UserFriend.query.get_or_404(request_id)
    if row.addressee_id != current_user.id:
        abort(403)
    row.status = 'accepted'
    db.session.commit()
    flash(f'You are now friends with @{row.requester.username}.', 'success')
    return redirect(url_for('main.public_profile', username=row.requester.username))


@friends_bp.route('/friends/<int:request_id>/decline', methods=['POST'])
@login_required
def decline_request(request_id):
    row = UserFriend.query.get_or_404(request_id)
    if row.addressee_id != current_user.id:
        abort(403)
    row.status = 'declined'
    db.session.commit()
    flash('Friend request declined.', 'info')
    return redirect(url_for('main.public_profile', username=row.requester.username))


@friends_bp.route('/friends/<int:user_id>/remove', methods=['POST'])
@login_required
def remove_friend(user_id):
    other = User.query.get_or_404(user_id)
    row = current_user.friend_request_row(other)
    if not row or row.status != 'accepted':
        flash('No active friendship to remove.', 'warning')
        return redirect(url_for('main.public_profile', username=other.username))
    db.session.delete(row)
    db.session.commit()
    flash(f'Removed @{other.username} from your friends.', 'info')
    return redirect(url_for('main.public_profile', username=other.username))
