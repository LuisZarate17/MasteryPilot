# Sprint 1 Report (August 18, 2025 - October 10, 2025)

## YouTube link of Sprint 1 Video

TODO: RECORD VIDEO

## What's New (User Facing)

- Language Model (Gemini currently) to communicate with for tutoring session
- Web-based GUI
- Quiz system for tutor to provide feedback for the student

## Work Summary (Developer Facing)

We began our research into using LLMs for tutoring purposes. We did experimentation and research into prompt engineering, which allowed us to come up with a strong initialization prompt for the LLM to be able to properly have safeguards and avoid security or privacy issues. We also made use of JSON formatting for the LLM's responses for the quiz system, which will help with making the quiz system more friendly on the user-facing side.

## Unfinished Work

- Capability for school administrators to view usage reports
- Creating system for teachers to monitor and track student progress in learning
- System for teacher to be alerted if a student is struggling to learn
- Using a local-LLM rather than a cloud-hosted one like Gemini, for use on a school district server

## Completed Issues/User Stories

Here are links to the issues that we completed in this sprint:

- #9: Quiz System with JSON – Fully implemented JSON-based quiz generation and grading.
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/9
- #2: Web UI – Base HTML and server integration started and functional in prototype.
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/2
- #7: Privacy Features and Documentation – Prompt safeguards added to prevent inappropriate content and ensure user data protection.
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/7
- #15: Documentation for Local Server Set-up – Installation and .env setup instructions written and tested.
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/15

## Incomplete Issues/User Stories

Here are links to issues we worked on but did not complete in this sprint:

- #3: Role-based Access and Rostering
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/3 - <<Database schema design started, authentication not implemented.>>
- #5: Local Language Model
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/5 - <<Researching, still testing local deployment options>>
- #6: Audit and Diagnostics System
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/6 - <<Logging planned but not connected yet.>>
- #10: Content and PDF Ingestion with RAG
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/10 - <<Research ongoing.>>
- #11: Student-defined Objectives and Mastery Criteria
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/11 - <<Outline drafted, not implemented.>>
- #12: Classroom Monitoring
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/12 - <<Backend integration pending.>>
- #13: Accessibility Features (WCAG 2.2 AA)
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/13 - <<Front-end testing not done.>>
- #14: Account System with OAuth
      https://github.com/Zelefant/CPTS421-AI-Tutor/issues/14 - <<OAuth flow still in development.>>
  
## Code Files for Review

Please review the following code files, which were actively developed during this sprint, for quality:

- [main.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/console_prototype/main.py)
- [README.md](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/console_prototype/README.md)
- [SPRINT-1-REPORT.md](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/console_prototype/SPRINT-1-REPORT.md)

## Retrospective Summary

Here's what went well:

- Research into prompt engineering
- Usage of JSON and CSV for quiz system
- Connection to LLM via API
- Creation of web app UI

Here's what we'd like to improve:

- Roles and account system
- Connection to a local LLM rather than to Gemini's cloud-based LLM

Here are changes we plan to implement in the next sprint:

- Usage of local LLM for school district server
- Teacher intervention notifications
- Role-based access for teachers, admins and students
- Progress dashboard w/ exports
