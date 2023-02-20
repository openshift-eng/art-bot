import asyncio
import fnmatch
import json
import logging
import re
import urllib.request
from typing import cast, Dict
from urllib.parse import quote

import koji
import requests
import yaml

import artbotlib.exectools

from . import util
from .constants import RHCOS_BASE_URL

logger = logging.getLogger(__name__)


@util.cached
def brew_list_components(nvr):
    koji_api = util.koji_client_session()
    logger.info('Getting info for build %s', nvr)
    build = koji_api.getBuild(nvr, strict=True)

    components = set()
    for archive in koji_api.listArchives(build['id']):
        for rpm in koji_api.listRPMs(imageID=archive['id']):
            components.add('{nvr}.{arch}'.format(**rpm))

    logger.info('Found components in build %s:\n%s', nvr, '\n'.join(components))
    return components


def list_components_for_image(so, nvr):
    try:
        logger.info('Getting components for build %s', nvr)
        components = brew_list_components(nvr)
    except Exception as e:
        logger.error('Failed getting component list for build %s: %s', nvr, e)
        so.say(f"Sorry, I couldn't find image {nvr} RPMs in brew: {e}")
        return

    so.snippet(payload='\n'.join(sorted(components)),
               intro='The following rpms are used',
               filename='{}-rpms.txt'.format(nvr))


def list_specific_rpms_for_image(matchers, nvr) -> set:
    logger.info(f'Searching for {matchers} in {nvr}')
    matched = set()
    for rpma in brew_list_components(nvr):
        name, _, _ = rpma.rsplit("-", 2)
        if any(fnmatch.fnmatch(name, m) for m in matchers):
            matched.add(rpma)

    logger.info('Found these matching rpms in image %s:\n%s', nvr, '\n'.join(matched))
    return matched


def specific_rpms_for_image(so, rpms, nvr):
    matchers = [rpm.strip() for rpm in rpms.split(",")]
    try:
        matched = list_specific_rpms_for_image(matchers, nvr)
    except koji.GenericError as e:
        msg = [
            str(e),
            'Make sure a valid brew build name is provided'
        ]
        logger.error('Failed getting rpm list for image %s: %s', nvr, e)
        so.say('\n'.join(msg))
        return

    if not matched:
        logger.info('No rpms matching %s were found in build %s', matchers, nvr)
        so.say(f'Sorry, no rpms matching {matchers} were found in build {nvr}')

    else:
        logger.info('Found following rpms matching %s in build %s:\n%s', matchers, nvr, '\n'.join(sorted(matched)))
        so.snippet(payload='\n'.join(sorted(matched)),
                   intro=f'The following rpm(s) are used in {nvr}',
                   filename='{}-rpms.txt'.format(nvr))


async def get_tag_specs(so, tag_spec, data_type, sem) -> str:
    """
    Fetches tag information by running 'oc image info'
    and returns the appropriate field depending on the data type provided
    """
    async with sem:
        release_component_name = tag_spec['name']
        release_component_image = tag_spec['from']['name']
        rc, stdout, stderr = await artbotlib.exectools.cmd_gather_async(
            f'oc image info -o=json {release_component_image}')
        if rc:
            logger.error('Command failed with status code %s:\n%s', rc, stderr)
            util.please_notify_art_team_of_error(so, stderr)
            return ''

        logger.debug('Image info for %s:\n%s', release_component_image, stdout)
        release_component_image_info = json.loads(stdout)
        component_labels = release_component_image_info['config']['config']['Labels']
        component_name = component_labels.get('com.redhat.component', 'UNKNOWN')
        component_version = component_labels.get('version', 'v?')
        component_release = component_labels.get('release', '?')
        component_upstream_commit_url = component_labels.get('io.openshift.build.commit.url', '?')
        component_distgit_commit = component_labels.get('vcs-ref', '?')
        component_rhcc_url = component_labels.get('url', '?')

        result = f'{release_component_name}='
        if data_type.startswith('nvr'):
            result += f'{component_name}-{component_version}-{component_release}'
        elif data_type.startswith('distgit'):
            distgit_name = component_name.rstrip('-container')
            result += f'http://pkgs.devel.redhat.com/cgit/{distgit_name}/commit/?id={component_distgit_commit}'
        elif data_type.startswith('commit'):
            result += f'{component_upstream_commit_url}'
        elif data_type.startswith('catalog'):
            result += f'{component_rhcc_url}'
        elif data_type.startswith('image'):
            result += release_component_image

        logger.debug('Tag specs for %s: %s', data_type, result)
        return result


def list_component_data_for_release_tag(so, data_type, release_tag):
    data_type = data_type.lower()
    data_types = ('nvr', 'distgit', 'commit', 'catalog', 'image')
    if not data_type.startswith(data_types):
        logger.error('The type of information about each component needs to be one of %s', data_types)
        so.say(f"Sorry, the type of information you want about each component needs to be one of: {data_types}")
        return

    so.say('Let me look into that. It may take a minute...')

    if 'nightly-' in release_tag:
        repo_url = 'registry.svc.ci.openshift.org/ocp/release'
    else:
        repo_url = 'quay.io/openshift-release-dev/ocp-release'

    image_url = f'{repo_url}:{release_tag}-x86_64'

    logger.info('Getting image info for %s', image_url)
    rc, stdout, stderr = artbotlib.exectools.cmd_assert(so, f'oc adm release info -o=json --pullspecs {image_url}')
    if rc:
        logger.error('Command failed with status code %s:\n%s', rc, stderr)
        util.please_notify_art_team_of_error(so, stderr)
        return

    payload = f'Finding information for: {image_url}\n'

    release_info = json.loads(stdout)
    tag_specs = list(release_info['references']['spec']['tags'])

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    sem = asyncio.Semaphore(100)

    # Send semaphore along with the get_tag_specs function to make sure that the semaphore uses the same event loop
    results = loop.run_until_complete(
        asyncio.gather(
            *[get_tag_specs(so, tag_spec, data_type, sem) for tag_spec in sorted(tag_specs, key=lambda x: x['name'])]))
    payload += '\n'.join(results)

    so.snippet(payload=payload,
               intro=f'The release components map to {data_type} as follows:',
               filename='{}-{}.txt'.format(release_tag, data_type))


def latest_images_for_version(so, major_minor):
    key = f'latest_images_built_for_version-{major_minor}'
    image_nvrs = util.CACHE_TTL.get(key)
    if image_nvrs:
        logger.info('Using cached image nvrs: %s', image_nvrs)
        return image_nvrs

    so.say(f"Determining images for {major_minor} - this may take a few minutes...")

    try:
        logger.info('Determining images for %s', major_minor)
        rc, stdout, stderr = artbotlib.exectools.cmd_assert(
            so, f"doozer --disable-gssapi --group openshift-{major_minor} --assembly stream images:print "
            f"'{{component}}-{{version}}-{{release}}' --show-base --show-non-release --short"
        )

    except Exception as e:  # convert any exception into generic (cmd_assert already reports details to monitoring)
        logger.error('Failed retrieving latest images for %s: %s', major_minor, e)
        so.say(
            f"Failed to retrieve latest images for version '{major_minor}': doozer could not find version '{major_minor}'")
        return []

    image_nvrs = [nvr.strip() for nvr in stdout.strip().split('\n')]
    logger.info('Found image nvrs in %s:\n%s', major_minor, '\n'.join(image_nvrs))

    # if there is no build for an image, doozer still prints it out like "component--".
    # filter out those non-builds so we don't expect to find them later.
    util.CACHE_TTL[key] = image_nvrs = [nvr for nvr in image_nvrs if not nvr.endswith('-')]
    return image_nvrs


def list_components_for_major_minor(so, major, minor):
    major_minor = f'{major}.{minor}'

    image_nvrs = latest_images_for_version(so, major_minor)
    if not image_nvrs:  # error retrieving
        return

    all_components = set()
    for nvr in image_nvrs:
        all_components.update(brew_list_components(nvr))

    image_nvrs = '\n'.join(sorted(image_nvrs))

    logger.info('Found following nvrs for %s:\n%s', major_minor, '\n'.join(image_nvrs))
    logger.info('RPMs used in their construction:\n%s', '\n'.join(all_components))

    output = f'I found the following nvrs for {major_minor} images:\n{image_nvrs}\n'
    output += 'And here are the rpms used in their construction:\n'
    output += '\n'.join(sorted(all_components))
    so.snippet(
        payload=output,
        intro=f'For latest {major_minor} builds (cached for an hour):',
        filename=f'{major_minor}-rpms.txt'
    )


def list_uses_of_rpms(so, names, major, minor, search_type="rpm"):
    """
    List all of the uses for a list of RPMs or packages,
    including in images, rhcos, and (TODO) the installer.

    :so: SlackOuput object for reporting results.
    :names: comma-separated list of package or rpm names
    :major, minor: text numbes representing product minor version
    :search_type: "rpm" or "package" (packages include RPM(s) often with different names)
    """
    major_minor = f'{major}.{minor}'
    name_list = re.split(",+", names.strip(","))  # normalize
    if not name_list[0]:
        logger.warning('Invalid %s name %s', search_type, names)
        so.say(f"Invalid {search_type} name {names}.")
        return

    try:
        koji_api = util.koji_client_session()
    except Exception as ex:
        logger.error('Failed connecting to Brew')
        so.monitoring_say(f"Failed to connect to brew; cannot look up components: {ex}")
        so.say("Failed to connect to brew; cannot look up components.")
        return

    if search_type.lower() == "rpm":
        rpms_search = set(name_list)
    else:
        try:
            rpms_for_package = _find_rpms_in_packages(koji_api, name_list, major_minor)
            logger.info('Found these packages named %s:\n%s', name_list, '\n'.join(rpms_for_package))

        except Exception as ex:
            logger.warning('Failed to look packages in Brew for %s: %s', major_minor, ex)
            so.monitoring_say(f"Failed to look up packages in brew: {ex}")
            so.say(f"Failed looking up packages in brew. Do tags exist for {major_minor}?")
            return

        if not rpms_for_package:
            so.say(
                f"Could not find any package(s) named {name_list} in brew. Package name(s) need to be exact (case sensitive)")
            return

        if len(name_list) > len(rpms_for_package):
            missing = [name for name in name_list if name not in rpms_for_package]
            so.say(f"Could not find package(s) {missing} in brew.")
        rpms_search = set(rpm.lower() for rpms in rpms_for_package.values() for rpm in rpms)

    image_nvrs = latest_images_for_version(so, major_minor)
    if not image_nvrs:  # error retrieving
        return

    rpms_for_image = dict()
    rpms_seen = set()
    if int(major) > 3:
        _index_rpms_in_rhcos(_find_rhcos_build_rpms(so, major_minor), rpms_search, rpms_for_image, rpms_seen)
    _index_rpms_in_images(image_nvrs, rpms_search, rpms_for_image, rpms_seen)
    logger.info('Usages of %s in %s:\n%s', names, major_minor, '\n'.join(rpms_for_image))

    if not rpms_for_image:
        so.say(f"It looks like nothing in {major_minor} uses that.")
        return

    output = "\n".join(f"{image} uses {rpms_for_image[image]}" for image in sorted(rpms_for_image.keys()))
    if search_type.lower() == "package":
        rpms_seen_for_package = {}
        for pkg, rpms in rpms_for_package.items():
            for rpm in rpms:
                if rpm in rpms_seen:
                    rpms_seen_for_package.setdefault(pkg, set()).add(rpm)
        packages_contents = "\n".join(
            f"package {pkg} includes rpm(s): {rpms}" for pkg, rpms in rpms_seen_for_package.items())
        if packages_contents:
            output = f"{packages_contents}\n\n{output}"

    logger.info('Search output:\n%s', output)
    so.snippet(payload=output,
               intro=f"Here are the images that used {names} in their construction:\n",
               filename=f"{major_minor}-rpm-images.txt")


def _index_rpms_in_images(image_nvrs, rpms_search, rpms_for_image, rpms_seen):
    for image_nvr in image_nvrs:
        for rpm_nvra in brew_list_components(image_nvr):
            name = rpm_nvra.rsplit("-", 2)[0].lower()
            if name in rpms_search:
                rpms_seen.add(name)
                rpm_nvr, _ = rpm_nvra.rsplit(".", 1)
                rpms_for_image.setdefault(image_nvr, set()).add(rpm_nvr)


def _index_rpms_in_rhcos(rpm_nvrs, rpms_search, rpms_for_image, rpms_seen):
    for rpm_nvr in rpm_nvrs:
        name = rpm_nvr.rsplit("-", 2)[0].lower()
        if name in rpms_search:
            rpms_seen.add(name)
            rpms_for_image.setdefault("RHCOS", set()).add(rpm_nvr)


def _find_rpms_in_packages(koji_api, name_list, major_minor):
    """
    Given a list of package names, look up the RPMs that are built in them.
    Of course, this is an inexact science to do generically; contents can
    vary from build to build, and multiple packages could build the same RPM name.
    We will first look for the latest build in the tags for the given
    major_minor version. If not there, we will look in brew for the package
    name and choose the latest build.

    :koji_api: existing brew connection
    :name_list: list of package names to search for
    :major_minor: minor version of OCP to search for builds in
    Returns: a map of package_name: set(rpm_names)
    """

    rpms_for_package = {}
    tags = _tags_for_version(major_minor)
    for package in name_list:
        for tag in tags:
            logger.info('Getting latest builds for package %s with tag %s', package, tag)
            for build in koji_api.getLatestBuilds(tag=tag, package=package):
                rpm_list = set(rpm["name"] for rpm in koji_api.listBuildRPMs(build["build_id"]))
                rpms_for_package.setdefault(package, set()).update(rpm_list)

        if package not in rpms_for_package:
            # it wasn't in our tags; look for it by name
            logger.info('Getting info for package %s', package)
            pkg_info = koji_api.getPackage(package)

            if not pkg_info:
                logger.warning('No info found for package %s', package)
                continue
            logger.info('Found info for package %s:\n%s', package, pkg_info)

            logger.info('Listing builds for package %s', package)
            latest_builds = koji_api.listBuilds(packageID=pkg_info["id"], state=1, queryOpts=dict(limit=1))
            logger.info('Latest builds for package %s: %s', package, latest_builds)

            if not latest_builds:
                continue

            rpm_list = set(rpm["name"] for rpm in koji_api.listBuildRPMs(latest_builds[0]["build_id"]))
            rpm_set = set(rpm_list)
            logger.info('RPMs for package %s: %s', package, rpm_set)
            rpms_for_package[package] = rpm_set

    return rpms_for_package


def _find_rhcos_build_rpms(so, major_minor, arch="x86_64", build_id=None):
    # returns a set of RPMs used in the specified or most recent build for release major_minor
    build_id = build_id or _find_latest_rhcos_build_id(so, major_minor, arch)
    if not build_id:
        return set()

    try:
        meta_url = f"{_rhcos_build_url(major_minor, build_id, arch)}/commitmeta.json"
        logger.info('Fetching URL %s', meta_url)

        with urllib.request.urlopen(meta_url) as url:
            data = json.loads(url.read().decode())
        rpms = data["rpmostree.rpmdb.pkglist"]
        logger.info('Found rpms: %s', rpms)

        return set(f"{n}-{v}-{r}" for n, e, v, r, a in rpms)

    except Exception as ex:
        logger.error('Encountered error looking up latest RHCOS build RPMs in %s: %s', major_minor, ex)
        so.say("Encountered error looking up the latest RHCOS build RPMs.")
        so.say_monitoring(f"Encountered error looking up the latest RHCOS build RPMs: {ex}")
        return set()


def _find_latest_rhcos_build_id(so, major_minor, arch="x86_64"):
    # returns the build id string
    # (may want to return "schema-version" also if this ever gets more complex)
    try:
        builds_json_url = f'{_rhcos_release_url(major_minor, arch)}/builds.json'
        logger.info('Fetching URL %s', builds_json_url)

        with urllib.request.urlopen(builds_json_url) as url:
            data = json.loads(url.read().decode())
        build = data["builds"][0]
        logger.info('Found build: %s', build)

        return build if isinstance(build, str) else build["id"]

    except Exception as ex:
        logger.error('Encountered error looking up the latest RHCOS build in %s: %s', major_minor, ex)
        so.say("Encountered error looking up the latest RHCOS build.")
        so.monitoring_say(f"Encountered error looking up the latest RHCOS build: {ex}")
        return None


def _rhcos_build_url(major_minor, build_id, arch="x86_64"):
    # path of build contents varies depending on the build schema; currently splits at 4.3
    arch_path = "" if major_minor in ["4.1", "4.2"] else f"/{arch}"
    return f"{_rhcos_release_url(major_minor, arch)}/{build_id}{arch_path}"


def _rhcos_release_url(major_minor, arch="x86_64"):
    arch_suffix = "" if arch == "x86_64" else f"-{arch}"
    return f"{RHCOS_BASE_URL}/storage/releases/rhcos-{major_minor}{arch_suffix}"


def _get_raw_group_config(group):
    response = requests.get(f"https://raw.githubusercontent.com/openshift/ocp-build-data/{quote(group)}/group.yml")
    response.raise_for_status()
    raw_group_config = cast(dict, yaml.safe_load(response.text))
    return raw_group_config


def _get_et_config(group: str, replace_vars: Dict[str, str]):
    response = requests.get(f"https://raw.githubusercontent.com/openshift/ocp-build-data/{quote(group)}/erratatool.yml")
    response.raise_for_status()
    et_config = cast(dict, yaml.safe_load(response.text.format(**replace_vars)))
    return et_config


def _tags_for_version(major_minor):
    group = f"openshift-{major_minor}"
    raw_group_config = _get_raw_group_config(group)
    replace_vars = raw_group_config.get("vars", {})
    et_config = _get_et_config(group, replace_vars=replace_vars)
    tag_pv_mapping = et_config.get("brew_tag_product_version_mapping", {})
    return list(tag_pv_mapping.keys())


def list_images_in_major_minor(so, major, minor):
    major_minor = f'{major}.{minor}'
    logger.info('Fetching image list for %s', major_minor)
    rc, stdout, stderr = artbotlib.exectools.cmd_assert(
        so, f'doozer --disable-gssapi --group openshift-{major_minor} --assembly stream images:print '
            f'\'{{image_name_short}}\' --show-base --show-non-release --short'
    )

    if rc:
        logger.error('Failed running doozer images:print for %s: %s', major_minor, stderr)
        util.please_notify_art_team_of_error(so, stderr)

    else:
        logger.info('Found images in %s:\n%s', major_minor, stdout)
        so.snippet(payload=stdout, intro=f'Here are the images being built for openshift-{major_minor}',
                   filename=f'openshift-{major_minor}.images.txt')
