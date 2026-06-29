import unittest
from unittest.mock import patch, mock_open
import json

from data_read import load_data

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
                    "break_duration": 5
                },
                {
                    "name": "Task 2",
                    "duration": 45
                }
            ],
            "time_blocks": [
                {
                    "start": "25.10.2023 09:00",
                    "end": "25.10.2023 10:00",
                    "daily": True
                },
                {
                    "start": "25.10.2023 15:00",
                    "end": "25.10.2023 16:00"
                }
            ]
        }
        mock_file_content = json.dumps(mock_json_data)
        
        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            user_tasks, time_blocks_raw = load_data("dummy_path.json")
            
            # Check user_tasks
            self.assertEqual(len(user_tasks), 2)
            self.assertEqual(user_tasks[0].name, "Task 1")
            self.assertEqual(user_tasks[0].duration, 120)
            self.assertEqual(user_tasks[0].min_chunk_duration, 30)
            self.assertEqual(user_tasks[0].max_chunk_duration, 60)
            self.assertEqual(user_tasks[0].break_duration, 5)
            
            self.assertEqual(user_tasks[1].name, "Task 2")
            self.assertEqual(user_tasks[1].duration, 45)
            self.assertIsNone(user_tasks[1].min_chunk_duration)
            self.assertIsNone(user_tasks[1].max_chunk_duration)
            self.assertEqual(user_tasks[1].break_duration, 0)
            
            # Check time_blocks_raw
            self.assertEqual(len(time_blocks_raw), 2)
            self.assertEqual(time_blocks_raw[0]["start"], "25.10.2023 09:00")
            self.assertEqual(time_blocks_raw[0]["end"], "25.10.2023 10:00")
            self.assertTrue(time_blocks_raw[0]["daily"])
            
            self.assertEqual(time_blocks_raw[1]["start"], "25.10.2023 15:00")
            self.assertEqual(time_blocks_raw[1]["end"], "25.10.2023 16:00")
            self.assertTrue(time_blocks_raw[1]["daily"]) # Defaults to True in the code if not provided
