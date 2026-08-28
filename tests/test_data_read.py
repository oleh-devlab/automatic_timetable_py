import unittest
from unittest.mock import patch, mock_open
import json
from datetime import datetime, timedelta

from src.data_read import load_data


class TestDataRead(unittest.TestCase):
    def test_load_data_valid_json(self):
        """Tests that load_data correctly parses valid JSON into objects."""
        mock_json_data = {
            "user_tasks": [
                {
                    "name": "Task 1",
                    "duration": 120,
                    "min_chunk_duration": 30,
                    "max_chunk_duration": 60,
                    "break_duration": 5,
                },
                {"name": "Task 2", "duration": 45},
            ],
            "time_blocks": [
                {"start": "25.10.2023 09:00", "end": "25.10.2023 10:00", "repeat": "daily"},
                {"start": "25.10.2023 15:00", "end": "25.10.2023 16:00"},
            ],
        }
        mock_file_content = json.dumps(mock_json_data)

        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            user_tasks, time_blocks, routines = load_data("dummy_path.json")

            # Check user_tasks
            self.assertEqual(len(user_tasks), 2)
            self.assertEqual(user_tasks[0].name, "Task 1")
            self.assertEqual(user_tasks[0].duration, timedelta(minutes=120))
            self.assertEqual(user_tasks[0].min_chunk_duration, timedelta(minutes=30))
            self.assertEqual(user_tasks[0].max_chunk_duration, timedelta(minutes=60))
            self.assertEqual(user_tasks[0].break_duration, timedelta(minutes=5))

            self.assertEqual(user_tasks[1].name, "Task 2")
            self.assertEqual(user_tasks[1].duration, timedelta(minutes=45))
            self.assertIsNone(user_tasks[1].min_chunk_duration)
            self.assertIsNone(user_tasks[1].max_chunk_duration)
            self.assertEqual(user_tasks[1].break_duration, timedelta(0))

            # Check time_blocks
            self.assertEqual(len(time_blocks), 2)
            self.assertEqual(time_blocks[0].start, datetime(2023, 10, 25, 9, 0))
            self.assertEqual(time_blocks[0].end, datetime(2023, 10, 25, 10, 0))
            self.assertTrue(time_blocks[0].daily)

            self.assertEqual(time_blocks[1].start, datetime(2023, 10, 25, 15, 0))
            self.assertEqual(time_blocks[1].end, datetime(2023, 10, 25, 16, 0))
            self.assertTrue(time_blocks[1].daily)

    def test_load_data_parses_time_block_weekdays(self):
        """A time block may carry a weekly recurrence rule; without it weekdays stays None."""
        mock_json_data = {
            "time_blocks": [
                {
                    "start": "25.10.2023 14:00",
                    "end": "25.10.2023 15:30",
                    "repeat": "weekly",
                    "weekdays": [1, 3],
                    "name": "Lecture",
                },
                {"start": "25.10.2023 09:00", "end": "25.10.2023 10:00", "repeat": "daily"},
            ]
        }

        with patch("builtins.open", mock_open(read_data=json.dumps(mock_json_data))):
            _, time_blocks, _ = load_data("dummy_path.json")

            self.assertEqual(time_blocks[0].weekdays, [1, 3])
            self.assertEqual(time_blocks[0].name, "Lecture")
            self.assertIsNone(time_blocks[1].weekdays)


class TestDataReadStrictness(unittest.TestCase):
    """The parser rejects what it does not understand instead of silently ignoring it."""

    def _load(self, data):
        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            return load_data("dummy_path.json")

    def _block(self, **overrides):
        block = {"start": "25.10.2023 14:00", "end": "25.10.2023 15:00"}
        block.update(overrides)
        return {"time_blocks": [block]}

    # --- Unknown fields ---

    def test_legacy_daily_key_is_rejected(self):
        """`daily` was replaced by `repeat`; a stale file must fail loudly, not schedule wrongly."""
        with self.assertRaises(ValueError) as ctx:
            self._load(self._block(daily=True))

        self.assertIn("daily", str(ctx.exception))
        self.assertIn("repeat", str(ctx.exception))  # the allowed-field list points at the replacement

    def test_misspelled_field_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._load(self._block(repeat="weekly", weekday=[2]))

        self.assertIn("time_blocks[0]", str(ctx.exception))
        self.assertIn("weekday", str(ctx.exception))

    def test_unknown_top_level_section_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._load({"user_tasks": [], "time_bloks": []})

        self.assertIn("time_bloks", str(ctx.exception))

    def test_unknown_task_and_routine_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            self._load({"user_tasks": [{"name": "T", "duration": 10, "prioroty": 3}]})
        with self.assertRaises(ValueError):
            self._load({"routines": [{"name": "R", "type": "flexible", "repeat": "daily", "duration": 10, "at": "7"}]})

    # --- Missing required fields ---

    def test_missing_required_field_names_the_element(self):
        with self.assertRaises(ValueError) as ctx:
            self._load({"user_tasks": [{"name": "T", "duration": 10}, {"name": "no duration"}]})

        self.assertIn("user_tasks[1]", str(ctx.exception))
        self.assertIn("duration", str(ctx.exception))

    # --- Recurrence rules ---

    def test_repeat_defaults_to_daily(self):
        _, time_blocks, _ = self._load(self._block())
        self.assertTrue(time_blocks[0].daily)
        self.assertIsNone(time_blocks[0].weekdays)

    def test_repeat_once_is_a_one_off_block(self):
        _, time_blocks, _ = self._load(self._block(repeat="once"))
        self.assertFalse(time_blocks[0].daily)

    def test_repeat_weekly_carries_weekdays(self):
        _, time_blocks, _ = self._load(self._block(repeat="weekly", weekdays=[1, 3]))
        self.assertEqual(time_blocks[0].weekdays, [1, 3])
        self.assertFalse(time_blocks[0].daily, "a weekly block is not also a daily one")

    def test_unknown_repeat_value_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._load(self._block(repeat="fortnightly"))

        self.assertIn("fortnightly", str(ctx.exception))

    def test_weekly_without_weekdays_is_rejected(self):
        for weekdays in ({}, {"weekdays": []}):
            with self.assertRaises(ValueError):
                self._load(self._block(repeat="weekly", **weekdays))

    def test_weekdays_without_weekly_is_rejected(self):
        """Previously `weekdays` silently overrode `daily`; now the two must agree."""
        with self.assertRaises(ValueError) as ctx:
            self._load(self._block(repeat="daily", weekdays=[2]))

        self.assertIn("weekdays", str(ctx.exception))

    def test_routine_recurrence_is_validated_the_same_way(self):
        routine = {"name": "R", "type": "flexible", "repeat": "weekly", "duration": 30}
        with self.assertRaises(ValueError):
            self._load({"routines": [routine]})  # weekly, no weekdays

        _, _, routines = self._load({"routines": [dict(routine, weekdays=[5])]})
        self.assertEqual(routines[0].weekdays, [5])

    def test_routine_with_unknown_repeat_is_rejected(self):
        with self.assertRaises(ValueError):
            self._load({"routines": [{"name": "R", "type": "flexible", "repeat": "once", "duration": 30}]})
