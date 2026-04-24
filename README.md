## System for AI Tutoring

## Project summary

A system for school districts to create individual AI tutors for their students, following their own curriculums and learning paths with teacher guidance.

### Additional information about the project

This AI tutoring system enables school districts to offer personalized learning experiences by providing students with an interactive AI tutor that adapts to their curriculum and skill level. The tutor delivers step-by-step guidance, practice exercises, and quizzes, while teachers can monitor progress, track mastery, and receive alerts if a student struggles. Built for dynamic content generation and strict privacy safeguards, the system supports multiple subjects and student profiles and is designed to scale from individual classrooms to district-wide deployment, with future plans for local LLM usage and advanced analytics dashboards.

## Installation

### Prerequisites

- Python 3.13 or newer
- Pip packages: google-generativeai, python-dotenv, django
- Gemini API key (Insert into .env file with the format: GEMINI_API_KEY="your api key")

### Add-ons

- Google Gemini API - Serves as the large-language model for the prototype system.

### Installation Steps

1. Clone the repository:
```
git clone https://github.com/Zelefant/CPTS421-AI-Tutor.git
cd CPTS421-AI-Tutor
```
2. Create and activate a virtual environment:
```
python -m venv .venv # Windows
.venv\Scripts\activate # macOS/Linux
source .venv/bin/activate
```
3. Upgrade pip and install dependencies:
```
pip install --upgrade pip
pip install google-generativeai python-dotenv django
```
4. Create a .env file in the folder "code" and add your Gemini API key:
```
GEMINI_API_KEY="your-api-key-here"
```
5. cd into the "llmsite" folder
6. Run the command: `python manage.py runserver`
7. Go to `http://127.0.0.1:8000` or whatever the IP address and port the command gives you.

## Functionality

1. Start the application by running the above commands.
2. The AI tutor will introduce itself and display the initial instructions.
3. Enter a message describing the topic or problem you want help with.
4. The tutor will respond with one step at a time. After completing the step, ask it to continue or ask for clarification.
5. Request quizzes or practice exams by asking the tutor; it will provide them in JSON format.
6. Submit quiz answers in CSV format; the tutor will return a graded JSON answer key.
7. The system maintains safeguards to prevent inappropriate content and adheres to the structured step-by-step approach.


## Known Problems

- Tutor requires internet access to use the Gemini API.
- Using a local LLM is not yet implemented (#5).
- All issues are tracked in GitHub, see the Incomplete Issues/User Stories section in the sprint report.


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

- [Sprint 4 Report](https://github.com/Zelefant/CPTS421-AI-Tutor/blob/master/docs/Reports/Sprint-4%20report.md) – Sprint 4 latest overview of work completed and unfinished work.
- [GitHub Issues](https://github.com/Zelefant/CPTS421-AI-Tutor/issues) - Current issues, user stories, and progress tracking.

## License

[See License](LICENSE.txt)






