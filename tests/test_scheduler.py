import unittest
from datetime import date

from src.config_manager import migrate_config
from src.scheduler import required_study_minutes_for_today, schedule_for_today


class ScheduleTests(unittest.TestCase):
    def test_tasks_are_sorted_by_focus_and_durations_are_summed(self):
        config = {
            "schedule": {
                "monday": {"tasks": [
                    {"id": "3", "focus": "later", "text": "Позже", "duration_minutes": 15},
                    {"id": "2", "focus": "additional", "text": "Дополнительная", "duration_minutes": 20},
                    {"id": "1", "focus": "main", "text": "Главная", "duration_minutes": 40},
                ]}
            }
        }
        day, tasks = schedule_for_today(config, date(2026, 11, 2))
        self.assertEqual(day, "понедельник")
        self.assertEqual([item["id"] for item in tasks], ["1", "2", "3"])
        self.assertEqual(required_study_minutes_for_today(config, date(2026, 11, 2)), 75)

    def test_new_default_schedule_is_empty(self):
        config = {"schedule": {"wednesday": {"tasks": []}}}
        self.assertEqual(schedule_for_today(config, date(2026, 11, 4))[1], [])
        self.assertEqual(required_study_minutes_for_today(config, date(2026, 11, 4)), 0)

    def test_legacy_text_tasks_are_preserved_and_converted(self):
        config = {"schedule": {"monday": {
            "required_study_minutes": 90,
            "tasks": ["Главное: Python — 45 минут", "Дополнительно: SQL — 30 минут", "Проверить почту"]
        }}}
        migrated = migrate_config(config)
        day, tasks = schedule_for_today(migrated, date(2026, 11, 2))
        self.assertEqual(len(tasks), 3)
        self.assertEqual([task["focus"] for task in tasks], ["main", "additional", "later"])
        self.assertEqual(migrated["schedule"]["monday"]["legacy_required_study_minutes"], 90)
        self.assertEqual(required_study_minutes_for_today(migrated, date(2026, 11, 2)), 75)

    def test_legacy_goal_is_fallback_when_task_durations_are_unknown(self):
        config = {"schedule": {"monday": {
            "legacy_required_study_minutes": 80,
            "tasks": [{"focus": "main", "text": "Не задано время", "duration_minutes": 0}]
        }}}
        self.assertEqual(required_study_minutes_for_today(config, date(2026, 11, 2)), 80)


if __name__ == "__main__":
    unittest.main()
