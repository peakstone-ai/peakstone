import subprocess
import csv
import glob
import random
import os

def task_func(file):
    """
    Divide a CSV file into several smaller files and shuffle the lines in each file.
    
    This function takes a CSV file path as input, divides it into smaller files using 
    the shell 'split' command, and shuffles the rows in each of the resulting files.
    The output files are named with a 'split_' prefix.

    Parameters:
    - file (str): The path to the CSV file.

    Returns:
    - list: The paths to the split files. Returns an empty list if the file does not exist, is not a CSV file, or if an error occurs during processing.
    
    Requirements:
    - subprocess
    - csv
    - glob
    - random
    - os

    Example:
    >>> task_func('/path/to/file.csv')
    ['/path/to/split_00', '/path/to/split_01', ...]
    """
    # Check if file exists
    if not os.path.exists(file):
        print("Provided file does not exist.")
        return []
    
    # Check for CSV file extension
    if not file.endswith('.csv'):
        print("Provided file is not a CSV.")
        return []

    try:
        subprocess.call(['split', '-n', '5', '-d', file, 'split_'])
        split_files = glob.glob('split_*')

        for split_file in split_files:
            with open(split_file, 'r') as f:
                reader = csv.reader(f)
                rows = list(reader)

            random.shuffle(rows)

            with open(split_file, 'w') as f:
                writer = csv.writer(f)
                writer.writerows(rows)

        return split_files
    except Exception as e:
        print(f"An error occurred: {e}")
        return []