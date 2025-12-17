"""
Authentication Routes - Login, Logout, Signup, Profile
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
from database import get_db_session
from models.user import User
from auth.helpers import login_user, logout_user, get_current_user
from auth.decorators import login_required, admin_required

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login - accepts username or email"""
    if request.method == 'POST':
        username_or_email = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username_or_email or not password:
            flash('Username/Email and password are required', 'error')
            return render_template('auth/login.html')
        
        try:
            with get_db_session() as db_session:
                # Try to find user by username OR email
                user = db_session.query(User).filter(
                    (User.username == username_or_email) | (User.email == username_or_email)
                ).first()
                
                if not user:
                    flash('Invalid username/email or password', 'error')
                    return render_template('auth/login.html')
                
                if not user.check_password(password):
                    flash('Invalid username/email or password', 'error')
                    return render_template('auth/login.html')
                
                if not user.is_active:
                    flash('Your account has been deactivated', 'error')
                    return render_template('auth/login.html')
                
                # Update last login
                user.last_login = datetime.utcnow()
                db_session.commit()
                
                # Log in user
                login_user(user)
                
                # Redirect to next URL or dashboard
                next_url = session.pop('next_url', None)
                if next_url:
                    return redirect(next_url)
                return redirect(url_for('dashboard.dashboard'))
        except Exception as e:
            flash('An error occurred. Please try again.', 'error')
            print(f"Login error: {e}")
            import traceback
            traceback.print_exc()
        
        return render_template('auth/login.html')
    
    # GET request - show login form
    return render_template('auth/login.html')


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    """User registration"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        company = request.form.get('company', '').strip()
        
        # Validation
        errors = []
        if not username:
            errors.append('Username is required')
        if not email:
            errors.append('Email is required')
        if not password:
            errors.append('Password is required')
        if password != confirm_password:
            errors.append('Passwords do not match')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/signup.html')
        
        try:
            with get_db_session() as db_session:
                # Check if username or email already exists
                existing_user = db_session.query(User).filter(
                    (User.username == username) | (User.email == email)
                ).first()
                
                if existing_user:
                    if existing_user.username == username:
                        flash('Username already exists', 'error')
                    else:
                        flash('Email already registered', 'error')
                    return render_template('auth/signup.html')
                
                # Create new user
                user = User(
                    username=username,
                    email=email,
                    full_name=full_name,
                    phone=phone,
                    company=company,
                    role='user',
                    is_active=True,
                    is_verified=False
                )
                user.set_password(password)
                
                db_session.add(user)
                db_session.commit()
                
                flash('Account created successfully! Please log in.', 'success')
                return redirect(url_for('auth.login'))
        except Exception as e:
            flash('An error occurred during registration. Please try again.', 'error')
            print(f"Signup error: {e}")
            return render_template('auth/signup.html')
    
    # GET request - show signup form
    return render_template('auth/signup.html')


@auth_bp.route('/logout')
def logout():
    """User logout - no login required (allows logout on expired session)"""
    timeout = request.args.get('timeout', '0') == '1'
    logout_user()
    if timeout:
        flash('Your session has expired. Please log in again.', 'info')
    else:
        flash('You have been logged out successfully', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile')
@login_required
def profile():
    """User profile page"""
    user = get_current_user()
    if not user:
        return redirect(url_for('auth.login'))
    
    return render_template('auth/profile.html', user=user)


@auth_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    """Update user profile"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        with get_db_session() as db_session:
            # Reload user from database
            db_user = db_session.query(User).filter_by(id=user.id).first()
            if not db_user:
                return jsonify({'error': 'User not found'}), 404
            
            # Update fields
            db_user.full_name = request.form.get('full_name', db_user.full_name)
            db_user.phone = request.form.get('phone', db_user.phone)
            db_user.company = request.form.get('company', db_user.company)
            db_user.email = request.form.get('email', db_user.email)
            db_user.updated_at = datetime.utcnow()
            
            db_session.commit()
            
            # Update session
            session['username'] = db_user.username
            
            return jsonify({'success': True, 'message': 'Profile updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/extend_session', methods=['POST'])
@login_required
def extend_session():
    """Extend user session by updating last activity"""
    # Touch the session to extend it
    session.permanent = True
    session.modified = True
    return jsonify({'success': True, 'message': 'Session extended'})


@auth_bp.route('/admin/users')
@login_required
@admin_required
def admin_users():
    """Admin page to view all users"""
    try:
        with get_db_session() as db_session:
            # Get all users
            users = db_session.query(User).order_by(User.created_at.desc()).all()
            
            # Pre-load all attributes and expunge to avoid DetachedInstanceError
            user_list = []
            for user in users:
                _ = user.username
                _ = user.email
                _ = user.full_name
                _ = user.phone
                _ = user.company
                _ = user.role
                _ = user.is_active
                _ = user.is_verified
                _ = user.created_at
                _ = user.last_login
                db_session.expunge(user)
                user_list.append(user)
        
        return render_template('auth/admin_users.html', users=user_list)
    except Exception as e:
        flash(f'Error loading users: {str(e)}', 'error')
        return redirect(url_for('dashboard.dashboard'))


@auth_bp.route('/admin/user/<int:user_id>/toggle_active', methods=['POST'])
@login_required
@admin_required
def toggle_user_active(user_id):
    """Toggle user active status (admin only)"""
    try:
        with get_db_session() as db_session:
            user = db_session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            # Prevent admin from deactivating themselves
            if user.id == session.get('user_id'):
                return jsonify({'error': 'You cannot deactivate your own account'}), 400
            
            user.is_active = not user.is_active
            db_session.commit()
            
            status = 'activated' if user.is_active else 'deactivated'
            return jsonify({
                'success': True,
                'message': f'User {status} successfully',
                'is_active': user.is_active
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/admin/user/<int:user_id>/change_role', methods=['POST'])
@login_required
@admin_required
def change_user_role(user_id):
    """Change user role (admin only)"""
    try:
        new_role = request.json.get('role')
        if new_role not in ['user', 'admin']:
            return jsonify({'error': 'Invalid role'}), 400
        
        with get_db_session() as db_session:
            user = db_session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            # Prevent admin from changing their own role
            if user.id == session.get('user_id'):
                return jsonify({'error': 'You cannot change your own role'}), 400
            
            user.role = new_role
            db_session.commit()
            
            return jsonify({
                'success': True,
                'message': f'User role changed to {new_role}',
                'role': new_role
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/admin/user/<int:user_id>/toggle_verified', methods=['POST'])
@login_required
@admin_required
def toggle_user_verified(user_id):
    """Toggle user verification status (admin only)"""
    try:
        with get_db_session() as db_session:
            user = db_session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            user.is_verified = not user.is_verified
            db_session.commit()
            
            status = 'verified' if user.is_verified else 'unverified'
            return jsonify({
                'success': True,
                'message': f'User {status} successfully',
                'is_verified': user.is_verified
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/create-admin-user', methods=['POST'])
@login_required
def create_admin_user():
    """Create admin user - accessible to all logged-in users but requires main admin password"""
    # Main admin password
    MAIN_ADMIN_PASSWORD = "Admin@1234009XO$"
    
    try:
        # Get form data
        admin_password = request.form.get('admin_password', '').strip()
        username = request.form.get('new_username', '').strip()
        email = request.form.get('new_email', '').strip()
        password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        full_name = request.form.get('new_full_name', '').strip()
        phone = request.form.get('new_phone', '').strip()
        company = request.form.get('new_company', '').strip()
        
        # Validate main admin password
        if admin_password != MAIN_ADMIN_PASSWORD:
            return jsonify({'error': 'Invalid main admin password'}), 401
        
        # Validate required fields
        errors = []
        if not username:
            errors.append('Username is required')
        if not email:
            errors.append('Email is required')
        if not password:
            errors.append('Password is required')
        if password != confirm_password:
            errors.append('Passwords do not match')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters')
        
        if errors:
            return jsonify({'error': '; '.join(errors)}), 400
        
        # Create admin user
        with get_db_session() as db_session:
            # Check if username or email already exists
            existing_user = db_session.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()
            
            if existing_user:
                if existing_user.username == username:
                    return jsonify({'error': 'Username already exists'}), 400
                else:
                    return jsonify({'error': 'Email already registered'}), 400
            
            # Create new admin user
            new_admin = User(
                username=username,
                email=email,
                full_name=full_name if full_name else None,
                phone=phone if phone else None,
                company=company if company else None,
                role='admin',
                is_active=True,
                is_verified=True
            )
            new_admin.set_password(password)
            
            db_session.add(new_admin)
            db_session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Admin user "{username}" created successfully'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

