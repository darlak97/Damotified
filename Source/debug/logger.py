import logging

# global addon logger
logger = logging.getLogger("Damotified")
logger.setLevel(logging.WARNING) # warning spam

if not logger.hasHandlers(): # attach handler
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(name)s | %(levelname)s] %(message)s')
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)