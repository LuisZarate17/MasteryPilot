# Sprint 4 Report    (Dates from 1/15/2026 to 2/17/2026)

YouTube link of Sprint: [https://youtu.be/IWeX7qB\_dKY](https://youtu.be/IWeX7qB_dKY) 

## What's New (User Facing)

* Server-side quiz grading — the backend now grades quizzes deterministically (LLM no longer used for scoring).  
* Progress Tracker integrated with quizzes — teacher Intervention tab shows students below thresholds, and progress shown as percentages.  
* Teacher features: chat history view, view students’ progress dashboards as teacher, teacher intervention alerts  
* Frontend polish: previous quizzes appear as read-only UI elements rather than raw JSON; progress shown more clearly.

## Work Summary (Developer Facing)

The main goal of this sprint was to complete the progress tracker. The pieces were there for it, it just was not implemented or integrated with the rest of the system. To make the progress tracker work, we had to change the quiz system to no longer have short-answer questions and remove the LLM from the scoring. The LLM now assigns a question a certain number of points and determines the correct answer before giving the quiz to the student.

In addition, teachers now have access to the unintegrated features from last sprint, like chat history and viewing students’ progress dashboards. The functionality was there for progress dashboards already, but it was not integrated into the UI, and the button to go to a student’s progress page didn’t do anything. The chat history required some extra work by cloning the chat page and making a separate chat history page, but it now works.

## Unfinished Work

- Local LLM \- Was originally Deployed but has been moved back to In Development. It currently does not run on our machines and therefore we cannot guarantee that it works properly.  
- Program to make swapping models less technical \- This, like the above bullet point, was originally complete, but after more testing it has been proven to be much more difficult than initially thought to swap between Huggingface models. More work will have to be put in and it will likely restrict the kinds of models you can use.  
- Documentation for local server set-up \- Has not been written  
- Privacy features and documentation \- Has not been written and security testing will be done next sprint  
- Accessibility features \- Pretty much done, but we haven’t actually made it a focus, it has just been naturally implemented thanks to HTML being easy to work with  
- Adaptive question difficulty \- Still a stretch goal, and likely unrealistic at the current stage

## Completed Issues/User Stories

Here are links to the issues that we completed in this sprint:  
\* https://github.com/Zelefant/CPTS421-AI-Tutor/issues/6  
\* https://github.com/Zelefant/CPTS421-AI-Tutor/issues/2  
\* https://github.com/Zelefant/CPTS421-AI-Tutor/issues/11  
\* https://github.com/Zelefant/CPTS421-AI-Tutor/issues/12

## Incomplete Issues/User Stories

Here are links to issues we worked on but did not complete in this sprint:

\* [https://github.com/Zelefant/CPTS421-AI-Tutor/issues/5](https://github.com/Zelefant/CPTS421-AI-Tutor/issues/5) \- Cannot test efficiently on local machines  
\* [https://github.com/Zelefant/CPTS421-AI-Tutor/issues/21](https://github.com/Zelefant/CPTS421-AI-Tutor/issues/21) \- Will require more work than previously thought  
\* [https://github.com/Zelefant/CPTS421-AI-Tutor/issues/15](https://github.com/Zelefant/CPTS421-AI-Tutor/issues/15) \- Did not get to writing this sprint

## Code Files for Review

Please review the following code files, which were actively developed during this sprint, for quality:

* \[[languagemodel\_legacy.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/languagemodel_legacy.py)\]  
* \[[views.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/views.py)\]  
* \[[utils.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/utils.py)\]  
* \[[urls.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/urls.py)\]  
* \[[models.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/models.py)\]  
* \[[landing.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/templates/landing.html)\]  
* \[[dashboard\_admin\_mentor.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/templates/dashboard_admin_mentor.html)\]  
* \[[chat\_history.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/templates/chat_history.html)\]  
* \[[chat\_api.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/templates/chat_api.html)\]  
* \[[chat.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/progress-tracker-backend/code/llmsite/tutor/templates/chat.html)\]

## Retrospective Summary

Here's what went well:  
\* Replaced unreliable LLM grading with deterministic server logic — improved reliability and auditability.  
\* Progress Tracker integrated with quizzes and teacher Intervention workflow completed.

Here's what we'd like to improve:  
\* Local language model deployed on stronger server.  
\* Documentation needs to be written.

Here are changes we plan to implement in the next sprint:  
\* Testing on actual server  
\* Adding modules for multiple local language models (deepseek, qwen, mistral, llama(already written))  
\* Writing documentation