#!/usr/bin/python3

import click
import os
import os.path
import slack
import pprint
import re
import logging
from os import O_NONBLOCK, read
import yaml
from multiprocessing.pool import ThreadPool
import traceback
import threading

import umb
from artbotlib.buildinfo import buildinfo_for_release
from artbotlib.translation import translate_names
from artbotlib.util import cmd_assert, please_notify_art_team_of_error, lookup_channel
from artbotlib.formatting import extract_plain_text, repeat_in_chunks
from artbotlib.slack_output import SlackOutput
from artbotlib import brew_list


logger = logging.getLogger()


# Do we have something that is not grade A?
# What will the grades be by <date>
# listen to the UMB and publish events to slack #release-x.y


def show_help(so):
    so.say("""Here are questions I can answer...

ART config
- What images do you build for {major}.{minor}?
- what is the (brew-image|brew-component) for dist-git {name} in {major}.{minor}?
- what is the (brew-image|brew-component) for dist-git {name}?
  (assumes latest version)

ART build info
- What rpms are in image {image-nvr}?
- Which rpm {rpm1,rpm2,...} is in image {image-nvr}?
- What rpms were used in the latest image builds for {major}.{minor}?
- Where in {major}.{minor} is the {name} RPM used?

ART releases:
- What (commits|catalogs|distgits|nvrs|images) are associated with {release-tag}?
- Which build of {image name} is in {release image name or pullspec}?

misc:
- How can I get ART to build a new image?
- Chunk (to {channel}): something you want repeated a sentence/line at a time in channel.
""")


def show_how_to_add_a_new_image(so):
    so.say('You can find documentation for that process here: https://mojo.redhat.com/docs/DOC-1179058#jive_content_id_Getting_Started')


bot_config = {}
@slack.RTMClient.run_on(event="open")
def on_load(**payload):
    pprint.pprint(payload["data"])
    web_client = payload["web_client"]
    try:
        bot_config["self"] = payload["data"]["self"]  # e.g. {'id': 'UTHKYT7FB', 'name': 'art-bot'}

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

    except Exception as exc:
        print(f"Error with the contents of your settings file {config_file}:\n{exc}")
        exit(1)


pool = ThreadPool(20)
@slack.RTMClient.run_on(event='message')
def incoming_message(**payload):
    pool.apply_async(respond, kwds=payload)


def respond(**payload):
    try:
        data = payload['data']
        web_client = payload['web_client']

        print('DATA')
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

        response = web_client.im_open(user=user_id)
        direct_message_channel_id = response["channel"]["id"]

        target_channel_id = direct_message_channel_id
        if from_channel in bot_config["friendly_channel_ids"]:
            # in these channels we allow the bot to respond directly instead of DM'ing user back
            target_channel_id = from_channel

        # If we changing channels, we cannot target the initial message to create a thread
        if target_channel_id != from_channel:
            thread_ts = None

        so = SlackOutput(
            web_client=web_client,
            request_payload=payload,
            target_channel_id=target_channel_id,
            monitoring_channel_id=bot_config["monitoring_channel_id"],
            thread_ts=thread_ts,
        )

        am_i_mentioned = f'<@{bot_config["self"]["id"]}>' in data['text']
        print(f'Gating {from_channel} {direct_message_channel_id} {am_i_mentioned}')
        plain_text = extract_plain_text(payload)
        print(f'Query was: {plain_text}')

        # We only want to respond if in a DM channel or we are mentioned specifically in another channel
        if from_channel == direct_message_channel_id or am_i_mentioned:

            so.monitoring_say(f"<@{user_id}> asked: {plain_text}")

            re_snippets = dict(
                major_minor=r'(?P<major>\d)\.(?P<minor>\d+)',
                name=r'(?P<name>[\w.-]+)',
                name_type=r'(?P<name_type>dist-?git)',
                name_type2=r'(?P<name_type2>brew-image|brew-component)',
                nvr=r'(?P<nvr>[\w.-]+)',
            )
            regex_maps = [
                # regex, flag(s), func
                (r'^help$', re.I, show_help),
                (r'^what rpms are in image %(nvr)s$' % re_snippets, re.I, brew_list.list_components_for_image),
                (r'^which rpms? (?P<rpms>[-\w.,* ]+) (is|are) in image %(nvr)s$' % re_snippets, re.I, brew_list.specific_rpms_for_image),
                (r'^what images do you build for %(major_minor)s$' % re_snippets, re.I, brew_list.list_images_in_major_minor),
                (r'^How can I get ART to build a new image$', re.I, show_how_to_add_a_new_image),
                (r'^What rpms were used in the latest image builds for %(major_minor)s$' % re_snippets, re.I, brew_list.list_components_for_major_minor),
                (r'^where in %(major_minor)s is the %(name)s RPM used$' % re_snippets, re.I, brew_list.list_images_using_rpm),
                (r'^What (?P<data_type>[\w.-]+) are associated with (?P<release_tag>[\w.-]+)$', re.I, brew_list.list_component_data_for_release_tag),
                (r'^what is the %(name_type2)s for %(name_type)s %(name)s(?: in %(major_minor)s)?$' % re_snippets, re.I, translate_names),
                (r'^(which|what) build of %(name)s is in (?P<release_img>[-.:/#\w]+)$' % re_snippets, re.I, buildinfo_for_release),
                (r'^chunk ?(to #?%(name)s)?:' % re_snippets, re.I, repeat_in_chunks),
            ]
            for r in regex_maps:
                m = re.match(r[0], plain_text, r[1])
                if m:
                    r[2](so, **m.groupdict())

            if not so.said_something:
                so.say("Sorry, I don't know how to help with that. Type 'help' to see what I can do.")
    except:
        print('Error responding to message:')
        pprint.pprint(payload)
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
    except:
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
    except:
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

    rtm_client = slack.RTMClient(token=bot_config['slack_api_token'], auto_reconnect=True)

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
