from datetime import datetime, timedelta


def seed_employee_data():
    return [
        {
            "name": "Arun",
            "skills": "Networking, Server",
            "workload": 30,
            "availability": "Available",
            "location": "Chennai",
            "performance": 92,
        },
        {
            "name": "Priya",
            "skills": "Python, Database",
            "workload": 60,
            "availability": "Available",
            "location": "Chennai",
            "performance": 88,
        },
        {
            "name": "Kavi",
            "skills": "Testing, Database",
            "workload": 40,
            "availability": "Available",
            "location": "Coimbatore",
            "performance": 91,
        },
        {
            "name": "Rahul",
            "skills": "Networking, Security",
            "workload": 75,
            "availability": "Available",
            "location": "Bangalore",
            "performance": 85,
        },
        {
            "name": "Meena",
            "skills": "Python, Testing",
            "workload": 20,
            "availability": "Available",
            "location": "Chennai",
            "performance": 94,
        },
    ]


def seed_task_data():
    now = datetime.now()
    return [
        {
            "name": "Server Failure",
            "description": "Restore critical server connectivity after a network outage.",
            "required_skills": "Networking",
            "priority": "Critical",
            "sla_hours": 1,
            "location": "Chennai",
            "status": "pending",
            "deadline": (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "name": "Database Backup",
            "description": "Complete scheduled backup and validation for production databases.",
            "required_skills": "Database",
            "priority": "High",
            "sla_hours": 4,
            "location": "Chennai",
            "status": "pending",
            "deadline": (now + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "name": "Application Testing",
            "description": "Execute smoke tests across the release candidate for the mobile app.",
            "required_skills": "Testing",
            "priority": "Medium",
            "sla_hours": 24,
            "location": "Coimbatore",
            "status": "pending",
            "deadline": (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "name": "Security Audit",
            "description": "Review firewall and access policy changes for the Bengaluru environment.",
            "required_skills": "Security",
            "priority": "High",
            "sla_hours": 6,
            "location": "Bangalore",
            "status": "pending",
            "deadline": (now + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
        },
    ]
