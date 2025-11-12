import logging
import os
import gitlab

from artbotlib import variables
from artbotlib.constants import GITLAB_INSTANCE_URL, GITLAB_PROJECT_PATH
logger = logging.getLogger(__name__)


def gitlab_mr_status(so, mr_url):
    """
    Fetches and displays GitLab MR pipeline job statuses.

    This command queries the GitLab API to retrieve the downstream pipeline jobs
    for a given merge request and displays their statuses.

    Args:
        so: SlackOutput instance for sending messages
        mr_url: Full GitLab MR URL (e.g., https://gitlab.cee.redhat.com/hybrid-platforms/art/ocp-shipment-data/-/merge_requests/207)
    """

    # Extract MR ID from URL
    mr_id = mr_url.rstrip('/').split('/')[-1]

    # Check for auth token
    token = os.environ.get('GITLAB_PRIVATE_TOKEN')
    if not token:
        so.say("Error: GITLAB_PRIVATE_TOKEN environment variable is not set. Please contact the bot administrator.")
        logger.error("GITLAB_PRIVATE_TOKEN environment variable not found")
        return

    so.say(f"Fetching pipeline job statuses for MR {mr_id}...")

    variables.active_slack_objects.add(so)

    try:
        # Connect to GitLab
        gl = gitlab.Gitlab(GITLAB_INSTANCE_URL, private_token=token)
        gl.auth()

        # Get the project
        project = gl.projects.get(GITLAB_PROJECT_PATH)

        # Get the Merge Request
        mr = project.mergerequests.get(mr_id)

        # Get the pipeline from the MR
        pipeline_info = mr.pipeline
        if not pipeline_info:
            so.say(f"No pipeline found for MR {mr_id}")
            return

        pipeline_id = pipeline_info['id']
        logger.info(f"Found pipeline {pipeline_id} for MR {mr_id}")

        # Get the main pipeline
        main_pipeline = project.pipelines.get(pipeline_id)

        # Get downstream pipelines via bridges
        bridges = main_pipeline.bridges.list(all=True)

        downstream_pipelines = []
        for bridge in bridges:
            if bridge.downstream_pipeline:
                downstream_pipelines.append(bridge.downstream_pipeline)

        if not downstream_pipelines:
            so.say(f"No downstream pipelines found for MR {mr_id} (Pipeline: {pipeline_id})")
            return

        # Format and display results
        result_lines = [f"*Pipeline Job Status for MR {mr_id}* (Pipeline: {pipeline_id})"]
        result_lines.append("")

        # Loop through downstream pipelines and collect job statuses
        for ds_pipeline_info in downstream_pipelines:
            ds_id = ds_pipeline_info['id']
            result_lines.append(f"*Downstream Pipeline {ds_id}:*")

            try:
                ds_pipeline = project.pipelines.get(ds_id)
                jobs = ds_pipeline.jobs.list(all=True)

                if not jobs:
                    result_lines.append("  (No jobs found for this pipeline)")
                    result_lines.append("")
                    continue

                # Group jobs by status for better readability
                status_groups = {}
                for job in jobs:
                    status = job.status.upper()
                    if status not in status_groups:
                        status_groups[status] = []
                    status_groups[status].append((job.name, job.id))

                # Display jobs grouped by status
                for status in sorted(status_groups.keys()):
                    jobs_list = status_groups[status]
                    result_lines.append(f"  *{status}* ({len(jobs_list)} jobs):")
                    for job_name, job_id in jobs_list:
                        result_lines.append(f"    • {job_name} (ID: {job_id})")

                result_lines.append("")

            except gitlab.exceptions.GitlabError as e:
                logger.error(f"Error fetching jobs for pipeline {ds_id}: {e}")
                result_lines.append(f"  Error fetching jobs: {e}")
                result_lines.append("")

        # Send the formatted message
        so.say("\n".join(result_lines))

    except Exception as e:
        so.say(f"Error fetching GitLab MR status: {e}")
        logger.exception(f"Unexpected error in gitlab_mr_status for MR {mr_id}")

    finally:
        variables.active_slack_objects.remove(so)
