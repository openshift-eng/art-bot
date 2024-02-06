import os
import re

from artbotlib import brew_list, elliott, brew
from artbotlib.buildinfo import buildinfo_for_release, alert_on_build_complete
from artbotlib.pr_status import pr_status
from artbotlib.taskinfo import alert_on_task_complete
from artbotlib.constants import PROW_BASE_URL
from artbotlib.help import greet_user, show_help
from artbotlib.kernel_info import kernel_info
from artbotlib.nightly_color import nightly_color_status
from artbotlib.pipeline_image_names import pipeline_from_github, pipeline_from_distgit, pipeline_from_brew, \
    pipeline_from_cdn, pipeline_from_delivery
from artbotlib.pr_in_build import pr_info
from artbotlib.prow import prow_job_status, first_prow_job_succeeds
from artbotlib.translation import translate_names
from fuzzywuzzy import process


def recommend_command(plain_text, patterns):
    """
    Suggests a correct command format based on input command.
    - plain_text: the input command text.
    - patterns: known command patterns for comparison.
    """
    command_tokens = set(re.findall(r"[\w']+", plain_text.lower()))  # Tokenizing the input

    def evaluate_match(example):
        # Inner function to calculate match score between input and known command example
        example_tokens = set(re.findall(r"[\w']+", example.lower()))
        common_tokens = set(command_tokens) & example_tokens
        common_tokens_count = len(common_tokens)

        # Special weight scores for certain tokens
        weights = {"pr": 3, "info": 2, "watch": 5, "where": 70, "in": 70, "rpm": 30, "used": 20}

        # Calculate adjusted score considering weights
        common_token_weights = [weights.get(token, 1) for token in common_tokens]
        adjusted_score = sum(common_token_weights)

        # Calculate how closely the input matches the example using FuzzyWuzzy
        fuzziness_score = process.extractOne(plain_text, [example])[1]

        # Introduce a balance factor for the fuzziness score
        balance_factor = 0.5
        fuzziness_score *= balance_factor

        # Final score is sum of common tokens count, adjusted score, and fuzziness score
        return common_tokens_count + adjusted_score + fuzziness_score

    # Find the highest scoring pattern
    patterns = sorted(patterns, key=lambda p: evaluate_match(p["example"]), reverse=True)

    closest_match_pattern = patterns[0]
    closest_match_example = closest_match_pattern["example"]

    # Replace generic URL parts with specific parts from input, if present
    repo_match = re.search(r"https://github.com/([\w-]+)/([\w-]+)", plain_text)
    if repo_match:
        repo_name = repo_match.group(2)
        closest_match_example = closest_match_example.replace("{repo}", repo_name)

    # Suggest the closest match or prompt for 'help'
    return f"I couldn't understand that. For reference, here's an example of a valid command:'{closest_match_example}?' Try following this format or write 'help' to see what I can do!"


def match_and_execute(so, plain_text, user_id, regex_maps):
    """
    Identify command pattern and execute the associated function.
    - so: an object instance
    - plain_text: the input command text.
    - user_id: unique identifier for a user.
    - regex_maps: mapping of regex patterns to corresponding functions.
    """
    for r in regex_maps:
        m = re.match(r["regex"], plain_text, r["flag"])  # Try to match text with current pattern
        if m:
            # If user_id is required, pass it to the function, otherwise call function with matched groups
            if r.get("user_id", False):
                r["function"](so, user_id, **m.groupdict())
            else:
                r["function"](so, **m.groupdict())
            return True  # Command was successfully matched and executed
    return False  # No match was found for the command


def handle_unmatched_command(so, plain_text, regex_maps):
    """
    Suggest a command or report a non-matching command.
    - plain_text: the input command text.
    - regex_maps: known command patterns for comparison.
    """
    recommended_command = recommend_command(plain_text, regex_maps)
    if recommended_command:
        so.say(recommended_command)  # Suggest a command
    else:
        so.say(f"'{plain_text}' did not match any known commands. Write 'help' to see what I can do!")  # Inform user of no match


def map_command_to_regex(so, plain_text, user_id):
    re_snippets = dict(
        major_minor=r"(?P<major>\d)\.(?P<minor>\d+)",
        name=r"(?P<name>[\w.-]+)",
        names=r"(?P<names>[\w.,-]+)",
        name_type=r"(?P<name_type>dist-?git)",
        name_type2=r"(?P<name_type2>brew-image|brew-component)",
        nvr=r"(?P<nvr>[\w.-]+)",
        wh=r"(which|what)",
    )

    regex_maps = [
        # "regex": regex string
        # "flag": flag(s)
        # "function": function (without parenthesis)
        # "example": An example command/query that would match the regex.

        {
            "regex": r"^\W*(hi|hey|hello|howdy|what'?s? up|yo|welcome|greetings)\b",
            "flag": re.I,
            "function": greet_user,
            "example": "hello"
        },
        {
            "regex": r"^help$",
            "flag": re.I,
            "function": show_help,
            "example": "help"
        },

        # ART releases:
        {
            "regex": r"^%(wh)s build of %(name)s is in (?P<release_img>[-.:/#\w]+)$" % re_snippets,
            "flag": re.I,
            "function": buildinfo_for_release,
            "example": "What build of ironic is in 4.12.0-0.ci-2022-12-13-165927"
        },
        {
            "regex": r"^%(wh)s (?P<data_type>[\w.-]+) are associated with (?P<release_tag>[\w.-]+)$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_component_data_for_release_tag,
            "example": "What images are associated with 4.10.10"
        },
        {
            "regex": r"^What kernel is used in (?P<release_img>[-.:/#\w]+)(?: for arch (?P<arch>[a-zA-Z0-9-]+))?$",
            "flag": re.I,
            "function": kernel_info,
            "example": "What kernel is used in 4.10.10 for arch amd64"
        },

        # ART build info
        {
            "regex": r"^%(wh)s images build in %(major_minor)s$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_images_in_major_minor,
            "example": "What images build in 4.10"
        },
        {
            "regex": r"^%(wh)s rpms were used in the latest image builds for %(major_minor)s$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_components_for_major_minor,
            "example": "Which rpms were used in the latest image builds for 4.10"
        },
        {
            "regex": r"^%(wh)s rpms are in image %(nvr)s$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_components_for_image,
            "example": "Which rpms are in image ose-installer-container-v4.10.0-202209241557.p0.gb7e59a8.assembly.stream"
        },
        {
            "regex": r"^%(wh)s rpms? (?P<rpms>[-\w.,* ]+) (is|are) in image %(nvr)s$" % re_snippets,
            "flag": re.I,
            "function": brew_list.specific_rpms_for_image,
            "example": "Which rpms ovn, zlib are in image ose-ovn-kubernetes-container-v4.7.0-202108160002.p0.git.9581e60.assembly.stream"
        },
        {
            "regex": r"^alert ?(if|when|on)? build (?P<build_id>\d+|https\://brewweb.engineering.redhat.com/brew/buildinfo\?buildID=\d+) completes$",
            "flag": re.I,
            "function": alert_on_build_complete,
            "user_id": True,
            "example": "Alert when https://brewweb.engineering.redhat.com/brew/buildinfo?buildid=123456 completes"
        },
        {
            "regex": r"^Watch (?P<build_id>https\://brewweb.engineering.redhat.com/brew/buildinfo\?buildID=\d+)$",
            "flag": re.I,
            "function": alert_on_build_complete,
            "user_id": True,
            "example": "Watch https://brewweb.engineering.redhat.com/brew/buildinfo?buildid=123456"
        },
        {
            "regex": r"^alert ?(if|when|on)? task (?P<task_id>\d+|https\://brewweb.engineering.redhat.com/brew/taskinfo\?taskID=\d+) completes$",
            "flag": re.I,
            "function": alert_on_task_complete,
            "user_id": True,
            "example": "Alert if task https://brewweb.engineering.redhat.com/brew/taskinfo?taskID=12345 completes"
        },
        {
            "regex": r"^Watch (?P<task_id>https\://brewweb.engineering.redhat.com/brew/taskinfo\?taskID=\d+)$",
            "flag": re.I,
            "function": alert_on_task_complete,
            "user_id": True,
            "example": "Watch https://brewweb.engineering.redhat.com/brew/taskinfo?taskID=12345"
        },
        {
            'regex': r'^pr info \s*(https://)*(github.com/)*(?P<org>[a-zA-Z0-9-]+)\/*(?P<repo>[a-zA-Z0-9-]+)(/pull/)(?P<pr_id>\d+)(?: component (?P<component>[a-zA-Z0-9-]+))? in %(major_minor)s(?: for arch (?P<arch>[a-zA-Z0-9-]+))?$' % re_snippets,
            'flag': re.I,
            'function': pr_info,
            "example": "pr info https://github.com/openshift/ptp-operator/pull/281 component ptp-operator in 4.12 for arch amd64"
        },
        {
            "regex": r"^(go|golang) version (for|of) %(nvr)s$" % re_snippets,
            "flag": re.I,
            "function": elliott.go_nvrs,
            "example": "go version for ose-ovn-kubernetes-container-v4.7.0-202108160002.p0.git.9581e60.assembly.stream"
        },
        {
            "regex": r"^(go|golang) version (for|of) advisory (?P<advisory_id>\d+)$",
            "flag": re.I,
            "function": elliott.go_advisory,
            "example": "go version for advisory 79678"
        },
        # * (go|golang) config for `major.minor`,`major.minor2`
        {
            "regex": r"^(go|golang) config (for|of) (?P<ocp_version_string>.*)$",
            "flag": re.I,
            "function": elliott.go_config,
            "example": "go config for versions 4.13 4.14 4.15 (with|including rhel version)"
        },
        {
            "regex": r"^timestamp (for|of) brew event (?P<brew_event>\d+)$",
            "flag": re.I,
            "function": brew.get_event_ts,
            "example": "timestamp for brew event 55331468"
        },

        # ART advisory info:
        {
            "regex": r"^image list.*advisory (?P<advisory_id>\d+)$",
            "flag": re.I,
            "function": elliott.image_list,
            "example": "image list for advisory 79678"
        },

        # ART config
        {
            "regex": r"^where in %(major_minor)s (is|are) the %(names)s (?P<search_type>RPM|package)s? used$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_uses_of_rpms,
            "example": "Where in 4.10 are the rpm1,rpm2,rpm3 rpms used"
        },
        {
            "regex": r"^what is the %(name_type2)s for %(name_type)s %(name)s(?: in %(major_minor)s)?$" % re_snippets,
            "flag": re.I,
            "function": translate_names,
            "example": "What is the brew-component for dist-git ironic in 4.10"
        },

        # ART pipeline
        {
            "regex": r"^.*(image )?pipeline \s*for \s*github \s*(https://)*(github.com/)*(openshift/)*(?P<github_repo>[a-zA-Z0-9-]+)(/|\.git)?\s*( in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_github,
            "example": "Image pipeline for github https://github.com/openshift/ose-cluster-network-operator in 4.10"
        },
        {
            "regex": r"^.*(image )?pipeline \s*for \s*distgit \s*(containers\/){0,1}(?P<distgit_repo_name>[a-zA-Z0-9-]+)( \s*in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_distgit,
            "example": "Image pipeline for distgit ironic in 4.10"
        },
        {
            "regex": r"^.*(image )?pipeline \s*for \s*package \s*(?P<brew_name>\S*)( \s*in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_brew,
            "example": "Image pipeline for package ironic-container in 4.10"
        },
        {
            "regex": r"^.*(image )?pipeline \s*for \s*cdn \s*(?P<cdn_repo_name>\S*)( \s*in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_cdn,
            "example": "Image pipeline for cdn <name> in 4.10"
        },
        {
            "regex": r"^.*(image )?pipeline \s*for \s*image \s*(registry.redhat.io\/)*(?P<delivery_repo_name>[a-zA-Z0-9-\/]+)\s*( \s*in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_delivery,
            "example": "image pipeline for image registry.redhat.io/openshift4/name in 4.10"
        },

        # Others
        {
            "regex": r"^Alert ?(if|when|on)? https://(?P<release_browser>[\w]+).ocp.releases.ci.openshift.org(?P<release_url>[\w/.-]+) ?(stops being blue|fails|is rejected|is red|is accepted|is green)?$",
            "flag": re.I,
            "function": nightly_color_status,
            "user_id": True,
            "example": "Alert if https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/4.13.0-0.ci-2022-12-19-111818 is green"
        },
        {
            "regex": r"^Watch https://(?P<release_browser>[\w]+).ocp.releases.ci.openshift.org(?P<release_url>[\w/.-]+)$",
            "flag": re.I,
            "function": nightly_color_status,
            "user_id": True,
            "example": "Watch https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/4.13.0-0.ci-2022-12-19-111818"
        },
        {
            "regex": rf"^Alert ?(if|when|on)? prow job {PROW_BASE_URL}/view/gs/(?P<job_path>\S*) completes$",
            "flag": re.I,
            "function": prow_job_status,
            "user_id": True,
            "example": "Alert when prow job https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344 completes"
        },
        {
            "regex": rf"^Watch {PROW_BASE_URL}/view/gs/(?P<job_path>\S*)$",
            "flag": re.I,
            "function": prow_job_status,
            "user_id": True,
            "example": "Watch https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344"
        },
        {
            "regex": rf"^Alert ?(if|when|on)? first prow job in(?P<job_paths>(( )*{PROW_BASE_URL}/view/gs/\S*)*) succeeds$",
            "flag": re.I,
            "function": first_prow_job_succeeds,
            "user_id": True,
            "example": "Alert when first prow job in https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344 succeeds"
        },
        {
            "regex": r"^Watch \s*(https://)*(github.com/)*(?P<org>[a-zA-Z0-9-]+)/*(?P<repo>[a-zA-Z0-9-]+)(/pull/)(?P<pr_id>\d+)",
            "flag": re.I,
            "function": pr_status,
            "user_id": True,
            "example": "Watch https://github.com/openshift-eng/art-bot/pull/157"
        },
    ]
    matched = match_and_execute(so, plain_text, user_id, regex_maps)

    if not matched:
        handle_unmatched_command(so, plain_text, regex_maps)
