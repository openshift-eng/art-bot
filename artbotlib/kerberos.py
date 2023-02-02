import logging
import os

from artbotlib import exectools

logger = logging.getLogger(__name__)


def do_kinit():
    """
    Function performs kinit with the already mounted keytab.
    This function is executed only in production
    :return: None
    """

    if "NEEDS_KINIT" in os.environ:  # check to see if the code is in production environment
        logger.info('Running kinit')
        cmd = f'kinit -kt /tmp/keytab/keytab ocp-build/buildvm.openshift.eng.bos.redhat.com@IPA.REDHAT.COM'
        rc, stdout, stderr = exectools.cmd_gather(cmd)
        if rc:
            logger.error('Kerberos error: %s', stderr)

    else:
        logger.info('This is not a production environment, kinit is not required')
