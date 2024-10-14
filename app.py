from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import requests
import json
from flask_migrate import Migrate
import sqlalchemy as sa
from alembic import op
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify




app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Required for flash messages

# Configure SQLite database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gym.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)  # Add this for migrations 


# revision identifiers, used by Alembic.
revision = '862477ac028e'  # This will be your new revision ID
down_revision = 'da8e4c9e6a47'  # This will be the ID of the previous migration
branch_labels = None
depends_on = None

def upgrade():
    # Add the payment_method column
    op.add_column('payment_history', sa.Column('payment_method', sa.String(length=50), nullable=False))

def downgrade():
    # Drop the payment_method column
    op.drop_column('payment_history', 'payment_method')


# Database model for gym users
class GymUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    package_type = db.Column(db.String(20), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), default='Active')

    # Define the relationship to PaymentHistory
    payment_history = db.relationship('PaymentHistory', backref='user', cascade="all, delete-orphan")



# Database model for attendance records
class AttendanceRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('gym_user.id'), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)  # Use Date field for attendance date

    user = db.relationship('GymUser', backref='attendances')
class SMSLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('gym_user.id'), nullable=False)
    notification_date = db.Column(db.Date, nullable=False)  # The due date the notification is for
    message = db.Column(db.String, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)  # When the SMS was sent
    status = db.Column(db.String, default='Pending')  # Status of SMS (Sent/Failed)
    
    user = db.relationship('GymUser', backref=db.backref('sms_logs', lazy=True))

class PaymentHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('gym_user.id'), nullable=False)
    payment_amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)

# Create the database and tables within an application context
with app.app_context():
    db.create_all()


@app.route('/renew_user/<int:user_id>', methods=['POST'])
def renew_user(user_id):
    user = GymUser.query.get_or_404(user_id)
    payment_amount = request.form['payment_amount']
    payment_method = request.form['payment_method']  # Get payment method from form
    new_due_date_str = request.form['renew_date']  # Get new due date from form

    if payment_amount and new_due_date_str:
        # Add a new payment record to the PaymentHistory table
        payment = PaymentHistory(
            user_id=user.id,
            payment_amount=payment_amount,
            payment_date=datetime.now().date(),
            payment_method=payment_method  # Save payment method
        )
        db.session.add(payment)

        # Parse the new due date from the form input
        try:
            new_due_date = datetime.strptime(new_due_date_str, '%Y-%m-%d').date()  # Adjust format if necessary
            user.due_date = new_due_date  # Set the user's due date to the new due date
        except ValueError:
            flash("Invalid due date format! Please use YYYY-MM-DD.", 'danger')
            return redirect(url_for('dashboard'))

        db.session.commit()

        flash(f"Membership for {user.name} has been renewed.", 'success')
    else:
        flash("Payment amount and due date are required!", 'danger')

    return redirect(url_for('dashboard'))

def get_upcoming_payments():
    upcoming = []
    today = datetime.now().date()
    users = GymUser.query.all()

    for user in users:
        if today <= user.due_date <= today + timedelta(days=7):
            sms_log = SMSLog.query.filter_by(user_id=user.id, notification_date=user.due_date).first()
            sms_status = sms_log.status if sms_log else 'Not Sent'
            latest_payment = PaymentHistory.query.filter_by(user_id=user.id).order_by(PaymentHistory.payment_date.desc()).first()
            upcoming.append({
                'name': user.name,
                'due_date': user.due_date,
                'sms_status': sms_status,
                'latest_payment': latest_payment.payment_amount if latest_payment else 'No Payments',
                'user_id': user.id,
                'sms_sent': sms_status == 'Sent'
            })

    return upcoming
def log_sms_status(sms_log, response):
    if response.status_code == 200:
        sms_log.status = 'Sent'
    else:
        sms_log.status = 'Not Sent'
        # Optional: log the error response
        print(f"Error sending SMS: {response.content}")

    # Save the log status to the database
    db.session.commit()


# Function to send SMS reminder 3 days before the due date
def send_sms(phone_number, message):
    url = "https://api-et.sms.et/notification/sendsms/"
    payload = json.dumps({
        "sms_number_to": phone_number,
        "sms_content": message
    })
    headers = {
        'Authorization': 'token 679e93a19492ed55294c5a46b5337594c1bdda40',
        'Content-Type': 'application/json'
    }
    response = requests.post(url, headers=headers, data=payload)
    return response.text



# Automatically check and send reminders for upcoming payments
def check_and_send_reminders():
    today = datetime.now().date()
    users = GymUser.query.all()

    for user in users:
        if user.due_date == today + timedelta(days=3):  # Send reminder 3 days before the due date
            
            # Check if an SMS has already been sent for this user for the current due date
            existing_log = SMSLog.query.filter_by(user_id=user.id, notification_date=user.due_date).first()

            if not existing_log:
                # Prepare the SMS message
                message = f"Dear {user.name}, your AK gym membership payment is due on {user.due_date}. Please pay it on time to avoid service disruption."
                
                # Send SMS (replace this with your actual SMS sending logic)
                send_sms(user.phone, message)
                
                # Log the SMS in the database
                new_sms_log = SMSLog(user_id=user.id, notification_date=user.due_date, message=message)
                db.session.add(new_sms_log)
                db.session.commit()

                print(f"SMS sent to {user.name} for the due date {user.due_date}")
            else:
                print(f"SMS already sent to {user.name} for the due date {user.due_date}")

@app.route('/')
def dashboard():
    today = datetime.now().date()  # Get today's date

    # Fetch attendance records for today
    today_attendance = AttendanceRecord.query.filter_by(attendance_date=today).all()
    # Fetch today's payment history
    today = date.today()
    payment_history = PaymentHistory.query.join(GymUser).filter(PaymentHistory.payment_date == today).all()
    # Automatically send reminders and get upcoming payments
    check_and_send_reminders()
    upcoming_payments = get_upcoming_payments()

    # Fetch all gym users for display
    gym_users = GymUser.query.all()

    return render_template('dashboard.html', 
                           gym_users=gym_users, 
                           attendance_records=today_attendance, 
                           upcoming_payments=upcoming_payments,
                           payment_history=payment_history)  # Pass payment history to template
#  payment history to watch
@app.route('/payment_history', methods=['GET'])
def payment_history():
    selected_month = request.args.get('month')

    if selected_month:
        # Parse the selected month to filter records
        start_date = datetime.strptime(selected_month, '%Y-%m').date()
        end_date = datetime(start_date.year, start_date.month + 1, 1).date()
        payment_records = PaymentHistory.query.join(GymUser).filter(
            PaymentHistory.payment_date >= start_date,
            PaymentHistory.payment_date < end_date
        ).all()
    else:
        payment_records = PaymentHistory.query.join(GymUser).all()

    return render_template('payment_history.html', payment_records=payment_records, selected_month=selected_month)

# Route to view attendance history and filter by month
@app.route('/attendance_history', methods=['GET'])
def attendance_history():
    month_filter = request.args.get('month')
    if month_filter:
        # Parse the selected month (YYYY-MM) into a date range
        year, month = map(int, month_filter.split('-'))
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)

        # Query attendance records within the selected month
        attendance_records = AttendanceRecord.query.filter(AttendanceRecord.attendance_date >= start_date, AttendanceRecord.attendance_date < end_date).all()
    else:
        # Get all attendance records if no month filter is applied
        attendance_records = AttendanceRecord.query.order_by(AttendanceRecord.attendance_date.desc()).all()

    return render_template('attendance_history.html', attendance_records=attendance_records)

# Route to manually update the SMS status
@app.route('/update_sms_status', methods=['POST'])
def update_sms_status():
    # Iterate over each user_id received from the form
    for user_id in request.form.getlist('user_ids'):
        sms_sent = request.form.get(f'sms_sent_{user_id}')

        # Fetch the user from the database
        user = GymUser.query.get(user_id)
        if not user:
            flash(f"User with ID {user_id} not found", "error")
            continue

        # Fetch or create an SMSLog for the user for the current date
        sms_log = SMSLog.query.filter_by(user_id=user.id, notification_date=datetime.now().date()).first()
        if sms_log:
            # Update the existing SMS log based on the manual input
            sms_log.status = 'Sent' if sms_sent else 'Not Sent'
        else:
            # Create a new SMS log if none exists
            new_sms_log = SMSLog(
                user_id=user.id,
                notification_date=datetime.now().date(),
                message="Payment reminder",
                status='Sent' if sms_sent else 'Not Sent'
            )
            db.session.add(new_sms_log)

        db.session.commit()

    flash("SMS status updated successfully", "success")
    return redirect(url_for('dashboard'))

@app.route('/register_user', methods=['POST'])
def register_user():
    name = request.form.get('name')
    phone = request.form.get('phone')
    package_type = request.form.get('package_type')
    due_date = request.form.get('due_date')
    payment_method = request.form.get('payment_method')
    payment_amount = request.form.get('payment_amount')

    # Ensure phone number starts with +251
    if not phone.startswith('+251'):
        phone = '+251' + phone.lstrip('0')  # Strip leading 0 and add +251

    # Save the user to the database
    new_user = GymUser(
        name=name, 
        phone=phone, 
        package_type=package_type, 
        due_date=datetime.strptime(due_date, '%Y-%m-%d').date()
    )
    db.session.add(new_user)
    db.session.commit()

    # Save the payment details in the PaymentHistory table
    payment_record = PaymentHistory(
        user_id=new_user.id,
        payment_amount=float(payment_amount),
        payment_date=datetime.utcnow().date(),  # Payment date defaults to current date
        payment_method=payment_method
    )
    db.session.add(payment_record)
    db.session.commit()

    flash('User registered successfully with payment details!', 'success')
    return redirect(url_for('dashboard'))

# Route to mark attendance for a user
@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    user_id = request.form.get('user_id')

    # Check if the user ID exists in the database
    user = GymUser.query.filter_by(id=user_id).first()

    if not user:
        flash('Error: User ID does not exist. Please select a valid user.', 'error')
        return redirect(url_for('dashboard'))

    # Logic to check if the user has already marked attendance today
    attendance_date = datetime.now().date()  # Use today's date for attendance

    existing_attendance = AttendanceRecord.query.filter_by(user_id=user.id, attendance_date=attendance_date).first()

    if existing_attendance:
        flash('Attendance already marked for today!', 'warning')
        return redirect(url_for('dashboard'))

    # Logic to add attendance record to the database
    try:
        new_attendance = AttendanceRecord(user_id=user.id, attendance_date=attendance_date)
        db.session.add(new_attendance)
        db.session.commit()
        flash('Attendance marked successfully!', 'success')
    except Exception as e:
        flash(f'Error marking attendance: {e}', 'error')

    return redirect(url_for('dashboard'))

# Route to delete a gym user and their attendance records
@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    user = GymUser.query.get(user_id)
    if user:
        # Delete associated attendance records
        AttendanceRecord.query.filter_by(user_id=user_id).delete()
        
        # Delete associated SMS logs
        SMSLog.query.filter_by(user_id=user_id).delete()

        # Now delete the user
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
    else:
        flash('Error: User not found.', 'error')
    return redirect(url_for('dashboard'))

# Route to update a gym user's details
@app.route('/update_user/<int:user_id>', methods=['POST'])
def update_user(user_id):
    user = GymUser.query.get(user_id)
    if user:
        user.name = request.form['name']
        user.phone = request.form['phone']
        user.package_type = request.form['package_type']

        # Convert due_date string to a date object
        due_date_str = request.form['due_date']
        user.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()

        db.session.commit()
        flash('User updated successfully!', 'success')
    else:
        flash('Error: User not found.', 'error')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
