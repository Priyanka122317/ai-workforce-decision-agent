import json
import os
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for

from ai_agent import generate_decision_explanation, summarize_scenario
from allocation_engine import (
    allocate_all_tasks,
    allocate_task,
    evaluate_task_candidates,
    extract_workload_increase_value,
    get_scenario_preview,
    reallocate_task,
)
from database import (
    create_employee,
    create_task,
    delete_employee,
    delete_task,
    get_alerts,
    get_audit_logs,
    get_allocation_summary,
    get_dashboard_summary,
    get_connection,
    get_employee_by_id,
    get_employees,
    get_task_by_id,
    get_tasks,
    init_db,
    insert_audit_event,
    mark_task_complete,
    update_employee,
    update_employee_availability,
    update_task,
)
from optimization_engine import optimize_workforce_plan

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")

init_db()


@app.route("/")
def index():
    dashboard = get_dashboard_summary()
    return render_template("dashboard.html", **dashboard)


@app.route("/employees")
def employees_page():
    employees = get_employees()
    return render_template("employees.html", employees=employees)


@app.route("/employees", methods=["POST"])
def employees_add():
    payload = request.form.to_dict()
    try:
        create_employee(payload)
        insert_audit_event(
            "Employee added",
            "N/A",
            payload.get("name"),
            "New employee profile created.",
            "Manual employee management",
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return redirect(url_for("employees_page"))


@app.route("/employee/<int:employee_id>/availability", methods=["POST"])
def update_availability(employee_id):
    value = (request.form.get("availability") or "Available").strip()
    employee = get_employee_by_id(employee_id)
    if not employee:
        return jsonify({"success": False, "message": "Employee not found."}), 404

    update_employee_availability(employee_id, value)
    insert_audit_event(
        "Employee availability changed",
        employee["availability"],
        value,
        f"Availability updated for {employee['name']}.",
        "Manual adjustment",
    )
    return redirect(url_for("employees_page"))


@app.route("/employees/<int:employee_id>/edit", methods=["POST"])
def employees_edit(employee_id):
    payload = request.form.to_dict()
    employee = get_employee_by_id(employee_id)
    if not employee:
        return jsonify({"success": False, "message": "Employee not found."}), 404
    try:
        update_employee(employee_id, payload)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    insert_audit_event(
        "Employee updated",
        employee["name"],
        payload.get("name", employee["name"]),
        "Employee profile updated.",
        "Manual employee management",
    )
    return redirect(url_for("employees_page"))


@app.route("/employees/<int:employee_id>/delete", methods=["POST"])
def employees_delete(employee_id):
    employee = get_employee_by_id(employee_id)
    if not employee:
        return jsonify({"success": False, "message": "Employee not found."}), 404
    delete_employee(employee_id)
    insert_audit_event(
        "Employee deleted",
        employee["name"],
        "Deleted",
        "Employee profile removed from the system.",
        "Manual employee management",
    )
    return redirect(url_for("employees_page"))


@app.route("/tasks")
def tasks_page():
    tasks = get_tasks()
    return render_template("tasks.html", tasks=tasks)


@app.route("/tasks", methods=["POST"])
def tasks_add():
    payload = request.form.to_dict()
    try:
        task_id = create_task(payload)
        task = get_task_by_id(task_id)
        insert_audit_event(
            "Task created",
            "N/A",
            task["name"],
            "New task added to the workforce queue.",
            "Task management",
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return redirect(url_for("tasks_page"))


@app.route("/tasks/<int:task_id>/complete", methods=["POST"])
def task_complete(task_id):
    task = get_task_by_id(task_id)
    if not task:
        return jsonify({"success": False, "message": "Task not found."}), 404

    result = mark_task_complete(task_id)
    if not result.get("success"):
        return redirect(url_for("tasks_page"))

    return redirect(url_for("tasks_page", message="Task completed. Employee workload recalculated."))


@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
def api_task_complete(task_id):
    task = get_task_by_id(task_id)
    if not task:
        return jsonify({"success": False, "message": "Task not found."}), 404

    result = mark_task_complete(task_id)
    if not result.get("success"):
        return jsonify(result), 200 if result.get("message") == "Task is already completed." else 400
    return jsonify(result)


@app.route("/tasks/<int:task_id>/edit", methods=["POST"])
def tasks_edit(task_id):
    task = get_task_by_id(task_id)
    if not task:
        return jsonify({"success": False, "message": "Task not found."}), 404
    try:
        update_task(task_id, request.form.to_dict())
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    insert_audit_event(
        "Task updated",
        task["name"],
        request.form.get("name", task["name"]),
        "Task details were refreshed to match current requirements.",
        "Task management",
    )
    return redirect(url_for("tasks_page"))


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
def tasks_delete(task_id):
    task = get_task_by_id(task_id)
    if not task:
        return jsonify({"success": False, "message": "Task not found."}), 404
    delete_task(task_id)
    insert_audit_event(
        "Task deleted",
        task["name"],
        "Deleted",
        "Task removed from the task queue.",
        "Task management",
    )
    return redirect(url_for("tasks_page"))


@app.route("/allocations")
def allocations_page():
    rows = get_allocation_summary()
    for row in rows:
        row["reason_text"] = row.get("reason") or "No reason recorded."
        row["status_label"] = "Allocated" if row.get("status") == "pending" else row.get("status", "Allocated")
    return render_template("allocations.html", allocations=rows)


@app.route("/audit")
def audit_page():
    logs = get_audit_logs()
    return render_template("audit.html", logs=logs)


@app.route("/scenarios")
def scenarios_page():
    employees = get_employees()
    tasks = get_tasks()
    return render_template("scenarios.html", employees=employees, tasks=tasks)


@app.route("/alerts")
def alerts_page():
    return render_template("alerts.html", alerts=get_alerts())


@app.route("/digital-twin")
def digital_twin_page():
    employees = get_employees()
    tasks = get_tasks()
    return render_template("digital_twin.html", employees=employees, tasks=tasks)


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/about")
def about_page():
    return render_template("about.html")


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(get_dashboard_summary())


@app.route("/api/employees", methods=["GET", "POST", "PUT", "DELETE"])
def api_employees():
    if request.method == "GET":
        return jsonify({"items": get_employees()})
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    if request.method == "POST":
        try:
            employee_id = create_employee(payload)
            return jsonify({"success": True, "employee_id": employee_id}), 201
        except ValueError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
    if request.method == "PUT":
        employee_id = int(payload.get("id") or 0)
        if not employee_id:
            return jsonify({"success": False, "message": "Employee id is required."}), 400
        try:
            update_employee(employee_id, payload)
            return jsonify({"success": True, "employee_id": employee_id})
        except ValueError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
    employee_id = int(request.args.get("id") or payload.get("id") or 0)
    if not employee_id:
        return jsonify({"success": False, "message": "Employee id is required."}), 400
    delete_employee(employee_id)
    return jsonify({"success": True, "employee_id": employee_id})


@app.route("/api/tasks", methods=["GET", "POST", "PUT", "DELETE"])
def api_tasks():
    if request.method == "GET":
        return jsonify({"items": get_tasks()})
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    if request.method == "POST":
        try:
            task_id = create_task(payload)
            return jsonify({"success": True, "task_id": task_id}), 201
        except ValueError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
    if request.method == "PUT":
        task_id = int(payload.get("id") or 0)
        if not task_id:
            return jsonify({"success": False, "message": "Task id is required."}), 400
        try:
            update_task(task_id, payload)
            return jsonify({"success": True, "task_id": task_id})
        except ValueError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
    task_id = int(request.args.get("id") or payload.get("id") or 0)
    if not task_id:
        return jsonify({"success": False, "message": "Task id is required."}), 400
    delete_task(task_id)
    return jsonify({"success": True, "task_id": task_id})


@app.route("/api/allocations")
def api_allocations():
    return jsonify({"items": get_allocation_summary()})


@app.route("/api/audit")
def api_audit():
    return jsonify({"items": get_audit_logs()})


@app.route("/api/alerts")
def api_alerts():
    return jsonify({"items": get_alerts()})


@app.route("/api/optimize")
def api_optimize():
    result = optimize_workforce_plan()
    return jsonify(result)


@app.route("/api/allocate", methods=["POST"])
def api_allocate():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    task_id = payload.get("task_id")
    if task_id:
        return jsonify(allocate_task(int(task_id), trigger="API manual allocation"))
    results = []
    for task in get_tasks():
        if task["status"] == "completed":
            continue
        result = allocate_task(task["id"], trigger="API allocation")
        results.append({"task_id": task["id"], "task_name": task["name"], **result})
    return jsonify({"success": True, "results": results})


@app.route("/api/reallocate", methods=["POST"])
def api_reallocate():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    task_id = int(payload.get("task_id") or 0)
    if not task_id:
        return jsonify({"success": False, "message": "Task id is required."}), 400
    return jsonify(reallocate_task(task_id, trigger="API reallocation"))


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    scenario_type = payload.get("scenario_type") or "employee_unavailable"
    preview = get_scenario_preview(scenario_type, payload)
    if not preview.get("success"):
        return jsonify(preview), 400
    preview["summary"] = summarize_scenario(scenario_type, json.dumps(preview, default=str))
    return jsonify(preview)


@app.route("/api/apply-simulation", methods=["POST"])
def api_apply_simulation():
    return apply_simulation_endpoint()


@app.route("/allocate", methods=["POST"])
def allocate_endpoint():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    task_id = payload.get("task_id")
    if task_id:
        result = allocate_task(int(task_id), trigger="Manual allocation")
        return jsonify(result)

    results = []
    for task in get_tasks():
        if task["status"] == "completed":
            continue
        result = allocate_task(task["id"], trigger="Task queue allocation")
        results.append({"task_id": task["id"], "task_name": task["name"], **result})
    return jsonify({"success": True, "results": results})


@app.route("/reallocate", methods=["POST"])
def reallocate_endpoint():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    task_id = int(payload.get("task_id") or 0)
    if not task_id:
        return jsonify({"success": False, "message": "Task id is required."}), 400
    result = reallocate_task(task_id, trigger="Manual reallocation")
    return jsonify(result)


@app.route("/simulate", methods=["POST"])
def simulate_endpoint():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    scenario_type = payload.get("scenario_type") or "employee_unavailable"
    preview = get_scenario_preview(scenario_type, payload)
    if not preview.get("success"):
        return jsonify(preview), 400
    summary = summarize_scenario(scenario_type, json.dumps(preview, default=str))
    preview["summary"] = summary
    return jsonify(preview)


@app.route("/apply-simulation", methods=["POST"])
def apply_simulation_endpoint():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    scenario_type = payload.get("scenario_type") or "employee_unavailable"
    if scenario_type == "employee_unavailable":
        employee_id = int(payload.get("employee_id") or 0)
        if employee_id <= 0:
            return jsonify({"success": False, "message": "Employee id is required."}), 400
        employee = get_employee_by_id(employee_id)
        if not employee:
            return jsonify({"success": False, "message": "Employee not found."}), 404
        update_employee_availability(employee_id, "Unavailable")
        for task in get_tasks():
            if task["status"] == "completed":
                continue
            assigned_emp = task["assigned_employee_id"]
            if assigned_emp == employee_id:
                reallocate_task(task["id"], trigger="Applied scenario: employee unavailable")
        insert_audit_event(
            "Scenario applied",
            employee["name"],
            "Unavailable",
            "Employee availability changed and dependent tasks were re-evaluated.",
            "Scenario simulator",
        )
        return jsonify({"success": True, "message": "Scenario applied successfully."})

    if scenario_type == "new_critical_task":
        task_id = create_task(
            {
                "name": payload.get("name", "Network Failure"),
                "description": payload.get("description", "Critical outage requiring immediate action."),
                "required_skills": payload.get("required_skills", "Networking"),
                "priority": "Critical",
                "sla_hours": int(payload.get("sla_hours", 1)),
                "location": payload.get("location", "Chennai"),
            }
        )
        result = allocate_task(task_id, trigger="Applied scenario: new critical task")
        insert_audit_event(
            "Critical task arrived",
            "N/A",
            payload.get("name", "Network Failure"),
            result.get("employee_name", "Unassigned"),
            "Scenario simulator",
        )
        return jsonify({"success": True, "message": "Critical task applied successfully.", "task_id": task_id, "result": result})

    if scenario_type == "priority_change":
        task_id = int(payload.get("task_id") or 0)
        task = get_task_by_id(task_id)
        if not task:
            return jsonify({"success": False, "message": "Task not found."}), 404
        new_priority = payload.get("priority", task["priority"])
        with get_connection() as conn:
            conn.execute("UPDATE tasks SET priority = ? WHERE id = ?", (new_priority, task_id))
        insert_audit_event(
            "Priority change applied",
            task["priority"],
            new_priority,
            "Priority was adjusted and the workforce plan was re-evaluated for impact.",
            "Scenario simulator",
        )
        return jsonify({"success": True, "message": "Priority change applied."})

    if scenario_type == "workload_increase":
        employee_id = int(payload.get("employee_id") or 0)
        employee = get_employee_by_id(employee_id)
        if not employee:
            return jsonify({"success": False, "message": "Employee not found."}), 404

        requested_increase = extract_workload_increase_value(payload)
        if requested_increase is None or requested_increase < 1 or requested_increase > 100:
            return jsonify({"success": False, "message": "Workload increase must be a numeric value between 1% and 100%."}), 400

        new_workload = min(100, int(employee["workload"]) + requested_increase)
        with get_connection() as conn:
            conn.execute("UPDATE employees SET workload = ? WHERE id = ?", (new_workload, employee_id))
        insert_audit_event(
            "Workload changed",
            str(employee["workload"]),
            str(new_workload),
            "Workload increased and dependent assignments were reviewed.",
            "Scenario simulator",
        )
        return jsonify({"success": True, "message": "Workload adjustment applied.", "new_workload": new_workload})

    if scenario_type == "sla_urgent":
        task_id = int(payload.get("task_id") or 0)
        task = get_task_by_id(task_id)
        if not task:
            return jsonify({"success": False, "message": "Task not found."}), 404
        new_sla = int(payload.get("sla_hours", 1))
        with get_connection() as conn:
            conn.execute("UPDATE tasks SET sla_hours = ? WHERE id = ?", (new_sla, task_id))
        insert_audit_event(
            "SLA adjusted",
            str(task["sla_hours"]),
            str(new_sla),
            "Task urgency was increased and the plan was re-evaluated for SLA risk.",
            "Scenario simulator",
        )
        return jsonify({"success": True, "message": "SLA urgency applied."})

    return jsonify({"success": False, "message": "Unsupported scenario type."}), 400


@app.route("/demo", methods=["POST"])
def demo_scenario():
    try:
        from database import get_connection
        from allocation_engine import allocate_task, reallocate_task

        with get_connection() as conn:
            conn.execute("DELETE FROM allocations")
            conn.execute("DELETE FROM audit_logs")
            conn.execute("UPDATE tasks SET status = 'pending', assigned_employee_id = NULL")
            conn.execute("UPDATE employees SET availability = 'Available', workload = CASE name WHEN 'Arun' THEN 30 WHEN 'Priya' THEN 60 WHEN 'Kavi' THEN 40 WHEN 'Rahul' THEN 75 WHEN 'Meena' THEN 20 ELSE workload END")

        for task in get_tasks():
            if task["status"] == "completed":
                continue
            allocate_task(task["id"], trigger="Demo initial allocation")

        critical_task_id = create_task(
            {
                "name": "Network Failure",
                "description": "Critical outage in the Chennai network segment requiring urgent attention.",
                "required_skills": "Networking",
                "priority": "Critical",
                "sla_hours": 1,
                "location": "Chennai",
            }
        )
        allocate_task(critical_task_id, trigger="Demo critical event")

        employee = get_employee_by_id(1)
        if employee:
            update_employee_availability(employee["id"], "Unavailable")
            for task in get_tasks():
                if task["assigned_employee_id"] == employee["id"]:
                    reallocate_task(task["id"], trigger="Demo employee unavailable")

        summary = "Demo scenario completed: initial allocation, critical task reallocation, and employee unavailability handling were processed successfully."
        return jsonify({"success": True, "summary": summary})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
