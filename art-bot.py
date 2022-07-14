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
import threading
import random

import umb
from artbotlib.buildinfo import buildinfo_for_release
from artbotlib.translation import translate_names
from artbotlib.util import cmd_assert, please_notify_art_team_of_error, lookup_channel
from artbotlib.formatting import extract_plain_text, repeat_in_chunks
from artbotlib.slack_output import SlackOutput
from artbotlib import brew_list, elliott
from artbotlib.pipeline_image_names import pipeline_from_distgit, pipeline_from_github, pipeline_from_brew, \
    pipeline_from_cdn, pipeline_from_delivery
from artbotlib.nightly_color import nightly_color_status

logger = logging.getLogger()


# Do we have something that is not grade A?
# What will the grades be by <date>
# listen to the UMB and publish events to slack #release-x.y


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

_*ART build info:*_
* Where in `major.minor` (is|are) the `name1,name2,...` (RPM|package) used?
* What rpms were used in the latest image builds for `major.minor`?
* What rpms are in image `image-nvr`?
* Which rpm `rpm1,rpm2,...` is in image `image-nvr`?

_*misc:*_
* How can I get ART to build a new image?
* Chunk (to `channel`): something you want repeated a sentence/line at a time in channel.
""")


def show_how_to_add_a_new_image(so):
    so.say('You can find documentation for that process here: https://mojo.redhat.com/docs/DOC-1179058#jive_content_id_Getting_Started')


bot_config = {}


def on_load(client: RTMClient, event: dict):
    pprint.pprint(event)
    web_client = client.web_client
    r = web_client.auth_test()
    try:
        bot_config["self"] = {"id": r.data["user_id"], "name": r.data["user"]}
        if "monitoring_channel" not in bot_config:
            raise Exception("No monitoring_channel configured.")
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

    except Exception as exc:
        print(f"Error with the contents of your settings file:\n{exc}")
        exit(1)


pool = ThreadPool(20)


def incoming_message(client: RTMClient, event: dict):
    pool.apply_async(respond, (client, event))


def respond(client: RTMClient, event: dict):
    try:
        data = event
        web_client = client.web_client

        print('\n----------------- DATA -----------------\n')
        pprint.pprint(data)

        if 'user' not in data:
            # This message was not from a user; probably the bot hearing itself or another bot
            return

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

        # If we changing channels, we cannot target the initial message to create a thread
        if target_channel_id != from_channel:
            thread_ts = None

        alt_username = None
        am_i_DMed = from_channel == direct_message_channel_id
        if bot_config["self"]["name"] != bot_config["username"]:
            alt_username = bot_config["username"]
            # alternate user must be mentioned specifically, even in a DM, else msg is left to default bot user to handle
            am_i_mentioned = f'@{bot_config["username"]}' in data['text']
            am_i_DMed = am_i_DMed and am_i_mentioned
            plain_text = extract_plain_text({"data": data}, alt_username)
        else:
            am_i_mentioned = f'<@{bot_config["self"]["id"]}>' in data['text']
            plain_text = extract_plain_text({"data": data})
            if plain_text.startswith("@"):
                return  # assume it's for an alternate name

        print(f'Gating {from_channel} {am_i_DMed} {am_i_mentioned}')

        print(f'Query was: {plain_text}')

        # We only want to respond if in a DM channel or we are mentioned specifically in another channel
        if not am_i_DMed and not am_i_mentioned:
            return

        so = SlackOutput(
            web_client=web_client,
            event=event,
            target_channel_id=target_channel_id,
            monitoring_channel_id=bot_config["monitoring_channel_id"],
            thread_ts=thread_ts,
            alt_username=alt_username,
        )

        so.monitoring_say(f"<@{user_id}> asked: {plain_text}")

        re_snippets = dict(
            major_minor=r'(?P<major>\d)\.(?P<minor>\d+)',
            name=r'(?P<name>[\w.-]+)',
            names=r'(?P<names>[\w.,-]+)',
            name_type=r'(?P<name_type>dist-?git)',
            name_type2=r'(?P<name_type2>brew-image|brew-component)',
            nvr=r'(?P<nvr>[\w.-]+)',
            wh=r'(which|what)',
        )

        regex_maps = [
            # 'regex': regex string
            # 'flag': flag(s)
            # 'function': function (without parenthesis)

            {'regex': r"^\W*(hi|hey|hello|howdy|what'?s? up|yo|welcome|greetings)\b",
             'flag': re.I,
             'function': greet_user
             },
            {
                'regex': r'^help$',
                'flag': re.I,
                'function': show_help
            },

            # ART releases:
            {
                'regex': r'^%(wh)s build of %(name)s is in (?P<release_img>[-.:/#\w]+)$' % re_snippets,
                'flag': re.I,
                'function': buildinfo_for_release
            },
            {
                'regex': r'^%(wh)s (?P<data_type>[\w.-]+) are associated with (?P<release_tag>[\w.-]+)$' % re_snippets,
                'flag': re.I,
                'function': brew_list.list_component_data_for_release_tag
            },

            # ART build info
            {
                'regex': r'^%(wh)s images build in %(major_minor)s$' % re_snippets,
                'flag': re.I,
                'function': brew_list.list_images_in_major_minor
            },
            {
                'regex': r'^%(wh)s rpms were used in the latest image builds for %(major_minor)s$' % re_snippets,
                'flag': re.I,
                'function': brew_list.list_components_for_major_minor
            },
            {
                'regex': r'^%(wh)s rpms are in image %(nvr)s$' % re_snippets,
                'flag': re.I,
                'function': brew_list.list_components_for_image
            },
            {
                'regex': r'^%(wh)s rpms? (?P<rpms>[-\w.,* ]+) (is|are) in image %(nvr)s$' % re_snippets,
                'flag': re.I,
                'function': brew_list.specific_rpms_for_image
            },

            # ART advisory info:
            {
                'regex': r'^image list.*advisory (?P<advisory_id>\d+)$',
                'flag': re.I,
                'function': elliott.image_list
            },

            # ART config
            {
                'regex': r'^where in %(major_minor)s (is|are) the %(names)s (?P<search_type>RPM|package)s? used$' % re_snippets,
                'flag': re.I,
                'function': brew_list.list_uses_of_rpms
            },
            {
                'regex': r'^what is the %(name_type2)s for %(name_type)s %(name)s(?: in %(major_minor)s)?$' % re_snippets,
                'flag': re.I,
                'function': translate_names
            },

            # ART pipeline
            {
                'regex': r'^.*(image )?pipeline \s*for \s*github \s*(https://)*(github.com/)*(openshift/)*(?P<github_repo>[a-zA-Z0-9-]+)(/|\.git)?\s*( in \s*(?P<version>\d+.\d+))?\s*$',
                'flag': re.I,
                'function': pipeline_from_github
            },
            {
                'regex': r'^.*(image )?pipeline \s*for \s*distgit \s*(containers\/){0,1}(?P<distgit_repo_name>[a-zA-Z0-9-]+)( \s*in \s*(?P<version>\d+.\d+))?\s*$',
                'flag': re.I,
                'function': pipeline_from_distgit
            },
            {
                'regex': r'^.*(image )?pipeline \s*for \s*package \s*(?P<brew_name>\S*)( \s*in \s*(?P<version>\d+.\d+))?\s*$',
                'flag': re.I,
                'function': pipeline_from_brew
            },
            {
                'regex': r'^.*(image )?pipeline \s*for \s*cdn \s*(?P<cdn_repo_name>\S*)( \s*in \s*(?P<version>\d+.\d+))?\s*$',
                'flag': re.I,
                'function': pipeline_from_cdn
            },
            {
                'regex': r'^.*(image )?pipeline \s*for \s*image \s*(registry.redhat.io/)*(openshift4/)*(?P<delivery_repo_name>[a-zA-Z0-9-]+)\s*( \s*in \s*(?P<version>\d+.\d+))?\s*$',
                'flag': re.I,
                'function': pipeline_from_delivery
            },

            # Others
            {
                'regex': r'^Alert if https://(?P<release_browser>[\w]+).ocp.releases.ci.openshift.org(?P<release_url>[\w/.-]+) (stops being blue|fails|is rejected|is red|is accepted|is green)$',
                'flag': re.I,
                'function': nightly_color_status,
                'user_id': True
            }
        ]

        for r in regex_maps:
            m = re.match(r['regex'], plain_text, r['flag'])
            if m:
                if r.get('user_id', False):  # if functions need to cc the user
                    r['function'](so, user_id, **m.groupdict())
                else:
                    r['function'](so, **m.groupdict())

        if not so.said_something:
            so.say("Sorry, I can't help with that yet. Ask 'help' to see what I can do.")

    except Exception:
        print('Error responding to message:')
        pprint.pprint(event)
        traceback.print_exc()
        raise


def consumer_start(topic, callback_handler, durable=False, user_data=None):
    """
    Create a consumer for a topic on the UMB.
    :param topic: The name of the topic (e.g. eng.clair.scan). The VirtualTopic name will be constructed for you.
    :param callback_handler: The method to invoke when a message is received. The method should accept
                                (message, user_data)  and return True when the consumer thread should terminate.
                                If False is returned, the callback will continue to be invoked as messages arrive.
    :param durable: Whether the subscription should be durable
    :param user_data: Anything you want passed to the callback when a message is delivered
    :return: The Thread created to run the consumer.
    """
    config = bot_config["umb"]
    consumer = umb.get_consumer(
        env=config["env"],
        client_cert_path=config["client_cert_file"],
        client_key_path=config["client_key_file"],
        ca_chain_path=config["ca_certs_file"],
    )
    t = threading.Thread(target=consumer_thread, args=(bot_config["umb"]["client_id"], topic, callback_handler, consumer, durable, user_data))
    t.start()
    return t


def clair_consumer_callback(msg, user_data):
    """
    :param msg: The incoming message to handle
    :param user_data: Any userdata provided to consumer.consume.
    :return: Will always return False to indicate more messages should be processed
    """
    try:
        print('annotations:')
        pprint.pprint(msg.annotations)

        print('properties:')
        pprint.pprint(msg.properties)

        print('body:')
        pprint.pprint(msg.body)
    except Exception:
        logging.error('Error handling message')
        traceback.print_exc()

    return False  # Tell consumer to keep consuming messages


def consumer_thread(client_id, topic, callback_handler, consumer, durable, user_data):
    try:
        topic_clair_scan = f'Consumer.{client_id}.art-bot.VirtualTopic.{topic}'
        if durable:
            subscription_name = topic
        else:
            subscription_name = None
        consumer.consume(topic_clair_scan, callback_handler, subscription_name=subscription_name, data=user_data)
    except Exception:
        traceback.print_exc()


@click.command()
def run():
    
    try:
        config_file = os.environ.get("ART_BOT_SETTINGS_YAML", f"{os.environ['HOME']}/.config/art-bot/settings.yaml")
        with open(config_file, 'r') as stream:
            bot_config.update(yaml.safe_load(stream))
    except yaml.YAMLError as exc:
        print(f"Error reading yaml in file {config_file}: {exc}")
        exit(1)
    except Exception as exc:
        print(f"Error loading art-bot config file {config_file}: {exc}")
        exit(1)

    def abs_path_home(filename):
        # if not absolute, relative to home dir
        return filename if filename.startswith("/") else f"{os.environ['HOME']}/{filename}"

    try:
        with open(abs_path_home(bot_config["slack_api_token_file"]), "r") as stream:
            bot_config["slack_api_token"] = stream.read().strip()
    except Exception as exc:
        print(f"Error: {exc}\nYou must provide a slack API token in your config. You can find this in bitwarden.")
        exit(1)

    logging.basicConfig()
    logging.getLogger('activemq').setLevel(logging.DEBUG)

    rtm_client = RTMClient(token=bot_config['slack_api_token'])
    rtm_client.on("hello")(on_load)
    rtm_client.on("message")(incoming_message)

    if "umb" in bot_config:
        # umb listener setup is optional

        bot_config["umb"].setdefault("env", "stage")
        bot_config["umb"].setdefault("ca_certs_file", umb.DEFAULT_CA_CHAIN)
        bot_config["umb"].setdefault("client_id", "openshift-art-bot-slack")
        try:
            if bot_config["umb"]["env"] not in ["dev", "stage", "prod"]:
                raise Exception(f"invalid umb env specified: {bot_config['umb']['env']}")
            for umbfile in ["client_cert_file", "client_key_file", "ca_certs_file"]:
                if not bot_config["umb"].get(umbfile, None):
                    raise Exception(f"config must specify a file for umb {umbfile}")
                bot_config["umb"][umbfile] = abs_path_home(bot_config["umb"][umbfile])
                if not os.path.isfile(bot_config["umb"][umbfile]):
                    raise Exception(f"config specifies a file for umb {umbfile} that does not exist: {bot_config['umb'][umbfile]}")
        except Exception as exc:
            print(f"Error in umb configuration: {exc}")
            exit(1)

        clair_consumer = consumer_start('eng.clair.>', clair_consumer_callback)
        clair_consumer.join()

    rtm_client.start()


if __name__ == '__main__':
    run()
