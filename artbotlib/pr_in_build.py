import os

import requests

API = f"{os.environ['ART_DASH_SERVER_ROUTE']}/api/v1"


def pr_merge_commit(repo, pr):
    response = requests.get(f"https://api.github.com/repos/openshift/{repo}/pulls/{pr}")
    return response.json().get("merge_commit_sha")


def get_branches(repo):
    response = requests.get(f"https://api.github.com/repos/openshift/{repo}/branches")
    return response.json()


def get_branch_ref(repo, version):
    branches = get_branches(repo)
    for data in branches:
        if data['name'] == f"release-{version}":
            return data['commit']['sha']


def get_commit_time(repo, commit):
    response = requests.get(f"https://api.github.com/repos/openshift/{repo}/commits/{commit}")
    return response.json()['commit']['committer']['date']


def get_commits_after(repo, commit, version):
    """
    Function to return commits in a repo from the given time (includes the current commit).
    """
    branch_ref = get_branch_ref(repo, version)
    datetime = get_commit_time(repo, commit)
    response = requests.get(
        f"https://api.github.com/repos/openshift/{repo}/commits?sha={branch_ref}&since={datetime}")

    result = []
    for data in response.json():
        result.append(data['sha'])
    return result[::-1]


def commit_in_build(version, commit, task_state):
    params = {
        'group': f"openshift-{version}",
        'label_io_openshift_build_commit_id': commit,
        'brew_task_state': f'{task_state}'
    }
    url = f"{API}/builds/"
    response = requests.get(url, params=params)
    return response.json()


def pr_in_build(repo, version, commit):
    """
    Function to get all the build ids associated with a list of commits
    :param repo: Name of the Openshift repository eg: hypershift
    :param version: Openshift version eg: 4.10
    :param commit: The commit sha
    """
    commits_after = get_commits_after(repo, commit, version)
    for commit in commits_after:
        response = commit_in_build(version, commit, 'success')
        if response['count'] > 0:
            builds = response['results']
            build_ids = [x['build_0_id'] for x in builds]
            return build_ids


def main(repo, version, commit):
    builds = pr_in_build(repo, version, commit)
    print(builds)


# if __name__ == '__main__':
#     main("hypershift", "4.10", "253febdcd032973c9741b32d36ded309a1776abc")
