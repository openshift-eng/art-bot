import asyncio
import json
import os
import re
import logging
from string import Template
from collections.abc import Iterable

import requests

import artbotlib.exectools
from artbotlib import util, pipeline_image_util
from artbotlib.exceptions import NullDataReturned
from artbotlib.constants import BREW_TASK_STATES, BREW_URL, GITHUB_API_OPENSHIFT, ART_DASH_SERVER_ROUTE

RELEASESTREAM_ENDPOINT_TEMPLATE = Template('https://${arch}.ocp.releases.ci.openshift.org/api/v1/releasestream')
VALID_ARCHES = [
    'amd64',
    'arm64',
    's390x',
    'ppc64le'
]


class PrInfo:
    def __init__(self, so, repo_name, pr_id, version, arch, component):
        self.logger = logging.getLogger(__class__.__name__)
        self.so = so
        self.repo_name = repo_name
        self.pr_id = pr_id
        self.pr_url = f'https://github.com/openshift/{repo_name}/pull/{pr_id}'

        self.version = version
        self.arch = arch if arch else 'amd64'
        self.component = component

        self.merge_commit = None
        self.distgit = None
        self.imagestream_tag = None
        self.commits = None

    def get_distgit(self):
        try:
            mappings = pipeline_image_util.github_distgit_mappings(self.version)
        except NullDataReturned as e:
            self.logger.warning('Exception raised while getting github/distgit mappings: %s', e)
            self.so.say(f'Could not retrieve distgit name for {self.repo_name}')
            util.please_notify_art_team_of_error(self.so, e)
            return None

        repo_mappings = mappings[self.repo_name]
        if not repo_mappings:
            self.logger.warning(f'No distgit mapping for repo {self.repo_name}')
            self.so.say(f'Unable to find the distgit repo associated with `{self.repo_name}`: '
                        f'please check the query and try again')
            return None

        # Multiple components build from the same upstream
        if len(repo_mappings) > 1:
            # The user must explicitly provide the component name
            if not self.component:
                self.so.say(f'Multiple components build from `{self.repo_name}`: '
                            f'please specify the one you\'re interested in and try again')
                return None

            # Does the component exist?
            if self.component not in repo_mappings:
                self.so.say(f'No distgit named `{self.component}` has been found: '
                            f'please check the query and try again')
                return None
            return self.component

        # No ambiguity: return the one and only mapped distgit
        return repo_mappings[0]

    def get_imagestream_tag(self):
        """
        Return the component image name in the payload
        """

        imagestream_tag = pipeline_image_util.get_image_stream_tag(self.distgit, self.version)
        if not imagestream_tag:
            self.logger.warning('Image for %s is not part of the payload', self.repo_name)
        return imagestream_tag

    def get_nightlies(self) -> list:
        """
        Fetch stable {major}.{minor} nightlies from RC and return a list where each element is a dict as such:
        {
            'name': ''4.11.0-0.nightly-2022-10-06-202307'',
            'phase': 'Accepted',
            'pullSpec': 'registry.ci.openshift.org/ocp/release:4.11.0-0.nightly-2022-10-06-202307',
            'downloadURL': 'https://openshift-release-artifacts.apps.ci.l2s4.p1.openshiftapps.com/
                            4.11.0-0.nightly-2022-10-06-202307'
        }

        The nightlies will be ordered from the most recent one to the oldest one
        """

        major, minor = self.version.split('.')
        releasestream_endpoint = RELEASESTREAM_ENDPOINT_TEMPLATE.substitute(arch=self.arch)
        if self.arch == 'amd64':
            nightly_endpoint = f'{releasestream_endpoint}/{major}.{minor}.0-0.nightly/tags'
        else:
            nightly_endpoint = f'{releasestream_endpoint}/{major}.{minor}.0-0.nightly-{self.arch}/tags'

        response = requests.get(nightly_endpoint)
        if response.status_code != 200:
            self.so.say(f'{major}.{minor} nightlies not available on RC')
            return []

        data = response.json()
        return data['tags']

    def get_releases(self) -> Iterable:
        """
        Fetch stable {major}.{minor} versions from RC;
        return an iterable object where each element is a dict as such:

        {
            'name': '4.11.8',
            'phase': 'Accepted',
            'pullSpec': 'quay.io/openshift-release-dev/ocp-release:4.11.8-x86_64',
            'downloadURL': 'https://openshift-release-artifacts.apps.ci.l2s4.p1.openshiftapps.com/4.11.8'
        }

        The versions will be ordered from the most recent one to the oldest one
        """

        major, minor = self.version.split('.')
        releasestream_endpoint = RELEASESTREAM_ENDPOINT_TEMPLATE.substitute(arch=self.arch)
        if self.arch == 'amd64':
            release_endpoint = f'{releasestream_endpoint}/{major}-stable/tags'
        else:
            release_endpoint = f'{releasestream_endpoint}/{major}-stable-{self.arch}/tags'

        response = requests.get(release_endpoint)
        if response.status_code != 200:
            self.so.say(f'OCP{major} not available on RC')
            return []

        data = response.json()
        pattern = re.compile(rf'{major}\.{minor}\.[0-9]+.+$')
        return filter(lambda x: re.match(pattern, x['name']), data['tags'])

    def get_branches(self) -> list:
        """
        Return a list of branch objects. Every branch is represented as dict like this one:
        {
            'name': 'release-4.8',
            'commit': {
                'sha': '53ebaa2b7cedbfaed56fde499e4326e313517080',
                'url': 'https://api.github.com/repos/openshift/metallb/commits/53ebaa2b7cedbfaed56fde499e4326e313517080'
            },
            'protected': True
        }
        """

        url = f'{GITHUB_API_OPENSHIFT}/{self.repo_name}/branches'
        response = requests.get(url)
        if response.status_code != 200:
            msg = f'Request to {url} returned with status code {response.status_code}'
            self.logger.warning(msg)
            raise RuntimeError(msg)
        return response.json()

    def get_branch_ref(self) -> str:
        """
        Return the SHA of release-{MAJOR}.{MINOR} HEAD
        """

        branches = self.get_branches()
        for data in branches:
            if data['name'] == f"release-{self.version}":
                return data['commit']['sha']

    def get_commit_time(self, commit) -> str:
        """
        Return the timestamp associated with a commit: e.g. "2022-10-21T19:48:29Z"
        """

        response = requests.get(f"{GITHUB_API_OPENSHIFT}/{self.repo_name}/commits/{commit}")
        return response.json()['commit']['committer']['date']

    def get_commits_after(self, commit) -> list:
        """
        Return commits in a repo from the given time (includes the current commit).
        """

        branch_ref = self.get_branch_ref()
        datetime = self.get_commit_time(commit)
        response = requests.get(
            f"{GITHUB_API_OPENSHIFT}/{self.repo_name}/commits?sha={branch_ref}&since={datetime}")

        result = []
        for data in response.json():
            result.append(data['sha'])
        return result[::-1]

    def pr_merge_commit(self):
        """
        Return the merge commit SHA associated with a PR
        """

        response = requests.get(f"{GITHUB_API_OPENSHIFT}/{self.repo_name}/pulls/{self.pr_id}")
        sha = response.json().get("merge_commit_sha")
        self.logger.debug('Found merge commit SHA: %s', sha)
        return sha

    def get_builds_from_db(self, commit, task_state):
        """
        Function to find the build using commit, from API, which queries the database.
        """
        params = {
            "group": f"openshift-{self.version}",
            "label_io_openshift_build_commit_id": commit,
            "brew_task_state": task_state
        }
        api = f"{os.environ['ART_DASH_SERVER_ROUTE']}/api/v1"
        url = f"{api}/builds/"
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json()

    def build_from_commit(self, task_state):
        """
        Function to get all the build ids associated with a list of commits
        """
        for commit in self.commits:
            response_data = self.get_builds_from_db(commit, task_state)
            if response_data and response_data["count"] > 0:
                builds = response_data["results"]
                build_ids = [x["build_0_id"] for x in builds]
                return sorted(build_ids)

    def find_builds(self):
        """
        Find successful or failed builds for the PR/merge commit. If none, report back to the user that the build
        hasn't started yet.
        """
        successful_builds = self.build_from_commit(BREW_TASK_STATES["Success"])
        if successful_builds:
            self.logger.info("Found successful builds for given PR")
            first_success = successful_builds[0]
            self.so.say(
                f"First successful build: <{BREW_URL}/buildinfo?buildID={first_success}|{first_success}>. All consecutive builds will include this PR.")
            return

        self.logger.info("No successful builds found given PR")
        failed_builds = self.build_from_commit(BREW_TASK_STATES["Failure"])
        if failed_builds:
            first_failure = failed_builds[0]
            self.logger.info(f"First failed build: {first_failure}")
            self.so.say(
                f"No successful build found. First failed build: <{BREW_URL}/buildinfo?buildID={first_failure}|{first_failure}>")
            return

        self.logger.info("No builds have run yet.")
        self.so.say("No builds have started yet for the PR. Check again later.")

    async def check_nightly_or_releases(self, releases: Iterable) -> str:
        """
        Check if the PR has made it into a nightly or release.
        Report the earliest one that has it, or if there are none
        """

        self.logger.info(f'Searching for {self.pr_url} into nightlies/releases...')

        earliest = None
        for release in releases:
            if release['phase'] == 'Failed':
                continue

            cmd = f'oc adm release info {release["pullSpec"]} --image-for {self.imagestream_tag}'
            _, stdout, _ = await artbotlib.exectools.cmd_gather_async(cmd)

            cmd = f'oc image info -o json {stdout}'
            _, stdout, _ = await artbotlib.exectools.cmd_gather_async(cmd)
            labels = json.loads(stdout)['config']['config']['Labels']
            commit_id = labels['io.openshift.build.commit.id']

            if commit_id in self.commits:
                self.logger.info(f'PR {self.pr_url} has been included in release {release["name"]}')
                earliest = release
            else:
                self.logger.info(f'PR {self.pr_url} has NOT been included in release {release["name"]}')
                break

        return earliest

    async def run(self):
        # Check arch
        if self.arch not in VALID_ARCHES:
            self.so.say(f'`{self.arch}` is not a valid architecture: '
                        f'please select one in one in {VALID_ARCHES} and try again')
            return
        self.logger.info('Using arch %s', self.arch)

        # Check distgit
        self.distgit = self.get_distgit()
        self.logger.info('Found distgit: %s', self.distgit)
        if not self.distgit:
            # Reason has already been told to the user...
            return

        msg = 'Gathering PR info...'
        self.so.say(msg)
        self.logger.info(msg)

        # Get merge commit associated to the PPR
        self.merge_commit = self.pr_merge_commit()
        # Get the commits that we need to check
        self.commits = self.get_commits_after(self.merge_commit)
        self.logger.debug(f'Found commits after {self.merge_commit}: {self.commits}')

        # Check if a build is associated for the merge commit
        self.find_builds()

        # Check into nightlies and releases
        self.imagestream_tag = self.get_imagestream_tag()
        if self.imagestream_tag:
            tasks = [
                asyncio.ensure_future(self.check_nightly_or_releases(self.get_nightlies())),
                asyncio.ensure_future(self.check_nightly_or_releases(self.get_releases()))
            ]
            try:
                earliest_nightly, earliest_release = await asyncio.gather(*tasks, return_exceptions=False)
            except Exception as e:
                self.so.say(f'Sorry, an error was raised during the handling of the request: {e}'
                            f'Please try again')
                return

            if earliest_nightly:
                self.so.say(f'<{self.pr_url}|PR> has been included starting from '
                            f'<{earliest_nightly["downloadURL"]}|{earliest_nightly["name"]}>')
            else:
                self.so.say(f'<{self.pr_url}|PR> has not been found in any `{self.version}` nightly')

            if earliest_release:
                self.so.say(f'<{self.pr_url}|PR> has been included starting from '
                            f'<{earliest_release["downloadURL"]}|{earliest_release["name"]}>')
            else:
                self.so.say(f'<{self.pr_url}|PR> has not been found in any `{self.version}` release')

        else:
            self.so.say(f'Couldn\'t get image stream tag for `{self.repo_name}` in `{self.version}`: '
                        f'will not look into nightlies nor releases...')


def pr_info(so, repo, pr_id, major, minor, arch, component):
    asyncio.new_event_loop().run_until_complete(PrInfo(so, repo, pr_id, f'{major}.{minor}', arch, component).run())
