import artbotlib.exectools
from . import util


def translate_names(so, _, name, name_type2, major=None, minor=None):
    query_name = {
        "brew-image": "image_name",
        "brew-component": "component",
    }[name_type2]
    major_minor = f"{major}.{minor}" if major and minor else "4.5"

    rc, stdout, stderr = artbotlib.exectools.cmd_gather(f"doozer --disable-gssapi --group openshift-{major_minor} --images {name} images:print \'{{{query_name}}}\' --show-base --show-non-release --short")
    if rc:
        so.say(f"Sorry, there is no image dist-git {name} in version {major_minor}.")
    else:
        so.say(f"Image dist-git {name} has {name_type2} '{stdout.strip()}' in version {major_minor}.")
