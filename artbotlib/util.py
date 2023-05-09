import cachetools
import datetime
import koji
import logging
import functools
import requests
import os
from threading import RLock
from artbotlib.exceptions import BrewNVRNotFound
from artbotlib.kerberos import do_kinit

logger = logging.getLogger(__name__)


def please_notify_art_team_of_error(so, payload):
    dt = datetime.datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
    so.snippet(payload=payload,
               intro='Sorry, I encountered an error. Please contact @art-team with the following details.',
               filename=f'error-details-{dt}.txt')


def paginator(paged_function, member_name):
    """
    Lists are paginated, so here's a generator to page through all of them if needed.
    paged_function: a function that takes a cursor parameter and returns a paginated response object
    member_name: the member of the response object that has the paginated payload

    Example usage:
        for channel in paginator(lambda cursor: web_client.users_conversations(cursor=cursor), "channels"):
            # do stuff with channel
    """
    cursor = ""
    while True:
        response = paged_function(cursor)
        for ch in response[member_name]:
            yield ch
        cursor = response["response_metadata"].get("next_cursor")
        if not cursor:
            break


def lookup_channel(web_client, name, only_private=False, only_public=False):
    """
    Look up a channel by name.
    Only searches channels to which the bot has been added.
    Returns None or a channel record e.g. {'id': 'CB95J6R4N', 'name': 'aos-art', 'is_private': False, ...}
    """
    if only_private and only_public:
        raise Exception("channels cannot be both private and public")

    if only_private:
        types = "private_channel"
    elif only_public:
        types = "public_channel" if only_public else types
    else:
        types = "public_channel, private_channel"

    channel = None
    for ch in paginator(lambda c: web_client.users_conversations(types=types, cursor=c), "channels"):
        if ch["name"] == name:
            channel = ch
            break

    return channel


def koji_client_session():
    koji_api = koji.ClientSession('https://brewhub.engineering.redhat.com/brewhub')
    koji_api.hello()  # test for connectivity
    return koji_api


LOCK = RLock()
CACHE = cachetools.LRUCache(maxsize=2000)


def cached(func):
    """decorator to memoize functions"""

    @cachetools.cached(CACHE, lock=LOCK)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


CACHE_TTL = cachetools.TTLCache(maxsize=100, ttl=3600)  # expire after an hour


def cached_ttl(func):
    """decorator to memoize functions"""

    @cachetools.cached(CACHE_TTL, lock=LOCK)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def refresh_krb_auth(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        do_kinit()
        func_ret = func(*args, **kwargs)
        return func_ret

    return wrapper


def log_config(debug: bool = False):
    default_formatter = logging.Formatter('%(asctime)s [%(levelname)s] {%(filename)s:%(lineno)d} %(message)s')
    default_handler = logging.StreamHandler()
    default_handler.setFormatter(default_formatter)
    logging.basicConfig(
        handlers=[default_handler],
        level=logging.DEBUG if debug else logging.INFO
    )
    logging.getLogger('activemq').setLevel(logging.DEBUG)


def ocp_version_from_release_img(release_img: str) -> str:
    """
    Given a nightly or release name, return the OCP version

    :param release_img: e.g. '4.12.0-0.nightly-2022-12-20-034740', '4.10.10', quay.io/openshift-release-dev/ocp-release:4.12.12-x86_64
    :return: e.g. '4.10'
    """

    # is it a pullspec?
    if ':' in release_img:
        release_img = release_img.split(':')[1]
    return '.'.join(release_img.split('-')[0].split('.')[:2])


def get_build_nvr(build_id):
    """
    Get the NVR from the build ID
    """
    try:
        koji_api = koji_client_session()
        build = koji_api.getBuild(build_id)
        nvr = build['nvr']
        logger.debug(f"NVR: {nvr}")
        return nvr
    except Exception as e:
        raise BrewNVRNotFound(e)


def github_api_all(url: str):
    """
    GitHub API paginates results. This function goes through all the pages and returns everything.
    This function is used only for GitHub API endpoints that return a list as response. The endpoints that return
    json are usually not paginated.
    """
    logger.info("Fetching URL using function github_api_all %s", url)
    params = {'per_page': 100, 'page': 1}
    header = {"Authorization": f"token {os.environ['GITHUB_PERSONAL_ACCESS_TOKEN']}"}
    num_requests = 1  # Guard against infinite loop
    max_requests = 100

    response = requests.get(url, params=params, headers=header)
    results = response.json()

    while "next" in response.links.keys() and num_requests <= max_requests:
        url = response.links['next']['url']
        response = requests.get(url, headers=header)

        if response.status_code != 200:
            logger.error('Could not fetch data from %s', url)

        results += response.json()
        num_requests += 1
    return results
