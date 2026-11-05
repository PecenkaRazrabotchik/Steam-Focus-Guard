import unittest
from datetime import date

from src.scheduler import required_study_minutes_for_today, schedule_for_today


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "rules": {"required_study_minutes": 75},
            "schedule": {
                "monday": {
                    "required_study_minutes": 90,
                    "tasks": ["Python", "SQL"],
                },
                "tuesday": {
                    "required_study_minutes": 60,
                    "tasks": ["English"],
                },
                "special_dates": {
                    "2026-11-03": {
                        "required_study_minutes": 25,
                        "label": "Особый день",
                        "tasks": ["Подготовить отчёт"],
                    }
                },
            },
        }

    def test_weekday_tasks_and_requirement(self):
        day_name, tasks = schedule_for_today(self.config, date(2026, 11, 2))
        self.assertEqual(day_name, "понедельник")
        self.assertEqual(tasks, ["Python", "SQL"])
        self.assertEqual(required_study_minutes_for_today(self.config, date(2026, 11, 2)), 90)

    def test_special_date_overrides_weekday(self):
        day_name, tasks = schedule_for_today(self.config, date(2026, 11, 3))
        self.assertEqual(day_name, "Особый день")
        self.assertEqual(tasks, ["Подготовить отчёт"])
        self.assertEqual(required_study_minutes_for_today(self.config, date(2026, 11, 3)), 25)

    def test_global_requirement_is_used_as_fallback(self):
        config = {"rules": {"required_study_minutes": 75}, "schedule": {}}
        self.assertEqual(required_study_minutes_for_today(config, date(2026, 11, 4)), 75)


if __name__ == "__main__":
    unittest.main()
