import json
import re

from . import util

def buildinfo_for_release(so, name, release_img):

    img_name = "machine-os-content" if name == "rhcos" else name  # rhcos shortcut...

    if ".ci." in re.sub(".*:", "", release_img):
        so.say("Sorry, no ART build info for a CI image.")
        return

    if ":" in release_img:
        # assume it's a pullspec already; make sure it's a known domain
        if not re.match(r'(quay.io|registry.svc.ci.openshift.org)/', release_img):
            so.say("Sorry, I can only look up pullspecs for quay.io or registry.svc.ci.")
            return
    elif "nightly" in release_img:
        suffix = "-s390x" if "s390x" in release_img else "-ppc64le" if "ppc64le" in release_img else ""
        release_img = f"registry.svc.ci.openshift.org/ocp{suffix}/release{suffix}:{release_img}"
    else:
        # assume public release name
        release_img = f"quay.io/openshift-release-dev/ocp-release:{release_img}"
        if not re.search(r'-(s390x|ppc64le|x86_64)$', release_img):
            # assume x86_64 if not specified; TODO: handle older images released without -x86_64 in pullspec
            release_img = f"{release_img}-x86_64"

    rc, stdout, stderr = util.cmd_gather(f"oc adm release info {release_img} --image-for {img_name}")
    if rc:
        so.say(f"Sorry, I wasn't able to query the release image pullspec {release_img}.")
        util.please_notify_art_team_of_error(so, stderr)
        return

    pullspec = stdout.strip()
    rc, stdout, stderr = util.cmd_gather(f"oc image info {pullspec} -o json")
    if rc:
        so.say(f"Sorry, I wasn't able to query the component image pullspec {pullspec}.")
        util.please_notify_art_team_of_error(so, stderr)
        return

    try:
        data = json.loads(stdout)
    except Exception as exc:
        so.say(f"Sorry, I wasn't able to decode the JSON info for pullspec {pullspec}.")
        util.please_notify_art_team_of_error(so, str(exc))
        return
    
    if img_name == "machine-os-content":
        # always a special case... not a brew build
        try:
            rhcos_build = data["config"]["config"]["Labels"]["version"]
        except Exception as exc:
            so.say(f"Sorry, I expected a 'version' label for pullspec {pullspec} but didn't see one. Weird huh?")
            return
        
        so.say(f"image {pullspec} came from RHCOS build {rhcos_build}")
        return

    try:
        labels = data["config"]["config"]["Labels"]
        name = labels["com.redhat.component"]
        version = labels["version"]
        release = labels["release"]
    except Exception as exc:
        so.say(f"Sorry, one of the component, version, or release labels is missing for pullspec {pullspec}. Weird huh?")
        return

    nvr = f"{name}-{version}-{release}"
    so.say(f"{img_name} image {pullspec} came from brew build {nvr}")
    return
