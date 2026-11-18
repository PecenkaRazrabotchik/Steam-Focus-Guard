import unittest
from src.task_manager import (
    PRIORITY_LEVELS, STATUS_LEVELS, normalize_task, normalize_tasks,
    planned_minutes, sort_tasks,
)


class TaskModelTests(unittest.TestCase):
    def test_legacy_text_is_migrated(self):
        task = normalize_task("Главное: Подготовить отчёт — 45 минут")
        self.assertEqual(task["focus"], "main")
        self.assertEqual(task["duration_minutes"], 45)
        self.assertEqual(task["status"], "todo")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["category"], "Учёба")
        self.assertIn("Подготовить отчёт", task["text"])

    def test_tasks_are_ordered_by_focus(self):
        tasks = normalize_tasks([
            {"id": "later", "focus": "later", "text": "Позже", "duration_minutes": 10},
            {"id": "extra", "focus": "additional", "text": "Дополнительно", "duration_minutes": 20},
            {"id": "main", "focus": "main", "text": "Главная", "duration_minutes": 30},
        ])
        self.assertEqual([task["id"] for task in tasks], ["main", "extra", "later"])
        self.assertEqual(planned_minutes(tasks), 60)

    def test_invalid_focus_falls_back_to_later(self):
        task = normalize_task({"focus": "unknown", "text": "Task", "duration_minutes": -5})
        self.assertEqual(task["focus"], "later")
        self.assertEqual(task["duration_minutes"], 0)

    def test_missing_dashboard_metadata_is_filled(self):
        task = normalize_task({"id": "abc", "focus": "main", "text": "Task", "duration_minutes": 30})
        self.assertEqual(task["status"], "todo")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["category"], "Другое")

    def test_invalid_status_and_priority_are_sanitized(self):
        task = normalize_task({
            "text": "Task", "focus": "additional", "duration_minutes": 10,
            "status": "unknown", "priority": "unknown", "category": " ",
        })
        self.assertEqual(task["status"], "todo")
        self.assertEqual(task["priority"], "medium")
        self.assertEqual(task["category"], "Другое")

    def test_dashboard_metadata_contains_expected_values(self):
        self.assertEqual(set(STATUS_LEVELS), {"todo", "in_progress", "done"})
        self.assertEqual(set(PRIORITY_LEVELS), {"urgent", "high", "medium", "low"})


if __name__ == "__main__":
    unittest.main()
