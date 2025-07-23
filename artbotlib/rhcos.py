import logging
import os
import re
import aiohttp
import subprocess
import tempfile
from subprocess import PIPE
import urllib.request
import json
from typing import Optional

from artbotlib import constants
from artbotlib import exectools
from artbotlib import util
from artcommonlib.rhcos import get_build_id_from_rhcos_pullspec

logger = logging.getLogger(__name__)


class RHCOSBuildInfo:
    def __init__(self, ocp_version, stream=None):
        self.ocp_version = ocp_version
        self.stream = stream or self._get_stream()

        raw_group_config = util._get_raw_group_config(f"openshift-{self.ocp_version}")
        self.is_layered = raw_group_config.get("rhcos", {}).get("layered_rhcos", False)

        rhcos_el_major = raw_group_config.get("vars", {}).get("RHCOS_EL_MAJOR", "")
        rhcos_el_minor = raw_group_config.get("vars", {}).get("RHCOS_EL_MINOR", "")
        self.rhcos_el_major_minor = f"{rhcos_el_major}.{rhcos_el_minor}"

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
        # https://releases-rhcos--prod-pipeline.apps.int.prod-stable-spoke1-dc-iad2.itup.redhat.com/storage/prod/streams/4.14-9.2/builds
        cmd = [
            "doozer",
            "--quiet",
            "--group", f'openshift-{self.ocp_version}',
            "config:read-group",
            "urls.rhcos_release_base.multi",
            "--default",
            "''"
        ]
        result = subprocess.run(cmd, stdout=PIPE, stderr=PIPE, check=False, universal_newlines=True, env=os.environ.copy())
        if result.returncode != 0:
            raise IOError(f"Command {cmd} returned {result.returncode}: stdout={result.stdout}, stderr={result.stderr}")
        match = re.search(r'streams/(.*)/builds', result.stdout)
        if match:
            stream = match[1]
        else:
            stream = self.ocp_version
        return stream

    def latest_build_id(self, arch="x86_64"):
        if self.is_layered:
            extensions_pullspec = f"quay.io/openshift-release-dev/ocp-v4.0-art-dev:{self.ocp_version}-{self.rhcos_el_major_minor}-node-image-extensions"
            labels = util.get_image_labels(extensions_pullspec, arch=arch)
            return labels.get("coreos.build.manifest-list-tag", "").replace("-node-image-extensions", "")

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

    def get_extensions_rpms(self, extensions_pullspec: str) -> set[str]:
        """
        Extract RPMs from the extensions layer.

        :param extensions_tag: Pullspec for node-image-extensions
        :return: Set of extension RPMs in name-version-release format
        """
        extensions_rpms = set()

        with tempfile.TemporaryDirectory() as temp_dir:
            extensions_file = util.extract_file_from_image(
                extensions_pullspec, "/usr/share/rpm-ostree/extensions.json", temp_dir
            )
            if not extensions_file:
                return extensions_rpms

            # Parse extensions.json
            try:
                with open(extensions_file, 'r') as f:
                    extensions_data = json.load(f)

                for name, vra in extensions_data.items():
                    version_release = vra.rsplit('.', 1)[0]  # Remove .<arch> suffix
                    extensions_rpms.add(f"{name}-{version_release}")

                logger.info('Found %s extension RPMs', len(extensions_rpms))

            except Exception as e:
                logger.error('Failed to parse extensions.json: %s', e)

        return extensions_rpms

    def get_node_rpms(self, node_image_pullspec: str):
        """
        Extract RPMs from the node layer.

        :param node_image_pullspec: Pullspec for node-image
        :return: Set of node RPMs in name-version-release format
        """
        node_rpms = set()

        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract base/meta.json from node-image
            meta_file = util.extract_file_from_image(
                node_image_pullspec, "/usr/share/openshift/base/meta.json", temp_dir
            )
            if not meta_file:
                return node_rpms

            # Parse meta.json
            try:
                with open(meta_file, 'r') as f:
                    meta_data = json.load(f)

                # Extract node RPMs
                rpm_list = meta_data.get("rpmdb.pkglist", [])
                for name, _, version, release, _ in rpm_list:
                    node_rpms.add(f"{name}-{version}-{release}")

                logger.info('Found %s node RPMs', len(node_rpms))

            except Exception as e:
                logger.error('Failed to parse node meta.json: %s', e)

        return node_rpms

    def get_rhel_rpms(self, rhel_build_id: str, arch="x86_64"):
        """
        Extract RPMs from the RHEL layer via commitmeta.json.

        :param rhel_build_id: RHEL build ID (e.g. 9.6.20250611-0)
        :param arch: Architecture (default: x86_64)
        :return: Set of RHEL RPMs in name-version-release format
        """
        rhel_rpms = set()

        commitmeta_url = f"{constants.RHCOS_BASE_URL}/storage/prod/streams/rhel-{self.rhcos_el_major_minor}/builds/{rhel_build_id}/{arch}/commitmeta.json"

        logger.info('Fetching RHEL layer commitmeta.json from: %s', commitmeta_url)

        try:
            with urllib.request.urlopen(commitmeta_url) as response:
                commitmeta_data = json.loads(response.read().decode())

            rhel_rpm_list = commitmeta_data.get("rpmostree.rpmdb.pkglist", [])
            for name, _, version, release, _ in rhel_rpm_list:
                rhel_rpms.add(f"{name}-{version}-{release}")

            logger.info('Found %s RHEL layer RPMs', len(rhel_rpms))

        except Exception as e:
            logger.error('Failed to fetch RHEL layer commitmeta.json: %s', e)

        return rhel_rpms

    def find_layered_rhcos_rpms(self, build_id: str, arch="x86_64") -> set[str]:
        """
        Retrieve RPMs from the layered RHCOS specified by build_id

        :param build_id: Build ID of the RHCOS build (e.g. 4.19-9.6-202506131500)
        :param arch: Architecture (default: x86_64)
        :return: Set of RPMs used in the RHCOS
        """
        try:
            # Get RPMs from extensions layer
            extensions_pullspec = f"quay.io/openshift-release-dev/ocp-v4.0-art-dev:{build_id}-node-image-extensions"
            logger.info('Processing extensions layer: %s', extensions_pullspec)
            extensions_rpms = self.get_extensions_rpms(extensions_pullspec)
            if not extensions_rpms:
                logger.warning('No extensions layer RPMs found')

            # Get RPMs from node layer
            node_image_pullspec = f"quay.io/openshift-release-dev/ocp-v4.0-art-dev:{build_id}-node-image"
            logger.info('Processing node layer: %s', node_image_pullspec)
            node_rpms = self.get_node_rpms(node_image_pullspec)
            if not node_rpms:
                logger.warning('No node layer RPMs found')

            # Get RHEL layer build ID from node-image labels
            node_labels = util.get_image_labels(node_image_pullspec, arch=arch)
            rhel_build_id = node_labels.get('org.opencontainers.image.version')

            # Get RPMs from RHEL layer
            logger.info('Processing RHEL layer with build ID: %s', rhel_build_id)
            rhel_rpms = self.get_rhel_rpms(rhel_build_id, arch)
            if not rhel_rpms:
                logger.warning("No RHEL layer RPMs found")

            return extensions_rpms | node_rpms | rhel_rpms

        except Exception as ex:
            logger.error('Error processing layered RHCOS %s: %s', build_id, ex)
            return set()

    def find_non_layered_rhcos_rpms(self, build_id: str, arch: str = "x86_64") -> set[str]:
        metadata = self.build_metadata(build_id, arch)
        if metadata == {}:
            return set()
        return set(f"{n}-{v}-{r}" for n, e, v, r, a in metadata["rpmostree.rpmdb.pkglist"])

    def find_rhcos_rpms(self, build_id: str, arch: str = "x86_64") -> set[str]:
        if self.is_layered:
            return self.find_layered_rhcos_rpms(build_id=build_id, arch=arch)
        return self.find_non_layered_rhcos_rpms(build_id=build_id, arch=arch)


async def get_rhcos_build_id_from_pullspec(release_img_pullspec: str) -> Optional[str]:
    """
    Given a nightly or release, return the associated RHCOS build id

    :param release_img_pullspec: e.g. registry.ci.openshift.org/ocp/release:4.12.0-0.nightly-2022-12-20-034740
    :return: e.g. 412.86.202212170457-0 (for traditional RHCOS) or 4.12-8.6-202212170457 (for layered RHCOS)
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

        # get_build_id_from_rhcos_pullspec() returns two different formats
        # depending on whether it's layered rhcos or not
        layered_match = re.match(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)\.(\d+)-0$", build_id)

        if layered_match:
            # get_build_id_from_rhcos_pullspec() for layered layered RHCOS returns ID
            # in format like 4.19.9.6.202505081313-0 but we need 4.19-9.6-202505081313
            build_id = f"{layered_match.group(1)}.{layered_match.group(2)}-{layered_match.group(3)}.{layered_match.group(4)}-{layered_match.group(5)}"

    except Exception as e:
        logger.error('Failed to fetch RHCOS build id from pullspec %s: %s', pullspec, e)

    return build_id


def rhcos_build_urls(ocp_version, build_id, arch="x86_64"):
    """
    base url for a release stream in the release browser
    @param build_id  the RHCOS build id string (e.g. "46.82.202009222340-0")
    @param arch      architecture we are interested in (e.g. "s390x")
    @return e.g.: https://releases-rhcos--prod-pipeline.apps.int.prod-stable-spoke1-dc-iad2.itup.redhat.com/?stream=releases/rhcos-4.6&release=46.82.202009222340-0#46.82.202009222340-0
    """

    arch = constants.RC_ARCH_TO_RHCOS_ARCH.get(arch, arch)
    rhcos_build_info = RHCOSBuildInfo(ocp_version)
    build_suffix = f"?stream=prod/streams/{rhcos_build_info.stream}&release={build_id}&arch={arch}"
    contents = f"{constants.RHCOS_BASE_URL}/contents.html{build_suffix}"
    stream = f"{constants.RHCOS_BASE_URL}/{build_suffix}"
    return contents, stream
