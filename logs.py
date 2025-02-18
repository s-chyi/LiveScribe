import sys
import os
from loguru import logger as _logger

def define_log_level(print_level="INFO", logfile_level="INFO"):
    _logger.remove()
    _logger.add(sys.stderr, level=print_level)

    log_dir = 'logs'
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
            print(f"Logs directory created at {log_dir}")
        except Exception as e:
            print(f"Failed to create logs directory: {str(e)}")
            _logger.add(sys.stderr, level="ERROR")
            _logger.error(f"Failed to create logs directory: {str(e)}")
            return _logger

    log_path = os.path.join(log_dir, 'log.txt')
    print(f"Log file path: {log_path}")

    try:
        _logger.add(log_path, level=logfile_level)
    except Exception as e:
        print(f"Failed to add log file: {str(e)}")
        _logger.add(sys.stderr, level="ERROR")
        _logger.error(f"Failed to add log file: {str(e)}")

    return _logger

logger = define_log_level()