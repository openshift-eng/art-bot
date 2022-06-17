import requests
import yaml
from requests_kerberos import HTTPKerberosAuth, OPTIONAL
from artbotlib import exceptions
from . import util


# Methods
def request_with_kerberos(url):
    # Kerberos authentication
    kerberos_auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)

    # Sending the kerberos ticket along with the request
    response = requests.get(url, auth=kerberos_auth)

    if response.status_code == 401:
        raise exceptions.KerberosAuthenticationError("")

    return response


def distgit_to_brew(distgit_name, version):
    brew_name = f"{distgit_name}-container"

    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    if response.status_code != 200:
        raise exceptions.DistgitNotFound(
            f"image dist-git {distgit_name} definition was not found at {url}")  # If yml file does not exist

    yml_file = yaml.safe_load(response.content)
    try:
        component_name = yml_file['distgit']['component']
    except KeyError:
        return brew_name

    return component_name


def get_image_stream_tag(distgit_name, version):
    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    yml_file = yaml.safe_load(response.content)
    if yml_file.get('for_payload', False):
        tag = yml_file['name'].split("/")[1]
        return tag[4:] if tag.startswith("ose-") else tag


def brew_to_cdn(brew_name, variant_name):
    url = f"https://errata.devel.redhat.com/api/v1/cdn_repo_package_tags?filter[package_name]={brew_name}&filter[variant_name]={variant_name}"
    response = request_with_kerberos(url)

    repos = []
    for item in response.json()['data']:
        repos.append(item['relationships']['cdn_repo']['name'])

    if not repos:
        raise exceptions.CdnFromBrewNotFound(f"CDN was not found for brew `{brew_name}` and variant `{variant_name}`")
    return repos


def get_cdn_repo_details(cdn_name):
    url = f"https://errata.devel.redhat.com/api/v1/cdn_repos/{cdn_name}"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        raise exceptions.CdnNotFound(f"CDN was not found for CDN name {cdn_name}")

    return response.json()


def cdn_to_comet(cdn_name):
    response = get_cdn_repo_details(cdn_name)

    try:
        return response['data']['attributes']['external_name']
    except Exception:
        raise exceptions.DeliveryRepoNotFound(f"Delivery Repo not found for CDN `{cdn_name}`")


def get_cdn_repo_id(cdn_name):
    response = get_cdn_repo_details(cdn_name)

    try:
        return response['data']['id']
    except Exception:
        raise exceptions.CdnIdNotFound(f"CDN ID not found for CDN `{cdn_name}`")


def distgit_is_available(distgit_repo_name):
    response = requests.head(f"https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}")
    return response.status_code == 200


def get_brew_id(brew_name):
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


def get_variant_id(cdn_name, variant_name):
    response = get_cdn_repo_details(cdn_name)

    try:
        for data in response['data']['relationships']['variants']:
            if data['name'] == variant_name:
                return data['id']
    except Exception:
        raise exceptions.VariantIdNotFound(f"Variant ID not found for CDN `{cdn_name}` and variant `{variant_name}`")


def get_product_id(variant_id):
    url = f"https://errata.devel.redhat.com/api/v1/variants/{variant_id}"
    response = request_with_kerberos(url)

    try:
        return response.json()['data']['attributes']['relationships']['product_version']['id']
    except Exception:
        raise exceptions.ProductIdNotFound(f"Product ID not found for variant `{variant_id}`")


def get_delivery_repo_id(name):
    url = f"https://pyxis.engineering.redhat.com/v1/repositories?filter=repository=={name}"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        raise exceptions.DeliveryRepoUrlNotFound(f"Couldn't find delivery repo link on Pyxis")

    try:
        repo_id = response.json()['data'][0]['_id']
    except Exception:
        raise exceptions.DeliveryRepoIDNotFound(f"Couldn't find delivery repo ID on Pyxis for {name}")

    return repo_id


@util.cached
def github_distgit_mappings(version):
    output = util.cmd_gather(f"doozer -g openshift-{version} images:print --short '{{name}}: {{upstream_public}}'")
    dict_data = {}
    for line in output[1].splitlines():
        array = line.split(": ")
        if len(array) == 2:
            dict_data[array[1]] = array[0]
    return dict_data


@util.cached
def distgit_github_mappings(version):
    output = util.cmd_gather(f"doozer -g openshift-{version} images:print --short '{{name}}: {{upstream_public}}'")
    dict_data = {}
    for line in output[1].splitlines():
        array = line.split(": ")
        if len(array) == 2:
            dict_data[array[0]] = array[1]
    return dict_data


def get_github_from_distgit(distgit_name, version):
    data = distgit_github_mappings(version)
    try:
        return data[distgit_name].split('/')[-1]
    except Exception:
        raise exceptions.GithubFromDistgitNotFound(
            f"Couldn't find GitHub repo from distgit `{distgit_name}` and version `{version}`")


def pipeline_from_distgit(so, distgit_repo_name, version):
    """
    List the Brew package name, CDN repo name and CDN repo details by getting the distgit name as input.

    :so: SlackOutput object for reporting results.
    :distgit_repo_name: Name of the distgit repo we get as input
    :version: OS version
    """
    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified

    payload = ""

    if not distgit_is_available(distgit_repo_name):  # Check if the given distgit repo actually exists
        # If incorrect distgit name provided, no need to proceed.
        payload += f"No distgit repo with name *{distgit_repo_name}* exists."
        so.say(payload)
        return
    else:
        so.say("Fetching data. Please wait...")
        try:
            github_repo = get_github_from_distgit(distgit_repo_name, version)
            payload += f"Upstream GitHub repository: <https://github.com/openshift/{github_repo}|*openshift/{github_repo}*>\n"
            payload += f"Private GitHub repository: <https://github.com/openshift-priv/{github_repo}|*openshift-priv/{github_repo}*>\n"

            payload += f"Production dist-git repo: <https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

            brew_package_name = distgit_to_brew(distgit_repo_name, version)
            brew_id = get_brew_id(brew_package_name)
            payload += f"Production brew builds: <https://brewweb.engineering.redhat.com/brew/packageinfo?packageID={brew_id}|*{brew_package_name}*>\n"
            tag = get_image_stream_tag(distgit_repo_name, version)
            if tag:
                payload += f"Payload tag: *{tag}* \n"

            variant = f"8Base-RHOSE-{version}"
            cdn_repo_names = brew_to_cdn(brew_package_name, variant)
            if len(cdn_repo_names) > 1:
                payload += "\n *Found more than one Brew to CDN mappings:*\n\n"

            for cdn_repo_name in cdn_repo_names:
                cdn_repo_id = get_cdn_repo_id(cdn_repo_name)
                variant_id = get_variant_id(cdn_repo_name, variant)
                product_id = get_product_id(variant_id)
                payload += f"CDN repo: <https://errata.devel.redhat.com/product_versions/{product_id}/cdn_repos/{cdn_repo_id}|*{cdn_repo_name}*>\n"

                delivery_repo_name = cdn_to_comet(cdn_repo_name)
                delivery_repo_id = get_delivery_repo_id(delivery_repo_name)
                payload += f"Delivery (Comet) repo: <https://comet.engineering.redhat.com/containers/repositories/{delivery_repo_id}|*{delivery_repo_name}*>\n\n"
        except exceptions.ArtBotExceptions as e:
            payload += "\n"
            payload += f"{e}"
            so.say(payload)
            so.monitoring_say(f"ERROR: {e}")
            return
        except exceptions.KerberosAuthenticationError as e:
            so.say(f"{e}. Contact the ART Team")
            so.monitoring_say(f"ERROR: {e} Check keytab.")
            return
        except exceptions.KojiClientError as e:
            so.say(e)
            so.monitoring_say(f"ERROR: {e}")
        except Exception as e:
            so.say("Unknown error. Contact the ART team.")
            so.monitoring_say(f"ERROR: Unclassified: {e}")
    so.say(payload)
