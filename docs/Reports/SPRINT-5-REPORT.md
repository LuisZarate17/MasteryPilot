# Sprint 5 Report (Feb 18 - March 15)

## YouTube link of Presentation Video
- [[Youtube Video Link]]()

## What's New (User Facing)

- Data export function
- Qwen3 and Mistral LLM modules

## Work Summary (Developer Facing)

The system is now designed to be deployed on a user's server. It also contains new modules for Qwen3 and Mistral support in addition to the existing LLaMA support.
We have also implemented data exporting of sessions for diagnostics and other purposes.

## Unfinished Work

- LLM tuning
- LLM response speed
- Security features

## Completed Issues/User Stories

Here are links to the issues that we completed in this sprint:

- Account system https://github.com/Zelefant/CPTS421-AI-Tutor/issues/14
- Program to make swapping models less technical https://github.com/Zelefant/CPTS421-AI-Tutor/issues/21
- Role-based access and rostering https://github.com/Zelefant/CPTS421-AI-Tutor/issues/3
- Bulk-generate new student accounts with CSV https://github.com/Zelefant/CPTS421-AI-Tutor/issues/22
- Classroom Monitoring https://github.com/Zelefant/CPTS421-AI-Tutor/issues/12
- Web UI (updated with dashboards from last time) https://github.com/Zelefant/CPTS421-AI-Tutor/issues/1

## Incomplete Issues/User Stories

Here are links to issues we worked on but did not complete in this sprint:

- Teacher Intervention Alerts https://github.com/Zelefant/CPTS421-AI-Tutor/issues/2
- Student-defined objectives and mastery criteria https://github.com/Zelefant/CPTS421-AI-Tutor/issues/11
- Audit and diagnostics system https://github.com/Zelefant/CPTS421-AI-Tutor/issues/6
- Privacy features/documentation https://github.com/Zelefant/CPTS421-AI-Tutor/issues/7
- Adaptive question difficulty (Stretch goal) https://github.com/Zelefant/CPTS421-AI-Tutor/issues/8
- Accessibility features (mostly already there but has not been a focus) https://github.com/Zelefant/CPTS421-AI-Tutor/issues/13
  
## Code Files for Review

Please review the following code files, which were actively developed during this sprint, for quality:

Main Program Python
- [languagemodel.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/languagemodel.py)
- [languagemodel_legacy.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/languagemodel_legacy.py) (Primarily used for testing)
- [views.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/views.py)
- [llmsite/urls.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/llmsite/urls.py)
- [tutor/urls.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/urls.py)
- [admin.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/admin.py)
- [apps.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/apps.py)
- [forms.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/forms.py)
- [models.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/models.py)
- [utils.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/code/llmsite/tutor/utils.py)
- [All files in migrations/ folder](https://github.com/Zelefant/CPTS421-AI-Tutor/tree/master/code/llmsite/tutor/migrations)

Main Program HTML
- [All files except init.html in the templates/ folder](https://github.com/Zelefant/CPTS421-AI-Tutor/tree/master/code/llmsite/tutor/templates)

Model Swapper
- [Form1.cs](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/model_selector_app/ModelSelector/ModelSelector/Form1.cs)
- [LoadingForm.cs](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/model_selector_app/ModelSelector/ModelSelector/LoadingForm.cs)
- [Model.cs](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/model_selector_app/ModelSelector/ModelSelector/Backend/Model.cs)
- [ScrapeHuggingfaceData.cs](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/model_selector_app/ModelSelector/ModelSelector/Backend/ScrapeHuggingfaceData.cs)


## Retrospective Summary

Here's what went well:

- New web UI is intuitive and easy to learn/use
- Code was relatively cohesive and decoupled, allowing for easy modification of individual parts
- All teammates pulled their weight and did equal amounts of work
- The backbone of the system was already there, and we just needed to complete the relatively easy features to create
- Increased familiarity with Django Web Framework has drastically improved our workflow since Sprint 1 and 2
- Everything is set up for success in Semester 2

Here's what we'd like to improve:

- Merge conflicts frequently created new bugs and issues that weren't there previously due to overwriting functions
- We need a more powerful system to run the application on so that we can test with a more robust Local LLM, LLaMA-3.2-2B-Instruct is pretty terrible at its job and takes ages to run. Gemini API also has a very limited amount of tokens for the free version, making testing difficult.
- More focus on unit testing for the deterministic parts of the application

Here are changes we plan to implement in the next sprint/semester:

- Use of either a rented WSU server or the client's home server for testing a stronger language model
- More unit tests
- Merge things earlier and more frequently so that we do not have huge merge conflicts that lead to new issues
