# Admin Operations Guide

## Overview

This guide is for administrators and mentors operating the Django web application. It covers account management, curriculum management, student monitoring, and maintenance tasks.

## Roles

### Admin

Admins can:

- View all teachers, admins, and students.
- Create and delete accounts.
- Edit student assignments and classes.
- Upload, view, and delete curriculum files.
- Export chat data for students.
- View student progress and chat history.

### Teacher/Mentor

Teachers can:

- View assigned students.
- View progress for assigned students.
- View chat history for assigned students.
- Upload and view curriculum files.
- Export chat data for assigned students.

Teachers cannot delete curriculum files or perform full account administration.

## Dashboard Sections

The custom dashboard is the main staff interface. It contains:

- Students
- Curriculum
- Intervention
- Accounts
- Export Data

## Account Management

### Create an account

Admins can create:

- Teacher accounts
- Admin accounts
- Student accounts

Required fields:

- Username
- Email
- Password

Additional student fields:

- Grade
- Classes

### Delete an account

Admins can delete teacher, admin, or student accounts from the dashboard. The current code prevents an admin from deleting their own account through the custom delete flow.

### Edit a student

Admins can update:

- Student classes
- Assigned teacher/mentor

## Curriculum Management

### Supported upload types

- `.txt`
- `.pdf`

### Upload limits

- Maximum size: 100 MB

### Curriculum storage

Uploaded files are stored in the Django `CURRICULUM_ROOT` directory on the application server.

### Who can perform actions

- Teachers and admins can upload files.
- Teachers and admins can view files.
- Only admins can delete files.

## Student Monitoring

### Student list

Staff can open:

- Chat history
- Detailed progress view

### Intervention section

The dashboard flags students who may need help based on quiz average thresholds:

- "Struggling"
- "Failing"

This is intended as a lightweight intervention signal, not a formal grading system.

## Data Export

Chat data can be exported in:

- CSV
- JSON

Export is student-specific. Admins can export any student. Teachers can export only students assigned to them.

## Progress Tracking

Progress is cached in the `StudentProgress` model. It tracks:

- Overall completion percent
- Current module/topic
- Quiz average
- Activity streak
- Last activity
- Session count
- Quiz count
- Message count

## Maintenance Commands

Run these from the Django project context.

### Import students from CSV

```bash
python manage.py import_students <csv_path>
```

Expected CSV fields:

- `username`
- `password`
- `full_name`
- `email`
- `school`
- `grade`
- `classes`

### Refresh student progress

Refresh all users:

```bash
python manage.py refresh_all_progress
```

Refresh students only:

```bash
python manage.py refresh_all_progress --students-only
```

Refresh one user:

```bash
python manage.py refresh_all_progress --user-id <id>
```

## Operational Best Practices

- Use strong passwords for manually created accounts.
- Assign mentors explicitly when student oversight is required.
- Review intervention flags regularly.
- Export student data only for approved operational or reporting reasons.
- Avoid storing exported chat files in unsecured shared locations.
- Keep curriculum documents organized and remove outdated material.

## Administrative Limitations

- No bulk account UI is present in the dashboard.
- Curriculum library does not currently track upload timestamps in the UI.
- Export is per-student, not bulk by class or date range.
- The application uses SQLite by default.
- Password reset email is configured for console output unless deployment changes it.
