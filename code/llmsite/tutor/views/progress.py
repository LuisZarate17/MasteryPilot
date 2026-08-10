"""Student progress: the landing page, the summary API, and the detail view."""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ..models import Session, StudentProfile, StudentProgress, TeacherProfile
from ..utils import calculate_student_progress, is_admin, is_teacher_or_admin


@login_required
def landing_page(request):
    """
    Authenticated landing page for students.
    Shows welcome message, progress summary widget, and CTAs.
    Teachers/admins are redirected to dashboard.
    """
    if is_teacher_or_admin(request.user):
        return redirect("dashboard")
    
    # Get or calculate progress for the current user
    try:
        progress = StudentProgress.objects.get(user=request.user)
    except StudentProgress.DoesNotExist:
        # First time user - calculate initial progress
        calculate_student_progress(request.user)
        progress = StudentProgress.objects.get(user=request.user)
        
    quiz_avg = None
    if progress.quiz_average:
        quiz_avg = progress.quiz_average * 100

    context = {
        'progress': progress,
        'quiz_avg': quiz_avg,
        'has_activity': progress.total_sessions > 0 or progress.total_quizzes > 0,
    }
    
    return render(request, "landing.html", context)


@login_required
@require_http_methods(["GET"])
def progress_summary(request):
    """
    API endpoint to fetch student progress summary.
    """
    user = request.user
    metrics = calculate_student_progress(user)
    
    if metrics['total_sessions'] == 0:
        next_step = "Start your first chat session"
    elif metrics['total_quizzes'] == 0:
        next_step = "Complete your first quiz"
    elif metrics['quiz_average'] and metrics['quiz_average'] < 70:
        next_step = "Review topics and improve quiz scores"
    else:
        next_step = "Continue learning with new topics"
    
    return JsonResponse({
        'ok': True,
        'overall_completion_percent': metrics['overall_completion_percent'],
        'current_module': metrics['current_module'],
        'last_activity': metrics['last_activity'],
        'activity_streak': metrics['activity_streak'],
        'next_step': next_step,
        'total_sessions': metrics['total_sessions'],
        'total_quizzes': metrics['total_quizzes'],
        'total_messages': metrics['total_messages'],
        'quiz_average': metrics['quiz_average'],
    })


@login_required
def progress_detail(request):
    """
    Full progress dashboard with charts, history, and detailed metrics.
    """
    student_id = request.GET.get('student_id')
    
    if student_id and is_teacher_or_admin(request.user):
        try:
            User = get_user_model()
            student_user = User.objects.get(id=student_id)
            
            if not is_admin(request.user):
                teacher_profile = TeacherProfile.objects.get(user=request.user)
                student_profile = StudentProfile.objects.get(user=student_user)
                if student_profile.teacher != teacher_profile:
                    return JsonResponse({'error': 'Access denied'}, status=403)
            
            target_user = student_user
        except (User.DoesNotExist, TeacherProfile.DoesNotExist, StudentProfile.DoesNotExist):
            return JsonResponse({'error': 'Student not found'}, status=404)
    else:
        target_user = request.user
    
    metrics = calculate_student_progress(target_user)
    
    try:
        progress = StudentProgress.objects.get(user=target_user)
    except StudentProgress.DoesNotExist:
        progress = None
    
    sessions = Session.objects.filter(owner=target_user).order_by('-created_at')[:20]
    session_history = []
    
    for session in sessions:
        quizzes = session.quizzes.filter(status='graded')
        quiz_count = quizzes.count()
        
        session_quiz_avg = None
        if quiz_count > 0:
            quiz_scores = []
            for quiz in quizzes:
                quiz_answer = quiz.answers.first()
                if quiz_answer and quiz_answer.graded_json:
                    correct = sum(1 for item in quiz_answer.graded_json.values() 
                                  if isinstance(item, dict) and item.get('isCorrect'))
                    total = len(quiz_answer.graded_json)
                    if total > 0:
                        quiz_scores.append((correct / total) * 100)
            
            if quiz_scores:
                session_quiz_avg = sum(quiz_scores) / len(quiz_scores)
        
        session_history.append({
            'id': str(session.id),
            'title': session.title,
            'created_at': session.created_at.isoformat(),
            'quiz_count': quiz_count,
            'quiz_average': round(session_quiz_avg, 2) if session_quiz_avg else None,
        })
    
    context = {
        'target_user': target_user,
        'metrics': metrics,
        'progress': progress,
        'session_history': session_history,
        'is_viewing_other': student_id is not None,
    }
    
    return render(request, 'progress_detail.html', context)
