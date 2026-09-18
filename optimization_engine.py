from __future__ import annotations

from ortools.sat.python import cp_model

from database import get_employees, get_tasks


def skill_overlap(employee_skills: str, task_skills: str) -> float:
    if not task_skills:
        return 1.0
    employee = {item.strip().lower() for item in str(employee_skills).split(",") if item.strip()}
    task = {item.strip().lower() for item in str(task_skills).split(",") if item.strip()}
    if not task:
        return 1.0
    overlap = employee & task
    return round(len(overlap) / len(task), 4) if task else 0.0


def calculate_compatibility_score(employee: dict, task: dict) -> float:
    overlap = skill_overlap(employee.get("skills", ""), task.get("required_skills", ""))
    availability = 1.0 if employee.get("availability") == "Available" else 0.0
    workload_penalty = max(0.0, 1.0 - (int(employee.get("workload", 0)) / 100.0))
    sla_factor = 1.0 if int(task.get("sla_hours", 24)) <= 6 else 0.75
    location_bonus = 1.0 if str(employee.get("location", "")).lower() == str(task.get("location", "")).lower() else 0.6
    performance = float(employee.get("performance", 0)) / 100.0
    score = (
        overlap * 0.30
        + availability * 0.20
        + workload_penalty * 0.15
        + sla_factor * 0.15
        + location_bonus * 0.10
        + performance * 0.10
    )
    return round(score * 100, 2)


def optimize_workforce_plan():
    employees = get_employees()
    tasks = [task for task in get_tasks() if task.get("status") != "completed"]
    if not tasks:
        return {"success": True, "assignments": [], "summary": "No active tasks require optimization."}

    model = cp_model.CpModel()
    decision_vars = {}
    candidate_map = {}

    for employee in employees:
        if employee.get("availability") != "Available":
            continue
        for task in tasks:
            score = calculate_compatibility_score(employee, task)
            if score <= 0:
                continue
            if skill_overlap(employee.get("skills", ""), task.get("required_skills", "")) <= 0:
                continue
            var = model.NewBoolVar(f"x_{employee['id']}_{task['id']}")
            decision_vars[(employee["id"], task["id"])] = var
            candidate_map[(employee["id"], task["id"])] = score

    for task in tasks:
        task_vars = [decision_vars[(employee_id, task["id"])] for employee_id, _task_id in decision_vars if _task_id == task["id"]]
        if task_vars:
            model.Add(sum(task_vars) <= 1)

    for employee in employees:
        employee_vars = [decision_vars[(employee["id"], task["id"])] for task in tasks if (employee["id"], task["id"]) in decision_vars]
        if employee_vars:
            max_assignments = max(1, int(employee.get("capacity", 100)) // 25)
            model.Add(sum(employee_vars) <= max_assignments)

    objective_terms = []
    for (employee_id, task_id), variable in decision_vars.items():
        objective_terms.append(candidate_map[(employee_id, task_id)] * variable)
    if objective_terms:
        model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "success": False,
            "message": "No feasible assignment exists under the current constraints.",
            "assignments": [],
            "reason": "Required skills, availability, workload, and SLA constraints were not simultaneously satisfiable.",
        }

    assignments = []
    for (employee_id, task_id), variable in decision_vars.items():
        if solver.Value(variable):
            employee = next(emp for emp in employees if emp["id"] == employee_id)
            task = next(item for item in tasks if item["id"] == task_id)
            assignments.append({
                "employee_id": employee_id,
                "employee_name": employee["name"],
                "task_id": task_id,
                "task_name": task["name"],
                "score": candidate_map[(employee_id, task_id)],
            })

    return {
        "success": True,
        "assignments": assignments,
        "summary": f"Global optimization evaluated {len(tasks)} tasks against {len(employees)} employees.",
        "total_tasks": len(tasks),
        "assigned_tasks": len(assignments),
    }
