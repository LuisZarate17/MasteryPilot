# User Manual

## Overview

This manual describes how students, teachers, and admins use the AI Tutor web application.

## Student Guide

### 1. Sign up or sign in

Students can create an account from the signup page or log in with an existing account.

During signup, the form may request:

- Username
- Full name
- Email
- Password
- School
- Grade
- Classes

### 2. Start at the landing page

After login, students are taken to the landing page. This page shows:

- Welcome message
- Overall progress
- Current topic
- Quiz average
- Activity streak
- Session, quiz, and message counts
- Last activity

Use the landing page to:

- Start a new chat
- Open detailed progress

### 3. Start a chat session

Open the chat page and select `New` in the session sidebar. A new tutoring session is created and the tutor responds with an opening message.

Students can:

- Ask questions
- Continue prior sessions from the sidebar
- Rename a session
- Delete a session

### 4. Work through tutor responses

The tutor is designed for guided learning rather than a single final answer workflow. Students should:

- Ask a question or describe a topic
- Read the tutor response
- Continue with follow-up questions
- Request additional explanation if needed

### 5. Take quizzes

When the tutor returns quiz content, the page displays a quiz card. Students can:

- Answer multiple-choice or short-answer questions
- Submit the quiz
- Review the quiz results modal

Quiz results contribute to progress tracking.

### 6. Review progress

Students can open the detailed progress page to review:

- Overall completion
- Session history
- Quiz-related progress information
- Recent activity

### 7. Reset password

If password reset is enabled in the deployment environment, students can use the password reset flow from the login area.

## Teacher Guide

### 1. Open the dashboard

Teachers are redirected to the dashboard after login.

### 2. Review students

In the Students section, teachers can:

- View students assigned to them
- Open chat history
- Open progress details

### 3. Review intervention list

The Intervention section highlights students who may need extra support based on performance thresholds.

### 4. Upload curriculum

Teachers can upload TXT or PDF curriculum documents in the Curriculum section. These files become part of the curriculum library used by the system.

### 5. Export student chat data

Teachers can export chat history for students assigned to them in CSV or JSON format.

## Admin Guide

Admins can perform all teacher actions plus:

- Create teacher, admin, and student accounts
- Delete accounts
- Edit student class data
- Assign or remove mentor relationships
- Delete curriculum files
- Export data for any student

## Common Tasks

### Rename a session

Use the edit icon in the session list.

### Delete a session

Use the delete icon in the session list and confirm the action.

### Open a prior session

Select it from the session sidebar.

### Export chat history

Go to the dashboard, open Export Data, choose a student and format, then download the file.

## Tips for Effective Use

- Keep session titles meaningful if you want clearer progress history.
- Use quizzes to measure understanding, not just chat volume.
- Review progress regularly rather than waiting until intervention thresholds are reached.
- Keep curriculum uploads current and relevant to the subjects being taught.

## Current User-Facing Limits

- Password reset depends on deployment email configuration.
- Some lesson notes and resources shown in chat are placeholder content.
- Progress and intervention indicators are helpful summaries, not formal assessment records.
- The interface is optimized for the current prototype workflow rather than district-scale administration.
