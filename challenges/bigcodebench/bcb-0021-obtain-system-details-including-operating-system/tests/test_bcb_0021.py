# Auto-generated from BigCodeBench BigCodeBench/21. Do not edit by hand.
import pathlib as _pathlib
exec(_pathlib.Path(__file__).with_name("solution.py").read_text(), globals())

import unittest
class TestCases(unittest.TestCase):
    
    def test_presence_OS(self):
        """Test that the result has the correct keys and that each key maps to the expected data type."""
        result = task_func()
        self.assertTrue('OS' in result and isinstance(result['OS'], str))
    def test_presence_architecture(self):
        """Test that the result has the correct keys and that each key maps to the expected data type."""
        result = task_func()
        self.assertTrue('Architecture' in result and isinstance(result['Architecture'], str))
    def test_presence_memory_usage(self):
        """Test that the result has the correct keys and that each key maps to the expected data type."""
        result = task_func()
        self.assertTrue('Memory Usage' in result and isinstance(result['Memory Usage'], str))
    def test_return_type(self):
        """Test that the result has the correct keys and that each key maps to the expected data type."""
        result = task_func()
        self.assertIsInstance(result, dict)
    def test_memory_usage_format(self):
        """Test that the 'Memory Usage' key is correctly formatted as a percentage."""
        result = task_func()
        self.assertRegex(result['Memory Usage'], r"\d{1,3}\.\d{2}%")
    
    def test_non_empty_values(self):
        """Ensure that the values associated with each key are non-empty."""
        result = task_func()
        for key, value in result.items():
            self.assertTrue(bool(value))
