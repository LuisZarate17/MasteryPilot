from .models import TeacherProfile, AdminProfile, StudentProgress, Session, Chat, Quiz, QuizAnswer
from django.db.models import Count, Q, Max
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

import csv, io

# Security

def is_teacher_or_admin(user):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    is_teacher = TeacherProfile.objects.filter(user=user).exists()
    is_admin = AdminProfile.objects.filter(user=user).exists()
    return is_teacher or is_admin

def is_admin(user):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    is_admin = AdminProfile.objects.filter(user=user).exists()
    return is_admin

# Quiz Grading

def create_or_replace_active_quiz(session, quiz_obj):
    Quiz.objects.filter(session=session, status="active").update(
        status="submitted",
        ended_at=timezone.now(),
    )
    return Quiz.objects.create(
        session=session,
        status="active",
        quiz_json=quiz_obj,
    )

def parse_csv_answers(csv_string: str) -> list[str]:
    f = io.StringIO(csv_string or "")
    rows = list(csv.reader(f))
    return [c.strip() for c in (rows[0] if rows else [])]



# Progress Tracking

def calculate_student_progress(user):
    """
    Aggregate student activity data and compute progress metrics.
    Uses Option C: Hybrid approach with quiz scores as primary signal,
    session activity as secondary signal.
    
    Returns dict of computed metrics and saves to StudentProgress model.
    """
    # Get or create progress record
    progress, created = StudentProgress.objects.get_or_create(user=user)
    
    # Query all sessions for this user
    sessions = Session.objects.filter(owner=user)
    total_sessions = sessions.count()
    
    # Get all user messages
    user_messages = Chat.objects.filter(
        session__owner=user,
        role='user'
    )
    total_messages = user_messages.count()
    
    # Get all graded quizzes
    graded_quizzes = Quiz.objects.filter(
        session__owner=user,
        status='graded'
    )
    
    total_quizzes = graded_quizzes.count()
    
    # Calculate quiz average from graded_json
    quiz_average = None
    earned_total = 0.0
    possible_total = 0.0
    for quiz in graded_quizzes:
        earned_total += quiz.earned_pts
        possible_total += quiz.possible_pts

    if possible_total > 0:
        quiz_average = earned_total / possible_total
    
    # Calculate overall completion percentage (Option C: Hybrid)
    # 70% weight on quiz performance, 30% weight on session activity
    quiz_component = 0.0
    if quiz_average is not None:
        # Normalize quiz average to 0-1 scale and apply weight
        quiz_component = (quiz_average / 100.0) * 70.0
    
    session_component = 0.0
    if total_sessions > 0:
        # Cap session activity at 10 sessions for 100% of this component
        session_score = min(total_sessions / 10, 1.0)
        session_component = session_score * 30.0
    
    overall_completion = quiz_component + session_component
    
    # Determine current module (most recent session title)
    current_module = ""
    latest_session = sessions.order_by('-created_at').first()
    if latest_session:
        current_module = latest_session.title
    
    # Find last activity timestamp
    last_activity = None
    last_chat = user_messages.order_by('-created_at').first()
    last_quiz = graded_quizzes.order_by('-started_at').first()
    
    if last_chat and last_quiz:
        last_activity = max(last_chat.created_at, last_quiz.started_at)
    elif last_chat:
        last_activity = last_chat.created_at
    elif last_quiz:
        last_activity = last_quiz.started_at
    
    # Calculate activity streak
    activity_streak = calculate_activity_streak(user)
    
    # Update progress record
    progress.overall_completion_percent = overall_completion
    progress.current_module = current_module
    progress.quiz_average = quiz_average
    progress.activity_streak = activity_streak
    progress.last_activity = last_activity
    progress.total_sessions = total_sessions
    progress.total_quizzes = total_quizzes
    progress.total_messages = total_messages
    progress.save()
    
    return {
        'overall_completion_percent': float(overall_completion),
        'current_module': current_module,
        'quiz_average': quiz_average * 100 if quiz_average is not None else None,
        'activity_streak': activity_streak,
        'last_activity': last_activity.isoformat() if last_activity else None,
        'total_sessions': total_sessions,
        'total_quizzes': total_quizzes,
        'total_messages': total_messages,
    }


def calculate_activity_streak(user):
    """
    Calculate consecutive days with at least one activity (chat or quiz).
    Returns the current streak count.
    """
    # Get all activity dates (chats and quizzes)
    chat_dates = Chat.objects.filter(
        session__owner=user,
        role='user'
    ).values_list('created_at', flat=True).order_by('-created_at')
    
    quiz_dates = Quiz.objects.filter(
        session__owner=user
    ).values_list('started_at', flat=True).order_by('-started_at')
    
    # Combine and get unique dates
    all_dates = list(chat_dates) + list(quiz_dates)
    if not all_dates:
        return 0
    
    # Convert to date objects (remove time) and get unique sorted dates
    activity_dates = sorted(
        set(dt.date() for dt in all_dates),
        reverse=True
    )
    
    if not activity_dates:
        return 0
    
    # Start counting from most recent date
    streak = 1
    today = timezone.now().date()
    
    # Check if most recent activity was today or yesterday
    most_recent = activity_dates[0]
    if most_recent < today - timedelta(days=1):
        # No activity yesterday or today, streak is broken
        return 0
    
    # Count consecutive days
    for i in range(len(activity_dates) - 1):
        current_date = activity_dates[i]
        next_date = activity_dates[i + 1]
        
        # Check if dates are consecutive (exactly 1 day apart)
        if (current_date - next_date).days == 1:
            streak += 1
        else:
            # Gap found, stop counting
            break
    
    return streak