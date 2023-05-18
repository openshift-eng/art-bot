#!/usr/bin/python3

import click
import os
import os.path
from slack_sdk.rtm.v2 import RTMClient
import pprint
import re
import logging
import yaml
from multiprocessing.pool import ThreadPool
import traceback
import random
from artbotlib.buildinfo import buildinfo_for_release, kernel_info, alert_on_build_complete
from artbotlib.pr_in_build import pr_info
from artbotlib.translation import translate_names
from artbotlib.util import lookup_channel, log_config
from artbotlib.formatting import extract_plain_text
from artbotlib.slack_output import SlackOutput
from artbotlib import brew_list, elliott
from artbotlib.pipeline_image_names import pipeline_from_distgit, pipeline_from_github, pipeline_from_brew, \
    pipeline_from_cdn, pipeline_from_delivery
from artbotlib.nightly_color import nightly_color_status
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt import App

logger = logging.getLogger()

bot_config = {}


def abs_path_home(filename):
    # if not absolute, relative to home dir
    return filename if filename.startswith("/") else f"{os.environ['HOME']}/{filename}"


config_file = None
try:
    config_file = os.environ.get("ART_BOT_SETTINGS_YAML", f"{os.environ['HOME']}/.config/art-bot/settings.yaml")
    with open(config_file, 'r') as stream:
        bot_config.update(yaml.safe_load(stream))

    with open(abs_path_home(bot_config["slack_api_token_file"]), "r") as stream:
        bot_config["slack_api_token"] = stream.read().strip()
except yaml.YAMLError as e:
    print(f"Error reading yaml in file {config_file}: {e}")
    exit(1)
except KeyError as e:
    print(f"Error: {e}\nYou must provide a slack API token in your config. You can find this in bitwarden.")
    exit(1)
except Exception as e:
    print(f"Error loading art-bot config file {config_file}: {e}")
    exit(1)

# Since 'slack_api_token' is needed and @app.event is a header,
# we're loading the settings.yml file outside a function
app = App(token=bot_config["slack_api_token"])

pool = ThreadPool(20)


def greet_user(so):
    greetings = ["Hi", "Hey", "Hello", "Howdy", "What's up", "Yo", "Greetings", "G'day", "Mahalo"]
    so.say(f"{greetings[random.randint(1, len(greetings)) - 1]}, {so.from_user_mention()}")


def show_help(so):
    so.say("""Here are questions I can answer...

_*ART config:*_
* What images build in `major.minor`?
* What is the image pipeline for (github|distgit|package|cdn|image) `name` [in `major.minor`]?
* What is the (brew-image|brew-component) for dist-git `name` [in `major.minor`]?

_*ART releases:*_
* Which build of `image_name` is in `release image name or pullspec`?
* What (commits|catalogs|distgits|nvrs|images) are associated with `release-tag`?
* Image list advisory `advisory_id`
* Alert if `release_url` (stops being blue|fails|is rejected|is red|is accepted|is green)
* What kernel is used in `release image name or pullspec`?

_*ART build info:*_
* Where in `major.minor` (is|are) the `name1,name2,...` (RPM|package) used?
* What rpms were used in the latest image builds for `major.minor`?
* What rpms are in image `image-nvr`?
* Which rpm `rpm1,rpm2,...` is in image `image-nvr`?
* pr info `GitHub PR URL` [component `name`] in `major.minor` [for `arch`]
* Alert when build `Brew build URL|Brew build ID` completes

_*misc:*_
* How can I get ART to build a new image?
* Chunk (to `channel`): something you want repeated a sentence/line at a time in channel.
""")


def show_how_to_add_a_new_image(so):
    so.say(
        'You can find documentation for that process here: https://mojo.redhat.com/docs/DOC-1179058#jive_content_id_Getting_Started')


def handle_message(client, event):
    web_client = client
    r = web_client.auth_test()
    try:
        bot_config["self"] = {"id": r.data["user_id"], "name": r.data["user"]}
        if "monitoring_channel" not in bot_config:
            print("Warning: no monitoring_channel configured.")
        else:
            found = lookup_channel(web_client, bot_config["monitoring_channel"], only_private=True)
            if not found:
                raise Exception(f"Invalid monitoring channel configured: {bot_config['monitoring_channel']}")
            bot_config["monitoring_channel_id"] = found["id"]

        bot_config.setdefault("friendly_channels", [])
        bot_config["friendly_channel_ids"] = []
        for channel in bot_config["friendly_channels"]:
            found = lookup_channel(web_client, channel)
            if not found:
                raise Exception(f"Invalid friendly channel configured: {channel}")
            bot_config["friendly_channel_ids"].append(found["id"])

        bot_config.setdefault("username", bot_config["self"]["name"])

    except Exception as e:
        print(f"Error with the contents of your settings file:\n{e}")
        exit(1)

    pool.apply_async(respond, (client, event))


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
            "regex": r"^What kernel is used in (?P<release_img>[-.:/#\w]+)$",
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


def respond(client, event):
    try:
        data = event
        web_client = client

        print('\n----------------- DATA -----------------\n')
        pprint.pprint(data)

        # Channel we were contacted from.
        from_channel = data['channel']

        # Get the id of the Slack user associated with the incoming event
        user_id = data['user']
        ts = data['ts']
        thread_ts = data.get('thread_ts', ts)

        if user_id == bot_config["self"]["id"]:
            # things like snippets may look like they are from normal users; if it is from us, ignore it.
            return

        response = web_client.conversations_open(users=user_id)
        direct_message_channel_id = response["channel"]["id"]

        target_channel_id = direct_message_channel_id
        if from_channel in bot_config["friendly_channel_ids"]:
            # in these channels we allow the bot to respond directly instead of DM'ing user back
            target_channel_id = from_channel

        # If we're changing channels, we cannot target the initial message to create a thread
        if target_channel_id != from_channel:
            thread_ts = None

        alt_username = None
        if bot_config["self"]["name"] != bot_config["username"]:
            alt_username = bot_config["username"]

        plain_text = extract_plain_text({"data": data}, alt_username)

        print(f'Gating {from_channel}')
        print(f'Query was: {plain_text}')

        so = SlackOutput(
            web_client=web_client,
            event=event,
            target_channel_id=target_channel_id,
            monitoring_channel_id=bot_config.get("monitoring_channel_id", None),
            thread_ts=thread_ts,
            alt_username=alt_username,
        )

        so.monitoring_say(f"received query: {plain_text}")

        try:
            map_command_to_regex(so, plain_text, user_id)
        except Exception as error:
            # Catch any unexpected error and display appropriate message to the user.
            so.say("Uh oh... there seems to be a problem. Please contact @.art-team")
            so.monitoring_say(f"Error: {error}")

        if not so.said_something:
            so.say("Sorry, I can't help with that yet. Ask 'help' to see what I can do.")

    except Exception:
        print('Error responding to message:')
        pprint.pprint(event)
        traceback.print_exc()
        raise


# The function is called when art-bot is directly mentioned. Eg: '@art-bot hey'
@app.event("app_mention")
def incoming_message(client, event):
    handle_message(client, event)


# This function will be called when any message is sent to any of the channels that art-bot is added to.
# The above function, incoming_message does not work for DMs. To handle that we have to use the event 'message'
# There is a field in event called channel_type. So we check to see if it's an 'im', which is a direct message
# and ignore the rest. https://api.slack.com/events/message.im
@app.event("message")
def incoming_dm(client, event):
    if event.get("channel_type") == "im":
        handle_message(client, event)


@click.option('--debug', default=False, is_flag=True, help='Show debug output on console.')
@click.command()
def run(debug):
    logging.basicConfig()
    logging.getLogger('activemq').setLevel(logging.DEBUG)

    # Get the Slack app token to start a socket connection
    try:
        with open(abs_path_home(bot_config["slack_app_token_file"]), "r") as stream:
            bot_config["slack_app_token"] = stream.read().strip()
    except Exception as exc:
        print(f"Error: {exc}\nYou must provide a slack APP token in your config. You can find this in bitwarden.")
        exit(1)

    log_config(debug)
    logging.getLogger('activemq').setLevel(logging.DEBUG)

    handler = SocketModeHandler(app, bot_config["slack_app_token"])
    handler.start()


if __name__ == "__main__":
    run()
