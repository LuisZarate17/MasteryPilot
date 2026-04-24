# Sprint 6 Report (March 16, 2026 - April 24, 2026)
## YouTube link of Sprint 6 Video (Make this video unlisted)
[Link](https://youtu.be/K4BfUxH6xQY)

## What's New (User Facing)
* Made ready for deployment and release
* LLM optimization improvements (massive speedup times on GPU-accelerated systems)
* Polishing of the UI
* End user documentation

## Work Summary (Developer Facing)
Our team prepared the system for deployment and delivery to the client. This included cleaning up any placeholder icons or UI elements, removing backdoors and polishing everything for an end user to use. We also made massive improvements to LLM response times by implementing the GPU-accelerated version of Torch into our application. Documentation was also created for teachers, admins and students to understand how to use the application effectively and safely.

## Unfinished Work
The model swapper, a previously planned feature, was not updated from last semester to work with the new module system. As such, swapping models requires modifying the settings.py file rather than a click of a button. This is all documented to make it as easy as possible for administrators, but is less convenient. In addition, the stretch goal of creating adaptive question difficulty is not possible with our current system and the time we had, so this was also scrapped.

## Completed Issues/User Stories
Here are links to the issues that we completed in this sprint:
* [#7 - Privacy Features and Documentation](https://github.com/Zelefant/CPTS421-AI-Tutor/issues/7)
* [#22 - Bulk Generate Student Accounts with CSV](https://github.com/Zelefant/CPTS421-AI-Tutor/issues/22)

## Incomplete Issues/User Stories
Here are links to issues we worked on but did not complete in this sprint:
* [#21 - Program to make swapping models less technical](https://github.com/Zelefant/CPTS421-AI-Tutor/issues/21)
The aforementioned model swapper was not updated to work with the LLM module system we created during the second semester.
* [#8 - Adaptive question difficulty](https://github.com/Zelefant/CPTS421-AI-Tutor/issues/8)
Scrapped stretch goal we never were able to reach.

## Code Files for Review
Please review the following code files, which were actively developed during this
sprint, for quality:
* [languagemodel_llama.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/languagemodel_llama.py)
* [languagemodel_mistral.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/languagemodel_mistral.py)
* [languagemodel_qwen.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/languagemodel_qwen.py)
* [views.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/views.py)
* [chat_api.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/templates/chat_api.html)
* [dashboard_admin_mentor.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/templates/dashboard_admin_mentor.html)
* [progress_detail.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/templates/progress_detail.html)

## Retrospective Summary
Here's what went well:
* Polishing and bug fixes
* Communication with the client
* Documentation creation
* Deployment and delivery to client

Here's what we'd like to improve:
* Model swapper functionality
* More bug fixes to the system
