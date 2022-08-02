import requests
import yaml
from requests_kerberos import HTTPKerberosAuth, OPTIONAL
from collections import defaultdict
from . import util
from artbotlib import exceptions
from typing import Union

# Functions for pipeline from GitHub
def github_repo_is_available(repo_name: str) -> bool:
    """
    Function to check whether the given GitHub repo name is valid

    :repo_name: The name of the GitHub repo.
    """
    response = requests.head(f"https://github.com/openshift/{repo_name}")
    return response.status_code == 200


def github_to_distgit(github_name: str, version: str) -> list:
    """
    Driver function to get the GitHub to distgit mappings from the GitHub name and OCP version.

    :github_name: The name of the GitHub repo
    :version: OCP version
    """
    data = github_distgit_mappings(version)
    distgits = data[github_name]
    if not distgits:
        raise exceptions.DistgitFromGithubNotFound(
            f"Couldn't find Distgit repo from GitHub `{github_name}` and version `{version}`")
    return distgits


# Distgit
def distgit_is_available(distgit_repo_name: str) -> bool:
    """
    Function to check whether the given distgit repo name is valid

    :distgit_repo_name: The name of the distgit repo.
    """
    response = requests.head(f"https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}")
    return response.status_code == 200


def distgit_to_github(distgit_name: str, version: str) -> str:
    """
    Driver function to get the distgit to GitHub mappings from the GitHub name and OCP version.

    :distgit_name: The name of the distgit repo
    :version: OCP version
    """
    data = distgit_github_mappings(version)
    try:
        return data[distgit_name].split('/')[-1]
    except Exception:
        raise exceptions.GithubFromDistgitNotFound(
            f"Couldn't find GitHub repo from distgit `{distgit_name}` and version `{version}`")


def distgit_to_brew(distgit_name: str, version: str) -> str:
    """
    Get the brew name from the distgit name.

    :distgit_name: The name of the distgit repo
    :version: The OCP version
    """
    brew_name = f"{distgit_name}-container"  # Default brew name

    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    if response.status_code != 200:
        raise exceptions.DistgitNotFound(
            f"image dist-git {distgit_name} definition was not found at {url}")  # If yml file does not exist

    yml_file = yaml.safe_load(response.content)
    try:
        return yml_file['distgit']['component']  # override default if component name specified in yml file
    except KeyError:
        return brew_name


def distgit_to_delivery(distgit_repo_name: str, version: str, variant: str) -> str:
    """
    Driver function for distgit -> delivery pipeline.

    :distgit_repo_name: The name of the distgit repo
    :version: OCP version
    :variant: RHOSE variant
    """
    payload = ""

    # Tag
    tag = get_image_stream_tag(distgit_repo_name, version)
    if tag:
        payload += f"Payload tag: *{tag}* \n"

    # Distgit -> Brew
    brew_package_name = distgit_to_brew(distgit_repo_name, version)
    brew_id = get_brew_id(brew_package_name)
    payload += f"Production brew builds: <https://brewweb.engineering.redhat.com/brew/packageinfo?packageID={brew_id}|*{brew_package_name}*>\n"

    # Bundle Builds
    if require_bundle_build(distgit_repo_name, version):
        bundle_component = get_bundle_override(distgit_repo_name, version)
        if not bundle_component:
            bundle_component = f"{'-'.join(brew_package_name.split('-')[:-1])}-metadata-component"
        bundle_distgit = f"{distgit_repo_name}-bundle"

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
        _ = get_brew_id(brew_name)
        return True
    except exceptions.BrewIdNotFound:
        return False


def brew_to_github(brew_name: str, version: str) -> str:
    """
    Driver function for Brew -> GitHub pipeline

    :brew_name: Name of the brew package
    :version: OCP version
    """
    payload = ""

    # Distgit
    distgit_repo_name = brew_to_distgit(brew_name, version)

    # Distgit -> GitHub
    github_repo = distgit_to_github(distgit_repo_name, version)
    payload += f"Upstream GitHub repository: <https://github.com/openshift/{github_repo}|*openshift/{github_repo}*>\n"
    payload += f"Private GitHub repository: <https://github.com/openshift-priv/{github_repo}|*openshift-priv/{github_repo}*>\n"

    # To keep the presented order same
    payload += f"Production dist-git repo: <https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

    # Bundle Builds
    if require_bundle_build(distgit_repo_name, version):
        bundle_component = get_bundle_override(distgit_repo_name, version)
        if not bundle_component:
            bundle_component = f"{'-'.join(brew_name.split('-')[:-1])}-metadata-component"
        bundle_distgit = f"{distgit_repo_name}-bundle"

        payload += f"Bundle Component: *{bundle_component}*\n"
        payload += f"Bundle Distgit: *{bundle_distgit}*\n"

    # Tag
    tag = get_image_stream_tag(distgit_repo_name, version)
    if tag:
        payload += f"Payload tag: *{tag}* \n"

    return payload


def get_brew_id(brew_name: str) -> int:
    """
    Get the brew id for the given brew name.

    :so: SlackOutput object for reporting results.
    :brew_name: The name of the brew package
    """
    try:
        koji_api = util.koji_client_session()
    except Exception:
        raise exceptions.KojiClientError("Failed to connect to Brew.")

    try:
        brew_id = koji_api.getPackageID(brew_name, strict=True)
    except Exception:
        raise exceptions.BrewIdNotFound(f"Brew ID not found for brew package `{brew_name}`. Check API call.")

    return brew_id


def brew_to_cdn(brew_name: str, variant_name: str) -> list:
    """
    Function to return all the Brew to CDN mappings (since more than one could be present)

    :brew_name: Brew package name
    :variant_name: The name of the product variant eg: 8Base-RHOSE-4.10
    """
    url = f"https://errata.devel.redhat.com/api/v1/cdn_repo_package_tags?filter[package_name]={brew_name}"
    response = request_with_kerberos(url)

    repos = []
    for item in response.json()['data']:
        repos.append(item['relationships']['cdn_repo']['name'])

    repos = list(set(repos))  # Getting only the unique repo names

    # Cross-check to see if the repo is mapped to the given variant
    results = []
    for repo in repos:
        response = get_cdn_repo_details(repo)
        for variant in response['data']['relationships']['variants']:
            if variant['name'] == variant_name:
                results.append(repo)
                break

    if not results:
        raise exceptions.CdnFromBrewNotFound(f"CDN was not found for brew `{brew_name}` and variant `{variant_name}`")
    return results


def brew_to_delivery(brew_package_name: str, variant: str) -> str:
    """
    Driver function for Brew -> Delivery pipeline

    :brew_package_name: Brew package name
    :variant: The 8Base-RHOSE variant
    """
    payload = ""
    cdn_repo_names = brew_to_cdn(brew_package_name, variant)
    if len(cdn_repo_names) > 1:
        payload += "\n *Found more than one Brew to CDN mappings:*\n\n"

    for cdn_repo_name in cdn_repo_names:
        # CDN
        payload += get_cdn_payload(cdn_repo_name, variant)

        # CDN -> Delivery
        payload += cdn_to_delivery_payload(cdn_repo_name)
    return payload


@util.cached
def doozer_brew_distgit(version: str) -> list:
    output = util.cmd_gather(f"doozer --disable-gssapi -g openshift-{version} images:print --short '{{component}}: {{name}}'")
    if "koji.GSSAPIAuthError" in output[2]:
        raise exceptions.KerberosAuthenticationError("Kerberos authentication failed for doozer")

    result = []
    for line in output[1].splitlines():
        array = line.split(": ")
        result.append(array)

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
        if len(line) == 2:
            dict_data[line[0]] = line[1]

    if not dict_data:
        raise exceptions.NullDataReturned("No data from doozer command for brew-distgit mapping")
    try:
        return dict_data[brew_name]
    except Exception:
        raise exceptions.BrewToDistgitMappingNotFound("Could not find brew-distgit mapping from ocp-build-data")


# CDN stuff
def cdn_is_available(cdn_name: str) -> bool:
    """
    Function to check if the given CDN repo name is available

    :cdn_name: Name of the CDN repo
    """
    try:
        _ = get_cdn_repo_details(cdn_name)
        return True
    except exceptions.CdnNotFound:
        return False


def get_cdn_repo_details(cdn_name: str) -> dict:
    """
    Function to get the details regarding the given CDN repo.

    :cdn_name: The name of the CDN repo
    """
    url = f"https://errata.devel.redhat.com/api/v1/cdn_repos/{cdn_name}"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        raise exceptions.CdnNotFound(f"CDN was not found for CDN name {cdn_name}")

    return response.json()


def cdn_to_delivery(cdn_name: str) -> str:
    """
    Function to get the delivery repo name from the CDN repo name.

    :cdn_name: THe CDN repo name
    """
    response = get_cdn_repo_details(cdn_name)

    try:
        return response['data']['attributes']['external_name']
    except Exception:
        raise exceptions.DeliveryRepoNotFound(f"Delivery Repo not found for CDN `{cdn_name}`")


def get_cdn_repo_id(cdn_name: str) -> int:
    """
    Function to get the CDN repo ID. Used to construct the CDN repo URL to direct to its page in Errata.

    :cdn_name: The name of the CDN repo
    """
    response = get_cdn_repo_details(cdn_name)

    try:
        return response['data']['id']
    except Exception:
        raise exceptions.CdnIdNotFound(f"CDN ID not found for CDN `{cdn_name}`")


def cdn_to_brew(cdn_name: str) -> str:
    """
    Function to get the brew name from the given CDN name

    :cdn_name: The CDN repo name
    """
    response = get_cdn_repo_details(cdn_name)

    brew_packages = response['data']['relationships']['packages']
    if len(brew_packages) > 1:
        raise exceptions.MultipleCdnToBrewMappings("Multiple Brew to CDN mappings found. Contact ART.")
    try:
        return brew_packages[0]['name']
    except KeyError:
        raise exceptions.BrewNotFoundFromCdnApi("Brew package not mapped to CDN in Errata. Contact ART.")


def get_variant_id(cdn_name: str, variant_name: str) -> int:
    """
    Function to get the id of the product variant. Used to get the product ID.

    :cdn_name: The name of the CDN repo
    :variant_name: The name of the product variant
    """
    response = get_cdn_repo_details(cdn_name)

    try:
        for data in response['data']['relationships']['variants']:
            if data['name'] == variant_name:
                return data['id']
    except Exception:
        raise exceptions.VariantIdNotFound(f"Variant ID not found for CDN `{cdn_name}` and variant `{variant_name}`")


def get_product_id(variant_id: int) -> int:
    """
    Function to get the product id. Used to construct the CDN repo URL to direct to its page in Errata.

    :variant_id: Product variant ID
    """
    url = f"https://errata.devel.redhat.com/api/v1/variants/{variant_id}"
    response = request_with_kerberos(url)

    try:
        return response.json()['data']['attributes']['relationships']['product_version']['id']
    except Exception:
        raise exceptions.ProductIdNotFound(f"Product ID not found for variant `{variant_id}`")


def cdn_to_github(cdn_name: str, version: str) -> str:
    """
    Driver function for the CDN -> GitHub pipeline

    :cdn_name: The name of the CDN repo
    :version: The OCP version
    """
    payload = ""

    # Brew
    brew_name = cdn_to_brew(cdn_name)
    brew_id = get_brew_id(brew_name)
    payload += f"Production brew builds: <https://brewweb.engineering.redhat.com/brew/packageinfo?packageID={brew_id}|*{brew_name}*>\n"

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
    cdn_repo_id = get_cdn_repo_id(cdn_repo_name)
    variant_id = get_variant_id(cdn_repo_name, variant)
    product_id = get_product_id(variant_id)

    return f"CDN repo: <https://errata.devel.redhat.com/product_versions/{product_id}/cdn_repos/{cdn_repo_id}|*{cdn_repo_name}*>\n"


def cdn_to_delivery_payload(cdn_repo_name: str):
    """
    Function to get the CDN payload for slack (since it's needed in multiple places.

    :cdn_repo_name: The name of the CDN repo
    """
    delivery_repo_name = cdn_to_delivery(cdn_repo_name)
    delivery_repo_id = get_delivery_repo_id(delivery_repo_name)
    return f"Delivery (Comet) repo: <https://comet.engineering.redhat.com/containers/repositories/{delivery_repo_id}|*{delivery_repo_name}*>\n\n"


# Delivery stuff
def delivery_repo_is_available(name: str) -> bool:
    """
    Function to check if the given delivery repo exists

    :name: Name of the delivery repo
    """
    try:
        _ = get_delivery_repo_id(name)
        return True
    except exceptions.DeliveryRepoIDNotFound:
        return False


def brew_from_delivery(delivery_repo: str) -> str:
    """
    Function to get the brew name from the delivery repo
    """
    url = f"https://pyxis.engineering.redhat.com/v1/repositories/registry/registry.access.redhat.com/repository/{delivery_repo}/images"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        raise exceptions.BrewFromDeliveryNotFound(
            f"Brew package could not be found from delivery repo `{delivery_repo}`")

    result = []
    for data in response.json()['data']:
        result.append(data['brew']['package'])

    result = list(set(result))
    if len(result) > 1:
        raise exceptions.MultipleBrewFromDelivery(f"Multiple brew packages found for delivery repo `{delivery_repo}`")

    return result.pop()


def brew_to_cdn_delivery(brew_name: str, variant: str, delivery_repo_name: str) -> str:
    """
    Function the get the CDN name from brew name, variant and delivery repo name

    :brew_name: Brew repo name
    :variant: 8Base-RHOSE variant
    :delivery_repo_name: Delivery repo name
    """
    cdn_repo_names = brew_to_cdn(brew_name, variant)
    for cdn_repo_name in cdn_repo_names:
        delivery = cdn_to_delivery(cdn_repo_name)
        if delivery == delivery_repo_name:
            return cdn_repo_name
    raise exceptions.BrewToCdnWithDeliveryNotFound(
        f"Could not find CDN from Brew name from delivery repo `{delivery_repo_name}`")


def get_delivery_repo_id(name: str) -> str:
    """
    Function to get the delivery repo id. Used to construct the delivery repo URL to direct to its page in Pyxis.

    :name: Delivery repo name
    """
    url = f"https://pyxis.engineering.redhat.com/v1/repositories?filter=repository=={name}"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        raise exceptions.DeliveryRepoUrlNotFound(f"Couldn't find delivery repo link on Pyxis")

    try:
        repo_id = response.json()['data'][0]['_id']
    except Exception:
        raise exceptions.DeliveryRepoIDNotFound(f"Couldn't find delivery repo ID on Pyxis for {name}")

    return repo_id


# Methods
@util.refresh_krb_auth
def request_with_kerberos(url: str) -> requests.Response():
    # Kerberos authentication
    kerberos_auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)

    # Sending the kerberos ticket along with the request
    response = requests.get(url, auth=kerberos_auth)

    if response.status_code == 401:
        raise exceptions.KerberosAuthenticationError("Kerberos Authentication failed")

    return response


def get_image_stream_tag(distgit_name: str, version: str) -> str:
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


@util.cached
def doozer_github_distgit(version: str) -> list:
    """
    Function to get the distgit to GitHub mappings from doozer

    :version: OCP version
    """
    output = util.cmd_gather(f"doozer --disable-gssapi -g openshift-{version} images:print --short '{{name}}: {{upstream_public}}'")
    if "koji.GSSAPIAuthError" in output[2]:
        raise exceptions.KerberosAuthenticationError("Kerberos authentication failed for doozer")

    result = []
    for line in output[1].splitlines():
        array = line.split(": ")
        result.append(array)

    return result


def github_distgit_mappings(version: str) -> dict:
    """
    Function to get the GitHub to Distgit mappings present in a particular OCP version.

    :version: OCP version
    """
    output = doozer_github_distgit(version)
    dict_data = defaultdict(list)
    for line in output:
        if len(line) == 2:
            dict_data[line[1].split("/")[-1]].append(line[0])

    if not dict_data:
        raise exceptions.NullDataReturned("No data from doozer command for github-distgit mapping")
    return dict_data


def distgit_github_mappings(version: str) -> dict:
    """
    Function to get the distgit to GitHub mappings present in a particular OCP version.

    :version: OCP version
    """
    output = doozer_github_distgit(version)
    dict_data = {}
    for line in output:
        if len(line) == 2:
            dict_data[line[0]] = line[1]
    if not dict_data:
        raise exceptions.NullDataReturned("No data from doozer command for distgit-github mapping")
    return dict_data


def require_bundle_build(distgit_name: str, version: str) -> bool:
    """
    Function to check if bundle build details need to be displayed

    :distgit_name: Name of the distgit repo
    :version: OCP version
    """
    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    if response.status_code != 200:
        raise exceptions.DistgitNotFound(
            f"image dist-git {distgit_name} definition was not found at {url}")  # If yml file does not exist

    yml_file = yaml.safe_load(response.content)
    try:
        _ = yml_file['update-csv']  # override default if component name specified in yml file
        return True
    except KeyError:
        return False


def get_bundle_override(distgit_name: str, version: str) -> Union[str, None]:
    """
    Check the yml file for an override for the bundle component name. Else return None

    :distgit_name: The name of the distgit repo
    :version: The OCP version
    """
    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    if response.status_code != 200:
        raise exceptions.DistgitNotFound(
            f"image dist-git {distgit_name} definition was not found at {url}")  # If yml file does not exist

    yml_file = yaml.safe_load(response.content)
    try:
        return yml_file['distgit']['bundle_component']
    except KeyError:
        return None
