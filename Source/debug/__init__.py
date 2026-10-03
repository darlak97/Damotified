from .logger import logger

def register():
    logger.debug("Debug module initialized.")

def unregister():
    logger.debug("Debug module disabled.")