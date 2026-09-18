import json
import os
from urllib import request, error


def _llm_available():
    return bool(os.getenv("LLM_API_KEY"))


def _deterministic_generation(employee_name, task_name, required_skill, employee, task, score):
    reasons = []
    if required_skill.lower() in [skill.strip().lower() for skill in str(employee.get("skills", "")).split(",") if skill.strip()]:
        reasons.append("matches the required skill")
    if employee.get("availability") == "Available":
        reasons.append("is available")
    if int(employee.get("workload", 0)) < 70:
        reasons.append("has manageable workload")
    if employee.get("location", "").lower() == task.get("location", "").lower():
        reasons.append("matches the task location")
    if int(employee.get("performance", 0)) >= 85:
        reasons.append("has strong historical performance")
    if not reasons:
        reasons = ["is the best available option"]

    summary = ", ".join(reasons[:-1]) + (" and " + reasons[-1] if len(reasons) > 1 else "")
    return f"{employee_name} was selected because they {summary}."


def _call_openai_explanation(employee_name, task_name, required_skill, employee, task, score):
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    if not api_key:
        return None

    prompt = (
        f"Use only actual information from the data. "
        f"Task: {task_name}, required skill: {required_skill}, priority: {task.get('priority')}, SLA: {task.get('sla_hours')} hours, location: {task.get('location')}. "
        f"Employee: {employee_name}, skills: {employee.get('skills')}, workload: {employee.get('workload')}%, availability: {employee.get('availability')}, location: {employee.get('location')}, performance: {employee.get('performance')}%. "
        f"Suitability score: {score}%. Explain why this employee is selected in one sentence."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise workforce allocation assistant. Use only factual values from the provided data and never invent data."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    req = request.Request("https://api.openai.com/v1/chat/completions", data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def generate_decision_explanation(task, employee, suitability_score, candidate_scores=None):
    task_name = task["name"] if isinstance(task, dict) else str(task)
    required_skill = task.get("required_skills", "") if isinstance(task, dict) else ""
    employee_name = employee["name"] if isinstance(employee, dict) else str(employee)
    candidate_scores = candidate_scores or []

    llm_text = _call_openai_explanation(employee_name, task_name, required_skill, employee, task, suitability_score)
    if llm_text:
        return llm_text

    return _deterministic_generation(employee_name, task_name, required_skill, employee, task, suitability_score)


def summarize_scenario(scenario_type, outcome_text):
    if _llm_available():
        prompt = f"Summarize this workforce scenario in one sentence: {scenario_type}. Outcome: {outcome_text}"
        payload = {
            "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": "You are a workforce planning assistant. Keep the summary brief and based on the facts provided."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        api_key = os.getenv("LLM_API_KEY")
        data = json.dumps(payload).encode("utf-8")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        req = request.Request("https://api.openai.com/v1/chat/completions", data=data, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    return f"Scenario: {scenario_type}. Outcome: {outcome_text}"
