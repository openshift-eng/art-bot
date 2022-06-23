from artbotlib import exceptions
from artbotlib import pipeline_image_util


# Driver functions
def pipeline_from_github(so, github_repo, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the GitHub repo name as input.

    GitHub -> Distgit -> Brew -> CDN -> Delivery

    :so: SlackOutput object for reporting results.
    :github_repo: Name of the GitHub repo we get as input
    :version: OCP version
    """
    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified
    variant = f"8Base-RHOSE-{version}"

    payload = ""

    if not pipeline_image_util.github_repo_is_available(github_repo):  # Check if the given GitHub repo actually exists
        # If incorrect GitHub name provided, no need to proceed.
        payload += f"No GitHub repo with name *{github_repo}* exists."
        so.say(payload)
        return
    else:
        so.say("Fetching data. Please wait...")

        # GitHub
        payload += f"Upstream GitHub repository: <https://github.com/openshift/{github_repo}|*openshift/{github_repo}*>\n"
        payload += f"Private GitHub repository: <https://github.com/openshift-priv/{github_repo}|*openshift-priv/{github_repo}*>\n"
        try:
            # GitHub -> Distgit
            distgit_repos = pipeline_image_util.github_to_distgit(github_repo, version)
            if len(distgit_repos) > 1:
                payload += f"\n*More than one dist-gits were found for the GitHub repo `{github_repo}`*\n\n"
            for distgit_repo_name in distgit_repos:
                payload += f"Production dist-git repo: <https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

                # Distgit -> Delivery
                payload += pipeline_image_util.distgit_to_delivery(distgit_repo_name, version, variant)

                payload += "\n"
        except exceptions.ArtBotExceptions as e:
            payload += "\n"
            payload += f"{e}"
            so.say(payload)
            so.monitoring_say(f"ERROR: {e}")
            return
        except exceptions.InternalServicesExceptions as e:
            so.say(f"{e}. Contact the ART Team")
            so.monitoring_say(f"ERROR: {e}")
            return
        except exceptions.ManyDistgitsForGithub as e:
            intro = f"More than one dist-git was found for the github repo `{github_repo}`. Which one did you mean?"
            so.snippet(intro=intro, payload=e)
            so.say(f"Please retry using the command, with version optional:\n \
_what is the image pipeline for github *{github_repo}* and distgit `dist-git-name` (in version `major.minor`)_")
            return
        except Exception as e:
            so.say("Unknown error. Contact the ART team.")
            so.monitoring_say(f"ERROR: Unclassified: {e}")
            return
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

    payload = ""

    if not pipeline_image_util.distgit_is_available(
            distgit_repo_name):  # Check if the given distgit repo actually exists
        # If incorrect distgit name provided, no need to proceed.
        payload += f"No distgit repo with name *{distgit_repo_name}* exists."
        so.say(payload)
        return
    else:
        so.say("Fetching data. Please wait...")
        try:
            # Distgit -> GitHub
            github_repo = pipeline_image_util.distgit_to_github(distgit_repo_name, version)
            payload += f"Upstream GitHub repository: <https://github.com/openshift/{github_repo}|*openshift/{github_repo}*>\n"
            payload += f"Private GitHub repository: <https://github.com/openshift-priv/{github_repo}|*openshift-priv/{github_repo}*>\n"

            # Distgit
            payload += f"Production dist-git repo: <https://pkgs.devel.redhat.com/cgit/containers/{distgit_repo_name}|*{distgit_repo_name}*>\n"

            # Distgit -> Delivery
            payload += pipeline_image_util.distgit_to_delivery(distgit_repo_name, version, variant)
        except exceptions.ArtBotExceptions as e:
            payload += "\n"
            payload += f"{e}"
            so.say(payload)
            so.monitoring_say(f"ERROR: {e}")
            return
        except exceptions.InternalServicesExceptions as e:
            so.say(f"{e}. Contact the ART Team")
            so.monitoring_say(f"ERROR: {e}")
            return
        except Exception as e:
            so.say("Unknown error. Contact the ART team.")
            so.monitoring_say(f"ERROR: Unclassified: {e}")
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

    payload = ""

    if not pipeline_image_util.brew_is_available(brew_name):  # Check if the given brew repo actually exists
        # If incorrect brew name provided, no need to proceed.
        payload += f"No brew repo with name *{brew_name}* exists."
        so.say(payload)
        return
    else:
        so.say("Fetching data. Please wait...")
        try:
            # Brew -> GitHub
            payload += pipeline_image_util.brew_to_github(brew_name, version)

            # Brew
            brew_id = pipeline_image_util.get_brew_id(brew_name)
            payload += f"Production brew builds: <https://brewweb.engineering.redhat.com/brew/packageinfo?packageID={brew_id}|*{brew_name}*>\n"

            # Brew -> Delivery
            payload += pipeline_image_util.brew_to_delivery(brew_name, variant)

        except exceptions.ArtBotExceptions as e:
            payload += "\n"
            payload += f"{e}"
            so.say(payload)
            so.monitoring_say(f"ERROR: {e}")
            return
        except exceptions.InternalServicesExceptions as e:
            so.say(f"{e}. Contact the ART Team")
            so.monitoring_say(f"ERROR: {e}")
            return
        except Exception as e:
            so.say("Unknown error. Contact the ART team.")
            so.monitoring_say(f"ERROR: Unclassified: {e}")
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

    payload = ""

    if not pipeline_image_util.cdn_is_available(cdn_repo_name):  # Check if the given brew repo actually exists
        # If incorrect brew name provided, no need to proceed.
        payload += f"No CDN repo with name *{cdn_repo_name}* exists."
        so.say(payload)
        return
    else:
        so.say("Fetching data. Please wait...")
        try:
            # CDN -> GitHub
            payload += pipeline_image_util.cdn_to_github(cdn_repo_name, version)

            # CDN
            payload += pipeline_image_util.get_cdn_payload(cdn_repo_name, variant)

            # CDN -> Delivery
            payload += pipeline_image_util.cdn_to_delivery_payload(cdn_repo_name)
        except exceptions.ArtBotExceptions as e:
            payload += "\n"
            payload += f"{e}"
            so.say(payload)
            so.monitoring_say(f"ERROR: {e}")
            return
        except exceptions.InternalServicesExceptions as e:
            so.say(f"{e}. Contact the ART Team")
            so.monitoring_say(f"ERROR: {e}")
            return
        except Exception as e:
            so.say("Unknown error. Contact the ART team.")
            so.monitoring_say(f"ERROR: Unclassified: {e}")
    so.say(payload)


def pipeline_from_delivery(so, delivery_repo_name, version):
    """
    Function to list the GitHub repo, Brew package name, CDN repo name and delivery repo by getting the delivery repo name as input.

    GitHub <- Distgit <- Brew <- CDN <- Delivery

    :so: SlackOutput object for reporting results.
    :delivery_repo_name: Name of the delivery repo we get as input
    :version: OCP version
    """
    if not version:
        version = "4.10"  # Default version set to 4.10, if unspecified
    variant = f"8Base-RHOSE-{version}"

    payload = ""

    if not pipeline_image_util.delivery_repo_is_available(delivery_repo_name):  # Check if the given delivery repo actually exists
        # If incorrect delivery repo name provided, no need to proceed.
        payload += f"No delivery repo with name *{delivery_repo_name}* exists."
        so.say(payload)
        return
    else:
        so.say("Fetching data. Please wait...")
        try:
            # Brew
            brew_name = pipeline_image_util.brew_from_delivery(delivery_repo_name)
            brew_id = pipeline_image_util.get_brew_id(brew_name)

            # Brew -> GitHub
            payload += pipeline_image_util.brew_to_github(brew_name, version)

            # To make the output consistent
            payload += f"Production brew builds: <https://brewweb.engineering.redhat.com/brew/packageinfo?packageID={brew_id}|*{brew_name}*>\n"

            # Brew -> CDN
            cdn_repo_name = pipeline_image_util.brew_to_cdn_delivery(brew_name, variant, delivery_repo_name)
            payload += pipeline_image_util.get_cdn_payload(cdn_repo_name, variant)

            # Delivery
            delivery_repo_id = pipeline_image_util.get_delivery_repo_id(delivery_repo_name)
            payload += f"Delivery (Comet) repo: <https://comet.engineering.redhat.com/containers/repositories/{delivery_repo_id}|*{delivery_repo_name}*>\n\n"
        except exceptions.ArtBotExceptions as e:
            payload += "\n"
            payload += f"{e}"
            so.say(payload)
            so.monitoring_say(f"ERROR: {e}")
            return
        except exceptions.InternalServicesExceptions as e:
            so.say(f"{e}. Contact the ART Team")
            so.monitoring_say(f"ERROR: {e}")
            return
        except Exception as e:
            so.say("Unknown error. Contact the ART team.")
            so.monitoring_say(f"ERROR: Unclassified: {e}")
    so.say(payload)
