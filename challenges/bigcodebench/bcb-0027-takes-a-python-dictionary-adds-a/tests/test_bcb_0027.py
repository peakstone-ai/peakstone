# Auto-generated from BigCodeBench BigCodeBench/27. Do not edit by hand.
import pathlib as _pathlib
exec(_pathlib.Path(__file__).with_name("solution.py").read_text(), globals())

import unittest
import json
import base64
from datetime import datetime
class TestCases(unittest.TestCase):
    
    def test_task_func_basic(self):
        """Test the task_func function with a basic dictionary."""
        data = {'name': 'John', 'age': 30, 'city': 'New York'}
        encoded_data = task_func(data)
        decoded_data = json.loads(base64.b64decode(encoded_data).decode('ascii'))
        self.assertEqual(data['name'], decoded_data['name'])
        self.assertEqual(data['age'], decoded_data['age'])
        self.assertEqual(data['city'], decoded_data['city'])
        self.assertIn('timestamp', decoded_data)
        self.assertIsInstance(datetime.strptime(decoded_data['timestamp'], "%Y-%m-%d %H:%M:%S"), datetime)
        
    def test_task_func_empty(self):
        """Test the task_func function with an empty dictionary."""
        data = {}
        encoded_data = task_func(data)
        decoded_data = json.loads(base64.b64decode(encoded_data).decode('ascii'))
        self.assertEqual(len(decoded_data), 1)
        self.assertIn('timestamp', decoded_data)
        self.assertIsInstance(datetime.strptime(decoded_data['timestamp'], "%Y-%m-%d %H:%M:%S"), datetime)
        
    def test_task_func_nested(self):
        """Test the task_func function with a nested dictionary."""
        data = {'user': {'name': 'John', 'age': 30}, 'location': {'city': 'New York', 'country': 'USA'}}
        encoded_data = task_func(data)
        decoded_data = json.loads(base64.b64decode(encoded_data).decode('ascii'))
        self.assertEqual(data['user'], decoded_data['user'])
        self.assertEqual(data['location'], decoded_data['location'])
        self.assertIn('timestamp', decoded_data)
        self.assertIsInstance(datetime.strptime(decoded_data['timestamp'], "%Y-%m-%d %H:%M:%S"), datetime)
        
    def test_task_func_numeric(self):
        """Test the task_func function with a dictionary containing numeric keys."""
        data = {1: 10, 2: 20, 3: 30}
        encoded_data = task_func(data)
        decoded_data = json.loads(base64.b64decode(encoded_data).decode('ascii'))
        data_str_keys = {str(k): v for k, v in data.items()}
        for k, v in data_str_keys.items():
            self.assertEqual(v, decoded_data[k])
        self.assertIn('timestamp', decoded_data)
        self.assertIsInstance(datetime.strptime(decoded_data['timestamp'], "%Y-%m-%d %H:%M:%S"), datetime)
        
    def test_task_func_mixed(self):
        """Test the task_func function with a dictionary containing mixed types of keys and values."""
        data = {'name': 'John', 1: 30, 'nested': {'key': 'value'}, 'list': [1, 2, 3]}
        encoded_data = task_func(data)
        decoded_data = json.loads(base64.b64decode(encoded_data).decode('ascii'))
        data_str_keys = {str(k): v for k, v in data.items()}
        for k, v in data_str_keys.items():
            self.assertEqual(v, decoded_data[k])
        self.assertIn('timestamp', decoded_data)
        self.assertIsInstance(datetime.strptime(decoded_data['timestamp'], "%Y-%m-%d %H:%M:%S"), datetime)
