import logging

from artbotlib import exceptions, constants
from artbotlib import pipeline_image_util

logger = logging.getLogger(__name__)


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

    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified
    variant = f"8Base-RHOSE-{version}"
    logger.info('Retrieving pipeline for github repo %s with variant %s', github_repo, variant)

    if not pipeline_image_util.github_repo_is_available(github_repo):  # Check if the given GitHub repo actually exists
        # If incorrect GitHub name provided, no need to proceed.
        logger.warning('No repo named %s found, giving up', github_repo)
        payload = f"No GitHub repo with name *{github_repo}* exists. Try again.\n"
        payload += "Example format: *what is the image pipeline for github `ironic-image`*"
        so.say(payload)
        return

    so.say("Fetching data. Please wait...")

    # GitHub
    payload = f"Upstream GitHub repository: <https://github.com/openshift/{github_repo}|*openshift/{github_repo}*>\n"
    payload += f"Private GitHub repository: <https://github.com/openshift-priv/{github_repo}|*openshift-priv/{github_repo}*>\n"

    try:
        # GitHub -> Distgit
        distgit_repos = pipeline_image_util.github_to_distgit(github_repo, version)
        logger.info('Found distgit(s) for repo %s: %s', github_repo, distgit_repos)

        if len(distgit_repos) > 1:
            logger.warning('More than one dist-gits were found for the GitHub repo %s', github_repo)
            payload += f"\n*More than one dist-gits were found for the GitHub repo `{github_repo}`*\n\n"

        for distgit_repo_name in distgit_repos:
            logger.info('Found distgit repo: %s', distgit_repo_name)
            payload += f"Production dist-git repo: <{constants.CGIT_URL}/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

            # Distgit -> Delivery
            payload += pipeline_image_util.distgit_to_delivery(distgit_repo_name, version, variant)
            payload += "\n"

    except exceptions.ArtBotExceptions as e:
        payload += "\n"
        payload += f"Raised exception: {e}"
        so.monitoring_say(f"ERROR: {e}")

    except exceptions.InternalServicesExceptions as e:
        so.say(f"Raised exception {e}. Contact the ART Team")
        so.monitoring_say(f"ERROR: {e}")

    except Exception as e:
        logger.error('Unexpected error while retrieving pipeline for github repo %s: %s', github_repo, e)
        so.say("Unknown error. Contact the ART team.")
        so.monitoring_say(f"ERROR: Unclassified: {e}")

    finally:
        so.say(payload)


def pipeline_from_distgit(so, distgit_repo_name, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the distgit name as input.

    GitHub <- Distgit -> Brew -> CDN -> Delivery

    :so: SlackOutput object for reporting results.
    :distgit_repo_name: Name of the distgit repo we get as input
    :version: OCP version
    """

    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified
    variant = f"8Base-RHOSE-{version}"
    logger.info('Retrieving pipeline for distgit repo %s with variant %s', distgit_repo_name, variant)

    if not pipeline_image_util.distgit_is_available(
            distgit_repo_name):  # Check if the given distgit repo actually exists
        # If incorrect distgit name provided, no need to proceed.
        logger.warning('No distgit repo %s found', distgit_repo_name)
        payload = f"No distgit repo with name *{distgit_repo_name}* exists. Try again\n"
        payload += "Example format: *what is the image pipeline for distgit `ironic`*"
        so.say(payload)
        return

    so.say("Fetching data. Please wait...")
    payload = ''

    try:
        # Distgit -> GitHub
        github_repo = pipeline_image_util.distgit_to_github(distgit_repo_name, version)
        payload = f"Upstream GitHub repository: <https://github.com/openshift/{github_repo}|*openshift/{github_repo}*>\n"
        payload += f"Private GitHub repository: <https://github.com/openshift-priv/{github_repo}|*openshift-priv/{github_repo}*>\n"

        # Distgit
        payload += f"Production dist-git repo: <{constants.CGIT_URL}/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

        # Distgit -> Delivery
        payload += pipeline_image_util.distgit_to_delivery(distgit_repo_name, version, variant)

    except exceptions.ArtBotExceptions as e:
        payload += "\n"
        payload += f"Raised exception: {e}"
        so.monitoring_say(f"ERROR: {e}")
        return

    except exceptions.InternalServicesExceptions as e:
        so.say(f"{e}. Contact the ART Team")
        so.monitoring_say(f"ERROR: {e}")
        return

    except Exception as e:
        logger.error('Unexpected error while retrieving pipeline for distgit repo %s: %s', distgit_repo_name, e)
        so.say("Unknown error. Contact the ART team.")
        so.monitoring_say(f"ERROR: Unclassified: {e}")
        return

    finally:
        so.say(payload)


def pipeline_from_brew(so, brew_name, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the brew name as input.

    GitHub <- Distgit <- Brew -> CDN -> Delivery

    :so: SlackOutput object for reporting results.
    :brew_name: Name of the brew repo we get as input
    :version: OCP version
    """

    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified
    variant = f"8Base-RHOSE-{version}"
    logger.info('Retrieving pipeline for brew package %s with variant %s', brew_name, variant)

    if not pipeline_image_util.brew_is_available(brew_name):  # Check if the given brew repo actually exists
        # If incorrect brew name provided, no need to proceed.
        logger.warning('No brew package %s found', brew_name)
        payload = f"No brew package with name *{brew_name}* exists. Try again\n"
        payload += "Example format: *what is the image pipeline for package `ironic-container`*"
        so.say(payload)
        return

    so.say("Fetching data. Please wait...")
    payload = ''

    try:
        # Brew -> GitHub
        payload = pipeline_image_util.brew_to_github(brew_name, version)

        # Brew
        brew_id = pipeline_image_util.get_brew_id(brew_name)
        payload += f"\nProduction brew builds: <{constants.BREW_URL}/packageinfo?packageID={brew_id}|*{brew_name}*>\n"

        # Brew -> Delivery
        payload += pipeline_image_util.brew_to_delivery(brew_name, variant)

    except exceptions.ArtBotExceptions as e:
        payload += "\n"
        payload += f"Raised exception: {e}"
        so.say(payload)
        so.monitoring_say(f"ERROR: {e}")

    except exceptions.InternalServicesExceptions as e:
        so.say(f"{e}. Contact the ART Team")
        so.monitoring_say(f"ERROR: {e}")

    except Exception as e:
        logger.error('Unexpected error while retrieving pipeline for brew package %s: %s', brew_name, e)
        so.say("Unknown error. Contact the ART team.")
        so.monitoring_say(f"ERROR: Unclassified: {e}")

    finally:
        so.say(payload)


def pipeline_from_cdn(so, cdn_repo_name, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the CDN name as input.

    GitHub <- Distgit <- Brew <- CDN -> Delivery

    :so: SlackOutput object for reporting results.
    :cdn_repo_name: Name of the CDN repo we get as input
    :version: OCP version
    """

    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified
    variant = f"8Base-RHOSE-{version}"
    logger.info('Retrieving pipeline for cdn repo %s with variant %s', cdn_repo_name, variant)

    if not pipeline_image_util.cdn_is_available(cdn_repo_name):  # Check if the given brew repo actually exists
        # If incorrect brew name provided, no need to proceed.
        logger.warning('No cdn repo %s found', cdn_repo_name)
        payload = f"No CDN repo with name *{cdn_repo_name}* exists. Try again\n"
        payload += "Example format: *what is the image pipeline for cdn `redhat-openshift4-ose-ironic-rhel8`*"
        so.say(payload)
        return

    so.say("Fetching data. Please wait...")
    payload = ''

    try:
        # CDN -> GitHub
        payload += pipeline_image_util.cdn_to_github(cdn_repo_name, version)

        # CDN
        payload += pipeline_image_util.get_cdn_payload(cdn_repo_name, variant)

        # CDN -> Delivery
        payload += pipeline_image_util.cdn_to_delivery_payload(cdn_repo_name)

    except exceptions.ArtBotExceptions as e:
        payload += "\n"
        payload += f"Raised exception: {e}"
        so.say(payload)
        so.monitoring_say(f"ERROR: {e}")

    except exceptions.InternalServicesExceptions as e:
        so.say(f"{e}. Contact the ART Team")
        so.monitoring_say(f"ERROR: {e}")

    except Exception as e:
        logger.error('Unexpected error while retrieving pipeline for cdn repo %s: %s', cdn_repo_name, e)
        so.say("Unknown error. Contact the ART team.")
        so.monitoring_say(f"ERROR: Unclassified: {e}")

    finally:
        so.say(payload)


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

    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified
    variant = f"8Base-RHOSE-{version}"
    logger.info('Retrieving pipeline for delivery repo %s with variant %s', delivery_repo_name, variant)

    delivery_repo_name = f"openshift4/{delivery_repo_name}"

    if not pipeline_image_util.delivery_repo_is_available(delivery_repo_name):  # Check if the given delivery repo actually exists
        # If incorrect delivery repo name provided, no need to proceed.
        logger.warning('No delivery repo %s found', delivery_repo_name)
        payload = f"No delivery repo with name *{delivery_repo_name}* exists. Try again\n"
        payload += "Example format: *what is the image pipeline for image `openshift4/ose-ironic-rhel8`*"
        so.say(payload)
        return

    so.say("Fetching data. Please wait...")
    payload = ''

    try:
        # Brew
        brew_name = pipeline_image_util.brew_from_delivery(delivery_repo_name)
        brew_id = pipeline_image_util.get_brew_id(brew_name)

        # Brew -> GitHub
        payload += pipeline_image_util.brew_to_github(brew_name, version)

        # To make the output consistent
        payload += f"Production brew builds: <{constants.BREW_URL}/packageinfo?packageID={brew_id}|*{brew_name}*>\n"

        # Brew -> CDN
        cdn_repo_name = pipeline_image_util.brew_to_cdn_delivery(brew_name, variant, delivery_repo_name)
        payload += pipeline_image_util.get_cdn_payload(cdn_repo_name, variant)

        # Delivery
        delivery_repo_id = pipeline_image_util.get_delivery_repo_id(delivery_repo_name)
        payload += f"Delivery (Comet) repo: <{constants.COMET_URL}/{delivery_repo_id}|*{delivery_repo_name}*>\n\n"

    except exceptions.ArtBotExceptions as e:
        payload += "\n"
        payload += f"Raised exception: {e}"
        so.say(payload)
        so.monitoring_say(f"ERROR: {e}")

    except exceptions.InternalServicesExceptions as e:
        so.say(f"{e}. Contact the ART Team")
        so.monitoring_say(f"ERROR: {e}")

    except Exception as e:
        so.say("Unknown error. Contact the ART team.")
        so.monitoring_say(f"ERROR: Unclassified: {e}")

    finally:
        so.say(payload)
