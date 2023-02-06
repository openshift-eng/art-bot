import logging
import re

import aiohttp

from artbotlib import constants

logger = logging.getLogger(__name__)


async def get_rhcos_build_id_from_release(release_img: str, arch) -> str:
    """
    Given a nightly or release, return the associated RHCOS build id

    :param release_img: e.g. 4.12.0-0.nightly-2022-12-20-034740, 4.10.10
    :param arch: one in {'amd64', 'arm64', 'ppc64le', 's390x'}
    :return: e.g. 412.86.202212170457-0
    """

    logger.info('Retrieving rhcos build ID for %s', release_img)

    async with aiohttp.ClientSession() as session:
        url = f'{constants.RELEASE_CONTROLLER_URL.substitute(arch=arch)}/releasetag/{release_img}/json'
        logger.info('Fetching URL %s', url)

        async with session.get(url) as resp:
            try:
                release_info = await resp.json()
            except aiohttp.client_exceptions.ContentTypeError:
                logger.warning('Failed fetching url %s', url)
                return None

    try:
        release_info = release_info['displayVersions']['machine-os']['Version']
        logger.info('Retrieved release info: %s', release_info)
        return release_info
    except KeyError:
        logger.error('Failed retrieving release info')
        raise


async def rhcos_build_metadata(build_id, ocp_version, arch):
    """
    Fetches RHCOS build metadata
    :param build_id: e.g. '410.84.202212022239-0'
    :param ocp_version: e.g. '4.10'
    :param arch: one in {'x86_64', 'ppc64le', 's390x', 'aarch64'}
    :return: tuple of (build info json data, pullspec text, release image text)
    """

    logger.info('Retrieving metadata for RHCOS build %s', build_id)

    # Old pipeline
    arch_suffix = '' if arch == 'x86_64' else f'-{arch}'
    old_pipeline_url = f'{constants.RHCOS_BASE_URL}/storage/releases/rhcos-{ocp_version}{arch_suffix}/' \
                       f'{build_id}/{arch}/commitmeta.json'
    try:
        async with aiohttp.ClientSession() as session:
            logger.info('Fetching URL %s', old_pipeline_url)
            async with session.get(old_pipeline_url) as resp:
                metadata = await resp.json()
        return metadata

    except aiohttp.client_exceptions.ContentTypeError:
        # This build belongs to the new pipeline
        logger.info('Failed fetching data for build %s, trying with the new pipeline...', build_id)
        pass

    # New pipeline
    new_pipeline_url = f'{constants.RHCOS_BASE_URL}/storage/prod/streams/{ocp_version}/builds/' \
                       f'{build_id}/{arch}/commitmeta.json'
    try:
        async with aiohttp.ClientSession() as session:
            logger.info('Fetching URL %s', new_pipeline_url)
            async with session.get(new_pipeline_url) as resp:
                metadata = await resp.json()
            return metadata
    except aiohttp.client_exceptions.ContentTypeError:
        logger.error('Failed fetching data from url %s', new_pipeline_url)
        raise


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
    logger.info('Found urls for rhcos build %s:\n%s\n%s', build_id, contents, stream)
    return contents, stream
