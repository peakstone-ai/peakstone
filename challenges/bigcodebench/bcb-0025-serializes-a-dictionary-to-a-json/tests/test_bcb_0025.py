# Auto-generated from BigCodeBench BigCodeBench/25. Do not edit by hand.
import pathlib as _pathlib
exec(_pathlib.Path(__file__).with_name("solution.py").read_text(), globals())

import unittest
import json
import zlib
import base64
class TestCases(unittest.TestCase):
    def test_case_1(self):
        # Test with a simple dictionary containing string values.
        data = {'key1': 'value1', 'key2': 'value2'}
        result = task_func(data)
        self.assertIsInstance(result, str)
        decompressed_data = json.loads(zlib.decompress(base64.b64decode(result)).decode())
        self.assertEqual(decompressed_data, data)
    def test_case_2(self):
        # Test with an empty dictionary.
        data = {}
        result = task_func(data)
        self.assertIsInstance(result, str)
        decompressed_data = json.loads(zlib.decompress(base64.b64decode(result)).decode())
        self.assertEqual(decompressed_data, data)
    def test_case_3(self):
        # Test with a dictionary containing mixed types (string and integers).
        data = {'name': 'John', 'age': 30, 'city': 'New York'}
        result = task_func(data)
        self.assertIsInstance(result, str)
        decompressed_data = json.loads(zlib.decompress(base64.b64decode(result)).decode())
        self.assertEqual(decompressed_data, data)
    def test_case_4(self):
        # Test with a nested dictionary containing lists of dictionaries.
        data = {'users': [{'id': 1, 'name': 'Alice'}, {'id': 2, 'name': 'Bob'}]}
        result = task_func(data)
        self.assertIsInstance(result, str)
        decompressed_data = json.loads(zlib.decompress(base64.b64decode(result)).decode())
        self.assertEqual(decompressed_data, data)
    def test_case_5(self):
        # Test with a dictionary containing multiple integer values.
        data = {'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5}
        result = task_func(data)
        self.assertIsInstance(result, str)
        decompressed_data = json.loads(zlib.decompress(base64.b64decode(result)).decode())
        self.assertEqual(decompressed_data, data)
