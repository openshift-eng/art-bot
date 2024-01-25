import logging
import re

import artbotlib.exectools
from . import util

logger = logging.getLogger(__name__)


@util.refresh_krb_auth
def image_list(so, advisory_id):
    logger.info('Getting image list for advisory %s', advisory_id)
    cmd = f'elliott advisory-images -a {advisory_id}'

    rc, stdout, stderr = artbotlib.exectools.cmd_assert(so, cmd)
    if rc:
        util.please_notify_art_team_of_error(so, stderr)
    else:
        logger.error('Command %s failed with status code %s: %s', cmd, rc, stderr)
        so.snippet(payload=stdout, intro=f"Here's the image list for advisory {advisory_id}",
                   filename=f'{advisory_id}.images.txt')


def is_valid_nvr(nvr):
    nvr_regex = re.compile(r'^[a-zA-Z0-9_-]+-v?[0-9]+(\.[0-9]+)+-[0-9]+(\.[a-zA-Z0-9_.-]+)*$')
    return nvr_regex.match(nvr) is not None


def go_nvrs(so, nvr):
    if not is_valid_nvr(nvr):
        so.say("I assume you are trying to get the go version for NVR. Please ensure you are using the correct format for the NVR or write 'help' to see what I can do!")
        return

    try:
        rc, stdout, stderr = artbotlib.exectools.cmd_assert(so, f'elliott go -n {nvr}')
    except Exception as e:
        so.say(f"An unexpected error occurred: {e}")
        util.please_notify_art_team_of_error(so, str(e))
        return

    if rc:
        so.say("There was a problem with the command.")
        return

    if not stdout:
        so.say("Invalid advisory. Try again.")
    else:
        # Assuming 'advisory_id' is defined elsewhere or should be 'nvr'
        so.snippet(payload=stdout, intro=f"Go version for advisory {nvr}:", filename='go_advisory_output.txt')


@util.refresh_krb_auth
def go_advisory(so, advisory_id):
    rc, stdout, stderr = artbotlib.exectools.cmd_assert(so, f'elliott go -a {advisory_id}')
    if not stdout:
        so.say("Invalid advisory. Try again.")
    else:
        so.snippet(payload=stdout, intro=f"Go version for advisory {advisory_id}:", filename='go_advisory_output.txt')


@util.refresh_krb_auth
def go_config(so, ocp_version_string):
    ocp_versions = re.findall(r'(\d\.\d+)', ocp_version_string)
    if not ocp_versions:
        so.say(f"Could not find ocp versions in {ocp_version_string}")
        return
    ocp_versions = ",".join(ocp_versions)

    ignore_rhel = True
    if "with rhel" in ocp_version_string or "including rhel" in ocp_version_string:
        ignore_rhel = False

    cmd = f"elliott go:report --ocp-versions {ocp_versions}"
    if ignore_rhel:
        cmd = f"{cmd} --ignore-rhel"

    try:
        rc, stdout, stderr = artbotlib.exectools.cmd_assert(so, cmd)
    except Exception as e:
        so.say(f"An unexpected error occurred: {e}")
        util.please_notify_art_team_of_error(so, str(e))
        return

    if rc:
        so.say("There was a problem with the command.")
        return

    if not stdout:
        so.say("Invalid input")
    else:
        so.snippet(payload=stdout, intro="Go config report:", filename='go_config_output.txt')
