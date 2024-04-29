import logging

import requests
import time
from typing import Union
import json
import artbotlib.variables as variables
from artbotlib.constants import COLOR_MAPS, TWELVE_HOURS, FIVE_MINUTES

logger = logging.getLogger(__name__)


def get_release_data(release_url, release_browser) -> json:
    """
    Function to get the release data from the API

    :param release_url: URL of the nightly/release eg: /releasestream/4.10.0-0.nightly/release/4.10.0-0.nightly-2022-07-13-131411
    :param release_browser: release browser eg: ppc64le/arm64/s390x/amd64
    :return: JSON object
    """

    url = f"https://{release_browser}.ocp.releases.ci.openshift.org/api/v1{release_url}"
    logger.info('Fetching URL %s', url)

    response = requests.get(url)  # query API to get the status
    status_code = response.status_code
    if status_code != 200:
        logger.error('Server responded with status code %s', status_code)

    return response.json()


def get_nightly_color(release_url, release_browser) -> Union[str, None]:
    """
    Function to get the color of the nightly for the given release browser

    :param release_url: URL of the nightly/release eg: /releasestream/4.10.0-0.nightly/release/4.10.0-0.nightly-2022-07-13-131411
    :param release_browser: release browser eg: ppc64le/arm64/s390x/amd64
    :return: Green/Red/None
    """

    status = get_release_data(release_url, release_browser)['phase']
    return COLOR_MAPS.get(status, None)


def get_failed_jobs(release_url, release_browser) -> str:
    """
    Function to get all the failed jobs

    :param release_url: URL of the nightly/release eg: /releasestream/4.10.0-0.nightly/release/4.10.0-0.nightly-2022-07-13-131411
    :param release_browser: release browser eg: ppc64le/arm64/s390x/amd64
    :return: Newline separated strings
    """

    status = get_release_data(release_url, release_browser)

    payload = "Jobs pending/failed:\n"
    jobs = status['results']['blockingJobs']
    for job in jobs:
        if jobs[job]['state'].lower() != "succeeded":
            payload += f"<{jobs[job]['url']}|{job}>\n"
    return payload


def get_latest_nightly_name(release_stream) -> Union[str, None]:
    url = f"https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/{release_stream}/tags"
    logger.info('Fetching URL %s', url)

    response = requests.get(url)  # query API to get list of nightly tags
    if response.status_code != 200:
        logger.error('Server responded with status code %s', response.status_code)
        return None

    return response.json()['tags'][0]['name']


def latest_nightly_color_status(so, user_id, version) -> None:
    """
    Driver function to provide slack update if color of the latest nightly changes from blue to green/red

    :param so: Slack object
    :param user_id: User ID of the person who invoked ART-Bot
    :param version: OCP version eg: 4.15/4.16
    :return: None
    """

    release_stream = f"{version}.0-0.nightly"

    latest_nightly_name = get_latest_nightly_name(release_stream)
    if latest_nightly_name is None:
        so.say(f"<@{user_id}> I could not retrieve latest nightlies from https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/{release_stream}/tags")
        return

    latest_release_url = f"/releasestream/{release_stream}/release/{latest_nightly_name}"

    nightly_color_status(so, user_id, latest_release_url, "amd64")


def nightly_color_status(so, user_id, release_url, release_browser) -> None:
    """
    Driver function to provide slack update if color of nightly changes from blue to green/red

    :param so: Slack object
    :param user_id: User ID of the person who invoked ART-Bot
    :param release_url: URL of the nightly eg: /releasestream/4.10.0-0.nightly/release/4.10.0-0.nightly-2022-07-13-131411
    :param release_browser: release browser eg: ppc64le/arm64/s390x/amd64
    :return: None
    """

    slack_url_payload = f"<https://{release_browser}.ocp.releases.ci.openshift.org{release_url}|{release_url.split('/')[-1]}>"
    color = get_nightly_color(release_url, release_browser)
    if color:  # if color is not blue return the current color and exit
        so.say(f"<@{user_id}> {slack_url_payload} is already `{color}` !")
        if color == "Red":
            payload = get_failed_jobs(release_url, release_browser)
            so.say(payload)
        return

    so.say(f"<@{user_id}> Ok, I'll respond here when tests have finished.")
    start = time.time()
    variables.active_slack_objects.add(so)
    try:
        while True:
            now = time.time()
            if now - start > TWELVE_HOURS:  # Timeout after 12 hrs.
                so.say(f"<@{user_id}> {slack_url_payload} didn't change even after 12 hrs :(")
                break

            time.sleep(FIVE_MINUTES)  # check every 5 minutes

            color = get_nightly_color(release_url, release_browser)
            if color:
                so.say(f"<@{user_id}> {slack_url_payload} changed to `{color}` !")
                if color == "Red":
                    payload = get_failed_jobs(release_url, release_browser)
                    so.say(payload)
                break
    finally:
        variables.active_slack_objects.remove(so)
