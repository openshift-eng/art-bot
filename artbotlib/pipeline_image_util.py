import logging

import requests
from typing import Union
import yaml

import artbotlib.exectools
from artbotlib import exceptions

logger = logging.getLogger(__name__)


def github_distgit_mappings(version: str) -> dict:
    """
    Function to get the GitHub to Distgit mappings present in a particular OCP version.

    :version: OCP version
    """

    rc, out, err = artbotlib.exectools.cmd_gather(
        f"doozer --disable-gssapi -g openshift-{version} --assembly stream images:print --short '{{upstream_public}}: {{name}}'")

    if rc != 0:
        if "koji.GSSAPIAuthError" in err:
            msg = "Kerberos authentication failed for doozer"
            logger.error(msg)
            raise exceptions.KerberosAuthenticationError(msg)

        logger.error('Doozer returned status %s: %s', rc, err)
        raise RuntimeError(f'doozer returned status {rc}')

    mappings = {}

    for line in out.splitlines():
        github, distgit = line.split(": ")
        reponame = github.split("/")[-1]
        if github not in mappings:
            mappings[reponame] = [distgit]
        else:
            mappings[reponame].append(distgit)

    if not mappings:
        logger.warning('No github-distgit mapping found in %s', version)
        raise exceptions.NullDataReturned("No data from doozer command for github-distgit mapping")
    return mappings


def get_image_stream_tag(distgit_name: str, version: str) -> Union[str, None]:
    """
    Function to get the image stream tag if the image is a payload image.
    The for_payload flag would be set to True in the yml file

    :distgit_name: Name of the distgit repo
    :version: OCP version
    """

    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    logger.info('Fetching url %s', url)
    response = requests.get(url)

    yml_file = yaml.safe_load(response.content)

    # Check if the image is in the payload
    if yml_file.get('for_payload', False):
        tag = yml_file['name'].split("/")[1]
        result = tag[4:] if tag.startswith("ose-") else tag  # remove 'ose-' if present
        logger.info('Found imagestream tag %s for component %s', result, distgit_name)
        return result

    # The image is not in the payload
    logger.info('Component %s does not belong to the OCP payload', distgit_name)
    return None
