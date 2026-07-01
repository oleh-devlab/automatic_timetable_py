import unittest
from unittest.mock import patch, mock_open
import json
from datetime import datetime, time, timedelta

from src.data_read import load_data


class TestDataReadRoutines(unittest.TestCase):
    """Tests for load_data parsing of the routines section."""

    def test_load_data_with_routines(self):
        """Tests that load_data correctly parses the routines section."""
        mock_json_data = {
            "user_tasks": [{"name": "Task 1", "duration": 60}],
            "time_blocks": [{"start": "01.07.2026 00:00", "end": "01.07.2026 10:00", "daily": True}],
            "routines": [
                {"name": "Workout", "type": "fixed", "repeat": "daily", "time": "07:00", "duration": 60},
                {
                    "name": "Study",
                    "type": "flexible",
                    "repeat": "daily",
                    "deadline_time": "18:00",
                    "duration": 30,
                    "priority": 5,
                    "break_duration": 5,
                },
                {
                    "name": "Cleaning",
                    "type": "flexible",
                    "repeat": "weekly",
                    "weekdays": [5],
                    "duration": 90,
                    "priority": 3,
                },
            ],
        }
        mock_file_content = json.dumps(mock_json_data)

        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            user_tasks, time_blocks_raw, routines = load_data("dummy.json")

            self.assertEqual(len(user_tasks), 1)
            self.assertEqual(len(time_blocks_raw), 1)
            self.assertEqual(len(routines), 3)

            # Fixed routine
            self.assertEqual(routines[0].name, "Workout")
            self.assertEqual(routines[0].type, "fixed")
            self.assertEqual(routines[0].repeat, "daily")
            self.assertEqual(routines[0].time, time(7, 0))
            self.assertEqual(routines[0].duration, timedelta(minutes=60))
            self.assertEqual(routines[0].priority, 0)  # default
            self.assertEqual(routines[0].break_duration, timedelta(0))  # default

            # Flexible daily routine
            self.assertEqual(routines[1].name, "Study")
            self.assertEqual(routines[1].type, "flexible")
            self.assertEqual(routines[1].repeat, "daily")
            self.assertEqual(routines[1].deadline_time, time(18, 0))
            self.assertEqual(routines[1].duration, timedelta(minutes=30))
            self.assertEqual(routines[1].priority, 5)
            self.assertEqual(routines[1].break_duration, timedelta(minutes=5))
            self.assertIsNone(routines[1].weekdays)

            # Weekly flexible routine
            self.assertEqual(routines[2].name, "Cleaning")
            self.assertEqual(routines[2].type, "flexible")
            self.assertEqual(routines[2].repeat, "weekly")
            self.assertEqual(routines[2].weekdays, [5])
            self.assertEqual(routines[2].duration, timedelta(minutes=90))
            self.assertEqual(routines[2].priority, 3)
            self.assertEqual(routines[2].break_duration, timedelta(0))  # default
            self.assertIsNone(routines[2].time)

    def test_load_data_without_routines_section(self):
        """load_data should return an empty routines list if the section is missing."""
        mock_json_data = {"user_tasks": [{"name": "T", "duration": 10}], "time_blocks": []}
        mock_file_content = json.dumps(mock_json_data)

        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            user_tasks, time_blocks_raw, routines = load_data("dummy.json")

            self.assertEqual(len(user_tasks), 1)
            self.assertEqual(len(routines), 0)

    def test_load_data_with_empty_routines(self):
        """load_data should handle an empty routines array."""
        mock_json_data = {"user_tasks": [], "time_blocks": [], "routines": []}
        mock_file_content = json.dumps(mock_json_data)

        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            user_tasks, time_blocks_raw, routines = load_data("dummy.json")

            self.assertEqual(len(user_tasks), 0)
            self.assertEqual(len(time_blocks_raw), 0)
            self.assertEqual(len(routines), 0)


if __name__ == "__main__":
    unittest.main()
