# BigCodeBench/16

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `glob`, `subprocess`, `os`.

```python
import os
import glob
import subprocess

def task_func(directory, backup_dir='/path/to/backup'):
    """
    Backup all '.log' files in a specified directory to a tar.gz file and delete the original files after backup.
    The backup file is named 'logs_backup.tar.gz' and placed in the specified backup directory.
    
    Parameters:
    - directory (str): The directory that contains the log files to be backed up.
    - backup_dir (str, optional): The directory where the backup file will be saved.
                                  Default is '/path/to/backup'.
    
    Returns:
    - str: The path to the backup file if logs are found, otherwise returns a message 'No logs found to backup'.
    
    Raises:
    - FileNotFoundError: If the specified directory does not exist.
    
    Requirements:
    - subprocess
    - glob
    - os
    
    Example:
    >>> task_func('/path/to/logs')
    '/path/to/backup/logs_backup.tar.gz'
    >>> task_func('/path/to/logs', '/alternative/backup/dir')
    '/alternative/backup/dir/logs_backup.tar.gz'
    """
```

<!-- imported from BigCodeBench (BigCodeBench/16) -->
