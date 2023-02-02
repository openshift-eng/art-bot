import logging

import artbotlib.exectools
from . import util

logger = logging.getLogger(__name__)


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
