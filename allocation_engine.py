from __future__ import annotations

from datetime import datetime

from database import (
    get_employee_by_id,
    get_employees,
    get_task_by_id,
    get_tasks,
    get_connection,
    insert_audit_event,
    insert_allocation,
    set_task_assignment,
)

WEIGHTS = {
    "skill_match": 0.30,
    "availability": 0.20,
    "workload_capacity": 0.15,
    "priority_sla": 0.15,
    "location": 0.10,
    "historical_performance": 0.10,
}

PRIORITY_LEVELS = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


def skill_list_to_set(value):
    if not value:
        return set()
    return {item.strip().lower() for item in str(value).split(",") if item.strip()}


def normalize_skill_match(employee_skills, task_skills):
    employee_set = skill_list_to_set(employee_skills)
    task_set = skill_list_to_set(task_skills)
    if not task_set:
        return 100.0
    overlap = employee_set & task_set
    if not overlap:
        return 0.0
    return round((len(overlap) / len(task_set)) * 100, 2)


def availability_score(employee):
    return 100.0 if employee["availability"] == "Available" else 0.0


def workload_capacity_score(employee):
    workload = int(employee["workload"] or 0)
    return max(0.0, 100.0 - workload)


def priority_sla_score(task):
    priority_weight = {"Critical": 100, "High": 80, "Medium": 60, "Low": 40}.get(task["priority"], 50)
    sla_hours = int(task["sla_hours"] or 24)
    if sla_hours <= 2:
        sla_factor = 100
    elif sla_hours <= 6:
        sla_factor = 80
    elif sla_hours <= 12:
        sla_factor = 60
    else:
        sla_factor = 40
    return round((priority_weight * 0.7) + (sla_factor * 0.3), 2)


def location_score(employee, task):
    if employee["location"].strip().lower() == task["location"].strip().lower():
        return 100.0
    return 50.0


def calculate_candidate_score(employee, task):
    skill_score = normalize_skill_match(employee["skills"], task["required_skills"])
    avail_score = availability_score(employee)
    workload_score = workload_capacity_score(employee)
    sla_score = priority_sla_score(task)
    location_score_value = location_score(employee, task)
    performance = float(employee["performance"] or 0)

    total = (
        skill_score * WEIGHTS["skill_match"]
        + avail_score * WEIGHTS["availability"]
        + workload_score * WEIGHTS["workload_capacity"]
        + sla_score * WEIGHTS["priority_sla"]
        + location_score_value * WEIGHTS["location"]
        + performance * WEIGHTS["historical_performance"]
    )
    return round(total, 2)


def decision_reasons(employee, task):
    reasons = []
    if normalize_skill_match(employee["skills"], task["required_skills"]) > 0:
        reasons.append("Required skill matched")
    if employee["availability"] == "Available":
        reasons.append("Employee is available")
    if int(employee["workload"] or 0) <= 70:
        reasons.append("Workload is within capacity")
    if employee["location"].strip().lower() == task["location"].strip().lower():
        reasons.append("Location matched")
    if int(employee["performance"] or 0) >= 80:
        reasons.append("Historical performance considered")
    if task["priority"] in ("Critical", "High") or int(task["sla_hours"] or 24) <= 6:
        reasons.append("SLA urgency considered")
    if not reasons:
        reasons.append("Best available option based on current constraints")
    return reasons


def build_candidate_reason(employee, task, score):
    reasons = decision_reasons(employee, task)
    joined = ", ".join(reasons[:5])
    return f"{employee['name']} scored {score}% because {joined}."


def evaluate_task_candidates(task, excluded_employee_ids=None):
    employees = get_employees()
    excluded = set(excluded_employee_ids or [])
    candidates = []
    for employee in employees:
        if employee["id"] in excluded:
            continue
        if employee["availability"] != "Available":
            continue
        skill = normalize_skill_match(employee["skills"], task["required_skills"])
        if skill <= 0:
            continue
        score = calculate_candidate_score(employee, task)
        candidates.append(
            {
                "employee_id": employee["id"],
                "employee_name": employee["name"],
                "score": score,
                "skill_match": skill,
                "availability": employee["availability"],
                "workload": employee["workload"],
                "location": employee["location"],
                "performance": employee["performance"],
                "reason": build_candidate_reason(employee, task, score),
                "reasons": decision_reasons(employee, task),
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def allocate_task(task_id, trigger="AI allocation"):
    task = get_task_by_id(task_id)
    if not task:
        return {"success": False, "message": "Task not found."}

    candidates = evaluate_task_candidates(task)
    if not candidates:
        insert_audit_event(
            "No suitable employee",
            "Unassigned",
            "Unassigned",
            f"No available candidate met the skill requirement for {task['name']}.",
            trigger,
        )
        return {"success": False, "message": "No suitable employee currently available. Task requires human intervention."}

    selection = candidates[0]
    employee = get_employee_by_id(selection["employee_id"])
    insert_allocation(task_id, employee["id"], selection["score"], selection["reason"])
    set_task_assignment(task_id, employee["id"])
    insert_audit_event(
        "Task assigned",
        "Unassigned",
        employee["name"],
        selection["reason"],
        trigger,
    )
    return {
        "success": True,
        "employee_id": employee["id"],
        "employee_name": employee["name"],
        "score": selection["score"],
        "reason": selection["reason"],
        "candidate_scores": candidates,
    }


def allocate_all_tasks():
    results = []
    for task in get_tasks():
        if task["status"] == "completed":
            continue
        result = allocate_task(task["id"], trigger="Manual allocation")
        results.append({"task_id": task["id"], "task_name": task["name"], **result})
    return results


def reallocate_task(task_id, trigger="Reallocation"):
    task = get_task_by_id(task_id)
    if not task:
        return {"success": False, "message": "Task not found."}

    previous_assignment = "Unassigned"
    current_allocation = None
    with get_connection() as conn:
        current_allocation = conn.execute(
            "SELECT a.*, e.name as employee_name FROM allocations a JOIN employees e ON e.id = a.employee_id WHERE a.task_id = ? AND a.status = 'active'",
            (task_id,),
        ).fetchone()
        if current_allocation:
            previous_assignment = current_allocation["employee_name"]

    candidates = evaluate_task_candidates(task, excluded_employee_ids=[current_allocation["employee_id"]] if current_allocation else [])
    if not candidates:
        insert_audit_event(
            "Reallocation failed",
            previous_assignment,
            "Unassigned",
            "No suitable employee currently available for reallocation.",
            trigger,
        )
        return {"success": False, "message": "No suitable employee currently available. Task requires human intervention."}

    selected = candidates[0]
    employee = get_employee_by_id(selected["employee_id"])
    if employee and previous_assignment == employee["name"]:
        return {"success": True, "message": "Task already assigned to the best candidate.", "employee_name": employee["name"], "score": selected["score"]}

    insert_allocation(task_id, employee["id"], selected["score"], selected["reason"])
    set_task_assignment(task_id, employee["id"])
    insert_audit_event(
        "Task reallocated",
        previous_assignment,
        employee["name"],
        selected["reason"],
        trigger,
    )

    return {
        "success": True,
        "previous_assignment": previous_assignment,
        "employee_name": employee["name"],
        "score": selected["score"],
        "reason": selected["reason"],
        "candidates": candidates,
    }


def _build_preview_after_entry(task, previous_employee_name, excluded_employee_id, trigger_name):
    candidates = evaluate_task_candidates(task, excluded_employee_ids=[excluded_employee_id])
    if not candidates:
        return {
            "task_name": task["name"],
            "priority": task["priority"],
            "sla_hours": task["sla_hours"],
            "location": task["location"],
            "previous_employee": previous_employee_name,
            "previous_assignment_status": "Unavailable",
            "proposed_employee": "No feasible replacement",
            "suitability_score": None,
            "status": "No Replacement",
            "decision": "No feasible replacement found",
            "reason": "No available employee matched the required skill and availability constraints.",
            "reasons": ["No available employee matched the required skill", "Employee availability constraint prevented reassignment", "No feasible replacement found"],
            "trigger": trigger_name,
        }

    selected = candidates[0]
    employee = get_employee_by_id(selected["employee_id"])
    return {
        "task_name": task["name"],
        "priority": task["priority"],
        "sla_hours": task["sla_hours"],
        "location": task["location"],
        "previous_employee": previous_employee_name,
        "previous_assignment_status": "Unavailable",
        "proposed_employee": employee["name"],
        "suitability_score": selected["score"],
        "status": "Reallocation Proposed",
        "decision": "Reallocation recommended",
        "reason": selected["reason"],
        "reasons": selected["reasons"],
        "trigger": trigger_name,
    }


def simulate_employee_unavailable(employee_id):
    employee = get_employee_by_id(employee_id)
    if not employee:
        return {"success": False, "message": "Employee not found."}

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT t.id, t.name, t.priority, t.location, t.required_skills, t.sla_hours, a.employee_id AS assigned_employee_id FROM tasks t JOIN allocations a ON a.task_id = t.id WHERE a.employee_id = ? AND a.status = 'active'",
            (employee_id,),
        ).fetchall()

    before = {
        "employee_name": employee["name"],
        "employee_status": "Unavailable",
        "tasks": [dict(row) for row in rows],
    }
    after = []
    for row in rows:
        task = get_task_by_id(row["id"])
        if not task:
            continue
        preview_entry = _build_preview_after_entry(task, employee["name"], employee_id, f"{employee['name']} became unavailable")
        after.append(preview_entry)

    return {
        "success": True,
        "event": f"{employee['name']} became unavailable",
        "before": before,
        "after": after,
    }


def simulate_new_critical_task(task_name, description, required_skills, location, sla_hours=1):
    task = {
        "id": None,
        "name": task_name,
        "description": description,
        "required_skills": required_skills,
        "priority": "Critical",
        "sla_hours": sla_hours,
        "location": location,
        "status": "pending",
    }
    candidates = evaluate_task_candidates(task)
    if not candidates:
        return {
            "success": True,
            "event": "New critical task detected",
            "task": task,
            "before": {"employee": "Unassigned", "status": "No Assignment"},
            "after": {
                "employee": "No feasible replacement",
                "status": "No Replacement",
                "reason": "No available employee matched the required skill requirements.",
                "suitability_score": None,
            },
        }

    selected = candidates[0]
    return {
        "success": True,
        "event": "New critical task detected",
        "task": task,
        "before": {"employee": "Unassigned", "status": "No Assignment"},
        "after": {
            "employee": selected["employee_name"],
            "status": "Reallocation Proposed",
            "reason": selected["reason"],
            "suitability_score": selected["score"],
            "reasons": selected["reasons"],
        },
    }


def extract_workload_increase_value(payload):
    for key in ("workload_increase", "workload_increase_percent", "increase_percent", "increase", "change", "scenario_value"):
        raw = payload.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if value < 0:
            return None
        return int(round(value))
    return None


def get_scenario_preview(event_type, payload):
    if event_type == "employee_unavailable":
        employee_id = int(payload.get("employee_id") or 0)
        if employee_id <= 0:
            return {"success": False, "message": "Employee id is required."}
        return simulate_employee_unavailable(employee_id)

    if event_type == "new_critical_task":
        return simulate_new_critical_task(
            payload.get("name", "Network Failure"),
            payload.get("description", "Critical network outage requiring urgent response."),
            payload.get("required_skills", "Networking"),
            payload.get("location", "Chennai"),
            int(payload.get("sla_hours", 1)),
        )

    if event_type == "priority_change":
        task_id = int(payload.get("task_id") or 0)
        task = get_task_by_id(task_id)
        if not task:
            return {"success": False, "message": "Task not found."}
        previous_priority = task["priority"]
        new_priority = payload.get("priority", previous_priority)
        temp_task = dict(task)
        temp_task["priority"] = new_priority
        candidates = evaluate_task_candidates(temp_task)
        if not candidates:
            return {
                "success": True,
                "event": "Priority change preview",
                "task_name": task["name"],
                "before": {"priority": previous_priority, "employee": "Current assignment"},
                "after": {"priority": new_priority, "employee": "No feasible replacement", "reason": "No candidate matched the required skills under the new urgency.", "status": "No Replacement"},
            }
        selected = candidates[0]
        return {
            "success": True,
            "event": "Priority change preview",
            "task_name": task["name"],
            "before": {"priority": previous_priority, "employee": "Current assignment"},
            "after": {"priority": new_priority, "employee": selected["employee_name"], "score": selected["score"], "reason": selected["reason"], "status": "Reallocation Proposed"},
        }

    if event_type == "sla_urgent":
        task_id = int(payload.get("task_id") or 0)
        task = get_task_by_id(task_id)
        if not task:
            return {"success": False, "message": "Task not found."}
        previous_hours = int(task["sla_hours"])
        new_hours = int(payload.get("sla_hours", previous_hours))
        temp_task = dict(task)
        temp_task["sla_hours"] = new_hours
        candidates = evaluate_task_candidates(temp_task)
        if not candidates:
            return {
                "success": True,
                "event": "SLA urgency preview",
                "task_name": task["name"],
                "before": {"sla_hours": previous_hours, "employee": "Current assignment"},
                "after": {"sla_hours": new_hours, "employee": "No feasible replacement", "reason": "SLA urgency increased and no valid replacement matched the constraints.", "status": "No Replacement"},
            }
        selected = candidates[0]
        return {
            "success": True,
            "event": "SLA urgency preview",
            "task_name": task["name"],
            "before": {"sla_hours": previous_hours, "employee": "Current assignment"},
            "after": {"sla_hours": new_hours, "employee": selected["employee_name"], "score": selected["score"], "reason": selected["reason"], "status": "Reallocation Proposed"},
        }

    if event_type == "workload_increase":
        employee_id = int(payload.get("employee_id") or 0)
        if employee_id <= 0:
            return {"success": False, "message": "Employee is required for the workload simulation."}

        employee = get_employee_by_id(employee_id)
        if not employee:
            return {"success": False, "message": "Employee not found."}

        increase = extract_workload_increase_value(payload)
        if increase is None:
            return {"success": False, "message": "Please enter a numeric workload increase between 1% and 100%."}
        if increase < 1 or increase > 100:
            return {"success": False, "message": "Workload increase must be between 1% and 100%."}

        before_workload = int(employee["workload"] or 0)
        requested_change = increase
        effective_workload = min(100, before_workload + requested_change)
        effective_change = max(0, effective_workload - before_workload)
        capacity_capped = before_workload >= 100 or effective_workload >= 100

        with get_connection() as conn:
            assigned_tasks = conn.execute(
                """
                SELECT t.id, t.name, t.priority, t.sla_hours, t.location
                FROM tasks t
                JOIN allocations a ON a.task_id = t.id
                WHERE a.employee_id = ? AND a.status = 'active'
                ORDER BY t.priority DESC
                """,
                (employee_id,),
            ).fetchall()

        affected_tasks = len(assigned_tasks)
        impact_message = "No active tasks require reassignment." if affected_tasks == 0 else f"{affected_tasks} active task(s) may need review."

        if capacity_capped and before_workload >= 100:
            decision = "Employee is already at maximum workload capacity."
            reason = "The workload increase is capped at 100%; the employee cannot exceed maximum workload capacity."
            explanation = (
                f"{employee['name']}'s workload is already at 100%, so the requested increase of +{requested_change}% is capped at 100%."
            )
        elif capacity_capped:
            decision = "Workload capacity reached; assignment review is recommended."
            reason = "The requested increase exceeds the remaining capacity, so the effective workload is capped at 100%."
            explanation = (
                f"{employee['name']}'s workload would rise from {before_workload}% to 100% because the workload cap was reached before the full requested increase could be applied."
            )
        elif new_workload := effective_workload:
            decision = "No reallocation required."
            reason = f"The employee remains within capacity after the workload increase." if effective_workload < 80 else "The employee is approaching capacity, but the current assignments remain acceptable for this preview."
            explanation = (
                f"{employee['name']}'s workload would rise from {before_workload}% to {effective_workload}% without exceeding the capacity threshold."
            )
        else:
            decision = "No reallocation required."
            reason = "The requested workload change does not require reallocation."
            explanation = f"{employee['name']}'s workload was not changed enough to require reassignment."

        return {
            "success": True,
            "scenario": "Employee workload increases",
            "event": "Workload increase preview",
            "employee": employee["name"],
            "employee_id": employee_id,
            "requested_change": requested_change,
            "effective_change": effective_change,
            "before": {"employee": employee["name"], "workload": before_workload},
            "after": {"employee": employee["name"], "workload": effective_workload},
            "impact": {
                "affected_tasks": affected_tasks,
                "message": impact_message,
                "sla_risk": "High" if effective_workload >= 80 else "Low",
                "capacity_reached": capacity_capped,
                "requested_change": requested_change,
                "effective_workload": effective_workload,
            },
            "decision": decision,
            "reason": reason,
            "explanation": explanation,
        }

    return {"success": False, "message": "Unsupported scenario type."}
