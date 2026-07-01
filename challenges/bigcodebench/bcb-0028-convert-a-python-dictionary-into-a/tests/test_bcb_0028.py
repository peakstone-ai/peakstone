# Auto-generated from BigCodeBench BigCodeBench/28. Do not edit by hand.
import pathlib as _pathlib
exec(_pathlib.Path(__file__).with_name("solution.py").read_text(), globals())

import unittest
from unittest.mock import patch, Mock
import requests
import json
# Mocking the requests.post method
def mock_post(*args, **kwargs):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "OK"
    return mock_response
class TestCases(unittest.TestCase):
    @patch('requests.post', side_effect=mock_post)
    def test_case_1(self, mock_post_method):
        data = {'name': 'John', 'age': 30, 'city': 'New York'}
        response = task_func(data, url="http://mock-api-url.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")
    
    @patch('requests.post', side_effect=mock_post)
    def test_case_2(self, mock_post_method):
        data = {'task': 'Write code', 'status': 'completed'}
        response = task_func(data, url="http://mock-api-url.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")
    @patch('requests.post', side_effect=mock_post)
    def test_case_3(self, mock_post_method):
        data = {}
        response = task_func(data, url="http://mock-api-url.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")
    @patch('requests.post', side_effect=mock_post)
    def test_case_4(self, mock_post_method):
        data = {'fruit': 'apple', 'color': 'red', 'taste': 'sweet'}
        response = task_func(data, url="http://mock-api-url.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")
    @patch('requests.post', side_effect=mock_post)
    def test_case_5(self, mock_post_method):
        data = {'country': 'USA', 'capital': 'Washington, D.C.'}
        response = task_func(data, url="http://mock-api-url.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")
    @patch('requests.post', side_effect=mock_post)
    def test_case_6(self, mock_post_method):
        # Test to verify that the POST request is made with the correct parameters
        data = {'name': 'John', 'age': 30, 'city': 'New York'}
        json_data = json.dumps(data)
        encoded_data = base64.b64encode(json_data.encode('ascii')).decode('ascii')
        task_func(data, url="http://mock-api-url.com")
        try:
            mock_post_method.assert_called_once_with("http://mock-api-url.com", data={"payload": encoded_data})
        except:
            mock_post_method.assert_called_once_with("http://mock-api-url.com", json={"payload": encoded_data})
