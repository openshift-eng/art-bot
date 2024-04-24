import logging
import re
import aiohttp
import subprocess
from subprocess import PIPE
import urllib
import json

from artbotlib import constants
from artbotlib import exectools
from artcommonlib.rhcos import get_build_id_from_rhcos_pullspec

logger = logging.getLogger(__name__)


class RHCOSBuildInfo:
    def __init__(self, ocp_version, stream=None):
        self.ocp_version = ocp_version
        self.stream = stream or self._get_stream()

    @property
    def _builds_base_url(self):
        return f'{constants.RHCOS_BASE_URL}/storage/prod/streams/{self.stream}/builds'

    @property
    def builds_url(self):
        return f'{self._builds_base_url}/builds.json'

    def build_url(self, build_id, arch="x86_64"):
        return f'{self._builds_base_url}/{build_id}/{arch}'

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

    def latest_build_id(self, arch="x86_64"):
        builds_json_url = self.builds_url
        logger.info('Fetching URL %s', builds_json_url)

        with urllib.request.urlopen(builds_json_url) as url:
            data = json.loads(url.read().decode())

        for build in data["builds"]:
            if arch in build["arches"]:
                logger.info('Found build: %s', build)
                return build["id"]

        return None

    def build_metadata(self, build_id, arch):
        """
        Fetches RHCOS build metadata
        :param build_id: e.g. '410.84.202212022239-0'
        :param arch: one in {'x86_64', 'ppc64le', 's390x', 'aarch64'}
        :return: parsed json metadata
        """

        logger.info('Retrieving metadata for RHCOS build %s', build_id)

        meta_url = f'{self.build_url(build_id, arch)}/commitmeta.json'
        try:
            with urllib.request.urlopen(meta_url) as url:
                data = json.loads(url.read().decode())
            return data
        except aiohttp.client_exceptions.ContentTypeError:
            logger.error('Failed fetching data from url %s', url)
            raise


async def get_rhcos_build_id_from_pullspec(release_img_pullspec: str) -> str:
    """
    Given a nightly or release, return the associated RHCOS build id

    :param release_img_pullspec: e.g. registry.ci.openshift.org/ocp/release:4.12.0-0.nightly-2022-12-20-034740
    :return: e.g. 412.86.202212170457-0
    """

    build_id = None
    # TODO: use artcommonlib to do all of this
    # Hardcode rhcos tags for now
    # this comes from https://github.com/openshift-eng/ocp-build-data/blob/cc6a68a3446f2e80dddbaa9210897ed2812cb103/group.yml#L71C13-L71C24
    # we have logic in artcommonlib.rhcos to do all of this, so do not repeat it here
    rhcos_tag_1 = "machine-os-content"
    rhcos_tag_2 = "rhel-coreos"
    rc, stdout, stderr = exectools.cmd_gather(f"oc adm release info {release_img_pullspec} --image-for {rhcos_tag_1}")
    if rc:
        rc, stdout, stderr = exectools.cmd_gather(f"oc adm release info {release_img_pullspec} --image-for {rhcos_tag_2}")
        if rc:
            logger.error('Failed to get RHCOS image for %s: %s', release_img_pullspec, stderr)
            return None

    pullspec = stdout.split('\n')[0]

    try:
        build_id = get_build_id_from_rhcos_pullspec(pullspec)
    except Exception as e:
        logger.error('Failed to fetch RHCOS build id from pullspec %s: %s', pullspec, e)

    return build_id


def rhcos_build_urls(ocp_version, build_id, arch="x86_64"):
    """
    base url for a release stream in the release browser
    @param build_id  the RHCOS build id string (e.g. "46.82.202009222340-0")
    @param arch      architecture we are interested in (e.g. "s390x")
    @return e.g.: https://releases-rhcos-art.apps.ocp-virt.prod.psi.redhat.com/?stream=releases/rhcos-4.6&release=46.82.202009222340-0#46.82.202009222340-0
    """

    arch = constants.RC_ARCH_TO_RHCOS_ARCH.get(arch, arch)
    rhcos_build_info = RHCOSBuildInfo(ocp_version)
    build_suffix = f"?stream=prod/streams/{rhcos_build_info.stream}&release={build_id}&arch={arch}"
    contents = f"{constants.RHCOS_BASE_URL}/contents.html{build_suffix}"
    stream = f"{constants.RHCOS_BASE_URL}/{build_suffix}"
    return contents, stream
