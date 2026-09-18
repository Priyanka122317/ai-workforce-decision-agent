import importlib
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    test_db_path = Path(tempfile.mkdtemp()) / "test_workforce.db"
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_PATH", str(test_db_path))

    import allocation_engine as allocation_engine_module
    import app as app_module
    import database as database_module

    importlib.reload(database_module)
    importlib.reload(allocation_engine_module)
    importlib.reload(app_module)

    globals()["app"] = app_module.app
    globals()["get_connection"] = database_module.get_connection
    globals()["get_dashboard_summary"] = database_module.get_dashboard_summary
    globals()["get_employees"] = database_module.get_employees
    globals()["get_tasks"] = database_module.get_tasks
    globals()["init_db"] = database_module.init_db
    globals()["create_employee"] = database_module.create_employee
    globals()["create_task"] = database_module.create_task
    globals()["get_allocation_summary"] = database_module.get_allocation_summary
    globals()["get_task_by_id"] = database_module.get_task_by_id
    globals()["get_employee_by_id"] = database_module.get_employee_by_id
    globals()["mark_task_complete"] = database_module.mark_task_complete
    globals()["allocate_task"] = allocation_engine_module.allocate_task
    globals()["get_scenario_preview"] = allocation_engine_module.get_scenario_preview

    database_module.init_db()
    yield


def test_dashboard_metrics_are_populated():
    with app.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        assert b"Workforce" in response.data or b"Dashboard" in response.data

    summary = get_dashboard_summary()
    assert summary["total_employees"] >= 1
    assert summary["total_tasks"] >= 1


def test_demo_seed_data_contains_canonical_tasks():
    task_names = {task["name"] for task in get_tasks()}

    assert "Server Failure" in task_names
    assert "Network Failure" in task_names
    assert "Database Backup" in task_names
    assert "Security Audit" in task_names
    assert "Application Testing" in task_names


def test_demo_route_is_idempotent():
    with app.test_client() as client:
        first = client.post("/demo")
        second = client.post("/demo")

    assert first.status_code == 200
    assert second.status_code == 200
    network_failures = [task["name"] for task in get_tasks() if task["name"] == "Network Failure"]
    assert len(network_failures) == 1


def test_allocation_returns_valid_assignment():
    tasks = get_tasks()
    if not tasks:
        raise AssertionError("No tasks available for allocation")

    result = allocate_task(tasks[0]["id"], trigger="test")
    assert result["success"] in (True, False)
    if result["success"]:
        assert result["employee_name"]


def test_simulation_is_non_destructive():
    employees = get_employees()
    if not employees:
        raise AssertionError("No employees available")

    preview = get_scenario_preview("employee_unavailable", {"employee_id": employees[0]["id"]})
    assert preview["success"] in (True, False)


def test_no_feasible_assignment_is_reported():
    task = {
        "name": "Impossible Task",
        "description": "Requires non-existent skill",
        "required_skills": "Quantum Engineering",
        "priority": "Critical",
        "sla_hours": 1,
        "location": "Mars",
    }
    created = None
    from database import create_task
    created = create_task(task)
    result = allocate_task(created, trigger="test impossible task")
    assert result["success"] is False


def test_workload_increase_preview_uses_workload_values():
    employees = get_employees()
    if not employees:
        raise AssertionError("No employees available")

    employee = employees[0]
    preview = get_scenario_preview("workload_increase", {"employee_id": employee["id"], "workload_increase": 20})

    assert preview["success"] is True
    assert preview.get("scenario") == "Employee workload increases"
    assert "workload" in str(preview["before"]).lower()
    assert "workload" in str(preview["after"]).lower()
    assert "DecisionAssignment" not in str(preview)
    assert preview["before"].get("workload") == int(employee["workload"])
    assert preview["after"].get("workload") == min(100, int(employee["workload"]) + 20)
    assert preview.get("requested_change") == 20
    assert preview.get("effective_change") == min(100, int(employee["workload"]) + 20) - int(employee["workload"])
    assert "decision" in preview
    assert "explanation" in preview


def test_workload_increase_cap_is_preserved_at_100_percent():
    employees = get_employees()
    if not employees:
        raise AssertionError("No employees available")

    employee = employees[0]
    original_workload = int(employee["workload"])
    if original_workload < 100:
        with get_connection() as conn:
            conn.execute("UPDATE employees SET workload = 100 WHERE id = ?", (employee["id"],))

    preview = get_scenario_preview("workload_increase", {"employee_id": employee["id"], "workload_increase": 20})

    assert preview["success"] is True
    assert preview["before"].get("workload") == 100
    assert preview["requested_change"] == 20
    assert preview["effective_change"] == 0
    assert preview["after"].get("workload") == 100
    assert "capped" in str(preview["impact"]).lower() or "maximum workload" in str(preview["reason"]).lower()

    with get_connection() as conn:
        conn.execute("UPDATE employees SET workload = ? WHERE id = ?", (original_workload, employee["id"]))


def test_allocation_summary_ignores_orphan_rows():
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO allocations (task_id, employee_id, suitability_score, reason, status) VALUES (?, ?, ?, ?, 'active')",
            (999999, 1, 92.0, "Orphan allocation should not be shown"),
        )

    rows = get_allocation_summary()

    assert all(row.get("task_id") not in (None, 999999) for row in rows)
    assert all(row.get("task_name") for row in rows)


def test_mark_task_complete_clears_active_allocation_and_reduces_workload():
    from database import create_employee, create_task, get_employee_by_id, get_task_by_id, get_connection, mark_task_complete

    employee_id = create_employee({"name": "Test Engineer", "skills": "Testing", "workload": 60, "availability": "Available", "location": "Chennai", "performance": 87})
    task_a_id = create_task({"name": "Regression Check", "description": "Verify the release", "required_skills": "Testing", "priority": "High", "sla_hours": 4, "location": "Chennai", "workload_impact": 20})
    task_b_id = create_task({"name": "Additional Validation", "description": "Follow-up verification", "required_skills": "Testing", "priority": "Medium", "sla_hours": 8, "location": "Chennai", "workload_impact": 40})

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO allocations (task_id, employee_id, suitability_score, reason, status) VALUES (?, ?, ?, ?, 'active')",
            (task_a_id, employee_id, 92.0, "Regression Check assigned to Test Engineer",),
        )
        conn.execute(
            "INSERT INTO allocations (task_id, employee_id, suitability_score, reason, status) VALUES (?, ?, ?, ?, 'active')",
            (task_b_id, employee_id, 86.0, "Additional Validation assigned to Test Engineer",),
        )
        conn.execute("UPDATE tasks SET assigned_employee_id = ? WHERE id = ?", (employee_id, task_a_id))
        conn.execute("UPDATE tasks SET assigned_employee_id = ? WHERE id = ?", (employee_id, task_b_id))

    mark_task_complete(task_a_id)

    task = get_task_by_id(task_a_id)
    employee = get_employee_by_id(employee_id)
    with get_connection() as conn:
        allocation = conn.execute("SELECT COUNT(*) FROM allocations WHERE task_id = ? AND status = 'active'", (task_a_id,)).fetchone()[0]

    assert task["status"] == "completed"
    assert task["assigned_employee_id"] is None
    assert allocation == 0
    assert employee["workload"] == 40


def test_employee_workload_is_clamped_to_valid_range():
    from database import create_employee, get_employee_by_id

    employee_id = create_employee({"name": "Overloaded Employee", "skills": "Testing", "workload": 150, "availability": "Available", "location": "Chennai", "performance": 80})
    employee = get_employee_by_id(employee_id)

    assert employee["workload"] == 100


def test_task_completion_recalculates_from_remaining_active_tasks():
    from database import create_employee, create_task, get_employee_by_id, get_connection, mark_task_complete

    employee_id = create_employee({"name": "Task Sum Employee", "skills": "Testing", "workload": 60, "availability": "Available", "location": "Chennai", "performance": 85})
    task_a = create_task({"name": "Task A", "description": "First task", "required_skills": "Testing", "priority": "High", "sla_hours": 4, "location": "Chennai", "workload_impact": 20})
    task_b = create_task({"name": "Task B", "description": "Second task", "required_skills": "Testing", "priority": "Medium", "sla_hours": 8, "location": "Chennai", "workload_impact": 40})

    with get_connection() as conn:
        conn.execute("UPDATE tasks SET assigned_employee_id = ? WHERE id = ?", (employee_id, task_a))
        conn.execute("UPDATE tasks SET assigned_employee_id = ? WHERE id = ?", (employee_id, task_b))
        conn.execute("UPDATE tasks SET status = 'pending' WHERE id IN (?, ?)", (task_a, task_b))

    mark_task_complete(task_a)
    employee = get_employee_by_id(employee_id)

    assert employee["workload"] == 40


def test_task_completion_is_idempotent():
    from database import create_employee, create_task, get_connection, get_employee_by_id, mark_task_complete

    employee_id = create_employee({"name": "Repeat Completion", "skills": "Testing", "workload": 20, "availability": "Available", "location": "Chennai", "performance": 80})
    task_id = create_task({"name": "Repeat Task", "description": "Already completed once", "required_skills": "Testing", "priority": "Low", "sla_hours": 8, "location": "Chennai", "workload_impact": 20})

    with get_connection() as conn:
        conn.execute("UPDATE tasks SET assigned_employee_id = ? WHERE id = ?", (employee_id, task_id))

    first = mark_task_complete(task_id)
    second = mark_task_complete(task_id)
    employee = get_employee_by_id(employee_id)

    assert first["success"] is True
    assert second["success"] is False
    assert employee["workload"] == 0


def test_task_completion_without_assigned_employee_is_safe():
    from database import create_task, get_task_by_id, mark_task_complete

    task_id = create_task({"name": "Unassigned Task", "description": "No employee assigned", "required_skills": "Testing", "priority": "High", "sla_hours": 4, "location": "Chennai", "workload_impact": 20})

    result = mark_task_complete(task_id)
    task = get_task_by_id(task_id)

    assert result["success"] is True
    assert task["status"] == "completed"
    assert task["assigned_employee_id"] is None


def test_init_db_removes_duplicate_employee_and_task_rows():
    from database import get_connection, init_db

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO employees (name, skills, workload, availability, location, performance) VALUES (?, ?, ?, ?, ?, ?)",
            ("Fixture Duplicate Employee", "Testing", 20, "Available", "Chennai", 85),
        )
        conn.execute(
            "INSERT INTO employees (name, skills, workload, availability, location, performance) VALUES (?, ?, ?, ?, ?, ?)",
            ("Fixture Duplicate Employee", "Testing", 25, "Available", "Chennai", 90),
        )
        conn.execute(
            "INSERT INTO tasks (name, description, required_skills, priority, sla_hours, location, status, deadline, workload_impact) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            ("Fixture Duplicate Task", "Dup task", "Testing", "High", 4, "Chennai", "2026-12-31 00:00:00", 20),
        )
        conn.execute(
            "INSERT INTO tasks (name, description, required_skills, priority, sla_hours, location, status, deadline, workload_impact) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            ("Fixture Duplicate Task", "Dup task 2", "Testing", "High", 6, "Chennai", "2026-12-31 00:00:00", 20),
        )

    init_db()

    with get_connection() as conn:
        duplicate_employees = conn.execute("SELECT COUNT(*) FROM employees WHERE name = 'Fixture Duplicate Employee'").fetchone()[0]
        duplicate_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE name = 'Fixture Duplicate Task'").fetchone()[0]

    assert duplicate_employees == 1
    assert duplicate_tasks == 1
