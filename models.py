# --- START OF FILE models.py ---

from sqlalchemy import func, CheckConstraint, text # <-- Add CheckConstraint, text
from sqlalchemy.orm import validates # <-- Add validates
from sqlalchemy.exc import OperationalError # <-- Import specific error for test data

from extensions import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, time, timedelta # <-- Add timedelta
import logging # <-- Add logging

logger = logging.getLogger(__name__) # Add logger


class UserCredentials(UserMixin, db.Model):
    __tablename__ = 'user_credentials'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    # Add 'librarian' to the list of allowed roles if you want DB constraints,
    # otherwise, just manage it application-side.
    # Example: role = db.Column(db.Enum('admin', 'student', 'teacher', 'hod', 'librarian', name='user_roles'), nullable=False)
    role = db.Column(db.String(20), nullable=False) # Keep as String if you prefer flexibility
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships defined via backref in other models
    # teacher_profile = defined in TeacherDetails
    # student_profile = defined in StudentDetails (If using the old model)
    # admin_profile = defined in AdminProfile
    # hod_profile = defined in HODProfile
    # book_borrowings = defined in BookIssue (student perspective)
    # books_issued_by = defined in BookIssue (librarian perspective)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<UserCredentials {self.id} {self.email} ({self.role})>'


class TeacherDetails(db.Model):
    __tablename__ = 'teacher_details'

    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.Integer, db.ForeignKey('user_credentials.id', ondelete="CASCADE"), unique=True, nullable=False)
    first_name = db.Column(db.String(64), nullable=False)
    last_name = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    photo_path = db.Column(db.String(500))  # Optional photo storage
    department = db.Column(db.String(64), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False, server_default=func.now())

    # Relationships
    credentials = db.relationship('UserCredentials', backref=db.backref('teacher_profile', uselist=False, cascade="all, delete-orphan", single_parent=True))

    def __repr__(self):
        return f'<TeacherDetails {self.id} {self.first_name} {self.last_name}>'


# NOTE: The original StudentDetails model might become less relevant if all students
# are only stored in the dynamic batch tables. Keep it if you have other uses for it,
# otherwise, you might consider removing it later. For now, keep it as is.
class StudentDetails(db.Model):
    __tablename__ = 'student_details'

    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.Integer, db.ForeignKey('user_credentials.id', ondelete="CASCADE"), unique=True, nullable=False)
    first_name = db.Column(db.String(64), nullable=False)
    last_name = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    photo_path = db.Column(db.String(500))
    roll_number = db.Column(db.String(20), unique=True, nullable=False)
    current_year = db.Column(db.Integer, nullable=False)
    current_semester = db.Column(db.Integer, nullable=False)
    admission_year = db.Column(db.Integer, nullable=False)
    course = db.Column(db.String(10), nullable=False) # Consider FK to Course model
    batch = db.Column(db.String(10), nullable=False)
    department = db.Column(db.String(64), nullable=False) # Maybe remove if derived from course?
    admission_date = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    credentials = db.relationship('UserCredentials', backref=db.backref('student_profile', uselist=False, cascade="all, delete-orphan", single_parent=True))

    def __repr__(self):
         return f'<StudentDetails {self.id} {self.roll_number}>'


class AdminProfile(db.Model):
    __tablename__ = 'admin_profiles'

    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.Integer, db.ForeignKey('user_credentials.id', ondelete="CASCADE"), unique=True, nullable=False)
    department = db.Column(db.String(64)) # e.g., 'IT', 'HR', 'Administration'
    access_level = db.Column(db.String(20), default='full') # e.g., 'full', 'limited'

    # Relationship
    credentials = db.relationship('UserCredentials', backref=db.backref('admin_profile', uselist=False, cascade="all, delete-orphan", single_parent=True))

    def __repr__(self):
        return f'<AdminProfile {self.id} (User: {self.credential_id})>'


class HODProfile(db.Model):
    __tablename__ = 'hod_profiles'

    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.Integer, db.ForeignKey('user_credentials.id', ondelete="CASCADE"), unique=True, nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    phone = db.Column(db.String(15), nullable=True) # Made nullable
    address = db.Column(db.String(255), nullable=True) # Made nullable
    photo_path = db.Column(db.String(500))
    department = db.Column(db.String(64), nullable=False)
    office_location = db.Column(db.String(64))
    appointment_date = db.Column(db.DateTime, nullable=False, server_default=func.now())

    # Relationships
    credentials = db.relationship('UserCredentials', backref=db.backref('hod_profile', uselist=False, cascade="all, delete-orphan", single_parent=True))

    def __repr__(self):
        return f'<HODProfile {self.id} {self.first_name} {self.last_name} ({self.department})>'


class Course(db.Model):
    __tablename__ = 'courses'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False) # Increased length
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    # Relationships defined via backref
    # batch_tables = defined in BatchTable
    # subjects = defined in CourseSubject

    def __repr__(self):
        return f'<Course {self.id} {self.code} - {self.name}>'


class BatchTable(db.Model):
    __tablename__ = 'batch_tables'

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(100), unique=True, nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id', ondelete='CASCADE'), nullable=False)
    course_name = db.Column(db.String(100), nullable=False)
    course_code = db.Column(db.String(20), nullable=False)
    admission_year = db.Column(db.Integer, nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    batch_id = db.Column(db.Integer, nullable=False) # e.g., 1, 2, 3, 4, 5
    created_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp())

    # Relationship with Course model
    course = db.relationship('Course', backref=db.backref('batch_tables', lazy=True, cascade="all, delete-orphan"))

    # Unique constraint for the combination
    __table_args__ = (
        db.UniqueConstraint('course_id', 'admission_year', 'semester', 'batch_id', name='uq_batch_combination'),
        db.Index('idx_batch_lookup', 'course_id', 'admission_year', 'semester', 'batch_id'),
    )

    def __repr__(self):
        return f'<BatchTable {self.id}: {self.table_name}>'


class CourseSubject(db.Model):
    __tablename__ = 'course_subjects'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id', ondelete='CASCADE'), nullable=False)
    batch_id = db.Column(db.Integer, nullable=False) # Batch ID (e.g., 1-5) linked conceptually to BatchTable, not FK
    subject_code = db.Column(db.String(30), nullable=False) # Increased length
    subject_name = db.Column(db.String(150), nullable=False) # Increased length
    # 'year' here refers to the academic year the subject is typically taught *in* (e.g., 1, 2, 3, 4)
    # OR the admission year it applies to. Be consistent! Let's assume it's Admission Year here based on usage.
    year = db.Column(db.Integer, nullable=False, index=True) # Refers to ADMISSION YEAR
    semester = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Define relationship with Course model
    course = db.relationship('Course', backref=db.backref('subjects', lazy=True, cascade="all, delete-orphan"))

    # Relationships defined via backref
    # periods = defined in SubjectPeriods
    # assignments = defined in SubjectAssignment
    # timetable_entries = defined in TimetableAssignment

    # Unique constraint to prevent duplicate subject entries for the same batch/sem/year/course
    __table_args__ = (
        db.UniqueConstraint('course_id', 'year', 'semester', 'batch_id', 'subject_code', name='uq_course_subject'),
        db.Index('idx_subject_lookup', 'course_id', 'year', 'semester', 'batch_id'),
    )

    def __repr__(self):
        return (f"<CourseSubject {self.id} {self.subject_code} - {self.subject_name} "
                f"(Course: {self.course_id}, Year: {self.year}, Sem: {self.semester}, Batch: {self.batch_id})>")


class SubjectPeriods(db.Model):
    __tablename__ = 'subject_periods'

    id = db.Column(db.Integer, primary_key=True)
    course_subject_id = db.Column(db.Integer, db.ForeignKey('course_subjects.id', ondelete='CASCADE'), nullable=False)
    max_periods_per_day = db.Column(db.Integer, nullable=False, default=1)
    max_periods_per_week = db.Column(db.Integer, nullable=False, default=5) # Default 5
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    course_subject = db.relationship('CourseSubject', backref=db.backref('periods', uselist=False, lazy=True, cascade="all, delete-orphan")) # Usually one setting per subject

    def __repr__(self):
        return f"<SubjectPeriods for Subject ID: {self.course_subject_id}>"


class SubjectAssignment(db.Model):
    __tablename__ = 'subject_assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    course_subject_id = db.Column(db.Integer, db.ForeignKey('course_subjects.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher_details.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Define relationships
    subject = db.relationship('CourseSubject', backref='assignments')
    teacher = db.relationship('TeacherDetails', backref='subject_assignments')

    # Prevent assigning the same teacher to the exact same subject instance multiple times
    __table_args__ = (
        db.UniqueConstraint('course_subject_id', 'teacher_id', name='uq_teacher_subject_assignment'),
    )

    def __repr__(self):
        # Add checks for relationship loading if using lazy='dynamic'
        subj_name = self.subject.subject_name if self.subject else self.course_subject_id
        teacher_name = f"{self.teacher.first_name} {self.teacher.last_name}" if self.teacher else self.teacher_id
        return f"<SubjectAssignment ID:{self.id} Subject:'{subj_name}' -> Teacher:'{teacher_name}'>"


# Removed TimetableAssignment and StudyMaterial for brevity as they weren't directly involved in the library request.
# Keep them if they are part of your original code.


class Attendance(db.Model):
    __tablename__ = 'attendance' # Generic attendance table, less ideal for dynamic students

    id = db.Column(db.Integer, primary_key=True)
    # These FKs might cause issues if student/subject records are deleted. Consider ON DELETE SET NULL or careful management.
    subject_id = db.Column(db.Integer, db.ForeignKey('course_subjects.id', ondelete='SET NULL'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_details.id', ondelete='SET NULL'), nullable=True) # FK to static table might be wrong
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher_details.id', ondelete='SET NULL'), nullable=True)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # present, absent, late
    remarks = db.Column(db.String(200))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # NOTE: Using dynamic attendance tables (like attendance_{course_id}_{year}) is generally better
    # when using dynamic student tables, as done in auth.py. This model might be unused or problematic.

    def __repr__(self):
        return f"<Attendance ID:{self.id} Student:{self.student_id} Subject:{self.subject_id} Date:{self.date} Status:{self.status}>"


class OTPModel(db.Model):
    __tablename__ = 'otp_store'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True) # Index email
    otp_code = db.Column(db.String(6), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)

    def is_valid(self):
        """Check if OTP is valid (not expired and not used)"""
        return not self.is_used and datetime.utcnow() < self.expires_at

    def __repr__(self):
        return f"<OTP {self.id} for {self.email}>"

# --- EMAIL SERVICE MODEL HERE ---

class EmailLog(db.Model):
    __tablename__ = 'email_logs'

    id = db.Column(db.Integer, primary_key=True)
    to_email = db.Column(db.String(255), nullable=False)
    from_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text)
    html_body = db.Column(db.Text)
    template_name = db.Column(db.String(255))
    context_data = db.Column(db.JSON)
    priority = db.Column(db.Integer, default=3)  # 1=Highest, 5=Lowest
    status = db.Column(db.String(20), default='pending')  # pending, sent, failed
    error_message = db.Column(db.Text)
    retry_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<EmailLog {self.id}: {self.to_email}>'

# --- NEW LIBRARY MODELS START ---

class Book(db.Model):
    __tablename__ = 'books'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    author = db.Column(db.String(255), nullable=False)
    isbn = db.Column(db.String(20), unique=True, nullable=True, index=True) # ISBN can be unique identifier, indexed
    publisher = db.Column(db.String(100))
    publication_year = db.Column(db.Integer)
    genre = db.Column(db.String(50))
    total_copies = db.Column(db.Integer, nullable=False, default=1)
    available_copies = db.Column(db.Integer, nullable=False, default=1)
    added_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, index=True) # To softly delete books, indexed
    cover_photo = db.Column(db.String(500))  # Add this line for cover photo path

    # Relationships defined via backref
    # issues = defined in BookIssue

    # Ensure available copies are not more than total copies and >= 0
    __table_args__ = (
        CheckConstraint('available_copies <= total_copies', name='check_available_copies_leq_total'),
        CheckConstraint('available_copies >= 0', name='check_available_copies_geq_zero'),
        CheckConstraint('total_copies >= 0', name='check_total_copies_geq_zero'),
    )

    # Use validates decorator for Python-level validation before commit
    @validates('available_copies')
    def validate_available_copies(self, key, value):
        if value is None:
            raise ValueError("Available copies cannot be null.")
        if value < 0:
            raise ValueError("Available copies cannot be negative.")
        # Check against current total_copies if available
        if hasattr(self, 'total_copies') and self.total_copies is not None and value > self.total_copies:
             # Log warning, but allow temporary state during update? Or raise error?
             # Let's raise error for consistency. Edit logic should handle calculation.
             # logger.warning(f"Attempt to set available_copies ({value}) > total_copies ({self.total_copies}) for book {self.id}")
             raise ValueError(f"Available copies ({value}) cannot exceed total copies ({self.total_copies}).")
        return value

    @validates('total_copies')
    def validate_total_copies(self, key, value):
        if value is None:
             raise ValueError("Total copies cannot be null.")
        if value < 0:
            raise ValueError("Total copies cannot be negative.")
        # If total copies are reduced below available, the edit_book logic should handle recalculating available_copies.
        # This validator just ensures total is not negative.
        return value

    def __repr__(self):
        return f'<Book {self.id}: {self.title} by {self.author}>'


class BookIssue(db.Model):
    __tablename__ = 'book_issues'

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id', ondelete='CASCADE'), nullable=False) # Cascade delete if book is hard-deleted
    # Store reference to the dynamic student table and the student's ID within that table
    student_table_name = db.Column(db.String(100), nullable=False, index=True) # Index for faster student lookup
    student_id_in_table = db.Column(db.Integer, nullable=False, index=True) # Index for faster student lookup
    # Store credential_id for easy lookup of user details like email for notifications
    # ON DELETE SET NULL: If user credentials are deleted, keep the issue record but nullify the link
    student_credential_id = db.Column(db.Integer, db.ForeignKey('user_credentials.id', ondelete='SET NULL'), nullable=True, index=True)
    librarian_credential_id = db.Column(db.Integer, db.ForeignKey('user_credentials.id', ondelete='SET NULL'), nullable=True) # Who issued the book
    issue_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False, index=True) # Index for finding overdue books
    return_date = db.Column(db.DateTime, nullable=True)
    is_returned = db.Column(db.Boolean, default=False, nullable=False, index=True) # Index for filtering returned
    fine_due = db.Column(db.Float, default=0.0) # Optional: For tracking fines

    # Relationships
    book = db.relationship('Book', backref=db.backref('issues', lazy=True, cascade="all, delete-orphan"))
    # Use distinct foreign_keys because student_credential_id and librarian_credential_id point to the same table
    student_user = db.relationship('UserCredentials', foreign_keys=[student_credential_id], backref=db.backref('book_borrowings', lazy=True))
    librarian_user = db.relationship('UserCredentials', foreign_keys=[librarian_credential_id], backref=db.backref('books_issued_by', lazy=True))

    # Index for combined student lookup
    __table_args__ = (
        db.Index('idx_student_issue_lookup', 'student_table_name', 'student_id_in_table', 'is_returned'),
        db.Index('idx_book_issue_lookup', 'book_id', 'is_returned'),
    )

    def __init__(self, **kwargs):
        super(BookIssue, self).__init__(**kwargs)
        # Set default due date if not provided (e.g., 14 days from issue date)
        if 'due_date' not in kwargs:
            # Ensure issue_date exists or use utcnow()
            issue_dt = kwargs.get('issue_date', datetime.utcnow())
            # Handle case where issue_date might be passed as None accidentally
            if issue_dt is None: 
                issue_dt = datetime.utcnow()
            self.due_date = issue_dt + timedelta(days=14)
        # Ensure due_date is datetime if passed as date
        elif isinstance(self.due_date, date) and not isinstance(self.due_date, datetime):
            self.due_date = datetime.combine(self.due_date, time(23, 59, 59))


    @property
    def is_overdue(self):
        """Checks if the book is currently overdue."""
        # Ensure due_date is a datetime object for comparison
        due_datetime = self.due_date
        if isinstance(due_datetime, date) and not isinstance(due_datetime, datetime):
            due_datetime = datetime.combine(due_datetime, time(23, 59, 59))

        return not self.is_returned and datetime.utcnow() > due_datetime

    @property
    def days_overdue(self):
        """Calculate the number of days a book is overdue."""
        if not self.is_overdue:
            return 0
            
        # Ensure due_date is a datetime object
        due_datetime = self.due_date
        if isinstance(due_datetime, date) and not isinstance(due_datetime, datetime):
            due_datetime = datetime.combine(due_datetime, time(23, 59, 59))
            
        current_time = datetime.utcnow()
        days = (current_time.date() - due_datetime.date()).days
        return max(0, days)  # Ensure we never return negative days

    def __repr__(self):
        return f'<BookIssue ID:{self.id} Book:{self.book_id}, StudentTable:{self.student_table_name}, StudentID:{self.student_id_in_table}, Due:{self.due_date.strftime("%Y-%m-%d") if self.due_date else "N/A"}>'

# --- NEW LIBRARY MODELS END ---


class LibrarianProfile(db.Model):
    __tablename__ = 'librarian_profiles'

    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.Integer, db.ForeignKey('user_credentials.id', ondelete="CASCADE"), unique=True, nullable=False)
    first_name = db.Column(db.String(64), nullable=False)
    last_name = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    photo_path = db.Column(db.String(255))
    joining_date = db.Column(db.Date, default=datetime.utcnow)
    
    # Relationship
    credentials = db.relationship('UserCredentials', backref=db.backref('librarian_profile', uselist=False, cascade="all, delete-orphan"))

    def __repr__(self):
        return f'<Librarian {self.first_name} {self.last_name}>'


@login_manager.user_loader
def load_user(user_id):
    # user_id is expected to be a string from the session cookie
    try:
        return UserCredentials.query.get(int(user_id))
    except (ValueError, TypeError):
        logger.error(f"Invalid user_id type for load_user: {user_id}")
        return None


def create_test_data():
    """Creates initial admin, courses, subjects, and library data if they don't exist."""
    try:
        # --- Admin User ---
        admin_email = 'admin@example.com'
        admin = UserCredentials.query.filter_by(email=admin_email).first()
        if not admin:
            admin_pwd = 'admin123'
            admin = UserCredentials(email=admin_email, role='admin', is_active=True)
            admin.set_password(admin_pwd)
            db.session.add(admin)
            db.session.flush() # Get ID
            admin_profile = AdminProfile(credential_id=admin.id, department='Administration', access_level='full')
            db.session.add(admin_profile)
            db.session.commit()
            logger.info(f"Admin user created: {admin_email} / {admin_pwd}")
        else:
            logger.debug("Admin user already exists.")

        # --- Courses ---
        courses_data = [
            {'code': 'CSE', 'name': 'Computer Science and Engineering'},
            {'code': 'ECE', 'name': 'Electronics and Communication Engineering'},
            {'code': 'ME', 'name': 'Mechanical Engineering'},
        ]
        courses = {}
        for c_data in courses_data:
            course = Course.query.filter_by(code=c_data['code']).first()
            if not course:
                course = Course(code=c_data['code'], name=c_data['name'])
                db.session.add(course)
                logger.info(f"Course added: {c_data['code']}")
            else:
                logger.debug(f"Course {c_data['code']} already exists.")
            courses[c_data['code']] = course
        db.session.commit() # Commit courses to get IDs

        # --- Subjects (Example for CSE 2024, Sem 1, Batch 1) ---
        cse_course_id = courses['CSE'].id
        admission_year_2024 = 2024
        semester_1 = 1
        batch_id_1 = 1

        subjects_data = [
            {'code': 'CS101', 'name': 'Introduction to Programming'},
            {'code': 'MA101', 'name': 'Calculus I'},
            {'code': 'PH101', 'name': 'Physics I'},
        ]
        subject_count = 0
        for s_data in subjects_data:
            exists = CourseSubject.query.filter_by(
                course_id=cse_course_id, year=admission_year_2024, semester=semester_1,
                batch_id=batch_id_1, subject_code=s_data['code']
            ).first()
            if not exists:
                subject = CourseSubject(
                    course_id=cse_course_id, year=admission_year_2024, semester=semester_1,
                    batch_id=batch_id_1, subject_code=s_data['code'], subject_name=s_data['name']
                )
                db.session.add(subject)
                subject_count += 1
        if subject_count > 0:
            db.session.commit()
            logger.info(f"Added {subject_count} sample subjects for CSE 2024 Sem 1 Batch 1.")
        else:
            logger.debug("Sample subjects already exist.")


        # --- Librarian User ---
        librarian_email = 'librarian@example.com'
        librarian = UserCredentials.query.filter_by(email=librarian_email).first()
        if not librarian:
            librarian_pwd = 'librarian123'
            librarian = UserCredentials(email=librarian_email, role='librarian', is_active=True)
            librarian.set_password(librarian_pwd)
            db.session.add(librarian)
            db.session.commit()
            logger.info(f"Librarian user created: {librarian_email} / {librarian_pwd}")
        else:
             logger.debug("Librarian user already exists.")


        # --- Sample Books ---
        if Book.query.count() == 0:
             sample_books_data = [
                 {'title': 'The Hitchhiker\'s Guide to the Galaxy', 'author': 'Douglas Adams', 'isbn': '978-0345391803', 'total_copies': 5, 'available_copies': 5},
                 {'title': 'Pride and Prejudice', 'author': 'Jane Austen', 'isbn': '978-0141439518', 'total_copies': 3, 'available_copies': 3}, # Corrected available
                 {'title': '1984', 'author': 'George Orwell', 'isbn': '978-0451524935', 'total_copies': 4, 'available_copies': 4},
                 {'title': 'Data Structures and Algorithms in Python', 'author': 'Goodrich, Tamassia, Goldwasser', 'isbn': '978-1118290279', 'total_copies': 2, 'available_copies': 2},
             ]
             for b_data in sample_books_data:
                 # Check if ISBN exists before adding
                 if b_data.get('isbn') and Book.query.filter_by(isbn=b_data['isbn']).first():
                     logger.warning(f"Skipping sample book add: ISBN {b_data['isbn']} already exists.")
                     continue
                 book = Book(**b_data)
                 db.session.add(book)

             db.session.commit()
             logger.info(f"Added {len(sample_books_data)} sample books.")
        else:
             logger.debug("Books already exist in the database.")

        return "Test data setup checked/executed."

    except OperationalError as oe:
        # Handle cases where tables might not exist yet during initial setup
        db.session.rollback()
        logger.error(f"OperationalError during test data creation (likely tables missing): {oe}")
        return f"Error during test data setup (OperationalError): {oe}"
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating test data: {e}", exc_info=True)
        return f"Error creating test data: {e}"


# --- END OF FILE models.py ---
