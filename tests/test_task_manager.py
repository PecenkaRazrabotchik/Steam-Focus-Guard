import unittest
from src.task_manager import normalize_task, normalize_tasks, planned_minutes, sort_tasks


class TaskModelTests(unittest.TestCase):
    def test_legacy_text_is_migrated(self):
        task = normalize_task("Главное: Подготовить отчёт — 45 минут")
        self.assertEqual(task["focus"], "main")
        self.assertEqual(task["duration_minutes"], 45)
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


if __name__ == "__main__":
    unittest.main()
