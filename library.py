# --- START OF FILE library.py ---

import logging
import os
import re
from datetime import datetime, timedelta
from functools import wraps
from flask import send_from_directory, abort
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    current_app,
    session,
)
from flask_login import login_required, current_user
from flask_mail import Message
from sqlalchemy import text, exc as sqlalchemy_exc, desc, asc, or_, and_, func
from werkzeug.utils import secure_filename

from extensions import db # Assuming mail is configured in extensions
from models import (
    Book,
    BookIssue,
    UserCredentials,
    BatchTable,
    Course,
)  # Import necessary models
from services.email_service import EmailService  # Add this import
from services.tasks import process_email_queue

library_bp = Blueprint("library", __name__, url_prefix="/library")
logger = logging.getLogger(__name__)

# Add these constants at the top of the file
COVER_UPLOAD_FOLDER = 'uploads/book_covers'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_secure_filename(filename):
    """Generate a secure filename with timestamp"""
    base = secure_filename(filename)
    name, ext = os.path.splitext(base)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{name}_{timestamp}{ext}"

# --- Helper Function to Get Student Info ---
def get_student_details(table_name, student_id_in_table):
    """Helper function to get student details from a dynamic batch table."""
    try:
        # Log input parameters
        logger.info(f"Attempting to get student details - Table: {table_name}, Student ID: {student_id_in_table}")

        # Validate input parameters
        if not table_name or not student_id_in_table:
            logger.error("Invalid input parameters: table_name or student_id_in_table is empty")
            return None

        # First verify if student exists in the table
        check_query = text(f"""
            SELECT EXISTS (
                SELECT 1 
                FROM {table_name} 
                WHERE id = :student_id
            )
        """)
        
        exists = db.session.execute(
            check_query, 
            {"student_id": student_id_in_table}
        ).scalar()

        if not exists:
            logger.warning(f"Student ID {student_id_in_table} not found in table {table_name}")
            return None

        # Get student details with course information
        query = text(f"""
            SELECT 
                s.id,
                s.first_name,
                s.last_name,
                s.email,
                s.credential_id,
                s.roll_number,
                s.phone,
                s.course,
                s.current_semester as semester,
                s.department as branch,
                s.batch as batch_id
            FROM {table_name} s
            WHERE s.id = :student_id
        """)
        
        result = db.session.execute(
            query, 
            {"student_id": student_id_in_table}
        ).fetchone()

        if not result:
            logger.error(f"Query returned no results despite existence check passing - Table: {table_name}, Student ID: {student_id_in_table}")
            return None

        # Log successful retrieval
        logger.info(f"Successfully retrieved student details for ID {student_id_in_table}")

        return {
            "id_in_table": result.id,
            "full_name": f"{result.first_name} {result.last_name}",
            "email": result.email,
            "credential_id": result.credential_id,
            "roll_number": result.roll_number,
            "phone": result.phone,
            "course": result.course,
            "semester": result.semester,
            "branch": result.branch,
            "batch_id": result.batch_id
        }

    except sqlalchemy_exc.ProgrammingError as e:
        logger.error(f"SQL Programming Error in get_student_details: {str(e)}\nTable: {table_name}, Student ID: {student_id_in_table}")
        raise
    except sqlalchemy_exc.SQLAlchemyError as e:
        logger.error(f"SQLAlchemy Error in get_student_details: {str(e)}\nTable: {table_name}, Student ID: {student_id_in_table}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_student_details: {str(e)}\nTable: {table_name}, Student ID: {student_id_in_table}", exc_info=True)
        raise


# --- Permission Check Decorator ---
def librarian_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role not in ["librarian", "admin"]:  # Allow admin too
            flash("Access denied. Librarian privileges required.", "danger")
            # Redirect based on actual role or to a generic 'unauthorized' page
            return redirect(
                url_for(
                    f"auth.{current_user.role}_dashboard"
                    if hasattr(current_user, "role")
                    else "auth.index"
                )
            )
        return f(*args, **kwargs)

    return decorated_function


# --- Routes ---


@library_bp.route("/dashboard")
@librarian_required
def dashboard():
    try:
        issued_count = BookIssue.query.filter_by(is_returned=False).count()
        overdue_count = BookIssue.query.filter(
            BookIssue.is_returned == False, BookIssue.due_date < datetime.utcnow()
        ).count()
        total_books = (
            db.session.query(db.func.sum(Book.total_copies))
            .filter(Book.is_active == True)
            .scalar()
            or 0
        )
        available_books = (
            db.session.query(db.func.sum(Book.available_copies))
            .filter(Book.is_active == True)
            .scalar()
            or 0
        )
    except Exception as e:
        logger.error(f"Error loading library dashboard data: {e}", exc_info=True)
        flash("Error loading dashboard statistics.", "danger")
        issued_count, overdue_count, total_books, available_books = 0, 0, 0, 0

    return render_template(
        "library/dashboard.html",
        issued_count=issued_count,
        overdue_count=overdue_count,
        total_books=total_books,
        available_books=available_books,
    )


# --- Book Management ---

# Removed normalize_search_term, get_search_tokens, build_search_query
# as they were not used directly by the called functions below.
# build_book_search_query handles the search logic for the views.

def build_book_search_query(query, search_query, include_student_search=False):
    """Build search query with OR conditions for each search field for books."""
    if not search_query:
        return query

    search_terms = search_query.strip().lower().split()
    if not search_terms:
        return query

    conditions = []
    for term in search_terms:
        term_filter = [
            func.lower(Book.title).like(f"%{term}%"),
            func.lower(Book.author).like(f"%{term}%"),
            func.lower(Book.isbn).like(f"%{term}%"),
            func.lower(Book.publisher).like(f"%{term}%"),
            func.lower(Book.genre).like(f"%{term}%"),
        ]

        if include_student_search:
            # Get all unique table names from book issues
            table_names = (
                db.session.query(BookIssue.student_table_name.distinct()).all()
            )

            # Create OR conditions for each table
            for (table_name,) in table_names:
                # Basic validation for table name format
                if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
                    logger.warning(
                        f"Skipping potentially unsafe table name in search: {table_name}"
                    )
                    continue

                # Format the SQL with the actual table name (using safe table name)
                student_search_sql = text(
                    f"""
                    EXISTS (
                        SELECT 1 FROM `{table_name}`
                        WHERE id = book_issues.student_id_in_table
                        AND book_issues.student_table_name = :table_name
                        AND (
                            LOWER(first_name) LIKE :search_term
                            OR LOWER(last_name) LIKE :search_term
                            OR LOWER(email) LIKE :search_term
                            OR LOWER(CONCAT(first_name, ' ', last_name)) LIKE :search_term
                        )
                    )
                """
                ).bindparams(table_name=table_name, search_term=f"%{term}%")

                term_filter.append(student_search_sql)

        conditions.append(or_(*term_filter))

    return query.filter(and_(*conditions))


@library_bp.route('/books/manage')
@login_required
def manage_books():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('search', '')
    
    query = Book.query
    
    if search_query:
        search = f"%{search_query}%"
        query = query.filter(or_(
            Book.title.ilike(search),
            Book.author.ilike(search),
            Book.isbn.ilike(search),
            Book.publisher.ilike(search)
        ))
    
    books = query.order_by(Book.title).paginate(
        page=page,
        per_page=10,
        error_out=False
    )
    
    if request.headers.get('HX-Request'):  # For AJAX requests
        return render_template(
            'library/manage_books_table.html',  # Create this partial template
            books=books,
            search_query=search_query
        )
    
    return render_template(
        'library/manage_books.html',
        books=books,
        search_query=search_query
    )


@library_bp.route("/books/add", methods=["GET", "POST"])
@librarian_required
def add_book():
    errors = {}
    if request.method == "POST":
        try:
            title = request.form.get("title")
            author = request.form.get("author")
            isbn = request.form.get("isbn")
            publisher = request.form.get("publisher")
            publication_year = request.form.get("publication_year")
            genre = request.form.get("genre")
            total_copies_str = request.form.get("total_copies", "1")

            # --- Input Validation ---
            if not title:
                errors["title"] = "Title is required."
            if not author:
                errors["author"] = "Author is required."

            try:
                total_copies = int(total_copies_str)
                if total_copies < 0:
                    errors["total_copies"] = "Total Copies cannot be negative."
            except (ValueError, TypeError):
                errors["total_copies"] = "Total Copies must be a valid number."
                total_copies = -1 # Mark as invalid

            pub_year_int = None
            if publication_year:
                try:
                    pub_year_int = int(publication_year)
                    current_year = datetime.utcnow().year
                    if (
                        pub_year_int < 1000 or pub_year_int > current_year + 1
                    ):
                        errors[
                            "publication_year"
                        ] = f"Publication Year seems invalid (1000 - {current_year + 1})."
                except (ValueError, TypeError):
                    errors[
                        "publication_year"
                    ] = "Publication Year must be a valid number."

            clean_isbn = isbn.strip() if isbn else None
            if clean_isbn and Book.query.filter(
                Book.isbn == clean_isbn, Book.is_active == True
            ).first():
                errors[
                    "isbn"
                ] = f"An active book with ISBN {clean_isbn} already exists."

            # Handle cover photo upload
            cover_photo_path = None
            if 'cover_photo' in request.files:
                cover_photo = request.files['cover_photo']
                if cover_photo and cover_photo.filename:
                    if not allowed_file(cover_photo.filename):
                        errors["cover_photo"] = "Invalid file format. Only PNG, JPG, JPEG, GIF allowed."
                    else:
                        # Check file size
                        cover_photo.seek(0, os.SEEK_END)
                        size = cover_photo.tell()
                        if size > MAX_FILE_SIZE:
                            errors["cover_photo"] = "File size exceeds 5MB limit."
                        else:
                            cover_photo.seek(0)
                            filename = generate_secure_filename(cover_photo.filename)
                            os.makedirs(COVER_UPLOAD_FOLDER, exist_ok=True)
                            cover_photo.save(os.path.join(COVER_UPLOAD_FOLDER, filename))
                            cover_photo_path = filename

            if errors:
                for field, msg in errors.items():
                    flash(msg, "danger")
                return render_template(
                    "library/add_edit_book.html",
                    form_action="Add",
                    form=request.form,
                    errors=errors,
                )
            # --- End Validation ---

            new_book = Book(
                title=title.strip(),
                author=author.strip(),
                isbn=clean_isbn,
                publisher=publisher.strip() if publisher else None,
                publication_year=pub_year_int,
                genre=genre.strip() if genre else None,
                total_copies=total_copies,
                available_copies=total_copies,
                is_active=True, # Explicitly set active on add
                cover_photo=cover_photo_path,
            )
            db.session.add(new_book)
            db.session.commit()
            flash("Book added successfully!", "success")
            logger.info(
                f"Book added: '{new_book.title}' by {new_book.author} (ID: {new_book.id}) by User: {current_user.email}"
            )
            return redirect(url_for("library.manage_books"))

        except sqlalchemy_exc.SQLAlchemyError as db_err:
            db.session.rollback()
            flash(f"Database error adding book: {db_err}", "danger")
            logger.error(f"Database error adding book: {db_err}", exc_info=True)
            return render_template(
                "library/add_edit_book.html",
                form_action="Add",
                form=request.form,
                errors=errors,
            )
        except Exception as e:
            db.session.rollback()
            flash(f"An unexpected error occurred: {str(e)}", "danger")
            logger.error(f"Error adding book: {str(e)}", exc_info=True)
            return render_template(
                "library/add_edit_book.html",
                form_action="Add",
                form=request.form,
                errors=errors,
            )

    # GET request
    return render_template("library/add_edit_book.html", form_action="Add", errors={})


@library_bp.route("/books/edit/<int:book_id>", methods=["GET", "POST"])
@librarian_required
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    if not book.is_active:
        flash("Cannot edit an inactive book.", "warning")
        return redirect(url_for("library.manage_books"))

    errors = {}
    if request.method == "POST":
        try:
            original_total = book.total_copies
            original_available = book.available_copies
            original_isbn = book.isbn

            # Get data from form
            title = request.form.get("title")
            author = request.form.get("author")
            isbn = request.form.get("isbn")
            publisher = request.form.get("publisher")
            publication_year = request.form.get("publication_year")
            genre = request.form.get("genre")
            total_copies_str = request.form.get("total_copies")

            # --- Input Validation ---
            if not title:
                errors["title"] = "Title is required."
            if not author:
                errors["author"] = "Author is required."

            new_total_copies = -1 # Default to invalid
            try:
                new_total_copies = int(total_copies_str)
                if new_total_copies < 0:
                    errors["total_copies"] = "Total Copies cannot be negative."
            except (ValueError, TypeError):
                errors["total_copies"] = "Total Copies must be a valid number."

            pub_year_int = None
            if publication_year:
                try:
                    pub_year_int = int(publication_year)
                    current_year = datetime.utcnow().year
                    if (
                        pub_year_int < 1000 or pub_year_int > current_year + 1
                    ):
                        errors[
                            "publication_year"
                        ] = f"Publication Year seems invalid (1000 - {current_year + 1})."
                except (ValueError, TypeError):
                    errors[
                        "publication_year"
                    ] = "Publication Year must be a valid number."

            clean_isbn = isbn.strip() if isbn else None
            if clean_isbn and clean_isbn != original_isbn:
                existing_book = Book.query.filter(
                    Book.isbn == clean_isbn,
                    Book.id != book_id,
                    Book.is_active == True,
                ).first()
                if existing_book:
                    errors[
                        "isbn"
                    ] = f"Another active book with ISBN {clean_isbn} already exists."

            issued_count = original_total - original_available
            if new_total_copies >= 0 and new_total_copies < issued_count:
                errors[
                    "total_copies"
                ] = f"Cannot set total copies ({new_total_copies}) less than currently issued ({issued_count})."

            # Handle cover photo upload
            cover_photo_path = book.cover_photo  # Keep existing path by default
            if 'cover_photo' in request.files:
                cover_photo = request.files['cover_photo']
                if cover_photo and cover_photo.filename:
                    if not allowed_file(cover_photo.filename):
                        errors["cover_photo"] = "Invalid file format. Only PNG, JPG, JPEG, GIF allowed."
                    else:
                        # Check file size
                        cover_photo.seek(0, os.SEEK_END)
                        size = cover_photo.tell()
                        if size > MAX_FILE_SIZE:
                            errors["cover_photo"] = "File size exceeds 5MB limit."
                        else:
                            cover_photo.seek(0)
                            
                            # Delete old cover photo if it exists
                            if book.cover_photo:
                                old_photo_path = os.path.join(COVER_UPLOAD_FOLDER, book.cover_photo)
                                try:
                                    if os.path.exists(old_photo_path):
                                        os.remove(old_photo_path)
                                        logger.info(f"Deleted old cover photo: {old_photo_path}")
                                except Exception as e:
                                    logger.error(f"Error deleting old cover photo {old_photo_path}: {e}")

                            # Save new cover photo
                            filename = generate_secure_filename(cover_photo.filename)
                            os.makedirs(COVER_UPLOAD_FOLDER, exist_ok=True)
                            cover_photo.save(os.path.join(COVER_UPLOAD_FOLDER, filename))
                            cover_photo_path = filename
                            logger.info(f"Saved new cover photo: {filename}")

            if errors:
                for field, msg in errors.items():
                    flash(msg, "danger")
                # Pre-fill form with attempted values for correction
                book.title = title
                book.author = author
                book.isbn = isbn # Keep raw form value for redisplay
                book.publisher = publisher
                book.publication_year = publication_year # Keep raw form value
                book.genre = genre
                # Don't update copy counts yet
                return render_template(
                    "library/add_edit_book.html",
                    book=book,
                    form_action="Edit",
                    errors=errors,
                    form=request.form, # Pass form data back
                )
            # --- End Validation ---

            # Update book attributes only if validation passed
            book.title = title.strip()
            book.author = author.strip()
            book.isbn = clean_isbn
            book.publisher = publisher.strip() if publisher else None
            book.publication_year = pub_year_int
            book.genre = genre.strip() if genre else None
            book.total_copies = new_total_copies
            # Recalculate available copies based on potentially new total
            book.available_copies = (
                new_total_copies - issued_count
            )  # Relies on check above
            book.cover_photo = cover_photo_path

            db.session.commit()
            flash("Book updated successfully!", "success")
            logger.info(
                f"Book updated: '{book.title}' (ID: {book.id}) by User: {current_user.email}"
            )
            return redirect(url_for("library.manage_books"))

        except sqlalchemy_exc.SQLAlchemyError as db_err:
            db.session.rollback()
            flash(f"Database error updating book: {db_err}", "danger")
            logger.error(
                f"Database error updating book {book_id}: {db_err}", exc_info=True
            )
            # Refetch original state for form redisplay
            book = Book.query.get(book_id)
            return render_template(
                "library/add_edit_book.html",
                book=book,
                form_action="Edit",
                errors=errors,
                form=request.form,
            )
        except Exception as e:
            db.session.rollback()
            flash(f"An unexpected error occurred: {str(e)}", "danger")
            logger.error(f"Error updating book {book_id}: {str(e)}", exc_info=True)
            book = Book.query.get(book_id)  # Refetch original state
            return render_template(
                "library/add_edit_book.html",
                book=book,
                form_action="Edit",
                errors=errors,
                form=request.form,
            )

    # GET request
    return render_template(
        "library/add_edit_book.html", book=book, form_action="Edit", errors={}
    )


@library_bp.route("/books/delete/<int:book_id>", methods=["POST"])
@librarian_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    try:
        # Check for active issues before deactivating
        active_issues = BookIssue.query.filter_by(
            book_id=book_id, is_returned=False
        ).count()
        if active_issues > 0:
            flash(
                f'Cannot deactivate "{book.title}". It has {active_issues} active issue(s). Return them first.',
                "danger",
            )
            return redirect(url_for("library.manage_books"))

        # Soft delete: Mark as inactive
        book.is_active = False
        book.available_copies = 0  # Explicitly set to 0 when inactive
        db.session.commit()
        flash(f'Book "{book.title}" marked as inactive.', "success")
        logger.warning(
            f"Book soft-deleted (inactive): '{book.title}' (ID: {book.id}) by User: {current_user.email}"
        )

    except sqlalchemy_exc.SQLAlchemyError as db_err:
        db.session.rollback()
        flash(f"Database error deactivating book: {db_err}", "danger")
        logger.error(
            f"Database error deleting book {book_id}: {db_err}", exc_info=True
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Error deactivating book: {str(e)}", "danger")
        logger.error(f"Error deleting book {book_id}: {str(e)}", exc_info=True)

    return redirect(url_for("library.manage_books"))


# --- Book Issuing Workflow ---


@library_bp.route("/issue")
@librarian_required
def issue_book_select_batch():
    try:
        courses = (
            db.session.query(BatchTable.course_id, BatchTable.course_name)
            .distinct()
            .order_by(BatchTable.course_name)
            .all()
        )
    except Exception as e:
        logger.error(
            f"Error fetching courses for issue batch selection: {e}", exc_info=True
        )
        flash("Error loading course data.", "danger")
        courses = []
    return render_template("library/issue_select_batch.html", courses=courses)


@library_bp.route("/issue/students")
@librarian_required
def issue_book_select_student():
    course_id = request.args.get("course_id")
    admission_year = request.args.get("admission_year")
    semester = request.args.get("semester")
    batch_id_param = request.args.get("batch_id")

    # --- Input Validation ---
    errors = []
    if not course_id:
        errors.append("Course selection is missing.")
    if not admission_year:
        errors.append("Admission Year selection is missing.")
    if not semester:
        errors.append("Semester selection is missing.")
    if not batch_id_param:
        errors.append("Batch ID selection is missing.")

    if errors:
        for error in errors:
            flash(error, "warning")
        return redirect(url_for("library.issue_book_select_batch"))
    # --- End Validation ---

    try:
        # Get the batch info
        batch_info = BatchTable.query.filter_by(
            course_id=course_id,
            admission_year=admission_year,
            semester=semester,
            batch_id=batch_id_param,
        ).first()

        if not batch_info:
            flash("Selected batch configuration not found.", "danger")
            return redirect(url_for("library.issue_book_select_batch"))

        # Get the table name from batch_info
        table_name = batch_info.table_name

        # Updated query with proper roll number sorting
        student_query = text(f"""
            SELECT 
                id,
                first_name,
                last_name,
                email,
                phone,
                roll_number
            FROM {table_name}
            ORDER BY CAST(REGEXP_REPLACE(roll_number, '[^0-9]', '') AS UNSIGNED), roll_number
        """)

        students = []
        results = db.session.execute(student_query)
        
        for row in results:
            students.append({
                "id": row.id,
                "first_name": row.first_name,
                "last_name": row.last_name,
                "email": row.email,
                "phone_number": row.phone,
                "roll_number": row.roll_number,
                "table_name": table_name  # Include table_name for the URL
            })

        return render_template(
            "library/issue_select_student.html",
            students=students,
            batch_info=batch_info
        )

    except Exception as e:
        logger.error(f"Error fetching students: {e}", exc_info=True)
        flash("Error retrieving student list.", "danger")
        return redirect(url_for("library.issue_book_select_batch"))




def get_issued_books(student_id_in_table, table_name):
    """Helper to get list of books currently issued to a student."""
    try:
        issues = (
            BookIssue.query.filter_by(
                student_id_in_table=student_id_in_table,
                student_table_name=table_name,
                is_returned=False,
            )
            .options(db.joinedload(BookIssue.book)) # Eager load book info
            .order_by(BookIssue.issue_date.desc())
            .all()
        )
        # Return list of tuples containing (issue, book) pairs
        return [(issue, issue.book) for issue in issues]
    except Exception as e:
        logger.error(
            f"Error fetching issued books for student {student_id_in_table} from table {table_name}: {e}",
            exc_info=True,
        )
        return []


def get_student_details_from_dynamic_table(table_name, student_id_in_table):
    """Fetches student details from a dynamic batch table and joins with BatchTable for course info."""
    try:
        # Basic table name format validation
        if not table_name or not table_name.startswith("student_batch_"):
            logger.error(f"Invalid table name format requested: {table_name}")
            flash("Invalid request: Malformed table name.", "danger")
            return None

        # Ensure student_id is a positive integer
        if not isinstance(student_id_in_table, int) or student_id_in_table <= 0:
            logger.error(f"Invalid student ID format requested: {student_id_in_table}")
            flash("Invalid request: Malformed student ID.", "danger")
            return None

        # First get student details from dynamic table
        student_query = text(f"""
            SELECT 
                s.id,
                s.first_name,
                s.last_name,
                s.email,
                s.roll_number,
                s.phone,
                s.course_id,
                s.current_year,
                s.admission_year,
                s.batch_id,
                s.semester
            FROM {table_name} s
            WHERE s.id = :student_id
        """)
        
        student_result = db.session.execute(student_query, {"student_id": student_id_in_table}).fetchone()
        
        if not student_result:
            logger.warning(f"Student not found in table {table_name} with ID {student_id_in_table}")
            return None

        # Get course details from BatchTable
        batch_info = BatchTable.query.filter_by(
            table_name=table_name,
            course_id=student_result.course_id,
            admission_year=student_result.admission_year,
            semester=student_result.semester,
            batch_id=student_result.batch_id
        ).first()

        return {
            "id": student_result.id,
            "full_name": f"{student_result.first_name} {student_result.last_name}",
            "first_name": student_result.first_name,
            "last_name": student_result.last_name,
            "email": student_result.email,
            "roll_number": student_result.roll_number,
            "phone": student_result.phone,
            "course_id": student_result.course_id,
            "course_name": batch_info.course_name if batch_info else "Unknown Course",
            "course_code": batch_info.course_code if batch_info else "N/A",
            "semester": student_result.semester,
            "current_year": student_result.current_year,
            "batch_id": student_result.batch_id
        }

    except sqlalchemy_exc.ProgrammingError as e:
        logger.error(f"Database error fetching student details: {e}")
        if "exist" in str(e).lower() or "unknown table" in str(e).lower():
            flash(f"Error: The student table '{table_name}' could not be found.", "danger")
        else:
            flash(f"Database error accessing student table '{table_name}'.", "danger")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching student details: {e}", exc_info=True)
        flash("An unexpected error occurred while fetching student details.", "danger")
        return None


@library_bp.route(
    "/student/<string:table_name>/<int:student_id_in_table>",
    methods=["GET", "POST"],
)
@librarian_required
def student_detail_issue(table_name, student_id_in_table):
    """View and manage book issues for a specific student."""
    try:
        # Use the new function to get student details
        student_details = get_student_details_from_dynamic_table(table_name, student_id_in_table)
        
        if not student_details:
            flash("Student not found.", "danger")
            return redirect(url_for("library.issue_book_select_batch"))

        # Get current book issues
        current_issues = get_issued_books(student_id_in_table, table_name)

        # Pass table_name separately since it's not in student_details
        return render_template(
            "library/student_detail_issue.html",
            student=student_details,
            issued_books=current_issues,
            has_overdue_books=any(issue.is_overdue for issue, _ in current_issues),
            table_name=table_name,  # Pass table_name separately
            student_id=student_details['id']  # Use the id from student_details
        )

    except Exception as e:
        logger.error(f"Error in student_detail_issue: {e}", exc_info=True)
        flash("Error retrieving student details.", "danger")
        return redirect(url_for("library.issue_book_select_batch"))


def send_grouped_overdue_notification(student_info, overdue_issues):
    """Sends a single email for multiple overdue books."""
    if not overdue_issues or not student_info or not student_info.get('email'):
        logger.warning("Skipping notification: Missing issues or student email.")
        return 0

    overdue_books_details = [
        {
            "title": issue.book.title,
            "due_date": issue.due_date.strftime("%Y-%m-%d"),
            "days_overdue": (datetime.utcnow() - issue.due_date).days,
        }
        for issue in overdue_issues
    ]

    if not overdue_books_details:
        return 0

    subject = f"Library Notice: {len(overdue_books_details)} Overdue {'Book' if len(overdue_books_details) == 1 else 'Books'}"

    try:
        # Direct database insert instead of using Celery task
        email_id = EmailService.send_email(
            to_email=student_info["email"],
            subject=subject,
            template_name="library/email/overdue_notification.html",
            context={
                "student_name": student_info.get("full_name", "Student"),
                "overdue_books": overdue_books_details,
            },
            # Single student notifications get higher priority
            priority=EmailService.PRIORITY_NORMAL if len(overdue_books_details) == 1 else EmailService.PRIORITY_LOW
        )
        
        return len(overdue_books_details) if email_id else -1
        
    except Exception as e:
        logger.error(
            f"Failed to queue grouped overdue email to {student_info['email']}: {e}",
            exc_info=True,
        )
        return -1


@library_bp.route(
    "/notify/student/all-overdue/<string:table_name>/<int:student_id_in_table>",
    methods=["POST"],
)
@librarian_required
def notify_student_all_overdue(table_name, student_id_in_table):
    redirect_url = url_for(
        "library.student_detail_issue",
        table_name=table_name,
        student_id_in_table=student_id_in_table,
    )
    try:
        student_info = get_student_details_from_dynamic_table(
            table_name, student_id_in_table
        )
        if not student_info or not student_info.get("email"):
            flash("Cannot send notification: Student email not found.", "danger")
            return redirect(redirect_url)

        current_time = datetime.utcnow()
        overdue_issues = (
            BookIssue.query.filter(
                BookIssue.student_table_name == table_name,
                BookIssue.student_id_in_table == student_id_in_table,
                BookIssue.is_returned == False,
                BookIssue.due_date < current_time,
            )
            .options(db.joinedload(BookIssue.book)) # Eager load book
            .all()
        )

        if not overdue_issues:
            flash("No overdue books found for this student.", "info")
            return redirect(redirect_url)

        result = send_grouped_overdue_notification(student_info, overdue_issues)

        if result > 0:
            flash(
                f"Overdue notification sent successfully for {result} books to {student_info['email']}.",
                "success",
            )
            logger.info(
                f"Grouped overdue notification sent to student {student_id_in_table} ({student_info['email']}) from {table_name} for {result} books"
            )
        elif result == 0:
            flash("No overdue books found or notification could not be prepared.", "info")
        else:
            flash("Failed to send overdue notification email. Check logs.", "danger")

    except Exception as e:
        flash(f"Error sending notifications: {str(e)}", "danger")
        logger.error(
            f"Error sending grouped notification to student {student_id_in_table} from {table_name}: {e}",
            exc_info=True,
        )

    return redirect(redirect_url)


# --- Book Returns & Issued List (Main View) ---


@library_bp.route("/issued")
@librarian_required
def view_issued_books():
    show_returned = request.args.get("show_returned", "false") == "true"
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 20

    query = BookIssue.query.join(Book, BookIssue.book_id == Book.id).options(
        db.joinedload(BookIssue.book) # Eager load book
    )

    if not show_returned:
        query = query.filter(BookIssue.is_returned == False)

    if search_query:
        query = build_book_search_query(
            query, search_query, include_student_search=True
        )

    issues_pagination = query.order_by(BookIssue.issue_date.desc()).paginate(
        page=page, per_page=per_page
    )

    enriched_issues = []
    # Batch fetch student details if performance becomes an issue
    for issue in issues_pagination.items:
        student_info = get_student_details_from_dynamic_table(
            issue.student_table_name, issue.student_id_in_table
        )
        student_name = "Student Info Unavailable"
        student_email = "N/A"
        if student_info:
            student_name = student_info.get(
                "full_name", f"Student ID {issue.student_id_in_table}"
            )
            student_email = student_info.get("email", "N/A")

        enriched_issues.append(
            {
                "issue": issue,
                "student_name": student_name,
                "student_email": student_email,
                "book_title": issue.book.title if issue.book else "Book Title Unavailable",
                "book_author": issue.book.author if issue.book else "Author Unavailable",
            }
        )

    return render_template(
        "library/issued_books.html",
        issues_pagination=issues_pagination,
        enriched_issues=enriched_issues,
        show_returned=show_returned,
        search_query=search_query,
    )

@library_bp.route('/books/available')
@librarian_required
def available_books():
    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10

    query = Book.query.filter(
        Book.is_active == True,
        Book.available_copies > 0
    )

    query = build_book_search_query(query, search_query) # Use the same search builder
    books_pagination = query.order_by(Book.title).paginate(page=page, per_page=per_page)

    return render_template('library/available_books.html',
                           books=books_pagination, # Renamed for clarity
                           search_query=search_query)


@library_bp.route("/return/<int:issue_id>", methods=["POST"])
@librarian_required
def return_book(issue_id):
    # Use with_for_update for issue and book if race conditions are a concern
    # issue = BookIssue.query.with_for_update().get(issue_id)
    issue = BookIssue.query.get(issue_id)
    redirect_url = request.referrer or url_for("library.view_issued_books")

    if not issue:
        flash("Issue record not found.", "danger")
        return redirect(redirect_url)

    if issue.is_returned:
        flash("This book has already been returned.", "warning")
        return redirect(redirect_url)

    # book = Book.query.with_for_update().get(issue.book_id)
    book = Book.query.get(issue.book_id)
    if not book:
        # This case should ideally not happen due to foreign key constraints
        # But good to handle defensively.
        flash("Associated book data missing. Cannot process return.", "danger")
        logger.error(
            f"Book with ID {issue.book_id} not found for issue ID {issue_id}"
        )
        # Don't modify the issue state if book is missing
        return redirect(redirect_url)

    try:
        issue.is_returned = True
        issue.return_date = datetime.utcnow()

        # Only increment available copies if the book is still active
        if book.is_active:
            # Prevent available_copies exceeding total_copies
            if book.available_copies < book.total_copies:
                book.available_copies += 1
            else:
                # Log this inconsistency
                logger.warning(
                    f"Book ID {book.id}: available_copies ({book.available_copies}) "
                    f"already at or above total_copies ({book.total_copies}) "
                    f"before return of issue {issue.id}. Not incrementing."
                )
        else:
            logger.warning(
                f"Book ID {book.id} is inactive. Not incrementing available copies on return of issue ID {issue.id}."
            )

        # Optional: Calculate and store fine if needed
        # fine = calculate_fine(issue) # Assuming a calculate_fine function exists
        # issue.fine_paid = 0 # Or based on payment status
        # if fine > 0:
        #     flash(f"Fine of ${fine:.2f} applicable.", "info")

        db.session.commit()
        flash(f'Book "{book.title}" marked as returned successfully.', "success")
        logger.info(
            f"Book Returned: '{book.title}' (ID: {book.id}), Issue ID: {issue.id} by User: {current_user.email}"
        )

    except sqlalchemy_exc.SQLAlchemyError as db_err:
        db.session.rollback()
        flash(f"Database error returning book: {db_err}", "danger")
        logger.error(
            f"Database error returning book for issue {issue_id}: {db_err}",
            exc_info=True,
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Error processing book return: {str(e)}", "danger")
        logger.error(
            f"Error returning book for issue {issue_id}: {e}", exc_info=True
        )

    return redirect(redirect_url)


# --- Overdue Management & Notifications ---


@library_bp.route("/overdue")
@librarian_required
def view_overdue_books():
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 20

    current_time = datetime.utcnow()

    query = (
        BookIssue.query.join(Book, BookIssue.book_id == Book.id)
        .options(db.joinedload(BookIssue.book))
        .filter(BookIssue.is_returned == False, BookIssue.due_date < current_time)
    )

    if search_query:
        query = build_book_search_query(
            query, search_query, include_student_search=True
        )

    overdue_pagination = query.order_by(BookIssue.due_date.asc()).paginate(
        page=page, per_page=per_page
    )

    enriched_overdue = enrich_overdue_data(overdue_pagination.items)

    if request.headers.get('HX-Request'):  # For AJAX requests
        return render_template(
            "library/overdue_books_table.html",  # Create this partial template
            overdue_pagination=overdue_pagination,
            enriched_overdue=enriched_overdue,
            search_query=search_query
        )

    return render_template(
        "library/overdue_books.html",
        overdue_pagination=overdue_pagination,
        enriched_overdue=enriched_overdue,
        search_query=search_query
    )


@library_bp.route("/notify/overdue/<int:issue_id>", methods=["POST"])
@librarian_required
def notify_single_overdue(issue_id):
    redirect_url = request.referrer or url_for("library.view_overdue_books")
    try:
        issue = BookIssue.query.options(db.joinedload(BookIssue.book)).get(issue_id) # Eager load book

        if not issue:
            flash(f"Issue record ID {issue_id} not found.", "danger")
            return redirect(redirect_url)
        if issue.is_returned:
            flash("Cannot send notification, book is already returned.", "warning")
            return redirect(redirect_url)
        if not issue.is_overdue:
            flash("Book is not overdue.", "info")
            return redirect(redirect_url)
        if not issue.book:
             flash("Associated book data missing. Cannot send notification.", "danger")
             logger.error(f"Book missing for overdue issue ID {issue_id}")
             return redirect(redirect_url)


        student_info = get_student_details_from_dynamic_table(
            issue.student_table_name, issue.student_id_in_table
        )
        if not student_info or not student_info.get("email"):
            flash(
                f"Could not find student email for issue ID {issue_id}. Cannot send notification.",
                "danger",
            )
            logger.warning(
                f"Missing student email for notification, issue ID: {issue_id}"
            )
            return redirect(redirect_url)

        # Use the grouped notification logic even for a single book
        result = send_grouped_overdue_notification(student_info, [issue])

        if result > 0:
            flash(f"Overdue notification sent successfully to {student_info['email']}.", "success")
            logger.info(
                f"Overdue notification sent for Issue ID: {issue_id} to {student_info['email']}"
            )
        elif result == 0:
             flash("Notification could not be prepared.", "warning")
        else:
            flash("Failed to send overdue notification email. Check logs.", "danger")


    except Exception as e:
        flash(f"Error sending notification: {str(e)}", "danger")
        logger.error(
            f"Error sending notification for issue {issue_id}: {e}", exc_info=True
        )

    return redirect(redirect_url)


@library_bp.route("/notify/overdue/all", methods=["POST"])
@librarian_required
def notify_all_overdue():
    sent_student_count = 0
    failed_student_count = 0
    total_books_notified = 0
    try:
        current_time = datetime.utcnow()
        overdue_issues = (
            BookIssue.query.filter(
                BookIssue.is_returned == False,
                BookIssue.due_date < current_time
            )
            .options(db.joinedload(BookIssue.book))
            .all()
        )

        if not overdue_issues:
            flash("No overdue books found to notify.", "info")
            return redirect(url_for("library.view_overdue_books"))

        # Group overdue books by student
        student_overdue_map = {}
        for issue in overdue_issues:
            key = (issue.student_table_name, issue.student_id_in_table)
            if key not in student_overdue_map:
                student_overdue_map[key] = []
            student_overdue_map[key].append(issue)

        # Prepare bulk emails
        bulk_emails = []
        for (table_name, student_id), issues_for_student in student_overdue_map.items():
            try:
                student_info = get_student_details_from_dynamic_table(
                    table_name, student_id
                )
                if not student_info or not student_info.get("email"):
                    logger.warning(
                        f"Skipping notification: No email found for student {student_id} in {table_name}"
                    )
                    failed_student_count += 1
                    continue

                overdue_books_details = [
                    {
                        "title": issue.book.title,
                        "due_date": issue.due_date.strftime("%Y-%m-%d"),
                        "days_overdue": (datetime.utcnow() - issue.due_date).days,
                    }
                    for issue in issues_for_student
                ]

                subject = f"Library Notice: {len(overdue_books_details)} Overdue Books"

                bulk_emails.append({
                    'to_email': student_info['email'],
                    'subject': subject,
                    'template_name': "library/email/overdue_notification.html",
                    'context': {
                        "student_name": student_info.get("full_name", "Student"),
                        "overdue_books": overdue_books_details,
                    },
                    'priority': EmailService.PRIORITY_BULK  # Use bulk priority for mass notifications
                })

                total_books_notified += len(overdue_books_details)
                sent_student_count += 1

            except Exception as e:
                logger.error(f"Error preparing notification for student {student_id}: {e}")
                failed_student_count += 1
                continue

        if bulk_emails:
            # Send all emails in bulk
            try:
                EmailService.send_bulk_emails(bulk_emails)
                flash(
                    f"Queued overdue notifications for {sent_student_count} students ({total_books_notified} books total).",
                    "success",
                )
            except Exception as e:
                flash("Failed to queue bulk notifications. Check logs.", "danger")
                logger.error(f"Bulk email queueing failed: {e}", exc_info=True)
        else:
            flash("No notifications were queued.", "warning")

        if failed_student_count > 0:
            flash(f"Failed to prepare notifications for {failed_student_count} students.", "warning")

    except Exception as e:
        flash(f"Error processing notifications: {str(e)}", "danger")
        logger.error("Error in notify_all_overdue", exc_info=True)
    process_email_queue.delay()
    return redirect(url_for("library.view_overdue_books"))


# --- API Endpoints for Cascading Dropdowns ---


@library_bp.route("/api/lib-courses")
@librarian_required
def api_get_lib_courses():
    try:
        # Fetch distinct course info used in BatchTable
        courses = (
            db.session.query(
                BatchTable.course_id,
                BatchTable.course_name,
                BatchTable.course_code,
            )
            .distinct()
            .order_by(BatchTable.course_name)
            .all()
        )
        return jsonify(
            [
                {"id": c.course_id, "name": c.course_name, "code": c.course_code}
                for c in courses
            ]
        )
    except Exception as e:
        logger.error(f"API Error fetching lib courses: {e}", exc_info=True)
        return jsonify({"error": "Could not fetch courses"}), 500


@library_bp.route("/api/lib-years")
@librarian_required
def api_get_lib_years():
    course_id = request.args.get("course_id")
    if not course_id:
        return jsonify([])
    try:
        # Fetch distinct admission years for the given course_id from BatchTable
        years = (
            db.session.query(BatchTable.admission_year)
            .filter(BatchTable.course_id == course_id)
            .distinct()
            .order_by(desc(BatchTable.admission_year))
            .all()
        )
        # years is a list of tuples like [(2023,), (2022,)]
        return jsonify([y[0] for y in years])
    except Exception as e:
        logger.error(
            f"API Error fetching lib years for course {course_id}: {e}",
            exc_info=True,
        )
        return jsonify({"error": "Could not fetch years"}), 500


@library_bp.route("/api/lib-semesters")
@librarian_required
def api_get_lib_semesters():
    course_id = request.args.get("course_id")
    admission_year = request.args.get("admission_year")
    if not course_id or not admission_year:
        return jsonify([])
    try:
        # Fetch distinct semesters for the given course and year from BatchTable
        semesters = (
            db.session.query(BatchTable.semester)
            .filter(
                BatchTable.course_id == course_id,
                BatchTable.admission_year == admission_year,
            )
            .distinct()
            .order_by(asc(BatchTable.semester))
            .all()
        )
        # semesters is a list of tuples like [(1,), (2,)]
        return jsonify([s[0] for s in semesters])
    except Exception as e:
        logger.error(
            f"API Error fetching lib semesters for course {course_id}, year {admission_year}: {e}",
            exc_info=True,
        )
        return jsonify({"error": "Could not fetch semesters"}), 500


@library_bp.route("/api/lib-batches")
@librarian_required
def api_get_lib_batches():
    course_id = request.args.get("course_id")
    admission_year = request.args.get("admission_year")
    semester = request.args.get("semester")
    if not course_id or not admission_year or not semester:
        return jsonify([])
    try:
        # Fetch distinct batch_ids (1-5) for the given course, year, sem from BatchTable
        batches = (
            db.session.query(BatchTable.batch_id)
            .filter(
                BatchTable.course_id == course_id,
                BatchTable.admission_year == admission_year,
                BatchTable.semester == semester,
            )
            .distinct()
            .order_by(asc(BatchTable.batch_id))
            .all()
        )
        # batches is a list of tuples like [(1,), (2,)]
        return jsonify([b[0] for b in batches])
    except Exception as e:
        logger.error(
            f"API Error fetching lib batches for course {course_id}, year {admission_year}, sem {semester}: {e}",
            exc_info=True,
        )
        return jsonify({"error": "Could not fetch batches"}), 500


# --- Book Issue with Search ---
@library_bp.route('/api/search-books')
@librarian_required
def search_available_books():
    search_query = request.args.get('q', '').strip()
    try:
        query = Book.query.filter(
            Book.is_active == True,
            Book.available_copies > 0
        )
        
        if search_query:
            search_terms = search_query.lower().split()
            conditions = []
            for term in search_terms:
                conditions.append(or_(
                    func.lower(Book.title).like(f'%{term}%'),
                    func.lower(Book.author).like(f'%{term}%'),
                    func.lower(Book.isbn).like(f'%{term}%')
                ))
            query = query.filter(or_(*conditions))
        
        books = query.order_by(Book.title).limit(10).all()
        
        return jsonify([{
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'isbn': book.isbn or 'N/A',
            'available_copies': book.available_copies,
            'cover_photo': url_for('library.get_cover_photo', filename=book.cover_photo) if book.cover_photo else None
        } for book in books])
    except Exception as e:
        logger.error(f"Error in book search API: {e}", exc_info=True)
        return jsonify({'error': 'Search failed'}), 500

@library_bp.route('/issue-book/<string:table_name>/<int:student_id>', methods=['GET', 'POST'])
@librarian_required
def issue_book(table_name, student_id):
    if request.method == 'POST':
        book_id = request.form.get('book_id')
        due_date = request.form.get('due_date')
        
        if not all([book_id, due_date]):
            flash('Book and due date are required.', 'danger')
            return redirect(request.referrer)
            
        try:
            book = Book.query.filter_by(id=book_id, is_active=True).first()
            if not book:
                flash('Selected book not found.', 'danger')
                return redirect(request.referrer)
                
            if book.available_copies <= 0:
                flash('No copies available for this book.', 'danger')
                return redirect(request.referrer)
                
            # Create new issue record
            new_issue = BookIssue(
                book_id=book_id,
                student_table_name=table_name,
                student_id_in_table=student_id,
                librarian_credential_id=current_user.id,
                issue_date=datetime.utcnow(),
                due_date=datetime.strptime(due_date, '%Y-%m-%d')
            )
            
            # Update available copies
            book.available_copies -= 1
            
            db.session.add(new_issue)
            db.session.commit()
            
            flash(f'Book "{book.title}" issued successfully!', 'success')
            return redirect(url_for('library.student_detail_issue', 
                                  table_name=table_name, 
                                  student_id_in_table=student_id))
                                  
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error issuing book: {e}", exc_info=True)
            flash('Error issuing book. Please try again.', 'danger')
            return redirect(request.referrer)
    
    # GET request - render form
    student_info = get_student_details_from_dynamic_table(table_name, student_id)
    if not student_info:
        flash('Student not found.', 'danger')
        return redirect(url_for('library.manage_books'))
        
    return render_template('library/issue_book.html',
                         student_info=student_info,
                         table_name=table_name,
                         student_id=student_id)


@library_bp.route("/cover_photo/<path:filename>")
def get_cover_photo(filename):
    """Serve book cover photos"""
    if not filename:
        return abort(404)
    try:
        full_path = os.path.join(COVER_UPLOAD_FOLDER, filename)
        logger.debug(f"Attempting to serve cover photo from: {full_path}")
        if not os.path.exists(full_path):
            logger.error(f"Cover photo file not found: {full_path}")
            return abort(404)
        return send_from_directory(COVER_UPLOAD_FOLDER, filename)
    except Exception as e:
        logger.error(f"Error serving cover photo {filename}: {e}")
        return abort(404)


# --- END OF FILE library.py ---
def enrich_overdue_data(overdue_issues):
    """
    Enriches overdue book issues with student and book information.
    """
    enriched_issues = []
    
    for issue in overdue_issues:
        try:
            # Get student details
            student_info = get_student_details_from_dynamic_table(
                issue.student_table_name, 
                issue.student_id_in_table
            )
            
            # Set default values
            student_name = "Student Info Unavailable"
            student_email = "N/A"
            
            # Update with actual values if available
            if student_info:
                student_name = student_info.get('full_name', f"Student ID {issue.student_id_in_table}")
                student_email = student_info.get('email', "N/A")

            # Create enriched data dictionary
            enriched_data = {
                'issue': issue,
                'book_title': issue.book.title if issue.book else "Unknown Book",
                'student_name': student_name,
                'student_email': student_email
            }
            
            enriched_issues.append(enriched_data)
            
        except Exception as e:
            logger.error(f"Error enriching data for issue {issue.id}: {e}", exc_info=True)
            # Add error placeholder
            enriched_issues.append({
                'issue': issue,
                'book_title': issue.book.title if issue.book else "Unknown Book",
                'student_name': "Error Loading Student Info",
                'student_email': "N/A"
            })
    
    return enriched_issues
