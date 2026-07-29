from typing import Dict, Any, List

# In-memory storage
tasks: Dict[int, Dict[str, Any]] = {}
images: Dict[int, Dict[str, Any]] = {}
results: Dict[int, Dict[str, Any]] = {}
quotes: Dict[int, Dict[str, Any]] = {}
exports: Dict[int, Dict[str, Any]] = {}

next_task_id = 1001
next_image_id = 1

def get_next_task_id() -> int:
    global next_task_id
    id = next_task_id
    next_task_id += 1
    return id

def get_next_image_id() -> int:
    global next_image_id
    id = next_image_id
    next_image_id += 1
    return id
