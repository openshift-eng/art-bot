#!/usr/bin/env python3

"""
This module provides functionality to watch Konflux pipelineruns and notify users
when they complete. It uses the existing Konflux watcher infrastructure from art-tools.
"""

import asyncio
import logging
import os
import re
import time
from typing import Optional, Tuple

from artbotlib import variables
from artbotlib.constants import FIVE_MINUTES, TWELVE_HOURS

# Import from art-tools
from kubernetes import config
from kubernetes.client import Configuration
from doozerlib.backend.konflux_watcher import KonfluxWatcher
from doozerlib.backend.pipelinerun_utils import PipelineRunInfo

logger = logging.getLogger(__name__)


def _parse_konflux_url(url: str) -> Optional[Tuple[str, str, str]]:
    """
    Parses a Konflux pipelinerun URL and extracts the namespace, application, and pipelinerun name.

    Arg(s):
        url (str): The Konflux pipelinerun URL

    Return Value(s):
        tuple: (namespace, application, pipelinerun_name) or None if parsing fails
    """
    pattern = r"https://konflux-ui\.apps\.[\w.-]+/ns/(?P<namespace>[\w-]+)/applications/(?P<application>[\w.-]+)/pipelineruns/(?P<pipelinerun>[\w-]+)"
    match = re.match(pattern, url)

    if not match:
        logger.warning(f"Failed to parse Konflux URL: {url}")
        return None

    return match.group("namespace"), match.group("application"), match.group("pipelinerun")


def _get_kubeconfig_path() -> Optional[str]:
    """
    Get the path to the kubeconfig file from environment variables.

    Return Value(s):
        str: Path to kubeconfig file, or None to use default
    """
    # Try KONFLUX_SA_KUBECONFIG first (used by doozer for OCP builds)
    kubeconfig = os.environ.get('KONFLUX_SA_KUBECONFIG')
    if kubeconfig:
        return kubeconfig

    # Fall back to standard KUBECONFIG
    kubeconfig = os.environ.get('KUBECONFIG')
    if kubeconfig:
        return kubeconfig

    # None will use default ~/.kube/config
    return None


async def _watch_pipelinerun(namespace: str, pipelinerun_name: str) -> PipelineRunInfo:
    """
    Watch a pipelinerun until it reaches a terminal state.

    Arg(s):
        namespace (str): The Kubernetes namespace
        pipelinerun_name (str): The name of the pipelinerun

    Return Value(s):
        PipelineRunInfo: The final state of the pipelinerun

    Raises:
        Exception: If unable to connect to Kubernetes or pipelinerun not found
    """
    # Load kubeconfig
    cfg = Configuration()
    kubeconfig_path = _get_kubeconfig_path()

    try:
        config.load_kube_config(
            config_file=kubeconfig_path,
            context=None,
            persist_config=False,
            client_configuration=cfg
        )
    except Exception as e:
        logger.error(f"Failed to load kubeconfig: {e}")
        raise

    # Get shared watcher for this namespace
    watcher = await KonfluxWatcher.get_shared_watcher(
        namespace=namespace,
        cfg=cfg,
        watch_labels=None  # Watch all pipelineruns in the namespace
    )

    # Wait for pipelinerun to reach terminal state
    logger.info(f"Waiting for pipelinerun {pipelinerun_name} in namespace {namespace} to complete")
    plr_info = await watcher.wait_for_pipelinerun_termination(pipelinerun_name)

    return plr_info


def watch_konflux_pipelinerun(so, user_id: str, pipelinerun_url: str):
    """
    Polls for a Konflux pipelinerun state and notifies the user when it completes.

    Arg(s):
        so: SlackOutput object for communicating with the user
        user_id (str): The Slack user ID to notify
        pipelinerun_url (str): The full Konflux pipelinerun URL
    """
    # Parse the URL
    parsed = _parse_konflux_url(pipelinerun_url)
    if not parsed:
        so.say(f"<@{user_id}> Sorry, I couldn't parse that Konflux URL. "
               f"Expected format: https://konflux-ui.apps.*.*/ns/<namespace>/applications/<app>/pipelineruns/<name>")
        return

    namespace, application, pipelinerun_name = parsed

    # Check for kubeconfig
    kubeconfig_path = _get_kubeconfig_path()
    if not kubeconfig_path:
        so.say(f"<@{user_id}> Sorry, I don't have access to Konflux. "
               f"Please set the KONFLUX_SA_KUBECONFIG or KUBECONFIG environment variable.")
        logger.error("No kubeconfig found in environment (KONFLUX_SA_KUBECONFIG or KUBECONFIG)")
        return

    so.say(f"Ok <@{user_id}>, I'll respond here when pipelinerun `{pipelinerun_name}` completes")

    # Handle pod restarts while loop is running
    variables.active_slack_objects.add(so)

    try:
        # Create event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Watch the pipelinerun
        plr_info = loop.run_until_complete(_watch_pipelinerun(namespace, pipelinerun_name))

        # Get the status
        succeeded_condition = plr_info.find_condition("Succeeded")
        if succeeded_condition:
            status = succeeded_condition.status  # "True", "False", or "Unknown"
            reason = succeeded_condition.reason  # "Succeeded", "Failed", "Cancelled", etc.

            # Map to user-friendly status
            if status == "True":
                final_status = "succeeded"
            elif status == "False":
                final_status = f"failed ({reason})" if reason else "failed"
            else:
                final_status = f"completed with unknown status ({reason})" if reason else "completed with unknown status"
        else:
            final_status = "completed (no status available)"

        logger.info(f"Pipelinerun {pipelinerun_name} {final_status}")
        so.say(f"<@{user_id}> pipelinerun `{pipelinerun_name}` {final_status}\n{pipelinerun_url}")

    except ValueError as e:
        # PipelineRun not found
        logger.error(f"PipelineRun {pipelinerun_name} not found: {e}")
        so.say(f"<@{user_id}> Sorry, I couldn't find pipelinerun `{pipelinerun_name}` in namespace `{namespace}`. "
               f"It may have been deleted or may not exist yet.")

    except Exception as e:
        # Other errors
        logger.error(f"Error watching pipelinerun {pipelinerun_name}: {e}")
        so.say(f"<@{user_id}> Sorry, there was an error watching pipelinerun `{pipelinerun_name}`: {e}")

    finally:
        # Remove slack object
        variables.active_slack_objects.remove(so)
