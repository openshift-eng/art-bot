import fnmatch
import json
import koji

from . import util

# TODO: use a real cache with expiry and stuff
CACHE = {}


def brew_list_components(nvr):
    if nvr in CACHE.setdefault("nvras_for_image", {}):
        return CACHE["nvras_for_image"][nvr]

    koji_api = koji.ClientSession('https://brewhub.engineering.redhat.com/brewhub', opts={'serverca': '/etc/pki/brew/legacy.crt'})
    build = koji_api.getBuild(nvr, strict=True)

    components = set()
    for archive in koji_api.listArchives(build['id']):
        for rpm in koji_api.listRPMs(imageID=archive['id']):
            components.add('{nvr}.{arch}'.format(**rpm))

    CACHE["nvras_for_image"][nvr] = components
    return components


def list_components_for_image(so, nvr):
    so.snippet(payload='\n'.join(sorted(brew_list_components(nvr))),
               intro='The following rpms are used',
               filename='{}-rpms.txt'.format(nvr))


def specific_rpms_for_image(so, rpms, nvr):
    matchers = [rpm.strip() for rpm in rpms.split(",")]
    matched = set()
    for rpma in brew_list_components(nvr):
        name, _, _ = rpma.rsplit("-", 2)
        if any(fnmatch.fnmatch(name, m) for m in matchers):
            matched.add(rpma)

    if not matched:
        so.say(f'Sorry, no rpms matching {matchers} were found in build {nvr}')
    else:
        so.snippet(payload='\n'.join(sorted(matched)),
               intro=f'The following rpm(s) are used in {nvr}',
               filename='{}-rpms.txt'.format(nvr))


def list_component_data_for_release_tag(so, data_type, release_tag):
    so.say('Let me look into that. It may take a minute...')

    data_type = data_type.lower()
    data_types = ('nvr', 'distgit', 'commit', 'catalog', 'image')

    if not data_type.startswith(data_types):
        so.say(f"Sorry, the type of information you want about each component needs to be one of: {data_types}")
        return

    if 'nightly-' in release_tag:
        repo_url = 'registry.svc.ci.openshift.org/ocp/release'
    else:
        repo_url = 'quay.io/openshift-release-dev/ocp-release'

    image_url = f'{repo_url}:{release_tag}'

    print(f'Trying: {image_url}')
    rc, stdout, stderr = util.cmd_assert(so, f'oc adm release info -o=json --pullspecs {image_url}')
    if rc:
        util.please_notify_art_team_of_error(so, stderr)
        return

    payload = f'Finding information for: {image_url}\n'

    release_info = json.loads(stdout)
    tag_specs = list(release_info['references']['spec']['tags'])
    for tag_spec in sorted(tag_specs, key=lambda x: x['name']):
        release_component_name = tag_spec['name']
        release_component_image = tag_spec['from']['name']
        rc, stdout, stderr = util.cmd_assert(so, f'oc image info -o=json {release_component_image}')
        if rc:
            util.please_notify_art_team_of_error(so, stderr)
            return
        release_component_image_info = json.loads(stdout)
        component_labels = release_component_image_info.get('config', {}).get('container_config', {}).get('Labels', {})
        component_name = component_labels.get('com.redhat.component', 'UNKNOWN')
        component_version = component_labels.get('version', 'v?')
        component_release = component_labels.get('release', '?')
        component_upstream_commit_url = component_labels.get('io.openshift.build.commit.url', '?')
        component_distgit_commit = component_labels.get('vcs-ref', '?')
        component_rhcc_url = component_labels.get('url', '?')

        payload += f'{release_component_name}='
        if data_type.startswith('nvr'):
            payload += f'{component_name}-{component_version}-{component_release}'
        elif data_type.startswith('distgit'):
            distgit_name = component_name.rstrip('-container')
            payload += f'http://pkgs.devel.redhat.com/cgit/{distgit_name}/commit/?id={component_distgit_commit}'
        elif data_type.startswith('commit'):
            payload += f'{component_upstream_commit_url}'
        elif data_type.startswith('catalog'):
            payload += f'{component_rhcc_url}'
        elif data_type.startswith('image'):
            payload += release_component_image
        else:
            so.say(f"Sorry, I don't know how to extract information about {data_type}")
            return

        payload += '\n'

        if '?' in payload:
            print(f'BAD INFO?')
            pprint.pprint(release_component_image_info)

    so.snippet(payload=payload,
               intro=f'The release components map to {data_type} as follows:',
               filename='{}-{}.txt'.format(release_tag, data_type))

def latest_images_for_version(so, major_minor):
    if major_minor not in CACHE.setdefault('latest_images_built_for_version', {}):
        so.say(f'Determining images for {major_minor} - this may take awhile (~2 minutes)...')

        rc, stdout, stderr = util.cmd_assert(so, f'doozer --group openshift-{major_minor} images:print \'{{component}}-{{version}}-{{release}}\' --show-base --show-non-release --short')
        if rc:
            util.please_notify_art_team_of_error(so, stderr)
            return None

        image_nvrs = [nvr.strip() for nvr in stdout.strip().split('\n')]
        CACHE['latest_images_built_for_version'][major_minor] = image_nvrs

    return CACHE['latest_images_built_for_version'][major_minor]


def list_components_for_major_minor(so, major, minor):
    major_minor = f'{major}.{minor}'

    image_nvrs = latest_images_for_version(so, major_minor)
    if not image_nvrs:  # error retrieving
        return

    all_components = set()
    for nvr in image_nvrs:
        all_components.update(brew_list_components(nvr))

    image_nvrs = '\n'.join(sorted(image_nvrs))
    output = f'I found the following nvrs for {major_minor} images:\n{image_nvrs}\n'
    output += 'And here are the rpms used in their construction:\n'
    output += '\n'.join(sorted(all_components))
    so.snippet(
        payload=output,
        intro='Here ya go...',
        filename=f'{major_minor}-rpms.txt'
    )


def list_images_using_rpm(so, name, major, minor):
    major_minor = f'{major}.{minor}'

    image_nvrs = latest_images_for_version(so, major_minor)
    if not image_nvrs:  # error retrieving
        return

    rpm_for_image = dict()
    for image_nvr in image_nvrs:
        first = True
        for rpm_nvra in brew_list_components(image_nvr):
            n, _, _ = rpm_nvra.rsplit('-', 2)
            if n == name:
                rpm_for_image[image_nvr] = rpm_nvra

    if not rpm_for_image:
        so.say(f'It looks like no images in {major_minor} use RPM {name}.')
        return

    output = '\n'.join(f'{image} uses {rpm_for_image[image]}' for image in sorted(rpm_for_image.keys()))
    so.snippet(payload=output,
               intro=f'Here are the images that used {name} in their construction:\n',
               filename=f'{major_minor}-rpm-{name}-images.txt')


def list_images_in_major_minor(so, major, minor):
    major_minor = f'{major}.{minor}'
    rc, stdout, stderr = util.cmd_assert(so, f'doozer --group openshift-{major_minor} images:print \'{{image_name_short}}\' --show-base --show-non-release --short')
    if rc:
        util.please_notify_art_team_of_error(so, stderr)
    else:
        so.snippet(payload=stdout, intro=f'Here are the images being built for openshift-{major_minor}',
                   filename=f'openshift-{major_minor}.images.txt')


