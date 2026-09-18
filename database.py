import os
import sqlite3
from pathlib import Path

from data.seed_data import seed_employee_data, seed_task_data

BASE_DIR = Path(__file__).resolve().parent
RAW_DB_PATH = os.getenv("DATABASE_PATH")
DB_PATH = Path(RAW_DB_PATH).resolve() if RAW_DB_PATH else BASE_DIR / "workforce.db"
if not DB_PATH.is_absolute():
    DB_PATH = (BASE_DIR / DB_PATH).resolve()


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                skills TEXT NOT NULL,
                workload INTEGER NOT NULL DEFAULT 0,
                availability TEXT NOT NULL DEFAULT 'Available',
                location TEXT NOT NULL,
                performance INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                required_skills TEXT NOT NULL,
                priority TEXT NOT NULL,
                sla_hours INTEGER NOT NULL,
                location TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                deadline TEXT,
                assigned_employee_id INTEGER,
                workload_impact INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (assigned_employee_id) REFERENCES employees(id)
            )
            """
        )

        task_columns = conn.execute("PRAGMA table_info(tasks)").fetchall()
        if not any(column[1] == "workload_impact" for column in task_columns):
            conn.execute("ALTER TABLE tasks ADD COLUMN workload_impact INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            "UPDATE tasks SET workload_impact = 0 WHERE workload_impact IS NULL"
        )

        for row in conn.execute("SELECT id, priority FROM tasks WHERE workload_impact <= 0 OR workload_impact IS NULL").fetchall():
            workload = task_priority_workload(row["priority"])
            conn.execute("UPDATE tasks SET workload_impact = ? WHERE id = ?", (workload, row["id"]))

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                employee_id INTEGER NOT NULL,
                suitability_score REAL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                FOREIGN KEY (employee_id) REFERENCES employees(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL,
                previous_assignment TEXT,
                new_assignment TEXT,
                reason TEXT,
                trigger TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    seed_default_data_if_empty()
    cleanup_test_generated_records()
    cleanup_duplicate_records()
    cleanup_orphan_allocations()


def cleanup_test_generated_records():
    test_employee_names = (
        "Duplicate Employee",
        "Overloaded Employee",
        "Repeat Completion",
        "Task Sum Employee",
        "Test Engineer",
    )
    test_task_names = (
        "Impossible Task",
        "Regression Check",
        "Task A",
        "Task B",
        "Repeat Task",
        "Unassigned Task",
        "Additional Validation",
        "Duplicate Task",
    )

    with get_connection() as conn:
        employee_ids = conn.execute(
            "SELECT id FROM employees WHERE name IN ({})".format(", ".join("?" for _ in test_employee_names)),
            test_employee_names,
        ).fetchall()
        employee_id_values = [row["id"] for row in employee_ids]

        if employee_id_values:
            placeholders = ", ".join("?" for _ in employee_id_values)
            conn.execute(f"DELETE FROM allocations WHERE employee_id IN ({placeholders})", employee_id_values)
            conn.execute(f"UPDATE tasks SET assigned_employee_id = NULL WHERE assigned_employee_id IN ({placeholders})", employee_id_values)

        task_ids = conn.execute(
            "SELECT id FROM tasks WHERE name IN ({})".format(", ".join("?" for _ in test_task_names)),
            test_task_names,
        ).fetchall()
        task_id_values = [row["id"] for row in task_ids]

        if task_id_values:
            placeholders = ", ".join("?" for _ in task_id_values)
            conn.execute(f"DELETE FROM allocations WHERE task_id IN ({placeholders})", task_id_values)
            conn.execute(f"UPDATE tasks SET assigned_employee_id = NULL WHERE id IN ({placeholders})", task_id_values)

        conn.execute(
            "DELETE FROM tasks WHERE name IN ({})".format(", ".join("?" for _ in test_task_names)),
            test_task_names,
        )
        conn.execute(
            "DELETE FROM employees WHERE name IN ({})".format(", ".join("?" for _ in test_employee_names)),
            test_employee_names,
        )


def cleanup_duplicate_records():
    with get_connection() as conn:
        employee_rows = conn.execute(
            "SELECT * FROM employees ORDER BY id"
        ).fetchall()
        seen_employees = {}
        for employee in employee_rows:
            key = (employee["name"] or "").strip().lower()
            if not key:
                continue
            if key in seen_employees:
                keep_id = seen_employees[key]
                keep_employee = conn.execute("SELECT * FROM employees WHERE id = ?", (keep_id,)).fetchone()
                if keep_employee:
                    merged_workload = max(normalize_workload(keep_employee["workload"]), normalize_workload(employee["workload"]))
                    merged_performance = max(int(keep_employee["performance"] or 0), int(employee["performance"] or 0))
                    merged_skills = (keep_employee["skills"] or "").strip() or (employee["skills"] or "").strip()
                    merged_location = (keep_employee["location"] or "").strip() or (employee["location"] or "").strip()
                    merged_availability = "Unavailable" if keep_employee["availability"] != "Available" or employee["availability"] != "Available" else "Available"

                    conn.execute(
                        "UPDATE employees SET skills = ?, workload = ?, availability = ?, location = ?, performance = ? WHERE id = ?",
                        (merged_skills, merged_workload, merged_availability, merged_location, merged_performance, keep_id),
                    )
                    conn.execute("UPDATE tasks SET assigned_employee_id = ? WHERE assigned_employee_id = ?", (keep_id, employee["id"]))
                    conn.execute("UPDATE allocations SET employee_id = ? WHERE employee_id = ?", (keep_id, employee["id"]))
                    conn.execute("DELETE FROM employees WHERE id = ?", (employee["id"],))
                else:
                    seen_employees[key] = employee["id"]
            else:
                seen_employees[key] = employee["id"]

        task_rows = conn.execute(
            "SELECT * FROM tasks ORDER BY id"
        ).fetchall()
        seen_tasks = {}
        for task in task_rows:
            key = (task["name"] or "").strip().lower()
            if not key:
                continue
            if key in seen_tasks:
                keep_id = seen_tasks[key]
                conn.execute("UPDATE allocations SET task_id = ? WHERE task_id = ?", (keep_id, task["id"]))
                conn.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
            else:
                seen_tasks[key] = task["id"]

        conn.execute("DELETE FROM allocations WHERE task_id IS NULL OR employee_id IS NULL")

    for employee in get_employees():
        recalculate_employee_workload(employee["id"])


def seed_default_data_if_empty():
    with get_connection() as conn:
        existing_employee_names = {row[0] for row in conn.execute("SELECT name FROM employees").fetchall()}
        for employee in seed_employee_data():
            if employee["name"] not in existing_employee_names:
                conn.execute(
                    """
                    INSERT INTO employees (name, skills, workload, availability, location, performance)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        employee["name"],
                        employee["skills"],
                        employee["workload"],
                        employee["availability"],
                        employee["location"],
                        employee["performance"],
                    ),
                )
                existing_employee_names.add(employee["name"])

        existing_task_names = {row[0] for row in conn.execute("SELECT name FROM tasks").fetchall()}
        for task in seed_task_data():
            if task["name"] not in existing_task_names:
                workload_impact = task_priority_workload(task.get("priority", "Medium"))
                conn.execute(
                    """
                    INSERT INTO tasks (name, description, required_skills, priority, sla_hours, location, status, deadline, workload_impact)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task["name"],
                        task["description"],
                        task["required_skills"],
                        task["priority"],
                        task["sla_hours"],
                        task["location"],
                        task["status"],
                        task["deadline"],
                        workload_impact,
                    ),
                )
                existing_task_names.add(task["name"])

    try:
        from allocation_engine import allocate_all_tasks

        allocate_all_tasks()
    except Exception:
        pass


def insert_audit_event(event, previous_assignment, new_assignment, reason, trigger):
    from datetime import datetime

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (timestamp, event, previous_assignment, new_assignment, reason, trigger)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                event,
                previous_assignment,
                new_assignment,
                reason,
                trigger,
            ),
        )


def get_employees():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM employees ORDER BY name"
        ).fetchall()
        return [dict(row) for row in rows]


def get_employee_by_id(employee_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return dict(row) if row else None


def get_tasks():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, deadline"
        ).fetchall()
        return [dict(row) for row in rows]


def get_task_by_id(task_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def get_allocations():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.*, e.name AS employee_name, t.name AS task_name, t.priority, t.location, t.sla_hours
            FROM allocations a
            JOIN employees e ON e.id = a.employee_id
            JOIN tasks t ON t.id = a.task_id
            WHERE a.status = 'active'
            ORDER BY t.priority DESC, a.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows if row["task_id"] and row["employee_id"]]


def get_audit_logs():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]


def get_dashboard_summary():
    with get_connection() as conn:
        total_employees = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        available_employees = conn.execute("SELECT COUNT(*) FROM employees WHERE availability = 'Available'").fetchone()[0]
        unavailable_employees = conn.execute("SELECT COUNT(*) FROM employees WHERE availability != 'Available'").fetchone()[0]
        total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        pending_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'").fetchone()[0]
        allocated_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE assigned_employee_id IS NOT NULL AND status != 'completed'").fetchone()[0]
        in_progress = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'in progress' OR status = 'in_progress'").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'").fetchone()[0]
        critical_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE priority = 'Critical' AND status != 'completed'").fetchone()[0]
        at_risk_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'completed' AND deadline IS NOT NULL AND datetime(deadline) <= datetime('now', '+2 hours')").fetchone()[0]
        critical_sla_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'completed' AND deadline IS NOT NULL AND datetime(deadline) <= datetime('now', '+1 hour')").fetchone()[0]
        breached_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'completed' AND deadline IS NOT NULL AND datetime(deadline) < datetime('now')").fetchone()[0]
        overloaded_employees = conn.execute("SELECT COUNT(*) FROM employees WHERE workload >= 80").fetchone()[0]
        unassigned_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'completed' AND assigned_employee_id IS NULL").fetchone()[0]
        reallocations = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE event LIKE '%realloc%' OR event LIKE '%reallocation%' OR event LIKE '%reassigned%'").fetchone()[0]
        current_allocations = conn.execute("SELECT COUNT(*) FROM allocations WHERE status = 'active'").fetchone()[0]

        employee_workload = conn.execute("SELECT name, workload FROM employees ORDER BY workload DESC").fetchall()
        tasks_by_priority = conn.execute("SELECT priority, COUNT(*) AS count FROM tasks WHERE status != 'completed' GROUP BY priority").fetchall()
        tasks_by_status = conn.execute("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status").fetchall()
        availability_snapshot = conn.execute("SELECT availability, COUNT(*) AS count FROM employees GROUP BY availability").fetchall()
        alerts = get_alerts()

        return {
            "total_employees": total_employees,
            "available_employees": available_employees,
            "unavailable_employees": unavailable_employees,
            "total_tasks": total_tasks,
            "pending_tasks": pending_tasks,
            "allocated_tasks": allocated_tasks,
            "in_progress": in_progress,
            "completed": completed,
            "critical_tasks": critical_tasks,
            "sla_risk_tasks": at_risk_tasks,
            "sla_critical_tasks": critical_sla_tasks,
            "sla_breached_tasks": breached_tasks,
            "overloaded_employees": overloaded_employees,
            "unassigned_tasks": unassigned_tasks,
            "reallocations": reallocations,
            "current_allocations": current_allocations,
            "ai_status": "Operational",
            "employee_workload": [dict(row) for row in employee_workload],
            "tasks_by_priority": [dict(row) for row in tasks_by_priority],
            "tasks_by_status": [dict(row) for row in tasks_by_status],
            "availability_snapshot": [dict(row) for row in availability_snapshot],
            "alerts": alerts,
        }


def get_alerts():
    with get_connection() as conn:
        total_critical = conn.execute("SELECT COUNT(*) FROM tasks WHERE priority = 'Critical' AND status != 'completed'").fetchone()[0]
        at_risk = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'completed' AND deadline IS NOT NULL AND datetime(deadline) <= datetime('now', '+2 hours')").fetchone()[0]
        breached = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'completed' AND deadline IS NOT NULL AND datetime(deadline) < datetime('now')").fetchone()[0]
        unavailable = conn.execute("SELECT COUNT(*) FROM employees WHERE availability != 'Available'").fetchone()[0]
        overloaded = conn.execute("SELECT COUNT(*) FROM employees WHERE workload >= 80").fetchone()[0]
        unassigned = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'completed' AND assigned_employee_id IS NULL").fetchone()[0]

        alerts = []
        if total_critical:
            alerts.append({"type": "Critical task", "severity": "Critical", "text": f"{total_critical} critical tasks require immediate resource attention."})
        if at_risk:
            alerts.append({"type": "SLA at risk", "severity": "Warning", "text": f"{at_risk} tasks are within the risk window and need review."})
        if breached:
            alerts.append({"type": "SLA breached", "severity": "Critical", "text": f"{breached} tasks have already exceeded their SLA thresholds."})
        if unavailable:
            alerts.append({"type": "Employee unavailable", "severity": "Warning", "text": f"{unavailable} employees are currently unavailable."})
        if overloaded:
            alerts.append({"type": "Employee overloaded", "severity": "Warning", "text": f"{overloaded} employees are at or above the overload threshold."})
        if unassigned:
            alerts.append({"type": "Unassigned task", "severity": "Info", "text": f"{unassigned} tasks are still waiting for a feasible assignment."})
        if not alerts:
            alerts.append({"type": "System healthy", "severity": "Info", "text": "No active alerts at the moment."})
        return alerts


def get_task_status(task):
    if not task or task.get("deadline") is None:
        return "SAFE"

    try:
        deadline_dt = __import__("datetime").datetime.strptime(task["deadline"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return "SAFE"

    remaining_hours = (deadline_dt - __import__("datetime").datetime.now()).total_seconds() / 3600
    if remaining_hours <= 1:
        return "CRITICAL"
    if remaining_hours <= 6:
        return "AT RISK"
    return "SAFE"


def normalize_workload(value):
    try:
        workload = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, workload))


def task_priority_workload(priority):
    mapping = {"Critical": 25, "High": 20, "Medium": 15, "Low": 10}
    normalized = str(priority or "Medium").strip().capitalize()
    return normalize_workload(mapping.get(normalized, 15))


def resolve_task_workload(task):
    if not task:
        return 0
    task_record = dict(task)
    workload_impact = task_record.get("workload_impact")
    if workload_impact is not None:
        return normalize_workload(workload_impact)
    return task_priority_workload(task_record.get("priority"))


def recalculate_employee_workload(employee_id):
    if employee_id is None:
        return 0

    with get_connection() as conn:
        active_tasks = conn.execute(
            "SELECT * FROM tasks WHERE assigned_employee_id = ? AND status != 'completed'",
            (employee_id,),
        ).fetchall()
        workload = sum(resolve_task_workload(dict(task)) for task in active_tasks)
        workload = normalize_workload(workload)
        conn.execute("UPDATE employees SET workload = ? WHERE id = ?", (workload, employee_id))
        return workload


def calculate_task_workload_impact(task):
    return resolve_task_workload(task)


def create_employee(payload):
    name = (payload.get("name") or "").strip()
    skills = (payload.get("skills") or "").strip()
    workload = normalize_workload(payload.get("workload") or 0)
    availability = (payload.get("availability") or "Available").strip()
    location = (payload.get("location") or "").strip()
    performance = int(payload.get("performance") or 0)

    if not all([name, skills, location]):
        raise ValueError("Name, skills, and location are required.")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO employees (name, skills, workload, availability, location, performance)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, skills, workload, availability, location, performance),
        )
        return cursor.lastrowid


def create_task(payload):
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    required_skills = (payload.get("required_skills") or "").strip()
    priority = (payload.get("priority") or "Medium").strip()
    sla_hours = int(payload.get("sla_hours") or 24)
    location = (payload.get("location") or "").strip()
    deadline = payload.get("deadline")
    workload_impact = payload.get("workload_impact")
    if workload_impact is None:
        workload_impact = task_priority_workload(priority)
    workload_impact = normalize_workload(workload_impact)

    if not all([name, required_skills, location]):
        raise ValueError("Task name, required skills, and location are required.")

    from datetime import datetime, timedelta

    if not deadline:
        deadline = (datetime.now() + timedelta(hours=sla_hours)).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks (name, description, required_skills, priority, sla_hours, location, status, deadline, workload_impact)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (name, description, required_skills, priority, sla_hours, location, deadline, workload_impact),
        )
        return cursor.lastrowid


def update_task(task_id, payload):
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    required_skills = (payload.get("required_skills") or "").strip()
    priority = (payload.get("priority") or "Medium").strip()
    sla_hours = int(payload.get("sla_hours") or 24)
    location = (payload.get("location") or "").strip()
    deadline = payload.get("deadline")
    workload_impact = payload.get("workload_impact")
    if workload_impact is None:
        workload_impact = task_priority_workload(priority)
    workload_impact = normalize_workload(workload_impact)

    if not all([name, required_skills, location]):
        raise ValueError("Task name, required skills, and location are required.")

    from datetime import datetime, timedelta

    if not deadline:
        deadline = (datetime.now() + timedelta(hours=sla_hours)).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET name = ?, description = ?, required_skills = ?, priority = ?, sla_hours = ?, location = ?, deadline = ?, workload_impact = ?
            WHERE id = ?
            """,
            (name, description, required_skills, priority, sla_hours, location, deadline, workload_impact, task_id),
        )
        task = conn.execute("SELECT assigned_employee_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task and task["assigned_employee_id"] is not None:
            active_tasks = conn.execute(
                "SELECT * FROM tasks WHERE assigned_employee_id = ? AND status != 'completed'",
                (task["assigned_employee_id"],),
            ).fetchall()
            updated_workload = normalize_workload(sum(resolve_task_workload(dict(item)) for item in active_tasks))
            conn.execute("UPDATE employees SET workload = ? WHERE id = ?", (updated_workload, task["assigned_employee_id"]))


def delete_task(task_id):
    with get_connection() as conn:
        task = conn.execute("SELECT assigned_employee_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        employee_id = task["assigned_employee_id"] if task else None
        conn.execute("DELETE FROM allocations WHERE task_id = ?", (task_id,))
        conn.execute("UPDATE tasks SET assigned_employee_id = NULL WHERE id = ?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    if employee_id is not None:
        recalculate_employee_workload(employee_id)


def update_employee_availability(employee_id, availability):
    with get_connection() as conn:
        conn.execute(
            "UPDATE employees SET availability = ? WHERE id = ?",
            (availability, employee_id),
        )


def update_employee(employee_id, payload):
    name = (payload.get("name") or "").strip()
    skills = (payload.get("skills") or "").strip()
    workload = normalize_workload(payload.get("workload") or 0)
    availability = (payload.get("availability") or "Available").strip()
    location = (payload.get("location") or "").strip()
    performance = int(payload.get("performance") or 0)

    if not all([name, skills, location]):
        raise ValueError("Name, skills, and location are required.")

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE employees
            SET name = ?, skills = ?, workload = ?, availability = ?, location = ?, performance = ?
            WHERE id = ?
            """,
            (name, skills, workload, availability, location, performance, employee_id),
        )


def delete_employee(employee_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM allocations WHERE employee_id = ?", (employee_id,))
        conn.execute("UPDATE tasks SET assigned_employee_id = NULL WHERE assigned_employee_id = ?", (employee_id,))
        conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))


def update_task_status(task_id, status):
    with get_connection() as conn:
        conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))


def mark_task_complete(task_id):
    with get_connection() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return {"success": False, "message": "Task not found."}

        if task["status"] == "completed":
            return {"success": False, "message": "Task is already completed."}

        employee_id = task["assigned_employee_id"]
        previous_workload = 0
        employee = None
        if employee_id is not None:
            employee = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
            if employee:
                previous_workload = normalize_workload(employee["workload"])

        conn.execute("UPDATE allocations SET status = 'inactive' WHERE task_id = ? AND status = 'active'", (task_id,))
        conn.execute(
            "UPDATE tasks SET status = 'completed', assigned_employee_id = NULL, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task_id,),
        )

        new_workload = 0
        if employee_id is not None:
            remaining_tasks = conn.execute(
                "SELECT * FROM tasks WHERE assigned_employee_id = ? AND status != 'completed'",
                (employee_id,),
            ).fetchall()
            new_workload = normalize_workload(sum(resolve_task_workload(dict(item)) for item in remaining_tasks))
            conn.execute("UPDATE employees SET workload = ? WHERE id = ?", (new_workload, employee_id))
        available_capacity = 100 - new_workload

        if employee:
            from datetime import datetime

            conn.execute(
                """
                INSERT INTO audit_logs (timestamp, event, previous_assignment, new_assignment, reason, trigger)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Task completed",
                    str(previous_workload),
                    str(new_workload),
                    f"Task {task['name']} completed and workload recalculated from remaining active tasks.",
                    "Task completion",
                ),
            )

        return {
            "success": True,
            "message": "Task completed. Employee workload recalculated.",
            "task": {
                "id": task["id"],
                "name": task["name"],
                "status": "completed",
            },
            "employee": {
                "id": employee_id,
                "name": employee["name"] if employee else None,
                "previous_workload": previous_workload,
                "new_workload": new_workload,
                "available_capacity": available_capacity,
            } if employee_id is not None else None,
        }


def set_task_assignment(task_id, employee_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET assigned_employee_id = ?, status = 'pending' WHERE id = ?",
            (employee_id, task_id),
        )
    if employee_id is not None:
        recalculate_employee_workload(employee_id)


def insert_allocation(task_id, employee_id, suitability_score, reason):
    task = get_task_by_id(task_id)
    employee = get_employee_by_id(employee_id)
    if not task or not employee:
        raise ValueError("Allocation requires both a valid task and a valid employee.")

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM allocations WHERE task_id = ? AND status = 'active'",
            (task_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE allocations SET employee_id = ?, suitability_score = ?, reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (employee_id, suitability_score, reason, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO allocations (task_id, employee_id, suitability_score, reason, status)
                VALUES (?, ?, ?, ?, 'active')
                """,
                (task_id, employee_id, suitability_score, reason),
            )
        conn.execute(
            "UPDATE tasks SET assigned_employee_id = ?, status = 'pending' WHERE id = ?",
            (employee_id, task_id),
        )
    recalculate_employee_workload(employee_id)


def clear_allocations_for_task(task_id):
    with get_connection() as conn:
        conn.execute("UPDATE allocations SET status = 'inactive' WHERE task_id = ?", (task_id,))


def get_active_allocations_for_employee(employee_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM allocations WHERE employee_id = ? AND status = 'active'",
            (employee_id,),
        ).fetchall()


def get_unscheduled_tasks():
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM tasks WHERE status != 'completed' ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END"
        ).fetchall()


def cleanup_orphan_allocations():
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM allocations
            WHERE status = 'active'
              AND (
                  task_id IS NULL
                  OR employee_id IS NULL
                  OR NOT EXISTS (SELECT 1 FROM tasks t WHERE t.id = allocations.task_id)
                  OR NOT EXISTS (SELECT 1 FROM employees e WHERE e.id = allocations.employee_id)
              )
            """
        )


def get_allocation_summary():
    cleanup_orphan_allocations()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.task_id, a.employee_id, t.name AS task_name, e.name AS employee_name, t.priority, t.sla_hours, t.location, a.suitability_score, a.reason, t.status
            FROM allocations a
            JOIN tasks t ON t.id = a.task_id
            JOIN employees e ON e.id = a.employee_id
            WHERE a.status = 'active'
            ORDER BY 
                CASE t.priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
                a.updated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows if row["task_id"] and row["task_name"] and row["employee_name"]]
