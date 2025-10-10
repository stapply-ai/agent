import json

default_profile = {
    "name": "Thomas Mueller",
    "email": "thomas.mueller@example.com",
    "phone": "+41781234567",
    "address": "Müllerstrasse 123, 8000 Zürich, Switzerland",
    "linkedin": "https://www.linkedin.com/in/thomas-mueller-1234567890",
    "github": "https://github.com/thomas-mueller",
    "website": "https://thomas-mueller.com",
    "summary": "I am a software engineer with 10 years of experience in the industry. I have a passion for building scalable and efficient systems.",
    "skills": ["Python", "Java", "JavaScript", "React", "Node.js", "SQL", "NoSQL"],
    "experience": [
        {
            "company": "Google",
            "title": "Software Engineer",
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
            "description": "Developed and maintained web applications using React and Node.js.",
        },
        {
            "company": "Facebook",
            "title": "Software Engineer",
            "start_date": "2018-01-01",
            "end_date": "2020-12-31",
            "description": "Developed and maintained mobile applications using React Native.",
        },
    ],
    "education": [
        {
            "school": "ETH Zurich",
            "degree": "Master of Science",
            "field_of_study": "Computer Science",
            "start_date": "2016-01-01",
            "end_date": "2020-12-31",
        }
    ],
}

default_profile_json = json.dumps(default_profile, indent=4)
