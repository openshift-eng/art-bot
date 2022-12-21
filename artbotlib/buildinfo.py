import asyncio
import json
import logging
import re
from typing import Tuple, Union
import time
from enum import Enum

import aiohttp
from aiohttp import client_exceptions
import koji

import artbotlib.exectools
from . import util, brew_list, constants


LOGGER = logging.getLogger(__name__)
util.log_config()


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

    LOGGER.info(f'Getting image info for {name}')

    if ".ci." in re.sub(".*:", "", release_img):
        so.say("Sorry, no ART build info for a CI image.")
        return None, None, None

    # Get release image pullspec
    release_img_pullspec, release_img_text = get_img_pullspec(release_img)
    if not release_img_pullspec:
        so.say("Sorry, I can only look up pullspecs for quay.io or registry.ci.openshift.org")
        return None, None, None

    # Get image pullspec
    rc, stdout, stderr = await artbotlib.exectools.cmd_gather_async(
        f"oc adm release info {release_img_pullspec} --image-for {name}",
        check=False
    )
    if rc:
        so.say(f"Sorry, I wasn't able to query the release image pullspec {release_img_pullspec}.")
        return None, None, None
    pullspec = stdout.strip()

    # Get image info
    rc, stdout, stderr = await artbotlib.exectools.cmd_gather_async(f"oc image info {pullspec} -o json")
    if rc:
        so.say(f"Sorry, I wasn't able to query the component image pullspec {pullspec}.")
        util.please_notify_art_team_of_error(so, stderr)
        return None, None, None

    # Parse JSON response
    try:
        data = json.loads(stdout)
    except Exception as exc:
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
    if img_name == "machine-os-content":
        # always a special case... not a brew build
        try:
            rhcos_build = build_info["config"]["config"]["Labels"]["version"]
            arch = build_info["config"]["architecture"]
        except KeyError:
            so.say(f"Sorry, I expected a 'version' label and architecture for pullspec "
                   f"{pullspec_text} but didn't see one. Weird huh?")
            return

        contents_url, stream_url = rhcos_build_urls(rhcos_build, arch)
        if contents_url:
            rhcos_build = f"<{contents_url}|{rhcos_build}> (<{stream_url}|stream>)"

        so.say(f"{release_img_text} `{img_name}` image {pullspec_text} came from RHCOS build {rhcos_build}")
        return

    try:
        labels = build_info["config"]["config"]["Labels"]
        name = labels["com.redhat.component"]
        version = labels["version"]
        release = labels["release"]
    except KeyError:
        so.say(f"Sorry, one of the component, version, or release labels is missing "
               f"for pullspec {pullspec_text}. Weird huh?")
        return

    nvr = f"{name}-{version}-{release}"
    url = brew_build_url(nvr)
    nvr_text = f"<{url}|{nvr}>" if url else nvr

    source_commit = labels.get("io.openshift.build.commit.id", "None")[:8]
    source_commit_url = labels.get("io.openshift.build.commit.url")
    source_text = f" from commit <{source_commit_url}|{source_commit}>" if source_commit_url else ""

    so.say(f"{release_img_text} `{img_name}` image {pullspec_text} came from brew build {nvr_text}{source_text}")
    return


def get_img_pullspec(release_img: str) -> Union[Tuple[None, None], Tuple[str, str]]:
    release_img_pullspec = release_img
    if ":" in release_img:
        # assume it's a pullspec already; make sure it's a known domain
        if not re.match(r"(quay.io|registry.ci.openshift.org)/", release_img):
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
    release_img_text = f"<docker://{release_img_pullspec}|{release_img}>"

    return release_img_pullspec, release_img_text


def rhcos_build_urls(build_id, arch="x86_64"):
    """
    base url for a release stream in the release browser
    @param build_id  the RHCOS build id string (e.g. "46.82.202009222340-0")
    @param arch      architecture we are interested in (e.g. "s390x")
    @return e.g.: https://releases-rhcos-art.apps.ocp-virt.prod.psi.redhat.com/?stream=releases/rhcos-4.6&release=46.82.202009222340-0#46.82.202009222340-0
    """

    minor_version = re.match("4([0-9]+)[.]", build_id)  # 4<minor>.8#.###
    if minor_version:
        minor_version = f"4.{minor_version.group(1)}"
    else:  # don't want to assume we know what this will look like later
        return None, None

    suffix = "" if arch in ["x86_64", "amd64"] else f"-{arch}"

    contents = f"{constants.RHCOS_BASE_URL}/" \
               f"contents.html?stream=releases/rhcos-{minor_version}{suffix}&release={build_id}"
    stream = f"{constants.RHCOS_BASE_URL}/?stream=releases/rhcos-{minor_version}{suffix}&release={build_id}#{build_id}"
    return contents, stream


async def rhcos_build_metadata(build_id, ocp_version, arch):
    """
    Fetches RHCOS build metadata
    :param build_id: e.g. '410.84.202212022239-0'
    :param ocp_version: e.g. '4.10'
    :param arch: one in {'x86_64', 'ppc64le', 's390x', 'aarch64'}
    :return: tuple of (build info json data, pullspec text, release image text)
    """

    LOGGER.info('Retrieving metadata for RHCOS build %s', build_id)

    # Old pipeline
    arch_suffix = '' if arch == 'x86_64' else f'-{arch}'
    old_pipeline_url = f'{constants.RHCOS_BASE_URL}/storage/releases/rhcos-{ocp_version}{arch_suffix}/' \
                       f'{build_id}/{arch}/commitmeta.json'
    try:
        async with aiohttp.ClientSession() as session:
            LOGGER.debug('Fetching URL %s', old_pipeline_url)
            async with session.get(old_pipeline_url) as resp:
                metadata = await resp.json()
        return metadata
    except aiohttp.client_exceptions.ContentTypeError:
        # This build belongs to the new pipeline
        pass

    # New pipeline
    new_pipeline_url = f'{constants.RHCOS_BASE_URL}/storage/prod/streams/{ocp_version}/builds/' \
                       f'{build_id}/{arch}/commitmeta.json'
    async with aiohttp.ClientSession() as session:
        LOGGER.debug('Fetching URL %s', new_pipeline_url)
        async with session.get(new_pipeline_url) as resp:
            metadata = await resp.json()
    return metadata


async def get_rhcos_build_id_from_release(release_img: str, arch) -> str:
    """
    Given a nightly or release, return the associated RHCOS build id

    :param release_img: e.g. 4.12.0-0.nightly-2022-12-20-034740, 4.10.10
    :param arch: one in {'amd64', 'arm64', 'ppc64le', 's390x'}
    :return: e.g. 412.86.202212170457-0
    """

    LOGGER.info('Retrieving rhcos build ID for %s', release_img)

    async with aiohttp.ClientSession() as session:
        url = f'https://{arch}.{constants.RC_BASE_HOSTNAME}/releasetag/{release_img}/json'
        LOGGER.debug('Fetching URL %s', url)

        async with session.get(url) as resp:
            release_info = await resp.json()

    return release_info['displayVersions']['machine-os']['Version']


def brew_build_url(nvr):
    try:
        build = util.koji_client_session().getBuild(nvr, strict=True)
    except Exception as e:
        # not clear how we'd like to learn about this... shouldn't happen much
        LOGGER.info(f"error searching for image {nvr} components in brew: {e}")
        return None

    return f"{constants.BREW_URL}/buildinfo?buildID={build['id']}"


def kernel_info(so, release_img, arch):
    """
    Currently, kernel and kernel-rt RPMs are found in images:
    - RHCOS
    - driver-toolkit
    - ironic-rhcos-downloader
    """

    # Validate arch parameter
    arch = 'amd64' if not arch else arch
    valid_arches = util.RC_ARCH_TO_RHCOS_ARCH.keys()
    if arch not in valid_arches:
        so.say(f'Arch {arch} is not valid: please choose one in {", ".join(valid_arches)}')
        return

    # Non-RHCOS kernel info
    async def non_rhcos_kernel_info(image):
        # Get image build for provided release image
        build_info, pullspec, _ = await get_image_info(so, image, release_img)
        labels = build_info["config"]["config"]["Labels"]
        name = labels["com.redhat.component"]
        version = labels["version"]
        release = labels["release"]
        build_nvr = f"{name}-{version}-{release}"

        # Get rpms version
        matched = brew_list.list_specific_rpms_for_image(['kernel-core', 'kernel-rt'], build_nvr)
        return {
            'name': image,
            'rpms': list(matched),
            'pullspec': pullspec
        }

    # RHCOS kernel info
    async def rhcos_kernel_info():
        ocp_version = util.ocp_version_from_release_img(release_img)
        rpms = []

        # Fetch release info from Release Controller to get RHCOS build ID
        rhcos_build_id = await get_rhcos_build_id_from_release(release_img, arch)

        # Fetch RHCOS build metadata
        metadata = await rhcos_build_metadata(rhcos_build_id, ocp_version, util.RC_ARCH_TO_RHCOS_ARCH[arch])
        pkg_list = metadata['rpmostree.rpmdb.pkglist']
        kernel_core = [pkg for pkg in pkg_list if 'kernel-core' in pkg][0]
        rpms.append(f'kernel-core.{".".join(kernel_core[2:])}')

        # Get kernel-rt-core from build labels, if available
        build_info, pullspec, _ = await get_image_info(so, 'machine-os-content', release_img)
        labels = build_info['config']['config']['Labels']
        if 'com.coreos.rpm.kernel-rt-core' in labels:
            rpms.append(f"kernel-rt-core.{labels['com.coreos.rpm.kernel-rt-core']}")

        return {
            'name': 'rhcos',
            'rpms': rpms,
            'pullspec': pullspec
        }

    so.say(f'Gathering image info for `{release_img}`...')

    # Format output and send to Slack
    res = asyncio.get_event_loop().run_until_complete(asyncio.gather(*[
        asyncio.ensure_future(non_rhcos_kernel_info('driver-toolkit')),
        asyncio.ensure_future(non_rhcos_kernel_info('ironic-machine-os-downloader')),
        asyncio.ensure_future(rhcos_kernel_info())
    ], return_exceptions=True))

    output = []
    for entry in res:
        if isinstance(entry, ChildProcessError):
            so.say(f"Sorry, I wasn't able to query the release image `{release_img}`.")
            return

        output.append(f'Kernel info for `{entry["name"]}` {entry["pullspec"]}:')
        output.append('```')
        output.extend(entry['rpms'])
        output.append('```')

    so.say('\n'.join(output))


def alert_on_build_complete(so, user_id, build_id):
    so.say(f'Ok <@{user_id}>, I\'ll respond here when the build completes')
    start = time.time()

    try:
        # Has the build passed in by ID?
        build_id = int(build_id)
    except ValueError: \
            # No, by URL
        build_id = int(build_id.split('=')[-1])

    while True:
        # Timeout after 12 hrs
        if time.time() - start > constants.TWELVE_HOURS:
            so.say(f'Build {build_id} did not complete in 12 hours, giving up...')
            return

        # Retrieve build info
        try:
            build = util.koji_client_session().getBuild(build_id, strict=True)
            state = BuildState(build['state'])
            LOGGER.info(f'Build {build_id} has state {state.name}')

        except ValueError:
            # Failed to convert the build state to a valid BuildState enum
            LOGGER.info(f'Unexpected status {build.state} for build {build_id}')
            so.say(f'Build {build_id} has unhandled status {state.name}. '
                   f'Check {constants.BREW_URL}/buildinfo?buildID={build_id} for details')
            return

        except koji.GenericError:
            # No such build
            message = f"Build {build_id} does not exist"
            so.say(message)
            return

        except Exception as e:
            # What else can happen?
            message = f"error getting information for build {build_id}: {e}"
            so.say(message)
            return

        # Check build state
        if state == BuildState.BUILDING:
            time.sleep(constants.FIVE_MINUTES)

        else:
            # state in [BuildState.COMPLETE, BuildState.FAILED, BuildState.CANCELED]:
            so.say(f'Build {build_id} completed with status {state.name}. '
                   f'Check {constants.BREW_URL}/buildinfo?buildID={build_id} for details')
            return
