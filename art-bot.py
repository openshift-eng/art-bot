#!/usr/bin/python3
import signal
import click
import os
import os.path
import pprint
import logging
import yaml
import traceback
from multiprocessing.pool import ThreadPool

from artbotlib.exectools import sigterm_handler
from artbotlib.regex_mapping import map_command_to_regex
from artbotlib.util import lookup_channel, log_config
from artbotlib.formatting import extract_plain_text
from artbotlib.slack_output import SlackOutput
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


def show_how_to_add_a_new_image(so):
    so.say('You can find documentation for that process here: '
           'https://mojo.redhat.com/docs/DOC-1179058#jive_content_id_Getting_Started')


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

    except Exception as exc:
        print(f"Error with the contents of your settings file:\n{exc}")
        exit(1)

    pool.apply_async(respond, (client, event))


def respond(client, event):
    try:
        data = event
        web_client = client

        logger.info(data)

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

        logger.info(f"Gating {from_channel}")
        logger.info(f"Query was: {plain_text}")

        so = SlackOutput(
            web_client=web_client,
            event=event,
            target_channel_id=target_channel_id,
            monitoring_channel_id=bot_config.get("monitoring_channel_id", None),
            thread_ts=thread_ts,
            alt_username=alt_username,
        )

        so.monitoring_say(f"<@{user_id}> asked: {plain_text}")

        try:
            map_command_to_regex(so, plain_text, user_id)
        except Exception as error:
            # Catch any unexpected error and display appropriate message to the user.
            so.say("Uh oh... there seems to be a problem. Please contact @.art-team")
            so.monitoring_say(f"Error: {error}")
            logger.error(error)

        if not so.said_something:
            so.say("Sorry, I can't help with that yet. Ask 'help' to see what I can do.")

    except Exception:
        logger.error("Error responding to message:")
        logger.error(event)
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
    log_config(debug)

    # Get the Slack app token to start a socket connection
    try:
        with open(abs_path_home(bot_config["slack_app_token_file"]), "r") as token_file:
            bot_config["slack_app_token"] = token_file.read().strip()
    except Exception as exc:
        print(f"Error: {exc}\nYou must provide a slack APP token in your config. You can find this in bitwarden.")
        exit(1)

    handler = SocketModeHandler(app, bot_config["slack_app_token"])
    handler.start()


signal.signal(signal.SIGTERM, sigterm_handler)

if __name__ == "__main__":
    run()
