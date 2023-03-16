import requests
import logging
from artbotlib import constants

logger = logging.getLogger(__name__)


def process_data(response_data: dict) -> str:
    payload = ""
    payload += f"Upstream GitHub repository: " \
               f"<{response_data.get('upstream_github_url')}|*openshift/{response_data['github_repo']}*>\n"
    payload += f"Private GitHub repository: " \
               f"<{response_data.get('private_github_url')}|*openshift-priv/{response_data['github_repo']}*>\n"

    distgits = response_data['distgit']

    for distgit in distgits:
        payload += f"Production dist-git repo: " \
                   f"<{distgit['distgit_url']}|*{distgit['distgit_repo_name']}*>\n"
        payload += f"Production brew builds: " \
                   f"<{distgit['brew']['brew_build_url']}|" \
                   f"*{distgit['brew']['brew_package_name']}*>\n"

        if distgit['brew']['bundle_component']:
            payload += f"Bundle Component: *{distgit['brew']['bundle_component']}*\n"

        if distgit['brew']['bundle_distgit']:
            payload += f"Bundle Component: *{distgit['brew']['bundle_distgit']}*\n"

        # Tag
        if distgit["brew"]["payload_tag"]:
            payload += f"Payload tag: *{distgit['brew']['payload_tag']}* \n"

        cdns = distgit['brew']['cdn']
        if len(cdns) > 1:
            payload += "\n *Found more than one Brew to CDN mappings:*\n\n"
        for cdn in cdns:
            payload += f"CDN repo: <{cdn['cdn_repo_url']}|" \
                       f"*{cdn['cdn_repo_name']}*>\n"

            payload += f"Delivery (Comet) repo: " \
                       f"<{cdn['delivery']['delivery_repo_url']}|" \
                       f"*{cdn['delivery']['delivery_repo_name']}*>\n\n"
    return payload


def handle_request(so, version, content_name, image_type):
    so.say("Fetching data, please wait...")
    if not version:
        version = "4.10"
    url = f"{constants.ART_DASH_API_ROUTE}/" \
          f"pipeline-image?starting_from={image_type}&name={content_name}&version={version}"
    logger.debug("URL to server: ", url)
    response = requests.get(url)

    if response.status_code != 200:
        logger.error(f"API Server error. Status code: {response.status_code}")
        so.say("API server error. Contact ART Team.")
        so.monitoring_say("ERROR: API server error.")
        return

    try:
        json_data = response.json()
    except Exception as e:
        logger.error(f"JSON Error: {e}")
        so.say("Error. Contact ART Team")
        so.monitoring_say(f"JSON Error: {e}")
        return

    try:
        payload = process_data(json_data["payload"])
        so.say(payload)
    except KeyError as e:
        logger.error(f"JSON Key Error: {e}")
        so.say("Error. Contact ART Team")
        so.monitoring_say(f"JSON Key Error: {e}")


# Driver functions
def pipeline_from_github(so, github_repo, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the GitHub repo name as input.

    GitHub -> Distgit -> Brew -> CDN -> Delivery

    :so: SlackOutput object for reporting results.
    :github_repo: Name of the GitHub repo we get as input. Example formats:
                                                            ironic-image
                                                            openshift/ironic-image
                                                            github.com/openshift/ironic-image
                                                            https://github.com/openshift/ironic-image.git
                                                            https://github.com/openshift/ironic-image/
                                                            https://github.com/openshift/ironic-image
    :version: OCP version
    """

    logger.info('Retrieving pipeline from github repo %s', github_repo)
    handle_request(so, version, content_name=github_repo, image_type="github")


def pipeline_from_distgit(so, distgit_repo_name, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the distgit name as input.

    GitHub <- Distgit -> Brew -> CDN -> Delivery

    :so: SlackOutput object for reporting results.
    :distgit_repo_name: Name of the distgit repo we get as input
    :version: OCP version
    """

    logger.info('Retrieving pipeline from distgit repo %s', distgit_repo_name)
    handle_request(so, version, content_name=distgit_repo_name, image_type="distgit")


def pipeline_from_brew(so, brew_name, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the brew name as input.

    GitHub <- Distgit <- Brew -> CDN -> Delivery

    :so: SlackOutput object for reporting results.
    :brew_name: Name of the brew repo we get as input
    :version: OCP version
    """

    logger.info('Retrieving pipeline from brew package %s', brew_name)
    handle_request(so, version, content_name=brew_name, image_type="package")


def pipeline_from_cdn(so, cdn_repo_name, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the CDN name as input.

    GitHub <- Distgit <- Brew <- CDN -> Delivery

    :so: SlackOutput object for reporting results.
    :cdn_repo_name: Name of the CDN repo we get as input
    :version: OCP version
    """

    logger.info('Retrieving pipeline from cdn %s', cdn_repo_name)
    handle_request(so, version, content_name=cdn_repo_name, image_type="cdn")


def pipeline_from_delivery(so, delivery_repo_name, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the delivery repo name as input.

    GitHub <- Distgit <- Brew <- CDN <- Delivery

    :so: SlackOutput object for reporting results.
    :delivery_repo_name: Name of the delivery repo we get as input. Example formats:
                                                    registry.redhat.io/openshift4/ose-ironic-rhel8
                                                    openshift4/ose-ironic-rhel8
                                                    ose-ironic-rhel8
    :version: OCP version
    """

    logger.info('Retrieving pipeline from delivery repo %s', delivery_repo_name)
    handle_request(so, version, content_name=delivery_repo_name, image_type="image")
