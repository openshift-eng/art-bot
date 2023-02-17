import artbotlib.exectools
import logging

logger = logging.getLogger(__name__)


def translate_names(so, _, name, name_type2, major=None, minor=None):
    query_name = {
        "brew-image": "image_name",
        "brew-component": "component",
    }[name_type2]
    logger.debug(f"Query name: {query_name}")

    major_minor = f"{major}.{minor}" if major and minor else "4.5"
    logger.debug(f"major minor: {major_minor}")

    cmd = f"doozer --disable-gssapi --group openshift-{major_minor} --assembly stream --images {name} images:print \'{{{query_name}}}\'" \
          f" --show-base --show-non-release --short"

    rc, stdout, stderr = artbotlib.exectools.cmd_gather(cmd)
    if rc:
        logger.warning(rc)
        so.say(f"Sorry, there is no image dist-git {name} in version {major_minor}.")
    else:
        so.say(f"Image dist-git {name} has {name_type2} '{stdout.strip()}' in version {major_minor}.")
