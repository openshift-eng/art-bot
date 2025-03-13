import asyncio
import json
import logging
import re
from typing import Tuple, Union
import time
from enum import Enum

import koji
from artcommonlib import redis
from pyartcd.constants import JENKINS_UI_URL
from pyartcd.locks import Lock, Keys

from . import util, constants, exectools, variables
from .rhcos import rhcos_build_urls

logger = logging.getLogger(__name__)


class BuildState(Enum):
    BUILDING = 0
    COMPLETE = 1
    FAILED = 3
    CANCELED = 4


async def get_image_info(so, name, release_img) -> Union[Tuple[None, None, None], Tuple[str, str, str]]:
    """
    Returns build info for image <name> in <release_img>. Notifies Slack in case of errors

    :param so: Slack outputter
    :param name: image to check build info for
    :param release_img: release image name or pullspec
    :return: tuple of (build info json data, pullspec text, release image text)
    """

    logger.info(f'Getting image info for {name}')

    if ".ci." in re.sub(".*:", "", release_img):
        logger.error("Sorry, no ART build info for a CI image.")
        so.say("Sorry, no ART build info for a CI image.")
        return None, None, None

    # Get release image pullspec
    logger.info('Retrieving pullspec for release image %s', release_img)
    release_img_pullspec, release_img_text = get_img_pullspec(release_img)
    if not release_img_pullspec:
        logger.error('Only pullspecs for quay.io or registry.ci.openshift.org can be looked up')
        so.say("Sorry, I can only look up pullspecs for quay.io or registry.ci.openshift.org")
        return None, None, None

    # Get image pullspec
    rc, stdout, stderr = await exectools.cmd_gather_async(
        f"oc adm release info {release_img_pullspec} --image-for {name}",
        check=False
    )
    if rc:
        logger.error('oc failed with rc %s: %s', rc, stderr)
        if f'no image tag "{name}" exists' in stderr:
            so.say(f"I wasn't able to find the image {name} in release {release_img_text}.")
        elif 'manifest unknown' in stderr:
            so.say(f"I wasn't able to find the release {release_img_text}.")
        else:
            so.say(f"Sorry, something went wrong when I tried to query {release_img_text}.")
        return None, None, None

    pullspec = stdout.strip()
    logger.info('Found image pullspec: %s', pullspec)

    # Get image info
    rc, stdout, stderr = await exectools.cmd_gather_async(f"oc image info {pullspec} -o json")
    if rc:
        logger.error('oc failed with rc %s: %s', rc, stderr)
        so.say(f"Sorry, I wasn't able to query the component image pullspec {pullspec}.")
        util.please_notify_art_team_of_error(so, stderr)
        return None, None, None

    # Parse JSON response
    logger.info('Parsing JSON response')
    try:
        data = json.loads(stdout)
    except Exception as exc:
        logger.error('Failed decoding the JSON info for pullspec %s', pullspec)
        so.say(f"Sorry, I wasn't able to decode the JSON info for pullspec {pullspec}.")
        util.please_notify_art_team_of_error(so, str(exc))
        return None, None, None

    return data, f"(<docker://{pullspec}|pullspec>)", release_img_text


def buildinfo_for_release(so, name, release_img):
    """
    :param so: Slack outputter
    :param name: image to check build info for, e.g. 'driver-toolkit'
    :param release_img: release image name or pullspec e.g. '4.11.0-0.nightly-2022-07-08-182347',
            'registry.ci.openshift.org/ocp/release:4.11.0-0.nightly-2022-07-11-080250', '4.10.22'
    """

    img_name = "machine-os-content" if name == "rhcos" else name  # rhcos shortcut...

    loop = asyncio.new_event_loop()

    build_info, pullspec_text, release_img_text = loop.run_until_complete(get_image_info(so, img_name, release_img))
    if not build_info:
        # Errors have already been notified: just do nothing
        return

    # Parse image build info
    # TODO: This needs to be all tags in "rhcos: payload_tags" group.yml file
    if img_name == "machine-os-content":
        # always a special case... not a brew build
        logger.info('Parsing RHCOS build info')

        try:
            rhcos_build_id = build_info["config"]["config"]["Labels"]["version"]
            arch = build_info["config"]["architecture"]
        except KeyError:
            logger.error("no 'version' or 'architecture' labels found: %s", build_info['config'])
            so.say(f"Sorry, I expected a 'version' label and architecture for pullspec "
                   f"{pullspec_text} but didn't see one. Weird huh?")
            return

        ocp_version = util.ocp_version_from_release_img(release_img)
        contents_url, stream_url = rhcos_build_urls(ocp_version, rhcos_build_id, arch)
        if contents_url:
            rhcos_build_url = f"<{contents_url}|{rhcos_build_id}> (<{stream_url}|stream>)"
            logger.info('Found RHCOS build: %s', stream_url)
        else:
            rhcos_build_url = rhcos_build_id
            logger.warning('No RHCOS build URLs found')

        so.say(f"{release_img_text} `{img_name}` image {pullspec_text} came from RHCOS build {rhcos_build_url}")
        return

    try:
        logger.info('Parsing build info')
        labels = build_info["config"]["config"]["Labels"]
        name = labels["com.redhat.component"]
        version = labels["version"]
        release = labels["release"]
        source_commit = labels.get("io.openshift.build.commit.id", "None")[:8]
        source_commit_url = labels.get("io.openshift.build.commit.url")
    except KeyError:
        logger.error('Some of the expected labels were not found: %s', labels)
        so.say(f"Some labels are missing for pullspec {pullspec_text}. Weird huh?")
        return

    nvr = f"{name}-{version}-{release}"
    logger.info('Found nvr: %s', nvr)

    url = brew_build_url(nvr)
    if not url:
        so.say(f'Sorry, I encountered an error searching for image {nvr} components in brew')
        return
    logger.info('Found brew build URL: %s', url)
    nvr_text = f"<{url}|{nvr}>" if url else nvr

    source_text = f" from commit <{source_commit_url}|{source_commit}>" if source_commit_url else ""
    so.say(f"{release_img_text} `{img_name}` image {pullspec_text} came from brew build {nvr_text}{source_text}")


def get_img_pullspec(release_img: str) -> Union[Tuple[None, None], Tuple[str, str]]:
    release_img_pullspec = release_img

    if ":" in release_img:
        # assume it's a pullspec already; make sure it's a known domain
        if not re.match(r"(quay.io|registry.ci.openshift.org)/", release_img):
            logger.warning('%s is not a known domain: giving up', release_img)
            return None, None
        release_img = re.sub(r".*/", "", release_img)

    elif "nightly" in release_img:
        suffix = "-s390x" if "s390x" in release_img else "-ppc64le" if "ppc64le" in release_img \
            else "-arm64" if "arm64" in release_img else ""
        release_img_pullspec = f"registry.ci.openshift.org/ocp{suffix}/release{suffix}:{release_img}"

    else:
        # assume public release name
        release_img_pullspec = f"quay.io/openshift-release-dev/ocp-release:{release_img}"
        if not re.search(r"-(s390x|ppc64le|x86_64)$", release_img_pullspec):
            # assume x86_64 if not specified; TODO: handle older images released without -x86_64 in pullspec
            release_img_pullspec = f"{release_img_pullspec}-x86_64"

    logger.info('Found pullspec for image %s: %s', release_img, release_img_pullspec)
    return release_img_pullspec, f"<docker://{release_img_pullspec}|{release_img}>"


def brew_build_url(nvr):
    try:
        build = util.koji_client_session().getBuild(nvr, strict=True)
    except Exception as e:
        # not clear how we'd like to learn about this... shouldn't happen much
        logger.error(f"error searching for image {nvr} components in brew: {e}")
        return None

    url = f"{constants.BREW_URL}/buildinfo?buildID={build['id']}"
    logger.info('Found brew build URL for %s: %s', nvr, url)
    return url


def alert_on_build_complete(so, user_id, build_id):
    so.say(f'Ok <@{user_id}>, I\'ll respond here when the build completes')
    start = time.time()
    variables.active_slack_objects.add(so)

    try:
        # Has the build passed in by ID?
        build_id = int(build_id)
    except ValueError:
        # No, by URL
        build_id = int(build_id.split('=')[-1])

    try:
        while True:
            # Timeout after 12 hrs
            if time.time() - start > constants.TWELVE_HOURS:
                so.say(f'Build {build_id} did not complete in 12 hours, giving up...')
                break

            # Retrieve build info
            build = util.koji_client_session().getBuild(build_id, strict=True)
            state = BuildState(build['state'])
            logger.info(f'Build {build_id} has state {state.name}')

            # Check build state
            if state == BuildState.BUILDING:
                time.sleep(constants.FIVE_MINUTES)

            else:
                # state in [BuildState.COMPLETE, BuildState.FAILED, BuildState.CANCELED]:
                so.say(f'Build {build_id} completed with status {state.name}. '
                       f'Check {constants.BREW_URL}/buildinfo?buildID={build_id} for details')
                break

    except ValueError:
        # Failed to convert the build state to a valid BuildState enum
        logger.warning(f'Unexpected status for build {build_id}')
        so.say(f'Unexpected status for build {build_id}. '
               f'Check {constants.BREW_URL}/buildinfo?buildID={build_id} for details')

    except koji.GenericError:
        # No such build
        logger.error('No such build %s', build_id)
        message = f"Build {build_id} does not exist"
        so.say(message)

    except Exception as e:
        # What else can happen?
        message = f"error getting information for build {build_id}: {e}"
        logger.error(message)
        so.say(message)

    finally:
        variables.active_slack_objects.remove(so)


def mass_rebuild_status(so, build_system: str):
    build_system = build_system.lower() if build_system else 'brew'
    if build_system.lower() not in ['brew', 'konflux']:
        so.say(f'Invalid build system "{build_system}. Valid values are ("brew", "konflux")')
        return

    if build_system.lower() == 'brew':
        lock = Lock.MASS_REBUILD.value
        key = Keys.BREW_MASS_REBUILD_QUEUE.value
    else:  # build_system.lower() == 'konflux'
        lock = Lock.KONFLUX_MASS_REBUILD.value
        key = Keys.KONFLUX_MASS_REBUILD_QUEUE.value

    output = []

    async def check_active():
        # Check for active mass rebuild
        job_path = await redis.get_value(lock)
        if not job_path:
            output.append('No mass rebuild currently running')
        else:
            output.append(f':construction: Mass rebuild actively running at {JENKINS_UI_URL}/{job_path}')

    async def check_enqueued():
        # Check for enqueued mass rebuilds
        result = await redis.call('zrange', key, 0, -1, desc=True)
        if not result:
            output.append('No mass rebuild currently enqueued')
        else:
            output.append(f':hourglass: Mass rebuilds currently waiting in the queue: {", ".join(result)}')

    tasks = [check_active(), check_enqueued()]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(asyncio.gather(*tasks))

    so.say('\n'.join(output))
