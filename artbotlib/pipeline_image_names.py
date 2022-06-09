import requests
import yaml
from requests_kerberos import HTTPKerberosAuth, REQUIRED


def distgit_to_brew(distgit_name, version):
    brew_name = f"{distgit_name}-container"

    response = requests.get(
        f"https://raw.githubusercontent.com/openshift/ocp-build-data/openshift-{version}/images/{distgit_name}.yml")

    if response.status_code != 200:
        print(f"Error: The specified yml file doesn't exist")
        return "Couldn't find Brew Package name"

    yml_file = yaml.safe_load(response.content)
    try:
        component_name = yml_file['distgit']['component']
    except KeyError:
        return brew_name

    return component_name


def brew_to_cdn(brew_name, variant_name):
    # Kerberos authentication
    kerberos_auth = HTTPKerberosAuth(mutual_authentication=REQUIRED, sanitize_mutual_error_response=False)

    try:
        # Sending the kerberos ticket along with the request
        response = requests.get(
            f"https://errata.devel.redhat.com/api/v1/cdn_repo_package_tags?page[number]=1&filter[package_name]={brew_name}&filter[variant_name]={variant_name}",
            auth=kerberos_auth)

        if response.status_code == 401:
            print("ERROR: Authentication failure. Enter kerberos password for ticket")

        json_file = response.json()
        return json_file['data'][0]['relationships']['cdn_repo']['name']
    except Exception as e:
        print(f"Error: {e}")
        return "Couldn't find CDN repo name."


def cdn_to_comet(cdn_name):
    # Kerberos authentication
    kerberos_auth = HTTPKerberosAuth(mutual_authentication=REQUIRED, sanitize_mutual_error_response=False)

    try:
        # Sending the kerberos ticket along with the request
        response = requests.get(f"https://errata.devel.redhat.com/api/v1/cdn_repos/{cdn_name}",
                                auth=kerberos_auth)

        if response.status_code == 401:
            print("ERROR: Authentication failure. Kerberos ticket")

        return response.json()['data']['attributes']['external_name']
    except Exception as e:
        print(f"Error: {e}")
        return "Couldn't find delivery repo name."


def check_distgit_availability(distgit_repo_name):
    response = requests.get(f"https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}")

    return response.status_code == 200


def pipeline_from_distgit(so, distgit_repo_name, version):
    """
    List the Brew package name, CDN repo name and CDN repo details by getting the distgit name as input.

    :so: SlackOuput object for reporting results.
    :distgit_repo_name: Name of the distgit repo we get as input
    :version: OS version
    """

    if not version:
        version = "4.11"  # Default version set to 4.11, if unspecified

    payload = ""
    if check_distgit_availability(distgit_repo_name): # Check if the given distgit repo actually exists
        payload += f"Distgit Repo: <https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

        brew_package_name = distgit_to_brew(distgit_repo_name, version)
        cdn_repo_name = brew_to_cdn(brew_package_name, "8Base-RHOSE-4.10")  # Default variant set to 8Base-RHOSE-4.10"
        cdn_repo_id = cdn_to_comet(cdn_repo_name)

        payload += f"Brew package: *{brew_package_name}*\n"
        payload += f"CDN repo: *{cdn_repo_name}*\n"
        payload += f"Delivery (Comet) repo: *{cdn_repo_id}*\n"

    else:
        # If incorrect distgit name provided, no need to proceed.
        payload += f"No distgit repo with name *{distgit_repo_name}* exists."

    so.say(payload)
