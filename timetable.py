from extensions import db
from models import UserCredentials, TeacherDetails, StudentDetails, AdminProfile, HODProfile, SubjectAssignment, Course, \
    CourseSubject, Attendance, BatchTable
from sqlalchemy import inspect, or_, text
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from flask_login import login_required, current_user
import random
import mysql.connector
import json
import io
import csv
from datetime import datetime
import copy
import multiprocessing
import math
import time
from functools import partial
from flask import Blueprint

timetable_bp = Blueprint('timetable', __name__, template_folder='templates/timetable')


def get_course_map():
    # Fetch all courses from the database
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    query = ("""
        SELECT id, name FROM courses
    """)
    cursor.execute(query)
    courses = cursor.fetchall()
    print(courses)
    # Create a dictionary to map course_id to course_name
    course_map = {str(course['id']): course['name'] for course in courses}
    print(course_map)
    return course_map


def format_batch_string(course_id, year, semester, batch_id):
    """
    Creates a consistently formatted batch string from components.
    Ensures all components are strings with proper spacing.
    """
    return f"{str(course_id)},{str(year)}, {str(semester)}, {str(batch_id)}"


def parse_batch_string(batch_string):
    """
    Parses a batch string into its components.
    Returns (course_id, year, semester, batch_id) as strings.
    """
    try:
        parts = batch_string.split(',')
        course_id = parts[0].strip()
        year = parts[1].strip()
        semester = parts[2].strip()
        batch_id = parts[3].strip()
        return course_id, year, semester, batch_id
    except Exception as e:
        print(f"Error parsing batch string '{batch_string}': {str(e)}")
        # Return default values or raise exception based on your preference
        return None, None, None, None


# Database connection function
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="toor",
        database="xyz"
    )


# Fetch subjects and teachers from the database
def fetch_subjects_and_teachers():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    query = """
    SELECT 
        sa.course_subject_id, 
        cs.subject_code, cs.subject_name, cs.year, cs.semester, cs.batch_id, cs.course_id, cs.is_active, cs.created_at,
        td.first_name, td.last_name, td.email, td.phone, td.department, td.appointment_date, td.photo_path
    FROM subject_assignments sa
    JOIN course_subjects cs ON sa.course_subject_id = cs.id
    JOIN teacher_details td ON sa.teacher_id = td.id
    WHERE cs.is_active = 1
    """
    cursor.execute(query)
    result = cursor.fetchall()

    # Get periods configuration from the database
    subject_periods = fetch_subject_periods()

    subjects = {}
    for row in result:
        subject_name = row['subject_name']
        teacher_name = f"{row['first_name']} {row['last_name']}"

        # Use the consistent format_batch_string function
        batch_name = format_batch_string(
            row['course_id'],
            row['year'],
            row['semester'],
            row['batch_id']
        )

        subject_code = row['subject_code']
        course_subject_id = row['course_subject_id']
        teacher_details = {
            "name": teacher_name,
            "email": row['email'],
            "phone": row['phone'],
            "department": row['department'],
            "appointment_date": row['appointment_date'],
            "photo_path": row['photo_path']
        }

        if batch_name not in subjects:
            subjects[batch_name] = {}

        if subject_name not in subjects[batch_name]:
            # Use saved periods if available, otherwise use defaults
            if course_subject_id in subject_periods:
                max_periods_per_day = subject_periods[course_subject_id]['max_periods_per_day']
                max_periods_per_week = subject_periods[course_subject_id]['max_periods_per_week']
            else:
                # Default values if no configuration exists
                max_periods_per_day = 1
                max_periods_per_week = 3

            subjects[batch_name][subject_name] = {
                "subject_code": subject_code,
                "course_subject_id": course_subject_id,
                "teachers": [],
                "details": {
                    "course_id": row['course_id'],
                    "created_at": row['created_at']
                },
                "constraints": {
                    "max_periods_per_day": max_periods_per_day,
                    "max_periods_per_week": max_periods_per_week
                }
            }

        subjects[batch_name][subject_name]["teachers"].append(teacher_details)

    cursor.close()
    db.close()
    return subjects


# Timetable configuration
days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
periods_per_day = 7


# Generate initial population with empty slots allowed
def generate_initial_population(subjects, batches, population_size):
    population = []
    for _ in range(population_size):
        timetable = {batch: {day: [""] * periods_per_day for day in days} for batch in batches}
        for batch in batches:
            # Initialize subject weekly counters
            subject_counters = {subject: 0 for subject in subjects[batch]}

            # First pass: try to assign subjects without exceeding constraints
            for day in days:
                # Shuffle periods to randomize initial assignments
                period_indices = list(range(periods_per_day))
                random.shuffle(period_indices)

                for period in period_indices:
                    # Randomly decide if this period should be assigned or left empty
                    if random.random() < 0.8:  # 80% chance of assignment
                        # Find eligible subjects (not exceeding weekly limit)
                        eligible_subjects = [
                            sub for sub in subjects[batch]
                            if subject_counters[sub] < subjects[batch][sub]["constraints"]["max_periods_per_week"]
                        ]

                        if eligible_subjects:
                            subject = random.choice(eligible_subjects)
                            teacher = random.choice(subjects[batch][subject]["teachers"])["name"]
                            timetable[batch][day][period] = f"{subject} ({teacher})"
                            subject_counters[subject] += 1

        population.append(timetable)
    return population


# Fitness function with updated scoring to prefer consecutive classes and respect max periods
def fitness(timetable, subjects, batches):
    penalty = 0
    teacher_schedule = {teacher["name"]: {day: [""] * periods_per_day for day in days} for batch in subjects for sub in
                        subjects[batch] for teacher in subjects[batch][sub]["teachers"]}

    for batch in batches:
        subject_weekly_count = {sub: 0 for sub in subjects[batch]}  # Track weekly count

        # First check weekly limits
        for day in days:
            daily_subject_count = {sub: 0 for sub in subjects[batch]}
            for period in range(periods_per_day):
                entry = timetable[batch][day][period]
                if entry:  # Skip empty periods
                    subject, teacher = entry.rsplit(" (", 1)
                    teacher = teacher.rstrip(")")

                    # Count subject occurrences
                    daily_subject_count[subject] += 1
                    subject_weekly_count[subject] += 1

                    # Enforce max periods per day
                    max_periods_per_day = subjects[batch][subject]["constraints"]["max_periods_per_day"]
                    if daily_subject_count[subject] > max_periods_per_day:
                        penalty += 50  # Higher penalty for exceeding daily limit

                    # Check teacher conflicts
                    if teacher_schedule[teacher][day][period] != "":
                        penalty += 100  # Very high penalty for teacher conflicts
                    else:
                        teacher_schedule[teacher][day][period] = batch

        # Check weekly limits and penalize severely if exceeded
        for subject, count in subject_weekly_count.items():
            max_periods_per_week = subjects[batch][subject]["constraints"]["max_periods_per_week"]
            if count > max_periods_per_week:
                penalty += 200 * (count - max_periods_per_week)  # Severe penalty for exceeding weekly limits

        # Reward consecutive periods for the same subject
        for day in days:
            for period in range(periods_per_day - 1):
                current_entry = timetable[batch][day][period]
                next_entry = timetable[batch][day][period + 1]

                if current_entry and next_entry:  # Both periods have assignments
                    current_subject = current_entry.split(" (")[0]
                    next_subject = next_entry.split(" (")[0]

                    if current_subject == next_subject:
                        penalty -= 2  # Reward consecutive classes of the same subject

        # Small penalty for empty periods surrounded by non-empty ones (gaps)
        for day in days:
            for period in range(1, periods_per_day - 1):
                prev_entry = timetable[batch][day][period - 1]
                current_entry = timetable[batch][day][period]
                next_entry = timetable[batch][day][period + 1]

                if (prev_entry and next_entry) and not current_entry:
                    penalty += 1  # Small penalty for isolated empty periods

    return penalty


# Selection function
def selection(population, subjects, batches):
    # Tournament selection
    tournament_size = 3
    selected = []

    for _ in range(2):  # Select 2 parents
        tournament = random.sample(population, min(tournament_size, len(population)))
        winner = min(tournament, key=lambda x: fitness(x, subjects, batches))
        selected.append(winner)

    return selected


# Crossover function
def crossover(parent1, parent2, batches):
    child = {batch: {day: [""] * periods_per_day for day in days} for batch in batches}

    for batch in batches:
        # For each batch, randomly choose which days to inherit from which parent
        for day in days:
            if random.random() < 0.5:
                # Inherit full day from parent1
                child[batch][day] = parent1[batch][day].copy()
            else:
                # Inherit full day from parent2
                child[batch][day] = parent2[batch][day].copy()

    return child


# Mutation function with respect to constraints
def mutate(timetable, subjects, batches, mutation_rate):
    for batch in batches:
        # Check current subject counts
        subject_count = {subject: 0 for subject in subjects[batch]}

        # Count current occurrences
        for day in days:
            for period in range(periods_per_day):
                entry = timetable[batch][day][period]
                if entry:
                    subject = entry.split(" (")[0]
                    subject_count[subject] += 1

        # Mutation that respects weekly limits
        for day in days:
            for period in range(periods_per_day):
                if random.random() < mutation_rate:
                    # 25% chance to clear a period
                    if random.random() < 0.25:
                        timetable[batch][day][period] = ""
                    else:
                        # Find subjects that haven't reached weekly limit
                        available_subjects = [
                            sub for sub in subjects[batch]
                            if subject_count[sub] < subjects[batch][sub]["constraints"]["max_periods_per_week"]
                        ]

                        if available_subjects:
                            # Select a subject that hasn't reached its limit
                            subject = random.choice(available_subjects)
                            teacher = random.choice(subjects[batch][subject]["teachers"])["name"]

                            # If this period already had a subject, decrement its count
                            if timetable[batch][day][period]:
                                old_subject = timetable[batch][day][period].split(" (")[0]
                                subject_count[old_subject] -= 1

                            # Assign new subject and increment its count
                            timetable[batch][day][period] = f"{subject} ({teacher})"
                            subject_count[subject] += 1

    return timetable


# Final optimization function to improve timetable quality
def optimize_timetable(timetable, subjects, batches):
    """
    Apply local optimization to improve the timetable by fixing specific issues
    """
    if not timetable:
        return timetable

    # Make a deep copy to avoid modifying the original
    optimized = copy.deepcopy(timetable)

    # 1. Distribute subjects more evenly across the week
    for batch in batches:
        # Count subjects per day
        daily_subjects = {day: {} for day in days}

        for day in days:
            for period in range(periods_per_day):
                entry = optimized[batch][day][period]
                if entry:
                    subject = entry.split(" (")[0]
                    if subject not in daily_subjects[day]:
                        daily_subjects[day][subject] = 0
                    daily_subjects[day][subject] += 1

        # Find days with too many of the same subject
        for day in days:
            for subject, count in daily_subjects[day].items():
                if count > 2:  # If more than 2 periods of same subject in a day
                    # Find a day with fewer instances of this subject
                    target_days = [d for d in days if d != day and (
                            subject not in daily_subjects[d] or daily_subjects[d].get(subject, 0) < 2)]

                    if target_days:
                        target_day = random.choice(target_days)

                        # Find a period with this subject on the original day
                        for period in range(periods_per_day):
                            entry = optimized[batch][day][period]
                            if entry and entry.split(" (")[0] == subject:
                                # Find an empty period on the target day
                                for target_period in range(periods_per_day):
                                    if not optimized[batch][target_day][target_period]:
                                        # Move the subject
                                        optimized[batch][target_day][target_period] = entry
                                        optimized[batch][day][period] = ""

                                        # Update counts
                                        daily_subjects[day][subject] -= 1
                                        if subject not in daily_subjects[target_day]:
                                            daily_subjects[target_day][subject] = 0
                                        daily_subjects[target_day][subject] += 1

                                        break

                                # Only move one instance per iteration
                                if daily_subjects[day][subject] <= 2:
                                    break

    # 2. Minimize gaps in the schedule
    for batch in batches:
        for day in days:
            # Find gaps (empty periods between classes)
            periods_with_classes = [p for p in range(periods_per_day) if optimized[batch][day][p]]

            if periods_with_classes:
                first_class = min(periods_with_classes)
                last_class = max(periods_with_classes)

                # Check for gaps
                for period in range(first_class, last_class + 1):
                    if not optimized[batch][day][period]:
                        # Try to fill this gap by moving a class from the end
                        if last_class < periods_per_day - 1:
                            for p in range(periods_per_day - 1, last_class, -1):
                                if optimized[batch][day][p]:
                                    # Move this class to fill the gap
                                    optimized[batch][day][period] = optimized[batch][day][p]
                                    optimized[batch][day][p] = ""
                                    last_class = max([i for i in range(periods_per_day) if optimized[batch][day][i]])
                                    break

    # 3. Check for teacher conflicts and resolve them
    teacher_schedule = {}

    # Build teacher schedule
    for batch in batches:
        for day in days:
            for period in range(periods_per_day):
                entry = optimized[batch][day][period]
                if entry:
                    teacher = entry.split(" (")[1][:-1]  # Remove the closing parenthesis
                    key = (day, period)

                    if key not in teacher_schedule:
                        teacher_schedule[key] = {}

                    if teacher not in teacher_schedule[key]:
                        teacher_schedule[key][teacher] = []

                    teacher_schedule[key][teacher].append((batch, entry))

    # Resolve conflicts
    for (day, period), teachers in teacher_schedule.items():
        for teacher, assignments in teachers.items():
            if len(assignments) > 1:
                # Teacher has multiple classes at the same time
                # Keep one assignment and move others
                kept = assignments[0]
                to_move = assignments[1:]

                for batch, entry in to_move:
                    subject = entry.split(" (")[0]

                    # Try to find an alternative teacher for this subject
                    alt_teachers = [t["name"] for t in subjects[batch][subject]["teachers"] if t["name"] != teacher]

                    if alt_teachers:
                        # Assign alternative teacher
                        new_teacher = random.choice(alt_teachers)
                        optimized[batch][day][period] = f"{subject} ({new_teacher})"
                    else:
                        # No alternative teacher, try to move to another period
                        moved = False

                        # Try to find an empty slot on the same day
                        for alt_period in range(periods_per_day):
                            if alt_period != period and not optimized[batch][day][alt_period]:
                                optimized[batch][day][alt_period] = entry
                                optimized[batch][day][period] = ""
                                moved = True
                                break

                        if not moved:
                            # Try another day
                            for alt_day in days:
                                if alt_day != day:
                                    for alt_period in range(periods_per_day):
                                        if not optimized[batch][alt_day][alt_period]:
                                            optimized[batch][alt_day][alt_period] = entry
                                            optimized[batch][day][period] = ""
                                            moved = True
                                            break

                                    if moved:
                                        break

    return optimized


# Main GA function with parallel processing and simulated annealing
def create_timetable(population_size=10, generations=100, mutation_rate=0.1, elite_size=2):
    subjects = fetch_subjects_and_teachers()
    batches = list(subjects.keys())

    if not batches:
        return None, "No active batches found in the database."

    # Use multiprocessing for initial population generation if population size is large enough
    if population_size >= 10 and multiprocessing.cpu_count() > 1:
        try:
            # Create a pool with number of processors
            num_processes = min(multiprocessing.cpu_count(), 4)  # Limit to 4 processes max
            pool = multiprocessing.Pool(processes=num_processes)

            # Split the work
            chunk_size = max(1, population_size // num_processes)
            if population_size % chunk_size == 0:
                chunks = [chunk_size] * (population_size // chunk_size)
            else:
                chunks = [chunk_size] * (population_size // chunk_size) + [population_size % chunk_size]

            # Create partial function with fixed parameters
            partial_generate = partial(generate_chunk, subjects=subjects, batches=batches)

            # Generate population in parallel
            population_chunks = pool.map(partial_generate, chunks)
            pool.close()
            pool.join()

            # Combine chunks
            population = []
            for chunk in population_chunks:
                population.extend(chunk)
        except Exception as e:
            print(f"Parallel processing failed: {str(e)}. Falling back to sequential processing.")
            population = generate_initial_population(subjects, batches, population_size)
    else:
        population = generate_initial_population(subjects, batches, population_size)

    best_fitness = float('inf')
    best_timetable = None
    best_generation = 0
    stagnation_counter = 0

    # For adaptive parameters
    initial_mutation_rate = mutation_rate
    current_temperature = 100.0  # Initial temperature for simulated annealing
    cooling_rate = 0.95  # Cooling rate for simulated annealing

    for generation in range(1, generations + 1):
        # Evaluate and sort population by fitness
        population_with_fitness = [(timetable, fitness(timetable, subjects, batches)) for timetable in population]
        population_with_fitness.sort(key=lambda x: x[1])  # Sort by fitness (lower is better)

        # Extract sorted population and keep track of best solution
        sorted_population = [item[0] for item in population_with_fitness]
        current_best = sorted_population[0]
        current_fitness = population_with_fitness[0][1]

        # Update best solution if improved
        if current_fitness < best_fitness:
            best_fitness = current_fitness
            best_timetable = current_best
            best_generation = generation
            stagnation_counter = 0
        else:
            stagnation_counter += 1

        # Apply elitism - keep the best solutions
        elites = sorted_population[:elite_size]

        # Create new population with crossover and mutation
        new_population = elites.copy()  # Start with elites

        # Calculate adaptive mutation rate that decreases over generations
        # but increases if we're stuck in local optima
        if stagnation_counter > 5:
            # Increase mutation rate if stuck to explore more
            adaptive_mutation_rate = min(0.5, initial_mutation_rate * (1 + 0.1 * stagnation_counter))
        else:
            adaptive_mutation_rate = initial_mutation_rate * (1 - 0.5 * (generation / generations))

        # Update simulated annealing temperature
        current_temperature *= cooling_rate

        # Fill the rest of the population with new offspring
        while len(new_population) < population_size:
            # Selection
            parent1, parent2 = selection(sorted_population, subjects, batches)

            # Crossover
            child = improved_crossover(parent1, parent2, batches)

            # Mutation
            child = mutate(child, subjects, batches, adaptive_mutation_rate)

            # Apply simulated annealing to accept or reject based on temperature
            child_fitness = fitness(child, subjects, batches)
            worst_elite_fitness = fitness(elites[-1], subjects, batches)

            # If child is better than worst elite, or passes the simulated annealing probability test
            if child_fitness < worst_elite_fitness or random.random() < math.exp(
                    (worst_elite_fitness - child_fitness) / current_temperature):
                new_population.append(child)
            else:
                # If rejected, add a slightly modified version of an elite
                elite_to_modify = random.choice(elites)
                modified_elite = mutate(copy.deepcopy(elite_to_modify), subjects, batches, adaptive_mutation_rate * 0.5)
                new_population.append(modified_elite)

        population = new_population

        # Early termination if we've reached a perfect solution
        if best_fitness <= 0:
            break

        # Apply restart mechanism if stuck for too long
        if stagnation_counter > 15:
            print(f"Restarting at generation {generation} due to stagnation")
            # Keep the elites and regenerate the rest
            new_random_population = generate_initial_population(subjects, batches, population_size - elite_size)
            population = elites + new_random_population
            stagnation_counter = 0
            current_temperature = 50.0  # Reset temperature partially

    # Final optimization to ensure constraints are strictly met
    best_timetable = optimize_timetable(best_timetable, subjects, batches)

    # Apply constraint satisfaction improvements
    best_timetable = enforce_hard_constraints(best_timetable, subjects, batches)

    return best_timetable, batches, subjects


# Helper function for parallel processing
def generate_chunk(chunk_size, subjects, batches):
    return generate_initial_population(subjects, batches, chunk_size)


# Enhanced constraint enforcement function
def enforce_hard_constraints(timetable, subjects, batches):
    """
    Enforce hard constraints that must be satisfied in the final timetable
    """
    if not timetable:
        return timetable

    # Make a deep copy to avoid modifying the original
    enforced = copy.deepcopy(timetable)

    # Track teacher assignments
    teacher_schedule = {}

    # First pass: identify all teacher conflicts
    conflicts = []

    for batch in batches:
        for day in days:
            for period in range(periods_per_day):
                entry = enforced[batch][day][period]
                if not entry:
                    continue

                if isinstance(entry, str):
                    # Parse the string format "Subject (Teacher)"
                    try:
                        subject, teacher = entry.rsplit(' (', 1)
                        teacher = teacher.rstrip(')')
                    except ValueError:
                        continue
                else:
                    # Handle dictionary format
                    subject = entry.get('subject_name', '')
                    teacher = entry.get('teacher_name', '')

                # Create a key for this time slot
                time_key = (day, period)

                if time_key not in teacher_schedule:
                    teacher_schedule[time_key] = {}

                if teacher not in teacher_schedule[time_key]:
                    teacher_schedule[time_key][teacher] = []

                teacher_schedule[time_key][teacher].append((batch, subject))

                # If this teacher has multiple assignments at this time
                if len(teacher_schedule[time_key][teacher]) > 1:
                    conflicts.append((time_key, teacher, teacher_schedule[time_key][teacher]))

    # Second pass: resolve conflicts
    for (day, period), teacher, conflict_assignments in conflicts:
        # Keep the first assignment and move others
        kept_assignment = conflict_assignments[0]
        to_move = conflict_assignments[1:]

        for batch, subject in to_move:
            # Try to find alternative teachers for this subject
            if batch in subjects and subject in subjects[batch]:
                alt_teachers = [t["name"] for t in subjects[batch][subject]["teachers"] if t["name"] != teacher]
                if alt_teachers:
                    # Assign alternative teacher
                    new_teacher = random.choice(alt_teachers)
                    enforced[batch][day][period] = f"{subject} ({new_teacher})"
                else:
                    # No alternative teacher, try to move to another period
                    # First, clear this assignment
                    enforced[batch][day][period] = ""

                    # Try to find an empty slot
                    moved = False

                    # Try same day first
                    for alt_period in range(periods_per_day):
                        if alt_period != period and not enforced[batch][day][alt_period]:
                            enforced[batch][day][alt_period] = f"{subject} ({teacher})"
                            moved = True
                            break

                    # If not moved, try other days
                    if not moved:
                        for alt_day in days:
                            if alt_day != day:
                                for alt_period in range(periods_per_day):
                                    if not enforced[batch][alt_day][alt_period]:
                                        enforced[batch][alt_day][alt_period] = f"{subject} ({teacher})"
                                        moved = True
                                        break
                            if moved:
                                break

    # Third pass: check subject constraints (max periods per day/week)
    for batch in batches:
        if batch not in subjects:
            continue

        # Track subject occurrences
        subject_count = {day: {subject: 0 for subject in subjects[batch]} for day in days}
        subject_total = {subject: 0 for subject in subjects[batch]}

        # Count occurrences
        for day in days:
            for period in range(periods_per_day):
                entry = enforced[batch][day][period]
                if not entry:
                    continue

                if isinstance(entry, str):
                    subject = entry.split(" (")[0]
                else:
                    subject = entry.get('subject_name', '')

                if subject in subject_count[day]:
                    subject_count[day][subject] += 1
                    subject_total[subject] += 1

        # Fix violations
        for day in days:
            for subject in subjects[batch]:
                max_per_day = subjects[batch][subject]["constraints"]["max_periods_per_day"]

                # If too many in a day, remove excess
                while subject_count[day][subject] > max_per_day:
                    # Find a period with this subject and remove it
                    for period in range(periods_per_day - 1, -1, -1):  # Start from the end
                        entry = enforced[batch][day][period]
                        if not entry:
                            continue

                        current_subject = entry.split(" (")[0] if isinstance(entry, str) else entry.get('subject_name',
                                                                                                        '')

                        if current_subject == subject:
                            enforced[batch][day][period] = ""
                            subject_count[day][subject] -= 1
                            subject_total[subject] -= 1
                            break

        # Check weekly totals
        for subject in subjects[batch]:
            max_per_week = subjects[batch][subject]["constraints"]["max_periods_per_week"]

            # If too many in a week, remove excess
            while subject_total[subject] > max_per_week:
                # Find a day with the most of this subject
                max_day = max(days, key=lambda d: subject_count[d][subject])

                # Find a period with this subject and remove it
                for period in range(periods_per_day - 1, -1, -1):  # Start from the end
                    entry = enforced[batch][max_day][period]
                    if not entry:
                        continue

                    current_subject = entry.split(" (")[0] if isinstance(entry, str) else entry.get('subject_name', '')

                    if current_subject == subject:
                        enforced[batch][max_day][period] = ""
                        subject_count[max_day][subject] -= 1
                        subject_total[subject] -= 1
                        break

    return enforced


# Analyze timetable
def analyze_timetable(timetable, subjects, batches):
    analysis = {}

    for batch in batches:
        # Skip if the batch is not in the timetable
        if batch not in timetable:
            continue

        # Try to find the corresponding batch in subjects
        subject_batch = batch
        if batch not in subjects:
            # Try to find a matching batch with different formatting
            batch_parts = parse_batch_string(batch)
            if None in batch_parts:
                continue  # Skip this batch if parsing fails

            for sb in subjects.keys():
                sb_parts = parse_batch_string(sb)
                if None in sb_parts:
                    continue

                # Compare the components
                if batch_parts == sb_parts:
                    subject_batch = sb
                    break

            # If we still can't find it, skip this batch
            if subject_batch not in subjects:
                continue

        analysis[batch] = {
            "subjects": {},
            "empty_periods": 0
        }

        subject_counts = {subject: {"daily": {day: 0 for day in days}, "total": 0}
                          for subject in subjects[subject_batch]}

        empty_count = 0

        for day in days:
            for period in range(periods_per_day):
                entry = timetable[batch][day][period]
                if entry:
                    # Extract subject name safely
                    try:
                        if " (" in entry and ")" in entry:
                            subject, _ = entry.rsplit(" (", 1)

                            # Check if this subject exists in the subjects dictionary
                            if subject in subject_counts:
                                subject_counts[subject]["daily"][day] += 1
                                subject_counts[subject]["total"] += 1
                            else:
                                # Unknown subject
                                print(f"Unknown subject in timetable: {subject}")
                        else:
                            print(f"Invalid entry format: {entry}")
                    except Exception as e:
                        print(f"Error processing entry {entry}: {str(e)}")
                else:
                    empty_count += 1

        analysis[batch]["empty_periods"] = empty_count

        for subject, counts in subject_counts.items():
            try:
                constraints = subjects[subject_batch][subject]["constraints"]
                analysis[batch]["subjects"][subject] = {
                    "weekly_total": counts["total"],
                    "max_weekly": constraints["max_periods_per_week"],
                    "daily_counts": {},
                    "compliant": True
                }

                for day in days:
                    daily_count = counts["daily"][day]
                    max_daily = constraints["max_periods_per_day"]
                    is_compliant = daily_count <= max_daily
                    if not is_compliant:
                        analysis[batch]["subjects"][subject]["compliant"] = False

                    analysis[batch]["subjects"][subject]["daily_counts"][day] = {
                        "count": daily_count,
                        "max": max_daily,
                        "compliant": is_compliant
                    }
            except Exception as e:
                print(f"Error analyzing subject {subject}: {str(e)}")
                # Skip this subject

    return analysis


# Routes
@timetable_bp.route('/render_timetable')
@login_required
def render_timetable():
    if current_user.role != 'hod' and current_user.role != 'admin':
        flash('Access  denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    return render_template('index.html')


@timetable_bp.route('/generate', methods=['POST'])
@login_required
def generate():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin pr HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    # Get form parameters with defaults
    population_size = int(request.form.get('population_size', 10))
    generations = int(request.form.get('generations', 100))
    mutation_rate = float(request.form.get('mutation_rate', 0.1))
    elite_size = max(2, int(population_size * 0.2))  # 20% of population, minimum 2

    # Record start time for performance tracking
    start_time = time.time()

    # Create timetable with improved algorithm
    timetable, batches, subjects = create_timetable(
        population_size=population_size,
        generations=generations,
        mutation_rate=mutation_rate,
        elite_size=elite_size
    )

    # Calculate generation time
    generation_time = time.time() - start_time

    if isinstance(batches, str):
        # Error message
        return render_template('index.html', error=batches)

    # Analyze the timetable
    analysis = analyze_timetable(timetable, subjects, batches)

    # Get course map for displaying course names
    course_map = get_course_map()

    # Save timetable, batches, and analysis to session
    session['timetable'] = json.dumps(timetable)
    session['batches'] = json.dumps(batches)
    session['analysis'] = json.dumps(analysis)
    session['course_map'] = json.dumps(course_map)

    algorithm_info = {
        'population_size': population_size,
        'generations': generations,
        'mutation_rate': mutation_rate,
        'elite_size': elite_size,
        'generation_time': f"{generation_time:.2f} seconds",
        'improvements': [
            'Elitism: Preserves the best solutions across generations',
            'Adaptive Mutation: Decreases mutation rate over time for fine-tuning',
            'Intelligent Crossover: Uses multiple strategies to preserve good patterns',
            'Local Optimization: Distributes subjects evenly and minimizes gaps',
            'Parallel Processing: Utilizes multiple CPU cores for faster generation',
            'Simulated Annealing: Helps escape local optima for better solutions',
            'Constraint Enforcement: Ensures all hard constraints are satisfied'
        ]
    }

    # Store algorithm info in session
    session['algorithm_info'] = algorithm_info

    return render_template(
        'results.html',
        timetable=timetable,
        batches=batches,
        days=days,
        periods_per_day=periods_per_day,
        analysis=analysis,
        algorithm_info=algorithm_info,
        course_map=course_map
    )


def fetch_all_subjects():
    """Fetch all active subjects from the database with their details"""
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    query = """
    SELECT 
        cs.id, cs.subject_code, cs.subject_name, cs.year, cs.semester, 
        cs.batch_id, cs.course_id, cs.is_active, cs.created_at
    FROM course_subjects cs
    WHERE cs.is_active = 1
    ORDER BY cs.year, cs.semester, cs.batch_id, cs.subject_name
    """
    cursor.execute(query)
    subjects = cursor.fetchall()

    cursor.close()
    db.close()
    return subjects


def fetch_subject_periods():
    """Fetch period configurations for all subjects"""
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    query = """
    SELECT 
        sp.id, sp.course_subject_id, sp.max_periods_per_day, sp.max_periods_per_week,
        sp.created_at, sp.updated_at
    FROM subject_periods sp
    """
    cursor.execute(query)
    results = cursor.fetchall()

    # Convert to dictionary for easy access by subject ID
    periods_dict = {}
    for row in results:
        periods_dict[row['course_subject_id']] = {
            'max_periods_per_day': row['max_periods_per_day'],
            'max_periods_per_week': row['max_periods_per_week'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }

    cursor.close()
    db.close()
    return periods_dict


def save_subject_periods(subject_id, max_periods_per_day, max_periods_per_week):
    """Save or update period configuration for a subject"""
    db = get_db_connection()
    cursor = db.cursor()

    # Check if entry exists
    check_query = "SELECT id FROM subject_periods WHERE course_subject_id = %s"
    cursor.execute(check_query, (subject_id,))
    result = cursor.fetchone()

    try:
        if result:
            # Update existing entry
            update_query = """
            UPDATE subject_periods 
            SET max_periods_per_day = %s, max_periods_per_week = %s 
            WHERE course_subject_id = %s
            """
            cursor.execute(update_query, (max_periods_per_day, max_periods_per_week, subject_id))
        else:
            # Create new entry
            insert_query = """
            INSERT INTO subject_periods (course_subject_id, max_periods_per_day, max_periods_per_week)
            VALUES (%s, %s, %s)
            """
            cursor.execute(insert_query, (subject_id, max_periods_per_day, max_periods_per_week))

        db.commit()
        success = True
    except Exception as e:
        db.rollback()
        print(f"Database error: {e}")
        success = False
    finally:
        cursor.close()
        db.close()

    return success


# Modify your existing fetch_subjects_and_teachers function to use the configured periods


# Add these new routes to your Flask application
@timetable_bp.route('/configure_periods')
@login_required
def configure_periods():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    """Render the subject periods configuration page"""
    subjects = fetch_all_subjects()
    subject_periods = fetch_subject_periods()
    course_map = get_course_map()  # Get the course map

    # Group subjects by batch
    batches = {}
    for subject in subjects:
        batch_key = f"{subject['course_id']},{subject['year']}, {subject['semester']}, {subject['batch_id']}"

        if batch_key not in batches:
            batches[batch_key] = []

        # Add period info if available, otherwise use defaults
        if subject['id'] in subject_periods:
            subject['max_periods_per_day'] = subject_periods[subject['id']]['max_periods_per_day']
            subject['max_periods_per_week'] = subject_periods[subject['id']]['max_periods_per_week']
        else:
            subject['max_periods_per_day'] = 1  # Default value
            subject['max_periods_per_week'] = 3  # Default value

        batches[batch_key].append(subject)

    return render_template('configure_periods.html', batches=batches, course_map=course_map)


@timetable_bp.route('/save_periods', methods=['POST'])
@login_required
def save_periods():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    """Save the period configuration for subjects"""
    if request.method == 'POST':
        processed_subjects = set()

        for key, value in request.form.items():
            if key.startswith('subject_'):
                parts = key.split('_')
                if len(parts) == 3 and parts[2] in ['day', 'week']:
                    subject_id = int(parts[1])

                    # Process each subject only once
                    if subject_id not in processed_subjects:
                        processed_subjects.add(subject_id)

                        # Get both values
                        day_key = f'subject_{subject_id}_day'
                        week_key = f'subject_{subject_id}_week'

                        if day_key in request.form and week_key in request.form:
                            try:
                                max_day = int(request.form[day_key])
                                max_week = int(request.form[week_key])

                                # Validate the input
                                if max_day < 1:
                                    max_day = 1
                                if max_day > 7:
                                    max_day = 7
                                if max_week < max_day:
                                    max_week = max_day
                                if max_week > 35:
                                    max_week = 35

                                # Save to database
                                save_subject_periods(subject_id, max_day, max_week)
                            except ValueError:
                                # Handle invalid input
                                continue

        return redirect(url_for('configure_periods', success=True))


# Add this new route to app.py
@timetable_bp.route('/save_timetable', methods=['POST'])
@login_required
def save_timetable():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
        
    try:
        batch_name = request.form.get('batch_name', '')
        timetable_data_str = request.form.get('timetable_data', '{}')

        try:
            timetable_data = json.loads(timetable_data_str)
        except json.JSONDecodeError as json_err:
            return render_template('index.html', error=f"Invalid timetable data format: {str(json_err)}")

        if not batch_name or not timetable_data:
            return redirect(url_for('timetable.render_timetable', error="No batch or timetable data received"))

        batch_parts = parse_batch_string(batch_name)
        if None in batch_parts:
            return redirect(url_for('timetable.render_timetable', error=f"Invalid batch format: {batch_name}"))

        course_id, year, semester, batch_id = batch_parts

        db = get_db_connection()
        cursor = db.cursor(buffered=True)  # Use buffered cursor

        try:
            # Delete existing entries for this batch
            cursor.execute("""
                DELETE FROM timetable_assignments 
                WHERE course_id = %s AND year = %s AND semester = %s AND batch_id = %s
            """, (course_id, year, semester, batch_id))
            db.commit()  # Commit the delete operation

            for day, day_data in timetable_data.items():
                for period, entry in enumerate(day_data):
                    if not entry or " (" not in entry or ")" not in entry:
                        continue

                    subject, teacher = entry.rsplit(' (', 1)
                    teacher = teacher.rstrip(')')

                    # Get subject_id
                    cursor.execute("""
                        SELECT cs.id 
                        FROM course_subjects cs 
                        WHERE cs.subject_name = %s AND cs.course_id = %s 
                        AND cs.year = %s AND cs.semester = %s 
                        AND cs.batch_id = %s AND cs.is_active = 1
                    """, (subject, course_id, year, semester, batch_id))
                    subject_result = cursor.fetchone()
                    if not subject_result:
                        continue
                    subject_id = subject_result[0]

                    # Get teacher_id
                    cursor.execute("""
                        SELECT td.id 
                        FROM teacher_details td 
                        WHERE CONCAT(td.first_name, ' ', td.last_name) = %s
                    """, (teacher,))
                    teacher_result = cursor.fetchone()
                    if not teacher_result:
                        continue
                    teacher_id = teacher_result[0]

                    # Insert assignment
                    cursor.execute("""
                        INSERT INTO timetable_assignments 
                        (course_id, year, semester, batch_id, day, period, subject_id, teacher_id, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (course_id, year, semester, batch_id, day, period, subject_id, teacher_id))

            db.commit()
            return redirect(url_for('timetable.view_saved_timetable'))

        finally:
            cursor.close()
            db.close()

    except Exception as e:
        if 'db' in locals():
            db.rollback()
            db.close()
        return render_template('index.html', error=f"Error saving timetable: {str(e)}")


@timetable_bp.route('/view_saved_timetable')
@login_required
def view_saved_timetable():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    """Retrieve and display the saved timetable"""
    try:
        # Connect to the database
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Get unique batches
        batch_query = """
        SELECT DISTINCT course_id, year, semester, batch_id 
        FROM timetable_assignments
        ORDER BY year, semester, batch_id
        """
        cursor.execute(batch_query)
        batch_results = cursor.fetchall()

        if not batch_results:
            # Instead of using saved_timetable.html, use index.html with a message
            return render_template('index.html',
                                   message="No saved timetable found. Please generate a new timetable.")

        # Build batch strings - ensure consistent formatting
        batches = []
        for batch in batch_results:
            # Convert all values to strings to avoid type issues
            course_id = str(batch['course_id'])
            year = str(batch['year'])
            semester = str(batch['semester'])
            batch_id = str(batch['batch_id'])
            batch_str = f"{course_id},{year}, {semester}, {batch_id}"
            batches.append(batch_str)

        # Initialize timetable structure
        timetable = {batch: {day: [""] * periods_per_day for day in days} for batch in batches}

        # Get timetable assignments
        assignment_query = """
        SELECT 
            ta.course_id, ta.year, ta.semester, ta.batch_id, ta.day, ta.period,
            cs.subject_name, CONCAT(td.first_name, ' ', td.last_name) as teacher_name
        FROM timetable_assignments ta
        JOIN course_subjects cs ON ta.subject_id = cs.id
        JOIN teacher_details td ON ta.teacher_id = td.id
        ORDER BY ta.year, ta.semester, ta.batch_id, FIELD(ta.day, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'), ta.period
        """
        cursor.execute(assignment_query)
        assignments = cursor.fetchall()

        # Fill the timetable with consistent string formatting
        for assignment in assignments:
            # Convert all values to strings to ensure consistency
            course_id = str(assignment['course_id'])
            year = str(assignment['year'])
            semester = str(assignment['semester'])
            batch_id = str(assignment['batch_id'])
            batch_str = f"{course_id},{year}, {semester}, {batch_id}"

            day = assignment['day']
            period = assignment['period']
            subject = assignment['subject_name']
            teacher = assignment['teacher_name']

            # Make sure period is an integer index
            period_idx = int(period)
            if 0 <= period_idx < periods_per_day:
                timetable[batch_str][day][period_idx] = f"{subject} ({teacher})"

        cursor.close()
        db.close()

        # Get success message from session
        success_message = session.pop('success_message', None)

        # Get subjects for analysis
        subjects = fetch_subjects_and_teachers()

        # Get course map for displaying course names
        course_map = get_course_map()

        # Try to analyze the timetable, if possible
        try:
            analysis = analyze_timetable(timetable, subjects, batches)
        except Exception as e:
            print(f"Error analyzing timetable: {str(e)}")
            analysis = {}  # Use empty analysis if there's an error

        return render_template('results.html',
                               timetable=timetable,
                               batches=batches,
                               days=days,
                               periods_per_day=periods_per_day,
                               analysis=analysis,
                               success_message=success_message,
                               viewing_saved=True,
                               course_map=course_map)

    except Exception as e:
        # Handle errors and provide more detailed error message
        import traceback
        error_msg = f"Error viewing saved timetable: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return render_template('index.html', error=f"Error viewing saved timetable: {str(e)}")


# Add these new routes to app.py

@timetable_bp.route('/edit_timetable')
@login_required
def edit_timetable():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    """Retrieve and display the saved timetable in an editable format"""
    try:
        # Connect to the database
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Get unique batches
        batch_query = """
        SELECT DISTINCT course_id, year, semester, batch_id 
        FROM timetable_assignments
        ORDER BY year, semester, batch_id
        """
        cursor.execute(batch_query)
        batch_results = cursor.fetchall()

        if not batch_results:
            return render_template('index.html',
                                   message="No saved timetable found. Please generate a new timetable.")

        # Build batch strings
        batches = []
        for batch in batch_results:
            # Convert all values to strings to avoid type issues
            course_id = str(batch['course_id'])
            year = str(batch['year'])
            semester = str(batch['semester'])
            batch_id = str(batch['batch_id'])
            batch_str = format_batch_string(course_id, year, semester, batch_id)
            batches.append(batch_str)

        # Initialize timetable structure
        timetable = {batch: {day: [""] * periods_per_day for day in days} for batch in batches}

        # Get timetable assignments
        assignment_query = """
        SELECT 
            ta.course_id, ta.year, ta.semester, ta.batch_id, ta.day, ta.period,
            cs.subject_name, cs.id as subject_id, 
            CONCAT(td.first_name, ' ', td.last_name) as teacher_name, td.id as teacher_id
        FROM timetable_assignments ta
        JOIN course_subjects cs ON ta.subject_id = cs.id
        JOIN teacher_details td ON ta.teacher_id = td.id
        ORDER BY ta.year, ta.semester, ta.batch_id, FIELD(ta.day, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'), ta.period
        """
        cursor.execute(assignment_query)
        assignments = cursor.fetchall()

        # Fill the timetable
        for assignment in assignments:
            batch_str = format_batch_string(
                str(assignment['course_id']),
                str(assignment['year']),
                str(assignment['semester']),
                str(assignment['batch_id'])
            )

            day = assignment['day']
            period = int(assignment['period'])
            subject = assignment['subject_name']
            teacher = assignment['teacher_name']
            subject_id = assignment['subject_id']
            teacher_id = assignment['teacher_id']

            if 0 <= period < periods_per_day:
                # Include subject_id and teacher_id for editing purposes
                timetable[batch_str][day][period] = {
                    "display": f"{subject} ({teacher})",
                    "subject_name": subject,
                    "teacher_name": teacher,
                    "subject_id": subject_id,
                    "teacher_id": teacher_id
                }

        # Get all available subjects and their assigned teachers for each batch
        all_subjects = {}

        for batch in batches:
            course_id, year, semester, batch_id = parse_batch_string(batch)

            subject_query = """
            SELECT 
                cs.id as subject_id, cs.subject_name, cs.subject_code,
                td.id as teacher_id, CONCAT(td.first_name, ' ', td.last_name) as teacher_name
            FROM course_subjects cs
            JOIN subject_assignments sa ON cs.id = sa.course_subject_id
            JOIN teacher_details td ON sa.teacher_id = td.id
            WHERE cs.course_id = %s AND cs.year = %s AND cs.semester = %s AND cs.batch_id = %s AND cs.is_active = 1
            ORDER BY cs.subject_name, teacher_name
            """
            cursor.execute(subject_query, (course_id, year, semester, batch_id))
            subject_results = cursor.fetchall()

            # Group subjects with their assigned teachers
            batch_subjects = {}
            for row in subject_results:
                subject_name = row['subject_name']
                if subject_name not in batch_subjects:
                    batch_subjects[subject_name] = {
                        "subject_id": row['subject_id'],
                        "subject_code": row['subject_code'],
                        "teachers": []
                    }

                batch_subjects[subject_name]["teachers"].append({
                    "teacher_id": row['teacher_id'],
                    "teacher_name": row['teacher_name']
                })

            all_subjects[batch] = batch_subjects

        cursor.close()
        db.close()
        course_map = get_course_map()
        print(course_map)
        session['timetable'] = json.dumps(timetable)
        return render_template('edit_timetable.html',
                               timetable=timetable,
                               batches=batches,
                               days=days,
                               periods_per_day=periods_per_day,
                               all_subjects=all_subjects,
                               course_map=course_map)

    except Exception as e:
        import traceback
        error_msg = f"Error loading editable timetable: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return render_template('index.html', error=f"Error loading editable timetable: {str(e)}")


@timetable_bp.route('/update_timetable', methods=['POST'])
@login_required
def update_timetable():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    """Save the modified timetable to the database"""
    if request.method == 'POST':
        try:
            # Get the timetable data from the form
            timetable_data = json.loads(request.form.get('timetable_data', '{}'))

            if not timetable_data:
                return redirect(url_for('timetable.render_timetable', error="No timetable data received"))

            # Connect to the database
            db = get_db_connection()
            cursor = db.cursor()

            # First, clear existing timetable entries
            clear_query = "DELETE FROM timetable_assignments WHERE 1=1"
            cursor.execute(clear_query)

            # Insert the new timetable data
            for batch, batch_data in timetable_data.items():
                # Parse batch information
                course_id, year, semester, batch_id = parse_batch_string(batch)

                for day, day_data in batch_data.items():
                    for period, entry in enumerate(day_data):
                        if entry and entry.get('subject_id') and entry.get('teacher_id'):
                            # Insert the assignment using the subject_id and teacher_id
                            insert_query = """
                            INSERT INTO timetable_assignments 
                            (course_id, year, semester, batch_id, day, period, subject_id, teacher_id, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            """
                            cursor.execute(insert_query, (
                                course_id, year, semester, batch_id, day, period,
                                entry['subject_id'], entry['teacher_id']
                            ))

            # Commit the changes
            db.commit()
            cursor.close()
            db.close()

            # Store success message in session
            session['success_message'] = "Timetable successfully updated!"

            return redirect(url_for('timetable.view_saved_timetable'))

        except Exception as e:
            import traceback
            error_msg = f"Error updating timetable: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            return render_template('index.html', error=f"Error updating timetable: {str(e)}")


PERIOD_TIMES = [
    "09:00 - 10:00",
    "10:00 - 11:00",
    "11:00 - 12:00",
    "01:00 - 02:00",
    "02:00 - 03:00",
    "03:00 - 04:00",
    "04:00 - 05:00"

]


@timetable_bp.route('/print_timetable')
@login_required
def print_timetable():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    # Get query parameters for batch selection (optional, can default to first batch)
    course_id = request.args.get('course_id')
    year = request.args.get('year')
    semester = request.args.get('semester')
    batch_id = request.args.get('batch_id')

    # If no parameters provided, use first batch
    if not all([course_id, year, semester, batch_id]):
        # Get the first batch from the database
        query = """
            SELECT DISTINCT course_id, year, semester, batch_id 
            FROM timetable_assignments 
            ORDER BY course_id, year, semester, batch_id 
            LIMIT 1
        """
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute(query)
        result = cursor.fetchone()

        if result:
            course_id = result['course_id']
            year = result['year']
            semester = result['semester']
            batch_id = result['batch_id']

    # Get course name
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT name FROM courses WHERE id = %s", (course_id,))
    course_result = cursor.fetchone()
    course_name = course_result['name'] if course_result else "Unknown Course"

    # Get days and periods_per_day (assuming these are constants or configuration)
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    periods_per_day = 7  # Adjust as needed

    # Get timetable data
    timetable = {day: [None] * periods_per_day for day in days}
    query = """
        SELECT ta.day, ta.period, ta.subject_id, ta.teacher_id, 
               cs.subject_name, cs.subject_code,
               CONCAT(td.first_name, ' ', td.last_name) as teacher_name
        FROM timetable_assignments ta
        JOIN course_subjects cs ON ta.subject_id = cs.id
        JOIN teacher_details td ON ta.teacher_id = td.id
        WHERE ta.course_id = %s AND ta.year = %s AND ta.semester = %s AND ta.batch_id = %s
    """

    cursor.execute(query, (course_id, year, semester, batch_id))
    assignments = cursor.fetchall()

    for assignment in assignments:
        day = assignment['day']
        period = int(assignment['period'])  # Ensure period is an integer

        # Skip if day is not in our days list
        if day not in timetable:
            continue

        # Skip if period is out of range
        if period < 0 or period >= periods_per_day:
            continue

        timetable[day][period] = {
            'subject_id': assignment['subject_id'],
            'teacher_id': assignment['teacher_id'],
            'subject_name': assignment['subject_name'],
            'subject_code': assignment['subject_code'],
            'teacher_name': assignment['teacher_name']
        }

    # Get subject summary (unique subject-teacher combinations)
    subjects = []
    subject_dict = {}

    for day in days:
        for period in range(periods_per_day):
            if timetable[day][period]:
                subject_id = timetable[day][period]['subject_id']
                if subject_id not in subject_dict:
                    subject_dict[subject_id] = {
                        'subject_name': timetable[day][period]['subject_name'],
                        'subject_code': timetable[day][period]['subject_code'],
                        'teacher_name': timetable[day][period]['teacher_name']
                    }

    subjects = list(subject_dict.values())

    # Sort subjects by name
    subjects.sort(key=lambda x: x['subject_name'])

    # Get current date for footer
    current_date = datetime.now().strftime("%d-%m-%Y")

    # Close the database connection
    cursor.close()
    db.close()

    return render_template(
        'print_timetable.html',
        course_name=course_name,
        year=year,
        semester=semester,
        batch_id=batch_id,
        days=days,
        periods_per_day=periods_per_day,
        period_times=PERIOD_TIMES,
        timetable=timetable,
        subjects=subjects,
        current_date=current_date
    )


# Improved crossover function that preserves good scheduling patterns
def improved_crossover(parent1, parent2, batches):
    child = {batch: {day: [""] * periods_per_day for day in days} for batch in batches}

    for batch in batches:
        # Choose a crossover strategy for this batch
        crossover_type = random.choice([1, 2, 3])

        if crossover_type == 1:
            # Day-based crossover: take entire days from either parent
            for day in days:
                # Randomly choose which parent to take this day from
                parent = parent1 if random.random() < 0.5 else parent2
                for period in range(periods_per_day):
                    child[batch][day][period] = parent[batch][day][period]

        elif crossover_type == 2:
            # Period-based crossover: for each period, choose from either parent
            for day in days:
                for period in range(periods_per_day):
                    # Randomly choose which parent to take this period from
                    parent = parent1 if random.random() < 0.5 else parent2
                    child[batch][day][period] = parent[batch][day][period]

        else:
            # Subject-based crossover: take all instances of a subject from one parent
            # First, identify all subjects in both parents
            all_subjects = set()

            for parent in [parent1, parent2]:
                for day in days:
                    for period in range(periods_per_day):
                        entry = parent[batch][day][period]
                        if entry:
                            subject = entry.split(" (")[0]
                            all_subjects.add(subject)

            # For each subject, choose which parent to take it from
            for subject in all_subjects:
                # Choose parent
                chosen_parent = parent1 if random.random() < 0.5 else parent2

                # Copy all instances of this subject from the chosen parent
                for day in days:
                    for period in range(periods_per_day):
                        entry = chosen_parent[batch][day][period]
                        if entry and entry.split(" (")[0] == subject:
                            child[batch][day][period] = entry

    return child


@timetable_bp.route('/download_timetable')
@login_required
def download_timetable():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    """Download the current timetable as a CSV file"""
    try:
        # Get timetable data from session
        timetable_json = session.get('timetable')
        batches_json = session.get('batches')

        if not timetable_json or not batches_json:
            return redirect(url_for('timetable.render_timetable', error="No timetable data available for download"))

        # Parse JSON data
        timetable = json.loads(timetable_json) if isinstance(timetable_json, str) else timetable_json
        batches = json.loads(batches_json) if isinstance(batches_json, str) else batches_json

        # Create a CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header row
        header = ['Batch', 'Day', 'Period', 'Subject', 'Teacher']
        writer.writerow(header)

        # Write timetable data
        for batch in batches:
            for day in days:
                for period in range(periods_per_day):
                    entry = timetable[batch][day][period]
                    if entry:  # Only include non-empty periods
                        if isinstance(entry, dict):  # Handle both string and dict formats
                            subject = entry.get('subject_name', '')
                            teacher = entry.get('teacher_name', '')
                        else:
                            # Parse the string format "Subject (Teacher)"
                            try:
                                subject, teacher = entry.rsplit(' (', 1)
                                teacher = teacher.rstrip(')')
                            except ValueError:
                                subject = entry
                                teacher = ''

                        writer.writerow([batch, day, period + 1, subject, teacher])

        # Prepare the response
        output.seek(0)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'timetable_{timestamp}.csv'
        )

    except Exception as e:
        import traceback
        error_msg = f"Error downloading timetable: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return redirect(url_for('timetable.render_timetable', error=f"Error downloading timetable: {str(e)}"))


@timetable_bp.route('/save_all_timetables', methods=['POST'])
@login_required
def save_all_timetables():
    if current_user.role != 'admin' and current_user.role != 'hod':
        flash('Access denied: Admin or HOD privileges required')
        return redirect(url_for(f'auth.{current_user.role}_dashboard'))
    
    db = None
    cursor = None
    
    try:
        # Get and validate timetable data
        timetable_data_str = request.form.get('timetable_data', '{}')
        try:
            timetable_data = json.loads(timetable_data_str)
        except json.JSONDecodeError as json_err:
            return render_template('index.html', error=f"Invalid timetable data format: {str(json_err)}")

        if not timetable_data:
            return redirect(url_for('timetable.render_timetable', error="No timetable data received"))

        # Initialize database connection
        db = get_db_connection()
        cursor = db.cursor(buffered=True, dictionary=True)

        # Clear all existing entries
        cursor.execute("DELETE FROM timetable_assignments")
        db.commit()

        # Process each batch
        for batch, batch_data in timetable_data.items():
            # Parse batch information
            batch_parts = parse_batch_string(batch)
            if None in batch_parts:
                continue
            
            course_id, year, semester, batch_id = batch_parts

            # Process each day
            for day, day_data in batch_data.items():
                # Process each period
                for period, entry in enumerate(day_data):
                    if not entry:
                        continue

                    try:
                        # Parse subject and teacher
                        if isinstance(entry, str):
                            if " (" not in entry or ")" not in entry:
                                continue
                            subject, teacher = entry.rsplit(' (', 1)
                            teacher = teacher.rstrip(')')
                        elif isinstance(entry, dict):
                            subject = entry.get('subject_name', '')
                            teacher = entry.get('teacher_name', '')
                        else:
                            continue

                        if not subject or not teacher:
                            continue

                        # Get subject_id
                        cursor.execute("""
                            SELECT id FROM course_subjects 
                            WHERE subject_name = %s 
                            AND course_id = %s 
                            AND year = %s 
                            AND semester = %s 
                            AND batch_id = %s 
                            AND is_active = 1
                        """, (subject, course_id, year, semester, batch_id))
                        subject_result = cursor.fetchone()
                        cursor.fetchall()  # Consume any remaining results
                        
                        if not subject_result:
                            continue
                        subject_id = subject_result['id']

                        # Get teacher_id
                        cursor.execute("""
                            SELECT id FROM teacher_details 
                            WHERE CONCAT(first_name, ' ', last_name) = %s
                        """, (teacher,))
                        teacher_result = cursor.fetchone()
                        cursor.fetchall()  # Consume any remaining results
                        
                        if not teacher_result:
                            continue
                        teacher_id = teacher_result['id']

                        # Insert the assignment
                        cursor.execute("""
                            INSERT INTO timetable_assignments 
                            (course_id, year, semester, batch_id, day, period, subject_id, teacher_id, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        """, (course_id, year, semester, batch_id, day, period, subject_id, teacher_id))

                    except Exception as e:
                        print(f"Error processing entry {entry}: {str(e)}")
                        continue

        # Commit all changes
        db.commit()
        flash('All timetables saved successfully!', 'success')
        return redirect(url_for('timetable.view_saved_timetable'))

    except Exception as e:
        if db:
            db.rollback()
        return render_template('index.html', error=f"Error saving timetables: {str(e)}")

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()