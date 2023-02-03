import logging

import requests
import yaml
from requests_kerberos import HTTPKerberosAuth, OPTIONAL

import artbotlib.exectools
from . import util, constants
from artbotlib import exceptions
from typing import Union

logger = logging.getLogger(__name__)


# Functions for pipeline from GitHub
def github_repo_is_available(repo_name: str) -> bool:
    """
    Function to check whether the given GitHub repo name is valid

    :repo_name: The name of the GitHub repo.
    """

    url = f"https://github.com/openshift/{repo_name}"
    logger.info('Checking if %s is reachable...', url)
    response = requests.head(url)

    if response.status_code == 200:
        return True

    logger.warning('Url %s does not exist', url)
    return False


def github_to_distgit(github_name: str, version: str) -> list:
    """
    Driver function to get the GitHub to distgit mappings from the GitHub name and OCP version.

    :github_name: The name of the GitHub repo
    :version: OCP version
    """

    logger.info('Retrieving distgit associated with %s', github_name)
    data = github_distgit_mappings(version)

    try:
        distgit = data[github_name]
        logger.info('Found distgit %s', distgit)
        return distgit

    except KeyError:
        logger.warning('No distgit associated with github repo %s found', github_name)
        raise exceptions.DistgitFromGithubNotFound(
            f"Couldn't find Distgit repo from GitHub `{github_name}` and version `{version}`")


# Distgit
def distgit_is_available(distgit_repo_name: str) -> bool:
    """
    Function to check whether the given distgit repo name is valid

    :distgit_repo_name: The name of the distgit repo.
    """

    url = f"{constants.CGIT_URL}/containers/{distgit_repo_name}"
    logger.info('Checking if %s is reachable...', url)
    response = requests.head(url)

    if response.status_code == 200:
        return True

    logger.warning('Url %s does not exist', url)
    return False


def distgit_to_github(distgit_name: str, version: str) -> str:
    """
    Driver function to get the distgit to GitHub mappings from the GitHub name and OCP version.

    :distgit_name: The name of the distgit repo
    :version: OCP version
    """

    logger.info('Retrieving github repo associated with distgit %s', distgit_name)
    data = distgit_github_mappings(version)

    try:
        github = data[distgit_name].split('/')[-1]
        logger.info('Found github repo %s', github)
        return github

    except KeyError:
        logger.warning('No github associated with distgit repo %s found', distgit_name)
        raise exceptions.GithubFromDistgitNotFound(
            f"Couldn't find GitHub repo from distgit `{distgit_name}` and version `{version}`")


def distgit_to_brew(distgit_name: str, version: str) -> str:
    """
    Get the brew name from the distgit name.

    :distgit_name: The name of the distgit repo
    :version: The OCP version
    """

    logger.info('Retrieving brew package associated with distgit %s', distgit_name)
    brew_name = f"{distgit_name}-container"  # Default brew name

    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    logger.info('Fetching data from %s', url)
    response = requests.get(url)

    if response.status_code != 200:
        logger.warning('No distgit definition found at %s', url)
        raise exceptions.DistgitNotFound(
            f"image dist-git {distgit_name} definition was not found at {url}")  # If yml file does not exist

    yml_file = yaml.safe_load(response.content)

    try:
        # override default if component name specified in yml file
        brew_name = yml_file['distgit']['component']
        return brew_name

    except KeyError:
        # fallback to default
        logger.warning('Falling back to default brew name %s', brew_name)

    finally:
        return brew_name


def distgit_to_delivery(distgit_repo_name: str, version: str, variant: str) -> str:
    """
    Driver function for distgit -> delivery pipeline.

    :distgit_repo_name: The name of the distgit repo
    :version: OCP version
    :variant: RHOSE variant
    """

    logger.info('Retrieving delivery repo associated with distgit %s', distgit_repo_name)
    payload = ""

    # Tag
    tag = get_image_stream_tag(distgit_repo_name, version)
    if tag:
        logger.info('Found tag %s', tag)
        payload += f"Payload tag: *{tag}* \n"

    # Distgit -> Brew
    brew_package_name = distgit_to_brew(distgit_repo_name, version)
    logger.info('Found Brew package: %s', brew_package_name)
    brew_id = get_brew_id(brew_package_name)
    payload += f"Production brew builds: <{constants.BREW_URL}/packageinfo?packageID={brew_id}|*{brew_package_name}*>\n"

    # Bundle Builds
    if require_bundle_build(distgit_repo_name, version):
        logger.info('Component %s requries bundle builds', distgit_repo_name)
        bundle_component = get_bundle_override(distgit_repo_name, version)

        if not bundle_component:
            bundle_component = f"{'-'.join(brew_package_name.split('-')[:-1])}-metadata-component"
        bundle_distgit = f"{distgit_repo_name}-bundle"

        logger.info('Found Brew bundle component: %s', bundle_component)
        logger.info('Found distgit bundle component: %s', bundle_distgit)

        payload += f"Bundle Component: *{bundle_component}*\n"
        payload += f"Bundle Distgit: *{bundle_distgit}*\n"

    # Brew -> Delivery
    payload += brew_to_delivery(brew_package_name, variant)
    return payload


# Brew stuff
def brew_is_available(brew_name: str) -> bool:
    """
    Function to check whether the given brew repo is valid

    :brew_name: The name of the brew repo.
    """

    try:
        get_brew_id(brew_name)
        logger.info('Brew package %s is valid', brew_name)
        return True

    except exceptions.BrewIdNotFound:
        logger.warning('Brew package %s was not found', brew_name)
        return False


def brew_to_github(brew_name: str, version: str) -> str:
    """
    Driver function for Brew -> GitHub pipeline

    :brew_name: Name of the brew package
    :version: OCP version
    """

    logger.info('Retrieving github repo from brew package %s', brew_name)
    payload = ""

    # Distgit
    distgit_repo_name = brew_to_distgit(brew_name, version)
    logger.info('Found distgit %s', distgit_repo_name)

    # Distgit -> GitHub
    github_repo = distgit_to_github(distgit_repo_name, version)
    logger.info('Found github %s', github_repo)

    payload += f"Upstream GitHub repository: <https://github.com/openshift/{github_repo}|*openshift/{github_repo}*>\n"
    payload += f"Private GitHub repository: <https://github.com/openshift-priv/{github_repo}|*openshift-priv/{github_repo}*>\n"

    # To keep the presented order same
    payload += f"Production dist-git repo: <{constants.CGIT_URL}/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

    # Bundle Builds
    if require_bundle_build(distgit_repo_name, version):
        logger.info('Component %s requries bundle builds', distgit_repo_name)
        bundle_component = get_bundle_override(distgit_repo_name, version)

        if not bundle_component:
            bundle_component = f"{'-'.join(brew_name.split('-')[:-1])}-metadata-component"
        bundle_distgit = f"{distgit_repo_name}-bundle"

        logger.info('Found Brew bundle component: %s', bundle_component)
        logger.info('Found distgit bundle component: %s', bundle_distgit)

        payload += f"Bundle Component: *{bundle_component}*\n"
        payload += f"Bundle Distgit: *{bundle_distgit}*\n"

    # Tag
    tag = get_image_stream_tag(distgit_repo_name, version)
    if tag:
        logger.info('Found tag: %s', tag)
        payload += f"Payload tag: *{tag}* \n"

    return payload


def get_brew_id(brew_name: str) -> int:
    """
    Get the brew id for the given brew name.

    :so: SlackOutput object for reporting results.
    :brew_name: The name of the brew package
    """

    logger.info('Getting brew id for package %s', )

    try:
        koji_api = util.koji_client_session()
    except Exception:
        msg = 'Failed to connect to Brew.'
        logger.error(msg)
        raise exceptions.KojiClientError(msg)

    try:
        brew_id = koji_api.getPackageID(brew_name, strict=True)
        logger.info('Found brew id %s', brew_id)

    except Exception:
        msg = f'Brew ID not found for brew package `{brew_name}`. Check API call.'
        logger.warning(msg)
        raise exceptions.BrewIdNotFound(msg)

    return brew_id


def brew_to_cdn(brew_name: str, variant_name: str) -> list:
    """
    Function to return all the Brew to CDN mappings (since more than one could be present)

    :brew_name: Brew package name
    :variant_name: The name of the product variant eg: 8Base-RHOSE-4.10
    """

    logger.info('Retrieving cdn from brew %s', brew_name)

    url = f"{constants.ERRATA_TOOL_URL}/api/v1/cdn_repo_package_tags?filter[package_name]={brew_name}"
    response = request_with_kerberos(url)
    if not response.status_code:
        msg = f'Failed fetching data from {url}'
        logger.error(msg)
        raise exceptions.ArtBotExceptions(msg)

    repos = []
    for item in response.json()['data']:
        repos.append(item['relationships']['cdn_repo']['name'])

    repos = list(set(repos))  # Getting only the unique repo names
    logger.info('Found repos %s', repos)

    # Cross-check to see if the repo is mapped to the given variant
    results = []
    for repo in repos:
        response = get_cdn_repo_details(repo)
        for variant in response['data']['relationships']['variants']:
            if variant['name'] == variant_name:
                results.append(repo)
                break

    if not results:
        msg = f'CDN was not found for brew `{brew_name}` and variant `{variant_name}`'
        logger.error(msg)
        raise exceptions.CdnFromBrewNotFound(msg)

    logger.info('Found CDN mappings: %s', results)
    return results


def brew_to_delivery(brew_package_name: str, variant: str) -> str:
    """
    Driver function for Brew -> Delivery pipeline

    :brew_package_name: Brew package name
    :variant: The 8Base-RHOSE variant
    """

    logger.info('Retrieving delivery repo from brew %s', brew_package_name)

    payload = ""
    cdn_repo_names = brew_to_cdn(brew_package_name, variant)
    if len(cdn_repo_names) > 1:
        payload += "\n *Found more than one Brew to CDN mappings:*\n\n"

    for cdn_repo_name in cdn_repo_names:
        logger.info('Found CDN %s', cdn_repo_name)

        # CDN
        payload += get_cdn_payload(cdn_repo_name, variant)

        # CDN -> Delivery
        payload += cdn_to_delivery_payload(cdn_repo_name)

    else:
        logger.warning('No CDN mappings found for brew %s', brew_package_name)

    return payload


@util.cached
def doozer_brew_distgit(version: str) -> list:
    output = artbotlib.exectools.cmd_gather(f"doozer --disable-gssapi -g openshift-{version} "
                                            f"images:print --short '{{component}}: {{name}}'")

    if "koji.GSSAPIAuthError" in output[2]:
        msg = 'Kerberos authentication failed for doozer'
        logger.error(msg)
        raise exceptions.KerberosAuthenticationError(msg)

    result = []
    for line in output[1].splitlines():
        result.append(line.split(": "))

    return result


def brew_to_distgit(brew_name: str, version: str) -> str:
    """
    Function to get the distgit name from the brew package name

    :brew_name: The name of the brew package
    :version: OCP version. Eg: 4.10
    """

    output = doozer_brew_distgit(version)

    dict_data = {}
    for line in output:
        if line:
            dict_data[line[0]] = line[1]

    if not dict_data:
        msg = 'No data from doozer command for brew-distgit mapping'
        logger.error(msg)
        raise exceptions.NullDataReturned(msg)

    try:
        distgit = dict_data[brew_name]
        logger.info('Found distgit %s', distgit)
        return distgit

    except Exception:
        msg = 'Could not find brew-distgit mapping from ocp-build-data for brew %s', brew_name
        logger.error(msg)
        raise exceptions.BrewToDistgitMappingNotFound(msg)


# CDN stuff
def cdn_is_available(cdn_name: str) -> bool:
    """
    Function to check if the given CDN repo name is available

    :cdn_name: Name of the CDN repo
    """

    try:
        get_cdn_repo_details(cdn_name)
        logger.info('CDN %s available', cdn_name)
        return True

    except exceptions.CdnNotFound:
        logger.error('CDN %s not found', cdn_name)
        return False


def get_cdn_repo_details(cdn_name: str) -> dict:
    """
    Function to get the details regarding the given CDN repo.

    :cdn_name: The name of the CDN repo
    """

    logger.info('Retrieving details for cdn %s', cdn_name)
    url = f"{constants.ERRATA_TOOL_URL}/api/v1/cdn_repos/{cdn_name}"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        msg = f'CDN was not found for CDN name {cdn_name}'
        logger.error(msg)
        raise exceptions.CdnNotFound(msg)

    return response.json()


def cdn_to_delivery(cdn_name: str) -> str:
    """
    Function to get the delivery repo name from the CDN repo name.

    :cdn_name: THe CDN repo name
    """

    logger.info('Retrieving delivery repo name from CDN %s', cdn_name)
    response = get_cdn_repo_details(cdn_name)

    try:
        delivery = response['data']['attributes']['external_name']
        logger.info('Found delivery repo %s', delivery)
        return delivery

    except Exception:
        msg = f'Delivery Repo not found for CDN `{cdn_name}`'
        logger.error(msg)
        raise exceptions.DeliveryRepoNotFound(msg)


def get_cdn_repo_id(cdn_name: str) -> int:
    """
    Function to get the CDN repo ID. Used to construct the CDN repo URL to direct to its page in Errata.

    :cdn_name: The name of the CDN repo
    """

    logger.info('Retrieving CDN id for %s', cdn_name)
    response = get_cdn_repo_details(cdn_name)

    try:
        cdn_id = response['data']['id']
        logger.info('Found cdn id %s', cdn_id)
        return cdn_id

    except Exception:
        msg = f'CDN ID not found for CDN `{cdn_name}`'
        logger.error(msg)
        raise exceptions.CdnIdNotFound(msg)


def cdn_to_brew(cdn_name: str) -> str:
    """
    Function to get the brew name from the given CDN name

    :cdn_name: The CDN repo name
    """

    logger.info('Retrieving brew name for CDN %s', cdn_name)
    response = get_cdn_repo_details(cdn_name)

    brew_packages = response['data']['relationships']['packages']
    if len(brew_packages) > 1:
        logger.error('Multiple Brew to CDN mappings found for %s', cdn_name)
        raise exceptions.MultipleCdnToBrewMappings("Multiple Brew to CDN mappings found. Contact ART.")

    try:
        brew_name = brew_packages[0]['name']
        logger.info('Found brew name %s', brew_name)
        return brew_name

    except KeyError:
        logger.error('No brew package found for cdn %s', cdn_name)
        raise exceptions.BrewNotFoundFromCdnApi("Brew package not mapped to CDN in Errata. Contact ART.")


def get_variant_id(cdn_name: str, variant_name: str) -> int:
    """
    Function to get the id of the product variant. Used to get the product ID.

    :cdn_name: The name of the CDN repo
    :variant_name: The name of the product variant
    """

    logger.info('Retrieving product variant id for cdn %s', cdn_name)
    response = get_cdn_repo_details(cdn_name)

    try:
        for data in response['data']['relationships']['variants']:
            if data['name'] == variant_name:
                prod_id = data['id']
                logger.info('Found id %s', prod_id)
                return prod_id

    except Exception:
        msg = f'Variant ID not found for CDN `{cdn_name}` and variant `{variant_name}`'
        logger.error(msg)
        raise exceptions.VariantIdNotFound(msg)


def get_product_id(variant_id: int) -> int:
    """
    Function to get the product id. Used to construct the CDN repo URL to direct to its page in Errata.

    :variant_id: Product variant ID
    """

    logger.info('Retrieving product id from variant %s', variant_id)
    url = f"{constants.ERRATA_TOOL_URL}/api/v1/variants/{variant_id}"
    response = request_with_kerberos(url)

    try:
        product_id = response.json()['data']['attributes']['relationships']['product_version']['id']
        logger.info('Found product id %s', product_id)
        return product_id

    except Exception:
        msg = f'Product ID not found for variant `{variant_id}`'
        logger.error(msg)
        raise exceptions.ProductIdNotFound(msg)


def cdn_to_github(cdn_name: str, version: str) -> str:
    """
    Driver function for the CDN -> GitHub pipeline

    :cdn_name: The name of the CDN repo
    :version: The OCP version
    """

    logger.info('Retrieving github from cdn %s', cdn_name)
    payload = ""

    # Brew
    brew_name = cdn_to_brew(cdn_name)
    logger.info('Found brew %s', brew_name)
    brew_id = get_brew_id(brew_name)
    payload += f"Production brew builds: <{constants.BREW_URL}/packageinfo?packageID={brew_id}|*{brew_name}*>\n"

    # Brew -> GitHub
    payload += brew_to_github(brew_name, version)
    # Use after brew to distgit mapping fixed
    return payload


def get_cdn_payload(cdn_repo_name: str, variant: str) -> str:
    """
    Function to get the CDN payload for slack (since it's needed in multiple places.

    :cdn_repo_name: The name of the CDN repo
    :variant: The 8Base-RHOSE variant
    """

    logger.info('Retrieving cdn payload for cdn %s', cdn_repo_name)
    cdn_repo_id = get_cdn_repo_id(cdn_repo_name)
    variant_id = get_variant_id(cdn_repo_name, variant)
    product_id = get_product_id(variant_id)
    logger.info('Found repo id=%s, variant id=%s, product id=%s', cdn_repo_id, variant_id, product_id)

    return f"CDN repo: <{constants.ERRATA_TOOL_URL}/product_versions/{product_id}/cdn_repos/{cdn_repo_id}|*{cdn_repo_name}*>\n"


def cdn_to_delivery_payload(cdn_repo_name: str):
    """
    Function to get the CDN payload for slack (since it's needed in multiple places.

    :cdn_repo_name: The name of the CDN repo
    """

    logger.info('Retrieving payload for cdn %s', cdn_repo_name)
    delivery_repo_name = cdn_to_delivery(cdn_repo_name)
    delivery_repo_id = get_delivery_repo_id(delivery_repo_name)
    logger.info('Found repo name=%s, repo id=%s', delivery_repo_name, delivery_repo_id)
    return f"Delivery (Comet) repo: <{constants.COMET_URL}/{delivery_repo_id}|*{delivery_repo_name}*>\n\n"


# Delivery stuff
def delivery_repo_is_available(name: str) -> bool:
    """
    Function to check if the given delivery repo exists

    :name: Name of the delivery repo
    """

    logger.info('Checking if delivery repo %s exists', name)
    try:
        get_delivery_repo_id(name)
        logger.info('Delivery repo %s found', name)
        return True

    except exceptions.DeliveryRepoIDNotFound:
        logger.error('Delivery repo %s not found', name)
        return False


def brew_from_delivery(delivery_repo: str) -> str:
    """
    Function to get the brew name from the delivery repo
    """

    logger.info('Retrieving brew name from delivery repo %s', delivery_repo)
    url = f"https://pyxis.engineering.redhat.com/v1/repositories/registry/registry.access.redhat.com/repository/{delivery_repo}/images"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        msg = f'Brew package could not be found from delivery repo `{delivery_repo}`'
        logger.error(msg)
        raise exceptions.BrewFromDeliveryNotFound(msg)

    result = []
    for data in response.json()['data']:
        result.append(data['brew']['package'])

    result = list(set(result))
    if len(result) > 1:
        msg = f'Multiple brew packages found for delivery repo `{delivery_repo}`'
        logger.error(msg)
        raise exceptions.MultipleBrewFromDelivery(msg)

    brew = result.pop()
    logger.info('Found brew %s', brew)
    return brew


def brew_to_cdn_delivery(brew_name: str, variant: str, delivery_repo_name: str) -> str:
    """
    Function the get the CDN name from brew name, variant and delivery repo name

    :brew_name: Brew repo name
    :variant: 8Base-RHOSE variant
    :delivery_repo_name: Delivery repo name
    """

    logger.info('Retrieving cdn from brew %s', brew_name)

    cdn_repo_names = brew_to_cdn(brew_name, variant)
    for cdn_repo_name in cdn_repo_names:
        delivery = cdn_to_delivery(cdn_repo_name)
        if delivery == delivery_repo_name:
            logger.info('Found delivery repo %s', cdn_repo_name)
            return cdn_repo_name

    msg = f'Could not find CDN from Brew name from delivery repo `{delivery_repo_name}`'
    logger.error(msg)
    raise exceptions.BrewToCdnWithDeliveryNotFound(msg)


def get_delivery_repo_id(name: str) -> str:
    """
    Function to get the delivery repo id. Used to construct the delivery repo URL to direct to its page in Pyxis.

    :name: Delivery repo name
    """

    logger.info('Retriving delivery repo id for %s', name)
    url = f"https://pyxis.engineering.redhat.com/v1/repositories?filter=repository=={name}"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        msg = "Couldn't find delivery repo link on Pyxis"
        logger.error(msg)
        raise exceptions.DeliveryRepoUrlNotFound(msg)

    try:
        repo_id = response.json()['data'][0]['_id']
        logger.info('Found repo id %s', repo_id)
        return repo_id

    except Exception:
        msg = f"Couldn't find delivery repo ID on Pyxis for {name}"
        logger.error(msg)
        raise exceptions.DeliveryRepoIDNotFound(msg)


# Methods
@util.refresh_krb_auth
def request_with_kerberos(url: str) -> requests.Response():
    # Kerberos authentication
    kerberos_auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)

    # Sending the kerberos ticket along with the request
    response = requests.get(url, auth=kerberos_auth)

    if response.status_code == 401:
        msg = 'Kerberos Authentication failed'
        logger.error(msg)
        raise exceptions.KerberosAuthenticationError(msg)

    return response


def get_image_stream_tag(distgit_name: str, version: str) -> str:
    """
    Function to get the image stream tag if the image is a payload image.
    The for_payload flag would be set to True in the yml file

    :distgit_name: Name of the distgit repo
    :version: OCP version
    """

    logger.info('Retrieving image stream tag for distgit %s', distgit_name)
    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    yml_file = yaml.safe_load(response.content)
    if yml_file.get('for_payload', False):  # Check if the image is in the payload
        tag = yml_file['name'].split("/")[1]
        return tag[4:] if tag.startswith("ose-") else tag  # remove 'ose-' if present

    else:
        logger.info('Image for %s is not in payload', distgit_name)


@util.cached
def github_distgit_mappings(version: str) -> dict:
    """
    Function to get the GitHub to Distgit mappings present in a particular OCP version.

    :version: OCP version
    """

    logger.info('Retrieving github to distgit mappings for version %s', version)
    rc, out, err = artbotlib.exectools.cmd_gather(
        f"doozer --disable-gssapi -g openshift-{version} images:print --short '{{upstream_public}}: {{name}}'")

    if rc != 0:
        if "koji.GSSAPIAuthError" in err:
            logger.error('Kerberos authentication error')
            raise exceptions.KerberosAuthenticationError("Kerberos authentication failed for doozer")

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
        msg = 'No data from doozer command for github-distgit mapping'
        logger.error(msg)
        raise exceptions.NullDataReturned(msg)

    logger.debug('Found github to distgit mappings: %s', mappings)
    return mappings


@util.cached
def distgit_github_mappings(version: str) -> dict:
    """
    Function to get the distgit to GitHub mappings present in a particular OCP version.

    :version: OCP version
    """

    logger.info('Retrieving distgit to github mappings for version %s', version)
    rc, out, err = artbotlib.exectools.cmd_gather(
        f"doozer --disable-gssapi -g openshift-{version} images:print --short '{{name}}: {{upstream_public}}'")

    if rc != 0:
        if "koji.GSSAPIAuthError" in err:
            logger.error('Kerberos authentication error')
            raise exceptions.KerberosAuthenticationError("Kerberos authentication failed for doozer")

        logger.error('Doozer returned status %s: %s', rc, err)
        raise RuntimeError(f'doozer returned status {rc}')

    mappings = {}
    for line in out.splitlines():
        distgit, github = line.split(": ")
        mappings[distgit] = github

    if not mappings:
        msg = 'No data from doozer command for distgit-github mapping'
        logger.error(msg)
        raise exceptions.NullDataReturned(msg)

    return mappings


def require_bundle_build(distgit_name: str, version: str) -> bool:
    """
    Function to check if bundle build details need to be displayed

    :distgit_name: Name of the distgit repo
    :version: OCP version
    """

    logger.info('Checking if component %s requires bundle builds', distgit_name)
    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    if response.status_code != 200:
        # If yml file does not exist
        msg = f'image dist-git {distgit_name} definition was not found at {url}'
        logger.error(msg)
        raise exceptions.DistgitNotFound(msg)

    yml_file = yaml.safe_load(response.content)
    try:
        _ = yml_file['update-csv']  # override default if component name specified in yml file
        logger.info('Component %s requires bundle builds', distgit_name)
        return True

    except KeyError:
        logger.info('Component %s does not require bundle builds', distgit_name)
        return False


def get_bundle_override(distgit_name: str, version: str) -> Union[str, None]:
    """
    Check the yml file for an override for the bundle component name. Else return None

    :distgit_name: The name of the distgit repo
    :version: The OCP version
    """

    logger.info('Checking if component %s has a bundle override configuration', distgit_name)
    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    if response.status_code != 200:
        # If yml file does not exist
        msg = f'image dist-git {distgit_name} definition was not found at {url}'
        logger.error(msg)
        raise exceptions.DistgitNotFound(msg)

    yml_file = yaml.safe_load(response.content)
    try:
        override = yml_file['distgit']['bundle_component']
        logger.info('Found bundle override %s for component %s', override, distgit_name)
        return override

    except KeyError:
        logger.info('Component %s does not have a bundle override', distgit_name)
        return None
