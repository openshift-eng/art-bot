import requests
import yaml
from requests_kerberos import HTTPKerberosAuth, REQUIRED


class ArtBotExceptions(Exception):
    def __int__(self, message):
        self.message = message


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


class CdnNotFound(ArtBotExceptions):
    """Exception raised if CDN is not found

        Attributes:
            message -- explanation of the error
        """

    def __init__(self, brew_name, variant):
        self.message = f"CDN was not found for brew `{brew_name}` and variant `{variant}`"
        super().__init__(self.message)


class DeliveryRepoNotFound(ArtBotExceptions):
    """Exception raised if delivery repo not found

        Attributes:
            message -- explanation of the error
        """

    def __init__(self, cdn_name):
        self.message = f"Delivery Repo not found for CDN `{cdn_name}`"
        super().__init__(self.message)


class KerberosAuthenticationError(Exception):
    """Exception raised for Authentication error if keytab or ticket is missing

    Attributes:
        message -- explanation of the error
    """

    def __init__(self):
        self.message = "Kerberos authentication failed. Check keytab"
        super().__init__(self.message)


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


def brew_to_cdn(brew_name, variant_name):
    # Kerberos authentication
    kerberos_auth = HTTPKerberosAuth(mutual_authentication=REQUIRED, sanitize_mutual_error_response=False)

    url = f"https://errata.devel.redhat.com/api/v1/cdn_repo_package_tags?page[number]=1&filter[package_name]={brew_name}&filter[variant_name]={variant_name}"
    # Sending the kerberos ticket along with the request
    response = requests.get(url, auth=kerberos_auth)

    if response.status_code == 401:
        raise KerberosAuthenticationError

    try:
        return response.json()['data'][0]['relationships']['cdn_repo']['name']
    except Exception:
        raise CdnNotFound(brew_name, variant_name)


def cdn_to_comet(cdn_name):
    # Kerberos authentication
    kerberos_auth = HTTPKerberosAuth(mutual_authentication=REQUIRED, sanitize_mutual_error_response=False)

    # Sending the kerberos ticket along with the request
    response = requests.get(f"https://errata.devel.redhat.com/api/v1/cdn_repos/{cdn_name}",
                            auth=kerberos_auth)

    if response.status_code == 401:
        raise KerberosAuthenticationError

    try:
        return response.json()['data']['attributes']['external_name']
    except Exception:
        raise DeliveryRepoNotFound(cdn_name)


def distgit_is_available(distgit_repo_name):
    response = requests.head(f"https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}")
    return response.status_code == 200


def pipeline_from_distgit(so, distgit_repo_name, version):
    """
    List the Brew package name, CDN repo name and CDN repo details by getting the distgit name as input.

    :so: SlackOuput object for reporting results.
    :distgit_repo_name: Name of the distgit repo we get as input
    :version: OS version
    """

    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified

    payload = ""

    if distgit_is_available(distgit_repo_name):  # Check if the given distgit repo actually exists
        payload += f"Distgit Repo: <https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

        try:
            brew_package_name = distgit_to_brew(distgit_repo_name, version)
            payload += f"Brew package: *{brew_package_name}*\n"

            cdn_repo_name = brew_to_cdn(brew_package_name, f"8Base-RHOSE-{version}")
            payload += f"CDN repo: *{cdn_repo_name}*\n"

            cdn_repo_id = cdn_to_comet(cdn_repo_name)
            payload += f"Delivery (Comet) repo: *{cdn_repo_id}*\n"
        except ArtBotExceptions as e:
            payload += "\n"
            payload += e.message
            so.say(payload)
            return
        except KerberosAuthenticationError as e:
            print(e.message)
            return
        except Exception as e:
            print(f"UNKNOWN ERROR: {e}")

    else:
        # If incorrect distgit name provided, no need to proceed.
        payload += f"No distgit repo with name *{distgit_repo_name}* exists."

    so.say(payload)
