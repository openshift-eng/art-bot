import os
import re

from artbotlib import brew_list, elliott
from artbotlib.buildinfo import buildinfo_for_release, kernel_info, alert_on_build_complete
from artbotlib.help import greet_user, show_help
from artbotlib.nightly_color import nightly_color_status
from artbotlib.pipeline_image_names import pipeline_from_github, pipeline_from_distgit, pipeline_from_brew, \
    pipeline_from_cdn, pipeline_from_delivery
from artbotlib.pr_in_build import pr_info
from artbotlib.translation import translate_names


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

        {
            "regex": r"^\W*(hi|hey|hello|howdy|what'?s? up|yo|welcome|greetings)\b",
            "flag": re.I,
            "function": greet_user
        },
        {
            "regex": r"^help$",
            "flag": re.I,
            "function": show_help
        },

        # ART releases:
        {
            "regex": r"^%(wh)s build of %(name)s is in (?P<release_img>[-.:/#\w]+)$" % re_snippets,
            "flag": re.I,
            "function": buildinfo_for_release
        },
        {
            "regex": r"^%(wh)s (?P<data_type>[\w.-]+) are associated with (?P<release_tag>[\w.-]+)$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_component_data_for_release_tag
        },
        {
            "regex": r"^What kernel is used in (?P<release_img>[-.:/#\w]+)(?: for arch (?P<arch>[a-zA-Z0-9-]+))?$",
            "flag": re.I,
            "function": kernel_info
        },

        # ART build info
        {
            "regex": r"^%(wh)s images build in %(major_minor)s$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_images_in_major_minor
        },
        {
            "regex": r"^%(wh)s rpms were used in the latest image builds for %(major_minor)s$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_components_for_major_minor
        },
        {
            "regex": r"^%(wh)s rpms are in image %(nvr)s$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_components_for_image
        },
        {
            "regex": r"^%(wh)s rpms? (?P<rpms>[-\w.,* ]+) (is|are) in image %(nvr)s$" % re_snippets,
            "flag": re.I,
            "function": brew_list.specific_rpms_for_image
        },
        {
            "regex": r"^alert ?(if|when|on)? build (?P<build_id>\d+|https\://brewweb.engineering.redhat.com/brew/buildinfo\?buildID=\d+) completes$",
            "flag": re.I,
            "function": alert_on_build_complete,
            "user_id": True
        },
        {
            'regex': r'^pr info \s*(https://)*(github.com/)*(openshift/)*(?P<repo>[a-zA-Z0-9-]+)(/pull/)(?P<pr_id>\d+)(?: component (?P<component>[a-zA-Z0-9-]+))? in %(major_minor)s(?: for arch (?P<arch>[a-zA-Z0-9-]+))?$' % re_snippets,
            'flag': re.I,
            'function': pr_info
        },

        # ART advisory info:
        {
            "regex": r"^image list.*advisory (?P<advisory_id>\d+)$",
            "flag": re.I,
            "function": elliott.image_list
        },

        # ART config
        {
            "regex": r"^where in %(major_minor)s (is|are) the %(names)s (?P<search_type>RPM|package)s? used$" % re_snippets,
            "flag": re.I,
            "function": brew_list.list_uses_of_rpms
        },
        {
            "regex": r"^what is the %(name_type2)s for %(name_type)s %(name)s(?: in %(major_minor)s)?$" % re_snippets,
            "flag": re.I,
            "function": translate_names
        },

        # ART pipeline
        {
            "regex": r"^.*(image )?pipeline \s*for \s*github \s*(https://)*(github.com/)*(openshift/)*(?P<github_repo>[a-zA-Z0-9-]+)(/|\.git)?\s*( in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_github
        },
        {
            "regex": r"^.*(image )?pipeline \s*for \s*distgit \s*(containers\/){0,1}(?P<distgit_repo_name>[a-zA-Z0-9-]+)( \s*in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_distgit
        },
        {
            "regex": r"^.*(image )?pipeline \s*for \s*package \s*(?P<brew_name>\S*)( \s*in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_brew
        },
        {
            "regex": r"^.*(image )?pipeline \s*for \s*cdn \s*(?P<cdn_repo_name>\S*)( \s*in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_cdn
        },
        {
            "regex": r"^.*(image )?pipeline \s*for \s*image \s*(registry.redhat.io/)*(openshift4/)*(?P<delivery_repo_name>[a-zA-Z0-9-]+)\s*( \s*in \s*(?P<version>\d+.\d+))?\s*$",
            "flag": re.I,
            "function": pipeline_from_delivery
        },

        # Others
        {
            "regex": r"^Alert ?(if|when|on)? https://(?P<release_browser>[\w]+).ocp.releases.ci.openshift.org(?P<release_url>[\w/.-]+) ?(stops being blue|fails|is rejected|is red|is accepted|is green)?$",
            "flag": re.I,
            "function": nightly_color_status,
            "user_id": True
        }
    ]

    matched_regex = False
    for r in regex_maps:
        m = re.match(r["regex"], plain_text, r["flag"])
        if m:
            matched_regex = True
            if r.get("user_id", False):  # if functions need to cc the user
                r["function"](so, user_id, **m.groupdict())
            else:
                r["function"](so, **m.groupdict())
    if os.environ.get("RUN_ENV") != "production" and not matched_regex:
        print(f"'{plain_text}' did not match any regexes.\n")
