import asyncio
import json
import logging
import os
import re
from collections.abc import Iterable

import requests
import yaml
from artcommonlib.konflux.konflux_build_record import KonfluxBuildRecord
from artcommonlib.konflux.konflux_db import KonfluxDb

import artbotlib.exectools
from artbotlib import pipeline_image_util, util
from artbotlib.constants import ART_BUILD_HISTORY_URL, RELEASE_CONTROLLER_STREAM_PATH, RELEASE_CONTROLLER_URL, GITHUB_API_REPO_URL
from artbotlib.exceptions import NullDataReturned


class PrInfo:
    def __init__(self, so, org, repo_name, pr_id, version, arch, component):
        self.logger = logging.getLogger(__class__.__name__)
        self.so = so
        self.org = org
        self.repo_name = repo_name
        self.pr_id = pr_id
        self.pr_url = f'https://github.com/{org}/{repo_name}/pull/{pr_id}'

        self.version = version
        self.arch = arch if arch else 'amd64'
        self.component = component
        self.valid_arches = artbotlib.constants.RC_ARCH_TO_RHCOS_ARCH.keys()
        self.releasestream_api_endpoint = \
            f'{RELEASE_CONTROLLER_URL.substitute(arch=self.arch)}/api/v1/releasestream'

        self.merge_commit = None
        self.distgit = None
        self.imagestream_tag = None
        self.commits = None
        self.header = {"Authorization": f"token {os.environ['GITHUB_PERSONAL_ACCESS_TOKEN']}"}

    def get_distgit(self):
        try:
            mappings = pipeline_image_util.github_distgit_mappings(self.version)
        except NullDataReturned as e:
            self.logger.warning('Exception raised while getting github/distgit mappings: %s', e)
            self.so.say(f'Could not retrieve distgit name for {self.org}/{self.repo_name}')
            util.please_notify_art_team_of_error(self.so, e)
            return None

        repo_with_org = f'{self.org}/{self.repo_name}'
        repo_mappings = mappings.get(repo_with_org, None)
        if not repo_mappings:
            self.logger.warning(f'No distgit mapping for repo {repo_with_org}')
            self.so.say(f'Unable to find the distgit repo associated with `{repo_with_org}`: '
                        f'please check the query and try again')
            return None

        # Multiple components build from the same upstream
        if len(repo_mappings) > 1:
            # The user must explicitly provide the component name
            if not self.component:
                self.logger.warning('Multiple components build from %s: one must be specified', repo_with_org)
                self.so.say(f'Multiple components build from `{repo_with_org}`: '
                            f'please specify the one you\'re interested in and try again')
                return None

            # Does the component exist?
            if self.component not in repo_mappings:
                self.logger.warning('No distgit "%s" found', self.component)
                self.so.say(f'No distgit named `{self.component}` has been found: '
                            f'please check the query and try again')
                return None
            return self.component

        # No ambiguity: return the one and only mapped distgit
        mapping = repo_mappings[0]
        self.logger.info('Found mapped distgit %s', mapping)
        return mapping

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

        self.logger.info('Fetching nightlies for %s', self.version)
        major, minor = self.version.split('.')

        if self.arch == 'amd64':
            nightly_endpoint = f'{self.releasestream_api_endpoint}/{major}.{minor}.0-0.nightly/tags'
        else:
            nightly_endpoint = f'{self.releasestream_api_endpoint}/{major}.{minor}.0-0.nightly-{self.arch}/tags'

        self.logger.info('Fetching endpoint %s', nightly_endpoint)
        response = requests.get(nightly_endpoint)
        if response.status_code != 200:
            msg = f'{major}.{minor} nightlies not available on RC'
            self.logger.warning(msg)
            self.so.say(msg)
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

        self.logger.info('Fetching releases for %s', self.version)
        major, minor = self.version.split('.')

        if self.arch == 'amd64':
            release_endpoint = f'{self.releasestream_api_endpoint}/{major}-stable/tags'
        else:
            release_endpoint = f'{self.releasestream_api_endpoint}/{major}-stable-{self.arch}/tags'

        self.logger.info('Fetching endpoint %s', release_endpoint)
        response = requests.get(release_endpoint)
        if response.status_code != 200:
            msg = f'OCP{major} not available on RC'
            self.logger.warning(msg)
            self.so.say(msg)
            return []

        data = response.json()
        pattern = re.compile(rf'{major}\.{minor}\.[0-9]+.*$')
        return filter(lambda x: re.match(pattern, x['name']), data['tags'])

    def get_commit_time(self, commit) -> str:
        """
        Return the timestamp associated with a commit: e.g. "2022-10-21T19:48:29Z"
        """

        url = f"{GITHUB_API_REPO_URL}/{self.org}/{self.repo_name}/commits/{commit}"
        self.logger.info('Fetching url %s', url)

        response = requests.get(url, headers=self.header)
        if response.status_code != 200:
            msg = f'Request to {url} returned with status code {response.status_code}'
            self.logger.error(msg)
            raise RuntimeError(msg)

        json_data = response.json()
        try:
            commit_time = json_data['commit']['committer']['date']
            return commit_time
        except KeyError:
            self.logger.error('Could not find commit time in json data: %s', json_data)
            raise

    def get_commits_after(self, commit, branch) -> list:
        """
        Return commits in a repo from the given time (includes the current commit).
        """

        datetime = self.get_commit_time(commit)
        url = f"{GITHUB_API_REPO_URL}/{self.org}/{self.repo_name}/commits?sha={branch}&since={datetime}"

        commits = util.github_api_all(url)

        result = []
        for data in commits:
            result.append(data['sha'])
        return result[::-1]

    def pr_merge_commit(self):
        """
        Return the merge commit SHA associated with a PR
        """

        url = f"{GITHUB_API_REPO_URL}/{self.org}/{self.repo_name}/pulls/{self.pr_id}"
        self.logger.info('Fetching url %s', url)

        response = requests.get(url, headers=self.header)
        if response.status_code != 200:
            msg = f'Request to {url} returned with status code {response.status_code}'
            self.logger.error(msg)
            raise RuntimeError(msg)

        json_data = response.json()
        try:
            sha = json_data["merge_commit_sha"]
            self.logger.info('Found merge commit SHA: %s', sha)
            branch = json_data["base"]["ref"]
            self.logger.info('Merge request branch: %s', branch)
            return sha, branch
        except KeyError:
            self.logger.error('Commit SHA not found in json data: %s', json_data)
            raise

    async def get_builds_from_db(self, commit, task_state):
        """
        Function to find builds from Konflux BigQuery DB using commit.
        Returns a list of KonfluxBuildRecord objects.
        """
        konflux_db = KonfluxDb()
        konflux_db.bind(KonfluxBuildRecord)

        builds = [build async for build in konflux_db.search_builds_by_fields(
            where={
                "group": f"openshift-{self.version}",
                "commitish": commit,
                "outcome": task_state
            },
        )]
        return builds

    def is_image_for_release(self, image_name):
        """
        Exclude images that are not in payloads
        """
        url = f'https://raw.githubusercontent.com/openshift-eng/ocp-build-data/openshift-{self.version}/images/{image_name}.yml'
        response = requests.get(url)
        if response.status_code == 200:
            yaml_content = yaml.safe_load(response.text)
            # Check key value for for_relaese
            return yaml_content.get('for_release', True)
        else:
            self.logger.info(f'response.status_code = {response.status_code}')

    async def build_from_commit(self, task_state):
        """
        Function to get all the build ids associated with a list of commits
        """

        for commit in self.commits:
            builds = await self.get_builds_from_db(commit, task_state)

            if builds:
                self.logger.info('Found %s builds from commit %s', len(builds), commit)
                build_for_image = {}
                for build in builds:
                    if self.is_image_for_release(build.name) and (build.name not in build_for_image or build.start_time < build_for_image[build.name].start_time):
                        build_for_image[build.name] = build

                return build_for_image.values()

            self.logger.info('Found no builds from commit %s', commit)

    async def find_builds(self):
        """
        Find successful or failed builds for the PR/merge commit. If none, report back to the user that the build
        hasn't started yet.
        """

        successful_builds = await self.build_from_commit("success")
        if successful_builds:
            self.logger.info(f'*** successful_builds: {successful_builds} ***')
            self.logger.info("Found successful builds for given PR")
            for build in successful_builds:
                self.so.say(f"First successful build: <{ART_BUILD_HISTORY_URL}/?nvr={build.nvr}|{build.nvr}>. All consecutive builds will include  this PR.")
            return

        self.logger.info("No successful builds found given PR")
        failed_builds = await self.build_from_commit("failure")
        if failed_builds:
            for build in failed_builds:
                self.logger.info(f"First failed build: {build}")
                self.so.say(f"No successful build found. First failed build: <{ART_BUILD_HISTORY_URL}/?nvr={build.nvr}|{build.nvr}>")
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
            if release['phase'] in ('Failed', 'Pending'):
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
        if self.arch not in self.valid_arches:
            self.logger.warning('Arch %s is not valid', self.arch)
            self.so.say(f'`{self.arch}` is not a valid architecture: '
                        f'please select one in one in {self.valid_arches} and try again')
            return

        self.logger.info('Using arch %s', self.arch)

        # Check distgit
        self.distgit = self.get_distgit()
        self.logger.info('Found distgit: %s', self.distgit)
        if not self.distgit:
            # Reason has already been told to the user...
            self.logger.warning('No distgit found')
            return

        msg = 'Gathering PR info...'
        self.so.say(msg)
        self.logger.info(msg)

        # Get merge commit and branch associated with the PPR
        self.merge_commit, self.branch = self.pr_merge_commit()

        # Handle closed PRs
        if self.merge_commit is None:
            self.logger.debug("PR has been closed without being merged")
            self.so.say(f"{self.branch} branch does not include this PR")
            return

        # Get the commits that we need to check
        # Handle master == main
        try:
            self.commits = self.get_commits_after(self.merge_commit, self.branch)
        except Exception as e:
            if self.branch == 'master':
                self.logger.debug('Could not find commits after %s in master branch: trying main branch', self.merge_commit)
                self.commits = self.get_commits_after(self.merge_commit, 'main')
            else:
                raise e

        if self.merge_commit not in self.commits:
            self.logger.debug("This branch doesn't have this PR merge commit")
            self.so.say(f"{self.branch} branch does not include this PR")
            return
        self.logger.debug(f'Found commits after {self.merge_commit}: {self.commits}')

        # Check if a build is associated for the merge commit
        await self.find_builds()

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
                self.logger.error('Raised exception: %s', e)
                self.so.say(f'Sorry, an error was raised during the handling of the request: {e}'
                            f'Please try again')
                return

            if earliest_nightly:
                self.so.say(f'<{self.pr_url}|PR> has been included starting from '
                            f'<{RELEASE_CONTROLLER_URL.substitute(arch=self.arch) + RELEASE_CONTROLLER_STREAM_PATH.substitute(type=f"{self.version}.0-0.nightly", name=earliest_nightly["name"])}|{earliest_nightly["name"]}>')
            else:
                self.so.say(f'<{self.pr_url}|PR> has not been found in any `{self.version}` nightly')

            if earliest_release:
                self.so.say(f'<{self.pr_url}|PR> has been included starting from '
                            f'<{RELEASE_CONTROLLER_URL.substitute(arch=self.arch) + RELEASE_CONTROLLER_STREAM_PATH.substitute(type=f"{self.version[0]}-stable", name=earliest_release["name"])}|{earliest_release["name"]}>')
            else:
                self.so.say(f'<{self.pr_url}|PR> has not been found in any `{self.version}` release')

        else:
            self.so.say(f'Couldn\'t get image stream tag for `{self.repo_name}` in `{self.version}`: '
                        f'will not look into nightlies nor releases...')


def pr_info(so, org, repo, pr_id, major, minor, arch, component):
    asyncio.new_event_loop().run_until_complete(PrInfo(so, org, repo, pr_id, f'{major}.{minor}', arch, component).run())
