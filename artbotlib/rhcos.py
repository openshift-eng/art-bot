import logging
import re
import aiohttp
import subprocess

from subprocess import PIPE
from artbotlib import constants

logger = logging.getLogger(__name__)


class RHCOSBuildInfo:
    def __init__(self, ocp_version):
        self.ocp_version = ocp_version
        self.stream = self._get_stream()

    def _get_stream(self):
        # doozer --quiet -g openshift-4.14 config:read-group urls.rhcos_release_base.multi --default ''
        # https://releases-rhcos-art.apps.ocp-virt.prod.psi.redhat.com/storage/prod/streams/4.14-9.2/builds
        cmd = [
            "doozer",
            "--quiet",
            "--group", f'openshift-{self.ocp_version}',
            "config:read-group",
            "urls.rhcos_release_base.multi",
            "--default",
            "''"
        ]
        result = subprocess.run(cmd, stdout=PIPE, stderr=PIPE, check=False, universal_newlines=True)
        if result.returncode != 0:
            raise IOError(f"Command {cmd} returned {result.returncode}: stdout={result.stdout}, stderr={result.stderr}")
        match = re.search(r'streams/(.*)/builds', result.stdout)
        if match:
            stream = match[1]
        else:
            stream = self.ocp_version
        return stream

    def release_url(self, arch="x86_64"):
        arch_suffix = "" if arch == "x86_64" else f"-{arch}"
        return f'{constants.RHCOS_BASE_URL}/storage/prod/streams/{self.ocp_version}'

    def build_url(self, build_id, arch="x86_64"):
        return f"{self.release_url(arch)}/builds/{build_id}/{arch}"

    def browser_urls(self, build_id, arch="x86_64"):
        """
        base url for a release stream in the release browser
        @param build_id  the RHCOS build id string (e.g. "412.86.202304050931-0")
        @param arch      architecture we are interested in (e.g. "x86_64")
        @return 2 url strings (content_url, stream_url) or (None, None) if we can't parse the build_id
        """

        build_suffix = f"?stream=prod/streams/{self.stream}&release={build_id}&arch={arch}"
        contents = f"{constants.RHCOS_BASE_URL}/contents.html{build_suffix}"
        stream = f"{constants.RHCOS_BASE_URL}/{build_suffix}"
        logger.info('Found urls for rhcos build %s:\n%s\n%s', build_id, contents, stream)
        return contents, stream

    async def build_metadata(self, build_id, arch):
        """
        Fetches RHCOS build metadata
        :param build_id: e.g. '410.84.202212022239-0'
        :param ocp_version: e.g. '4.10'
        :param arch: one in {'x86_64', 'ppc64le', 's390x', 'aarch64'}
        :return: tuple of (build info json data, pullspec text, release image text)
        """

        logger.info('Retrieving metadata for RHCOS build %s', build_id)

        pipeline_url = f'{self.build_url(build_id, arch)}/commitmeta.json'
        try:
            async with aiohttp.ClientSession() as session:
                logger.info('Fetching URL %s', pipeline_url)
                async with session.get(pipeline_url) as resp:
                    metadata = await resp.json()
                return metadata
        except aiohttp.client_exceptions.ContentTypeError:
            logger.error('Failed fetching data from url %s', pipeline_url)
            raise


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
