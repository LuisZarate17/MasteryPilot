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

- https://github.com/users/Zelefant/projects/1?pane=issue&itemId=132190302&issue=Zelefant%7CCPTS421-AI-Tutor%7C13
- https://github.com/users/Zelefant/projects/1/views/1?pane=issue&itemId=132190044&issue=Zelefant%7CCPTS421-AI-Tutor%7C5
- https://github.com/users/Zelefant/projects/1/views/1?pane=issue&itemId=132190448&issue=Zelefant%7CCPTS421-AI-Tutor%7C15

## Incomplete Issues/User Stories

Here are links to issues we worked on but did not complete in this sprint:
- Privacy features/documentation https://github.com/Zelefant/CPTS421-AI-Tutor/issues/7
- Adaptive question difficulty (Stretch goal) https://github.com/Zelefant/CPTS421-AI-Tutor/issues/8
  
## Code Files for Review

Please review the following code files, which were actively developed during this sprint, for quality:

[dashboard_admin_mentor.html](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/deployment_testing/code/llmsite/tutor/templates/dashboard_admin_mentor.html)
[tests.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/deployment_testing/code/llmsite/tutor/tests.py)
[urls.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/deployment_testing/code/llmsite/tutor/urls.py)
[views.py](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/deployment_testing/code/llmsite/tutor/views.py)

## Retrospective Summary

Here's what went well:

- Deployment to the server was easy to do
- Everything other than the LLM works flawlessly

Here's what we'd like to improve:

- LLM response speed and behavior is poor based on client's testing.

Here are changes we plan to implement in the next sprint/semester:

- Improve LLM response speeds
- Implement better system prompt for the LLM to make it behave better
