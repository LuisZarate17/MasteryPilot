## MasteryPilot

## Project summary

A system for school districts to create individual AI tutors for their students, following their own curriculums and learning paths with teacher guidance.

### Additional information about the project

This AI tutoring system enables school districts to offer personalized learning experiences by providing students with an interactive AI tutor that adapts to their curriculum and skill level. The tutor delivers step-by-step guidance, practice exercises, and quizzes, while teachers can monitor progress, track mastery, and receive alerts if a student struggles. Built for dynamic content generation and strict privacy safeguards, the system supports multiple subjects and student profiles and is designed to scale from individual classrooms to district-wide deployment, with future plans for local LLM usage and advanced analytics dashboards.

## Installation

### Prerequisites

- Python 3.13 or newer

### Add-ons

- Qwen3 - One of three LLM modules you can use (Default module)
- LLaMA - One of three LLM modules you can use (Requires license from Meta)
- Mistral - One of three LLM modules you can use

### Installation Steps

1. Clone the repository:
```
git clone https://github.com/Zelefant/CPTS421-AI-Tutor.git
cd CPTS421-AI-Tutor
```
2. Run setup.sh:
```
source ./setup.sh
```
3. When finished, go to the IP address and port listed in the console

## Functionality

1. Start the application by running the above commands.
2. The AI tutor will introduce itself and display the initial instructions.
3. Enter a message describing the topic or problem you want help with.
4. The tutor will respond with one step at a time. After completing the step, ask it to continue or ask for clarification.
5. Request quizzes by asking the tutor; it will provide them in a specially formatted quiz UI.
6. The system maintains safeguards to prevent inappropriate content and adheres to the structured step-by-step approach.


## Known Problems

- Model Swapper is not functional with the current version of the product. To swap the LLM, you must access code/llmsite/llmsite/settings.py and change LLM_MODULE to either "qwen", "mistral" or "llama" depending on the model you wish to use.


## Contributing

1. Fork the repository.
2. Create your feature branch: git checkout -b my-new-feature.
3. Make your changes and commit: git commit -am 'Add some feature'.
4. Push to the branch: git push origin my-new-feature.
5. Submit a pull request for review.

## Additional Documentation

- [Documentation Index](docs/README.md) - Entry point for sponsor handoff, deployment, admin, and user documentation.
- [Handoff Overview](docs/HANDOFF_OVERVIEW.md) - Sponsor-facing project summary and scope.
- [Deployment Guide](docs/DEPLOYMENT.md) - Technical setup and operational guidance for the Django application.
- [Admin Operations Guide](docs/ADMIN_OPERATIONS.md) - Staff workflows for accounts, curriculum, exports, and maintenance.
- [User Manual](docs/USER_MANUAL.md) - Client-facing usage guide for students, teachers, and admins.
- [Model Selector Utility](docs/MODEL_SELECTOR.md) - Notes for the separate Windows model configuration tool.
- [Known Limitations](docs/KNOWN_LIMITATIONS.md) - Current technical and operational limits.

- [Sprint 6 Report]() – Sprint 6 latest overview of work completed and unfinished work.
- [GitHub Issues](https://github.com/Zelefant/CPTS421-AI-Tutor/issues) - Current issues, user stories, and progress tracking.

## License

[See License](LICENSE.txt)






