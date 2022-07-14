import requests
import time
from typing import Union

COLOR_MAPS = {
    'Accepted': 'Green',
    'Rejected': 'Red'
}

TWELVE_HOURS = 60 * 60 * 12
FIVE_MINUTES = 60 * 5


def get_nightly_color(release_url, release_browser) -> Union[str, None]:
    """
    Function to get the color of the nightly for the given release browser
    :param release_url: URL of the nightly/release eg: /releasestream/4.10.0-0.nightly/release/4.10.0-0.nightly-2022-07-13-131411
    :param release_browser: release browser eg: ppc64le/arm64/s390x/amd64
    :return:
    """
    url = f"https://{release_browser}.ocp.releases.ci.openshift.org/api/v1{release_url}"
    response = requests.get(url)  # query API to get the status

    status = response.json()['phase']
    return COLOR_MAPS.get(status, None)


def nightly_color_status(so, user_id, release_url, release_browser) -> None:
    """
    Driver function to provide slack update if color of nightly changes from blue to green/red
    :param so: Slack object
    :param user_id: User ID of the person who invoked ART-Bot
    :param release_url: URL of the nightly eg: /releasestream/4.10.0-0.nightly/release/4.10.0-0.nightly-2022-07-13-131411
    :param release_browser: release browser eg: ppc64le/arm64/s390x/amd64
    :return: None
    """
    try:
        color = get_nightly_color(release_url, release_browser)
        if color:  # if color is not blue return the current color and exit
            so.say(f"<@{user_id}> Color of nightly is already `{color}`")
            return

        so.say(f"<@{user_id}> Ok, I'll respond here when tests have finished.")
        start = time.time()
        while True:
            now = time.time()
            if now - start > TWELVE_HOURS:  # Timeout after 12 hrs.
                so.say(f"<@{user_id}> Color didn't change even after 12 hrs :(")
                break

            time.sleep(FIVE_MINUTES)  # check every 5 minutes

            color = get_nightly_color(release_url, release_browser)
            if color:
                so.say(f"<@{user_id}> Color of {release_browser} nightly {release_url.split('/')[-1]} changed to `{color}`!")
                break
    except Exception as e:
        so.say(f"Unexpected Error: {e}")
