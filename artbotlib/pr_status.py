import datetime
import logging
import time

import requests

from artbotlib import constants

logger = logging.getLogger(__name__)


def pr_status(so, user_id, repo, pr_id):
    so.say(f'Ok <@{user_id}>, I\'ll respond here when the PR merges')

    pr_url = f'https://github.com/openshift/{repo}/pull/{pr_id}'
    api_endpoint = f'{constants.GITHUB_API_OPENSHIFT}/{repo}/pulls/{pr_id}'

    start = time.time()
    while True:
        # Timeout after 12 hrs
        if time.time() - start > constants.ONE_WEEK:
            so.say(f'PR {pr_url} did not merge after a week.'
                   f'Giving up...')
            return

        try:
            # Fetch API for PR
            logger.info('Fetching PR info from %s', api_endpoint)

            data = requests.get(api_endpoint).json()
            pr_state = data['state']

            # Check PR state
            if pr_state == 'open':
                logger.info('PR %s is still open. Sleeping for 5 minutes...', pr_url)
                time.sleep(constants.FIVE_MINUTES)

            else:
                logger.info('PR %s has status %s', pr_url, pr_state)

                if data['merged_at']:
                    # PR was merged
                    dto = datetime.datetime.strptime(data['merged_at'], '%Y-%m-%dT%H:%M:%SZ')
                    so.say(f'PR {pr_url} was merged at '
                           f'{datetime.datetime.strftime(dto, "%b %d, %Y at %H:%M:%S")}')
                else:
                    # PR was closed without merging
                    dto = datetime.datetime.strptime(data['closed_at'], '%Y-%m-%dT%H:%M:%SZ')
                    so.say(f'PR {pr_url} was closed unmerged at '
                           f'{datetime.datetime.strftime(dto, "%b %d, %Y at %H:%M:%S")}')

                # All done
                return

        except requests.exceptions.ConnectionError as e:
            logger.error('Error fetching data from %s:\n%s', api_endpoint, e)
            so.say('Sorry, something went wrong when fetching data for %s', pr_url)
            return

        except KeyError:
            msg = f'Error retrieving PR status from {api_endpoint}'
            logger.error(msg)
            so.say(msg)
            return
