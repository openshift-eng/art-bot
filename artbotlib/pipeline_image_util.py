import requests
import yaml
import artbotlib.exectools
from artbotlib import exceptions
from typing import Union


def github_distgit_mappings(version: str) -> dict:
    """
    Function to get the GitHub to Distgit mappings present in a particular OCP version.

    :version: OCP version
    """

    rc, out, err = artbotlib.exectools.cmd_gather(
        f"doozer --disable-gssapi -g openshift-{version} images:print --short '{{upstream_public}}: {{name}}'")

    if rc != 0:
        if "koji.GSSAPIAuthError" in err:
            raise exceptions.KerberosAuthenticationError("Kerberos authentication failed for doozer")
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
    response = requests.get(url)

    yml_file = yaml.safe_load(response.content)
    if yml_file.get('for_payload', False):  # Check if the image is in the payload
        tag = yml_file['name'].split("/")[1]
        return tag[4:] if tag.startswith("ose-") else tag  # remove 'ose-' if present
    return None
