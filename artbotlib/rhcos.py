import logging
import re
import aiohttp
import subprocess
import urllib
import json

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

    @property
    def _builds_base_url(self):
        return f'{constants.RHCOS_BASE_URL}/storage/prod/streams/{self.stream}/builds'

    @property
    def builds_url(self):
        return f'{self._builds_base_url}/builds.json'

    def build_url(self, build_id, arch="x86_64"):
        return f'{self._builds_base_url}/{build_id}/{arch}'

    def get_latest_build_id(self, arch="x86_64"):
        builds_json_url = self.builds_url
        logger.info('Fetching URL %s', builds_json_url)

        with urllib.request.urlopen(builds_json_url) as url:
            data = json.loads(url.read().decode())

        for build in data["builds"]:
            if arch in build["arches"]:
                logger.info('Found build: %s', build)
                return build["id"]

        return None

    def browser_urls(self, build_id, arch="x86_64"):
        """
        release browser urls for a build_id and release stream
        @param build_id  the RHCOS build id string (e.g. "412.86.202304050931-0")
        @param arch      architecture we are interested in (e.g. "x86_64")
        @return 2 url strings (content_url, stream_url) or (None, None) if we can't parse the build_id
        """

        build_suffix = f"?stream=prod/streams/{self.stream}&release={build_id}&arch={arch}"
        content_url = f"{constants.RHCOS_BASE_URL}/contents.html{build_suffix}"
        stream_url = f"{constants.RHCOS_BASE_URL}/{build_suffix}"
        return content_url, stream_url

    async def build_metadata(self, build_id, arch):
        """
        Fetches RHCOS build metadata
        :param build_id: e.g. '410.84.202212022239-0'
        :param arch: one in {'x86_64', 'ppc64le', 's390x', 'aarch64'}
        :return: parsed json metadata
        """

        logger.info('Retrieving metadata for RHCOS build %s', build_id)

        url = f'{self.build_url(build_id, arch)}/commitmeta.json'
        try:
            async with aiohttp.ClientSession() as session:
                logger.info('Fetching URL %s', url)
                async with session.get(url) as resp:
                    metadata = await resp.json()
                return metadata
        except aiohttp.client_exceptions.ContentTypeError:
            logger.error('Failed fetching data from url %s', url)
            raise


async def get_rhcos_build_rpms(so, major_minor, arch="x86_64", build_id=None):
    # returns a set of RPMs used in the specified or most recent rhcos build for release major_minor
    rhcos_build_info = RHCOSBuildInfo(major_minor)
    build_id = build_id or rhcos_build_info.get_latest_build_id(arch)
    if not build_id:
        return set()

    try:
        metadata = await rhcos_build_info.build_metadata(build_id, arch)
        rpms = metadata["rpmostree.rpmdb.pkglist"]
        logger.info('Found rpms: %s', rpms)
        return set(f"{n}-{v}-{r}" for n, e, v, r, a in rpms)

    except Exception as ex:
        logger.error('Encountered error looking up latest RHCOS build RPMs in %s: %s', major_minor, ex)
        so.say("Encountered error looking up the latest RHCOS build RPMs.")
        so.say_monitoring(f"Encountered error looking up the latest RHCOS build RPMs: {ex}")
        return set()


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
