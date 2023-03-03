import logging
import time
from enum import Enum

import koji

from artbotlib import constants, util

logger = logging.getLogger(__name__)


class TaskState(Enum):
    FREE = 0
    OPEN = 1
    CLOSED = 2
    CANCELED = 3
    ASSIGNED = 4
    FAILED = 5


def alert_on_task_complete(so, user_id, task_id):
    so.say(f'Ok <@{user_id}>, I\'ll respond here when the task completes')
    start = time.time()

    try:
        # Has the task passed in by ID?
        task_id = int(task_id)
    except ValueError:
        # No, by URL
        task_id = int(task_id.split('=')[-1])

    while True:
        # Timeout after 12 hrs
        if time.time() - start > constants.TWELVE_HOURS:
            so.say(f'Task {task_id} did not complete in 12 hours, giving up...')
            return

        # Retrieve task info
        try:
            task_info = util.koji_client_session().getTaskInfo(task_id, strict=True)
            state = TaskState(task_info['state'])
            logger.info(f'Task {task_id} has state {state.name}')

        except ValueError:
            # Failed to convert the build state to a valid BuildState enum
            logger.warning(f'Unexpected status {task_info.state} for task {task_id}')
            so.say(f'Task {task_id} has unhandled status {state.name}. '
                   f'Check {constants.BREW_URL}/buildinfo?buildID={task_id} for details')
            return

        except koji.GenericError:
            # No such build
            logger.error('No such task %s', task_id)
            message = f"Task {task_id} does not exist"
            so.say(message)
            return

        except Exception as e:
            # What else can happen?
            message = f"error getting information for task {task_id}: {e}"
            logger.error(message)
            so.say(message)
            return

        # Check build state
        if state in [TaskState.OPEN, TaskState.FREE, TaskState.ASSIGNED]:
            time.sleep(constants.FIVE_MINUTES)

        else:
            # state in [TaskState.CLOSED, TaskState.FAILED, TaskState.CANCELED]:
            so.say(f'Task {task_id} completed with status {state.name}. '
                   f'Check {constants.BREW_URL}/taskinfo?taskID={task_id} for details')
            return
