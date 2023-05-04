import asyncio
import json
import logging
import time
from enum import Enum

import aiohttp
from aiohttp import client_exceptions

from artbotlib import variables
from artbotlib.constants import FIVE_MINUTES, TWELVE_HOURS, PROW_BASE_URL

GS_WEB_URL = 'https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs'

logger = logging.getLogger(__name__)


class ProwJobState(Enum):
    PENDING = 'pending'
    FAILURE = 'failure'
    SUCCESS = 'success'


async def get_job_state(job_path: str) -> str:
    """
    Gets Prow job state. Raises:
      - requests.exceptions.HTTPError in case of errors when fetching the job page
      - KeyError, if the job data does not contain the 'state' field

    :param job_path: e.g. origin-ci-test/logs/release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344

    'job_path' can be appended to PROW_BASE_URL/view/gs/ to get the full job URL. The job state can be obtained from
    the job artifacts, that can be found at GS_WEB_URL/job_path/prowjob.json
    """

    prow_job_json_url = f'{GS_WEB_URL}/{job_path}/prowjob.json'

    # Fetch job data
    async with aiohttp.ClientSession() as session:
        logger.info('Fetching url %s', prow_job_json_url)
        async with session.get(prow_job_json_url) as response:
            try:
                response.raise_for_status()
                # reponse.json() will throw an exception as the content type is text/plain
                job_data = json.loads(await response.text())
            except aiohttp.client_exceptions.ClientResponseError:
                logger.warning('Failed fetching %s: %s', prow_job_json_url, response.reason)
                raise

    # Parse job JSON data and check status
    try:
        job_state = job_data['status']['state']
        logger.info('Job state is %s', job_state)
    except KeyError:
        logger.warning('Could not get job state from JSON data')
        raise

    return job_state


def prow_job_status(so, user_id: str, job_path: str):
    """
    Polls for a Prow job state and notifies the user when the job completes.
    Times out after 12 hours
    """

    so.say(f'Ok <@{user_id}>, I\'ll respond here when the job completes')
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Supposed initial state
    job_state = ProwJobState.PENDING.value
    start = time.time()

    # Handle pod restarts while loop is running
    variables.active_slack_objects.add(so)

    while job_state == ProwJobState.PENDING.value:
        # Timeout after 12 hrs.
        now = time.time()
        if now - start > TWELVE_HOURS:  # Timeout after 12 hrs.
            logger.warning('Prow job %s did not complete within 12 hours, giving up', job_path)
            so.say(f"<@{user_id}> job {job_path} didn't complete even after 12 hrs :(")
            break
        logger.info('Checking state for job %s', job_path)

        # Retrieve job state
        try:
            job_state = loop.run_until_complete(get_job_state(job_path))
            logger.info('Job %s is in state %s', job_path, job_state)

        except aiohttp.client_exceptions.ClientResponseError:
            msg = f'Failed fetching job data from {job_path}'
            logger.error(msg)
            so.say(msg)
            break

        except KeyError:
            msg = f'Failed parsing job data from {job_path}'
            logger.error(msg)
            so.say(msg)
            break

        # Check state and possibly notify user
        if job_state != ProwJobState.PENDING.value:
            logger.info('Prow job %s completed with status %s', job_path, job_state)
            so.say(f'<@{user_id}> prow job `{job_path}` completed with status `{job_state}`')
            break

        # If not completed yet, wait and retry
        time.sleep(FIVE_MINUTES)

    # Remove slack object
    variables.active_slack_objects.remove(so)


def first_prow_job_succeeds(so, user_id: str, job_paths: str):
    """
    Polls for a set of Prow job states and notifies the user when the first one completes.
    Times out after 12 hours
    """

    job_paths = job_paths.replace(f'{PROW_BASE_URL}/view/gs', '')

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    start = time.time()

    paths = [job.strip().replace(F'{PROW_BASE_URL}/view/gs/', '') for job in job_paths.split()]

    # This counter accounts for temporary outages (all jobs would fail)
    fail_count = 0
    max_attempts = 3

    # Handle pod restarts while loop is running
    variables.active_slack_objects.add(so)

    while True:
        # Timeout after 12 hrs.
        now = time.time()
        if now - start > TWELVE_HOURS:  # Timeout after 12 hrs.
            logger.warning('No job in %s completed within 12 hours', paths)
            so.say(f"<@{user_id}> no job in {job_paths} completed within 12 hrs :(")
            break

        logger.info('Checking states for jobs %s', job_paths)

        tasks = [get_job_state(path) for path in paths]
        results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))

        # If all tasks failed, give up after 3 attempts
        if all([isinstance(result, Exception) for result in results]):
            if fail_count >= max_attempts:
                msg = 'Sorry, failed checking all provided Prow jobs'
                logger.warning(msg)
                so.say(msg)
                break

            time.sleep(FIVE_MINUTES)
            max_attempts += 1
            continue

        # Filter out jobs that triggered an exception, and their results
        failed_indexes = []
        for index, result in enumerate(results):
            if isinstance(result, Exception):
                failed_indexes.append(index)

        failed_indexes.sort(reverse=True)
        for index in failed_indexes:
            results.pop(index)
            paths.pop(index)

        # If all jobs failed, notify the user
        if all([result == ProwJobState.FAILURE.value for result in results]):
            logger.warning('All jobs in %s failed', job_paths)
            so.say(f"<@{user_id}> all jobs failed!")
            break

        # If at least one job passed, notify the user
        for index, result in enumerate(results):
            if result == ProwJobState.SUCCESS.value:
                logger.info('Prow job %s completed successfully', paths[index])
                so.say(f"<@{user_id}> prow job {paths[index]} completed successfully!")
                break

        # If not completed yet, wait and retry
        time.sleep(FIVE_MINUTES)

    # Remove slack object
    variables.active_slack_objects.remove(so)
