import json
import os
import re

def task_func(
    file_path,
    attribute,
    INPUT_JSON={
        "type": "object",
        "properties": {
            "name": {"type": str},  
            "age": {"type": int},   
            "email": {"type": str}  
        },
        "required": ["name", "age", "email"]
    },
    EMAIL_REGEX=r"^[a-z0-9]+[\._]?[a-z0-9]+[@]\w+[.]\w{2,3}$"):
    """
    Validate the structure and contents of a JSON file against predefined schema rules and retrieve a specified attribute from the JSON object. Ensures that all required fields exist, match their defined types, and checks the validity of the email format using a regular expression.
    
    Parameters:
    file_path (str): The path to the JSON file.
    attribute (str): The attribute to retrieve from the JSON object.
    INPUT_JSON (dict): The input json to validate. The default value is:
    '{
        "type": "object",
        "properties": {
            "name": {"type": str},  
            "age": {"type": int},   
            "email": {"type": str}  
        },
        "required": ["name", "age", "email"]
    }'.
    EMAIL_REGEX (str): The regex used to check the email validity. Default to 'r"^[a-z0-9]+[\._]?[a-z0-9]+[@]\w+[.]\w{2,3}$")'

    Returns:
    Any: The value of the specified attribute, consistent with the type defined in the JSON schema.

    Requirements:
    - json
    - os
    - re

    Errors:
    - Raises ValueError if the file does not exist, required attributes are missing, types do not match, or the email format is invalid.

    Example:
    >>> task_func('/path/to/file.json', 'email')
    'john.doe@example.com'
    """
    if not os.path.isfile(file_path):
        raise ValueError(f'{file_path} does not exist.')

    with open(file_path, 'r') as f:
        data = json.load(f)

    for key in INPUT_JSON['required']:
        if key not in data:
            raise ValueError(f'{key} is missing from the JSON object.')
        if not isinstance(data[key], INPUT_JSON['properties'][key]['type']):
            raise ValueError(f'{key} is not of type {INPUT_JSON["properties"][key]["type"]}.')

    if 'email' in data and not re.fullmatch(EMAIL_REGEX, data['email']):
        raise ValueError('Email is not valid.')

    return data[attribute]