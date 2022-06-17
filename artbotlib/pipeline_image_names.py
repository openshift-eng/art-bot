import requests
import yaml
from requests_kerberos import HTTPKerberosAuth, OPTIONAL
from . import util


# Super class for all ART bot exceptions
class ArtBotExceptions(Exception):
    def __int__(self, message):
        self.message = message


# Art bot exceptions
class DistgitNotFound(ArtBotExceptions):
    """Exception raised for errors in the input dist-git name.

    Attributes:
        distgit_name -- input dist-git name which caused the error
        message -- explanation of the error
    """

    def __init__(self, distgit_name, url):
        self.distgit_name = distgit_name
        self.message = f"image dist-git {distgit_name} definition was not found at {url}"
        super().__init__(self.message)


class CdnFromBrewNotFound(ArtBotExceptions):
    """Exception raised if CDN is not found from brew name and variant

        Attributes:
            message -- explanation of the error
        """

    def __init__(self, brew_name, variant):
        self.message = f"CDN was not found for brew `{brew_name}` and variant `{variant}`"
        super().__init__(self.message)


class CdnNotFound(ArtBotExceptions):
    """Exception raised if CDN is not found from CDN name

        Attributes:
            message -- explanation of the error
        """

    def __init__(self, cdn_name):
        self.message = f"CDN was not found for CDN name {cdn_name}"
        super().__init__(self.message)


class DeliveryRepoNotFound(ArtBotExceptions):
    """Exception raised if delivery repo not found

        Attributes:
            message -- explanation of the error
        """

    def __init__(self, cdn_name):
        self.message = f"Delivery Repo not found for CDN `{cdn_name}`"
        super().__init__(self.message)


class BrewIdNotFound(ArtBotExceptions):
    """Exception raised if brew id not found for the given brew package name

            Attributes:
                message -- explanation of the error
            """

    def __init__(self, brew_name):
        self.message = f"Brew ID not found for brew package `{brew_name}`. Check API call."
        super().__init__(self.message)


class VariantIdNotFound(ArtBotExceptions):
    """Exception raised if variant id not found for a CDN repo

            Attributes:
                message -- explanation of the error
            """

    def __init__(self, cdn_name, variant_name):
        self.message = f"Variant ID not found for CDN `{cdn_name}` and variant `{variant_name}`"
        super().__init__(self.message)


class CdnIdNotFound(ArtBotExceptions):
    """Exception raised if CDN id not found for a CDN repo

            Attributes:
                message -- explanation of the error
            """

    def __init__(self, cdn_name):
        self.message = f"CDN ID not found for CDN `{cdn_name}`"
        super().__init__(self.message)


class ProductIdNotFound(ArtBotExceptions):
    """Exception raised if Product id not found for a product variant

            Attributes:
                message -- explanation of the error
            """

    def __init__(self, variant_id):
        self.message = f"Product ID not found for variant `{variant_id}`"
        super().__init__(self.message)


class DeliveryRepoUrlNotFound(ArtBotExceptions):
    """Exception raised if delivery repo not found on Pyxis.

            Attributes:
                message -- explanation of the error
            """

    def __init__(self, variant_id):
        self.message = f"Couldn't find delivery repo link on Pyxis"
        super().__init__(self.message)


class DeliveryRepoIDNotFound(ArtBotExceptions):
    """Exception raised if delivery repo ID not found on Pyxis.

            Attributes:
                message -- explanation of the error
            """

    def __init__(self, name):
        self.message = f"Couldn't find delivery repo ID on Pyxis for {name}"
        super().__init__(self.message)


class GithubFromDistgitNotFound(ArtBotExceptions):
    """Exception raised if Github repo could not be found from the distgit name

            Attributes:
                message -- explanation of the error
            """

    def __init__(self, distgit_name, version):
        self.message = f"Couldn't find GitHub repo from distgit `{distgit_name}` and version `{version}`"
        super().__init__(self.message)


# Other exceptions
class KojiClientError(Exception):
    """Exception raised when we cannot connect to brew.

        Attributes:
            message -- explanation of the error
        """

    def __init__(self):
        self.message = "Failed to connect to Brew."
        super().__init__(self.message)


class KerberosAuthenticationError(Exception):
    """Exception raised for Authentication error if keytab or ticket is missing

    Attributes:
        message -- explanation of the error
    """

    def __init__(self):
        self.message = "Kerberos authentication failed."
        super().__init__(self.message)


# Methods
def request_with_kerberos(url):
    # Kerberos authentication
    kerberos_auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)

    # Sending the kerberos ticket along with the request
    response = requests.get(url, auth=kerberos_auth)

    if response.status_code == 401:
        raise KerberosAuthenticationError()

    return response


def distgit_to_brew(distgit_name, version):
    brew_name = f"{distgit_name}-container"

    url = f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml"
    response = requests.get(url)

    if response.status_code != 200:
        raise DistgitNotFound(distgit_name, url)  # If yml file does not exist

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
    url = f"https://errata.devel.redhat.com/api/v1/cdn_repo_package_tags?page[number]=1&filter[package_name]={brew_name}&filter[variant_name]={variant_name}"
    response = request_with_kerberos(url)

    repos = []
    for item in response.json()['data']:
        repos.append(item['relationships']['cdn_repo']['name'])

    if not repos:
        raise CdnFromBrewNotFound(brew_name, variant_name)
    return repos


def get_cdn_repo_details(cdn_name):
    url = f"https://errata.devel.redhat.com/api/v1/cdn_repos/{cdn_name}"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        raise CdnNotFound(cdn_name)

    return response.json()


def cdn_to_comet(cdn_name):
    response = get_cdn_repo_details(cdn_name)

    try:
        return response['data']['attributes']['external_name']
    except Exception:
        raise DeliveryRepoNotFound(cdn_name)


def get_cdn_repo_id(cdn_name):
    response = get_cdn_repo_details(cdn_name)

    try:
        return response['data']['id']
    except Exception:
        raise CdnIdNotFound(cdn_name)


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
        raise KojiClientError

    try:
        brew_id = koji_api.getPackageID(brew_name, strict=True)
    except Exception:
        raise BrewIdNotFound(brew_name)

    return brew_id


def get_variant_id(cdn_name, variant_name):
    response = get_cdn_repo_details(cdn_name)

    try:
        for data in response['data']['relationships']['variants']:
            if data['name'] == variant_name:
                return data['id']
    except Exception:
        raise VariantIdNotFound(cdn_name, variant_name)


def get_product_id(variant_id):
    url = f"https://errata.devel.redhat.com/api/v1/variants/{variant_id}"
    response = request_with_kerberos(url)

    try:
        return response.json()['data']['attributes']['relationships']['product_version']['id']
    except Exception:
        raise ProductIdNotFound(variant_id)


def get_delivery_repo_id(name):
    url = f"https://pyxis.engineering.redhat.com/v1/repositories?filter=repository=={name}"
    response = request_with_kerberos(url)

    if response.status_code == 404:
        raise DeliveryRepoUrlNotFound

    try:
        repo_id = response.json()['data'][0]['_id']
    except Exception:
        raise DeliveryRepoIDNotFound(name)

    return repo_id


def github_distgit_mappings(version):
    output = util.cmd_gather("doozer -g openshift-" + version + " images:print --short '{name}: {upstream_public}'")
    data = output[1].split("\n")
    dict_data = {}
    for line in data:
        array = line.split(": ")
        if array != ['']:
            dict_data[array[1]] = array[0]
    return dict_data


def distgit_github_mappings(version):
    output = util.cmd_gather("doozer -g openshift-" + version + " images:print --short '{name}: {upstream_public}'")
    data = output[1].split("\n")
    dict_data = {}
    for line in data:
        array = line.split(": ")
        if array != ['']:
            dict_data[array[0]] = array[1]
    return dict_data


@util.cached
def get_github_from_distgit(distgit_name, version):
    data = distgit_github_mappings(version)
    try:
        return data[distgit_name].split('/')[-1]
    except Exception:
        raise GithubFromDistgitNotFound(distgit_name, version)


def get_distgit_from_github(git_repo, version):
    data = github_distgit_mappings(version)
    return data[git_repo]
    # TODO: For next iteration


def pipeline_from_distgit(so, distgit_repo_name, version):
    """
    List the Brew package name, CDN repo name and CDN repo details by getting the distgit name as input.

    :so: SlackOutput object for reporting results.
    :distgit_repo_name: Name of the distgit repo we get as input
    :version: OS version
    """
    so.say("Fetching data. Please wait...")

    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified

    payload = ""

    if distgit_is_available(distgit_repo_name):  # Check if the given distgit repo actually exists
        github_repo = get_github_from_distgit(distgit_repo_name, version)
        payload += f"Upstream GitHub repository: <https://github.com/openshift/{github_repo}|*openshift/{github_repo}*>\n"
        payload += f"Private GitHub repository: <https://github.com/openshift-priv/{github_repo}|*openshift-priv/{github_repo}*>\n"

        payload += f"Production dist-git repo: <https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"
        try:
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
        except ArtBotExceptions as e:
            payload += "\n"
            payload += e.message
            so.say(payload)
            so.monitoring_say(f"ERROR: {e.message}")
            return
        except KerberosAuthenticationError as e:
            so.say(e.message + " Contact the ART Team")
            so.monitoring_say(f"ERROR: {e.message} Check keytab.")
            return
        except KojiClientError as e:
            so.say(e.message)
            so.monitoring_say(f"ERROR: {e.message}")
        except Exception as e:
            so.say("Unknown error. Contact the ART team.")
            so.monitoring_say(f"ERROR: Unclassified: {e}")

    else:
        # If incorrect distgit name provided, no need to proceed.
        payload += f"No distgit repo with name *{distgit_repo_name}* exists."
        so.monitoring_say(f"No distgit repo with name *{distgit_repo_name}* exists.")

    so.say(payload)
