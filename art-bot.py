#!/usr/bin/python3

import click
import os
import slack
import pprint
import re
import koji
import logging
from os import O_NONBLOCK, read
import json
from multiprocessing.pool import ThreadPool
import traceback
import threading

import umb
from artbotlib.buildinfo import buildinfo_for_release
from artbotlib.translation import translate_names
from artbotlib.util import cmd_assert, please_notify_art_team_of_error
from artbotlib.formatting import extract_plain_text

MONITORING_CHANNEL = 'GTDLQU9LH'  # art-bot-monitoring
BOT_FRIENDLY_CHANNELS = 'GDBRP5YJH'  # channels we allow the bot to talk directly in instead of DM'ing user back
BOT_ID = 'UTHKYT7FB'
AT_BOT_ID = f'<@{BOT_ID}>'

logger = logging.getLogger()


class SlackOutput:

    def __init__(self, web_client, request_payload, target_channel_id, thread_ts):
        self.request_payload = request_payload
        self.web_client = web_client
        self.target_channel_id = target_channel_id
        self.thread_ts = thread_ts
        self.said_something = False

    def say(self, msg):
        print(f'Responding back through: {self.target_channel_id}')
        self.said_something = True
        self.web_client.chat_postMessage(
            channel=self.target_channel_id,
            text=msg,
            thread_ts=self.thread_ts
        )

    def snippet(self, payload, intro=None, filename=None, filetype=None):
        self.said_something = True
        print('Called with payload: {}'.format(payload))
        print(f'Responding back through: {self.target_channel_id}')
        r = self.web_client.files_upload(
            initial_comment=intro,
            channels=self.target_channel_id,
            content=payload,
            filename=filename,
            filetype=filetype,
            thread_ts=self.thread_ts
        )
        print('Response: ')
        pprint.pprint(r)

    def monitoring_say(self, msg):
        try:
            self.web_client.chat_postMessage(
                channel=MONITORING_CHANNEL,
                text=msg
            )
        except:
            print('Error sending information to monitoring channel')
            traceback.print_exc()

    def monitoring_snippet(self, payload, intro=None, filename=None, filetype=None):
        try:
            print('Called with monitoring payload: {}'.format(payload))
            r = self.web_client.files_upload(
                initial_comment=intro,
                channels=MONITORING_CHANNEL,
                content=payload,
                filename=filename,
                filetype=filetype,
            )
            print('Response: ')
            pprint.pprint(r)
        except:
            print('Error sending snippet to monitoring channel')
            traceback.print_exc()

    def from_user_mention(self):
        return f'<@{self.from_user_id()}>'

    def from_user_id(self):
        return self.request_payload.get('data').get('user', None)

    def from_channel(self):
        return self.request_payload.get('data').get('channel', None)


# Do we have something that is not grade A?
# What will the grades be by <date>
# listen to the UMB and publish events to slack #release-x.y


def show_help(so):
    so.say("""Here are questions I can answer...

FAQs
- How can I get ART to build a new image?

ART internal
- What (commits|catalogs|distgits|nvrs|images) are associated with {release-tag}
- What rpms are used in {image-nvr}?
- What rpms were used in the latest images builds for {major}.{minor}?

Information:
- What images do you build for {major}.{minor}?
- Which build of {image name} is in {release image name or pullspec}?
- translate distgit {name} to brew-image for {major}.{minor}
- translate distgit {name} to brew-image
  (assumes latest version)
""")


def show_how_to_add_a_new_image(so):
    so.say('You can find documentation for that process here: https://mojo.redhat.com/docs/DOC-1179058#jive_content_id_Getting_Started')


def brew_list_components(nvr):
    koji_api = koji.ClientSession('https://brewhub.engineering.redhat.com/brewhub', opts={'serverca': '/etc/pki/brew/legacy.crt'})
    build = koji_api.getBuild(nvr, strict=True)
    components = set()
    for archive in koji_api.listArchives(build['id']):
        for rpm in koji_api.listRPMs(imageID=archive['id']):
            components.add('{nvr}.{arch}'.format(**rpm))
    return components


def list_components_for_image(so, nvr):
    so.say('Sure.. let me check on {}'.format(nvr))
    so.snippet(payload='\n'.join(sorted(brew_list_components(nvr))),
               intro='The following rpms are used',
               filename='{}-rpms.txt'.format(nvr))


def list_component_data_for_release_tag(so, data_type, release_tag):
    so.say('Let me look into that. It may take a minute...')

    data_type = data_type.lower()
    data_types = ('nvr', 'distgit', 'commit', 'catalog', 'image')

    if not data_type.startswith(data_types):
        so.say(f"Sorry, the type of information you want about each component needs to be one of: {data_types}")
        return

    if 'nightly-' in release_tag:
        repo_url = 'registry.svc.ci.openshift.org/ocp/release'
    else:
        repo_url = 'quay.io/openshift-release-dev/ocp-release'

    image_url = f'{repo_url}:{release_tag}'

    print(f'Trying: {image_url}')
    rc, stdout, stderr = cmd_assert(so, f'oc adm release info -o=json --pullspecs {image_url}')
    if rc:
        please_notify_art_team_of_error(so, stderr)
        return

    payload = f'Finding information for: {image_url}\n'

    release_info = json.loads(stdout)
    tag_specs = list(release_info['references']['spec']['tags'])
    for tag_spec in sorted(tag_specs, key=lambda x: x['name']):
        release_component_name = tag_spec['name']
        release_component_image = tag_spec['from']['name']
        rc, stdout, stderr = cmd_assert(so, f'oc image info -o=json {release_component_image}')
        if rc:
            please_notify_art_team_of_error(so, stderr)
            return
        release_component_image_info = json.loads(stdout)
        component_labels = release_component_image_info.get('config', {}).get('container_config', {}).get('Labels', {})
        component_name = component_labels.get('com.redhat.component', 'UNKNOWN')
        component_version = component_labels.get('version', 'v?')
        component_release = component_labels.get('release', '?')
        component_upstream_commit_url = component_labels.get('io.openshift.build.commit.url', '?')
        component_distgit_commit = component_labels.get('vcs-ref', '?')
        component_rhcc_url = component_labels.get('url', '?')

        payload += f'{release_component_name}='
        if data_type.startswith('nvr'):
            payload += f'{component_name}-{component_version}-{component_release}'
        elif data_type.startswith('distgit'):
            distgit_name = component_name.rstrip('-container')
            payload += f'http://pkgs.devel.redhat.com/cgit/{distgit_name}/commit/?id={component_distgit_commit}'
        elif data_type.startswith('commit'):
            payload += f'{component_upstream_commit_url}'
        elif data_type.startswith('catalog'):
            payload += f'{component_rhcc_url}'
        elif data_type.startswith('image'):
            payload += release_component_image
        else:
            so.say(f"Sorry, I don't know how to extract information about {data_type}")
            return

        payload += '\n'

        if '?' in payload:
            print(f'BAD INFO?')
            pprint.pprint(release_component_image_info)

    so.snippet(payload=payload,
               intro=f'The release components map to {data_type} as follows:',
               filename='{}-{}.txt'.format(release_tag, data_type))


def list_components_for_major_minor(so, major, minor):
    so.say('I can answer that! But this will take awhile (~10 minutes)...')
    major_minor = f'{major}.{minor}'
    rc, stdout, stderr = cmd_assert(so, f'doozer --group openshift-{major_minor} images:print \'{{component}}-{{version}}-{{release}}\' --show-base --show-non-release --short')
    if rc:
        please_notify_art_team_of_error(so, stderr)
    else:
        output = f'I found the following nvrs for {major_minor} images:\n{stdout}\n'
        all_components = set()
        for nvr in stdout.strip().split('\n'):
            all_components.update(brew_list_components(nvr.strip()))
        output += 'And here are the rpms used in their construction:\n'
        output += '\n'.join(sorted(all_components))
        so.snippet(payload=output,
                   intro='Here ya go...',
                   filename=f'{major_minor}-rpms.txt')


def list_images_in_major_minor(so, major, minor):
    major_minor = f'{major}.{minor}'
    rc, stdout, stderr = cmd_assert(so, f'doozer --group openshift-{major_minor} images:print \'{{image_name_short}}\' --show-base --show-non-release --short')
    if rc:
        please_notify_art_team_of_error(so, stderr)
    else:
        so.snippet(payload=stdout, intro=f'Here are the images being built for openshift-{major_minor}',
                   filename=f'openshift-{major_minor}.images.txt')


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
        text = data['text']
        ts = data['ts']
        thread_ts = data.get('thread_ts', ts)

        if user_id == BOT_ID:
            # things like snippets may look like they are from normal users; if it is from us, ignore it.
            return

        am_i_mentioned = AT_BOT_ID in text

        if am_i_mentioned:
            text = text.replace(AT_BOT_ID, '').strip()

        text = ' '.join(text.split())  # Replace different whitespace with single space
        text = text.rstrip('?')  # remove any question marks from the end

        response = web_client.im_open(user=user_id)
        direct_message_channel_id = response["channel"]["id"]

        target_channel_id = direct_message_channel_id
        if from_channel in BOT_FRIENDLY_CHANNELS:
            target_channel_id = from_channel

        # If we changing channels, we cannot target the initial message to create a thread
        if target_channel_id != from_channel:
            thread_ts = None

        so = SlackOutput(web_client=web_client, request_payload=payload, target_channel_id=target_channel_id, thread_ts=thread_ts)

        print(f'Gating {from_channel} {direct_message_channel_id} {am_i_mentioned}')

        # We only want to respond if in a DM channel or we are mentioned specifically in another channel
        if from_channel == direct_message_channel_id or am_i_mentioned:

            so.monitoring_say(f"<@{user_id}> asked: {data['text']}")

            regex_maps = [
                # regex, flag(s), func
                (r'^help$', re.I, show_help),
                (r'^what rpms are used in (?P<nvr>[\w.-]+)$', re.I, list_components_for_image),
                (r'^what images do you build for (?P<major>\d)\.(?P<minor>\d+)$', re.I, list_images_in_major_minor),
                (r'^How can I get ART to build a new image$', re.I, show_how_to_add_a_new_image),
                (r'^What rpms were used in the latest images builds for (?P<major>\d)\.(?P<minor>\d+)$', re.I, list_components_for_major_minor),
                (r'^What (?P<data_type>[\w.-]+) are associated with (?P<release_tag>[\w.-]+)$', re.I, list_component_data_for_release_tag),
                (r'(?:translate|xlate) ^$', re.I, translate_names),
                (r'Which build of (?P<img_name>\S+) is in (?P<release_img>\S+)$', re.I, buildinfo_for_release),
            ]
            for r in regex_maps:
                m = re.match(r[0], text, r[1])
                if m:
                    r[2](so, **m.groupdict())

            if not so.said_something:
                so.say("Sorry, I don't know how to help with that. Type 'help' to see what I can do.")
    except:
        print('Error responding to message:')
        pprint.pprint(payload)
        traceback.print_exc()
        raise


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
@click.option("--env", required=False, metavar="ENVIRONMENT",
              default='stage',
              type=click.Choice(['dev', 'stage', 'prod']),
              help="Which UMB environment to use")
@click.option('--client-id', required=False, metavar='CLIENT-ID',
              type=click.STRING,
              help='The client-id associated with the cert/key pair fo the UMB',
              default='openshift-art-bot-slack-prod')
@click.option("--client-cert", required=True, metavar="CERT-PATH",
              type=click.Path(exists=True),
              help="Path to the client certificate for UMB authentication")
@click.option("--client-key", required=True, metavar="KEY-PATH",
              type=click.Path(exists=True),
              help="Path to the client key for UMB authentication")
@click.option("--ca-certs", type=click.Path(exists=True),
              default=umb.DEFAULT_CA_CHAIN,
              help="Manually specify the path to the RHIT CA Trust Chain. "
              "Default: {}".format(umb.DEFAULT_CA_CHAIN))
def run(env, client_id, client_cert, client_key, ca_certs):
    if not os.environ.get('SLACK_API_TOKEN', None):
        print('You must export SLACK_API_TOKEN into the environment. You can find this in bitwarden.')
        exit(1)

    logging.basicConfig()
    logging.getLogger('activemq').setLevel(logging.DEBUG)

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
        consumer = umb.get_consumer(env=env, client_cert_path=client_cert, client_key_path=client_key,
                                    ca_chain_path=ca_certs)
        t = threading.Thread(target=consumer_thread, args=(client_id, topic, callback_handler, consumer, durable, user_data))
        t.start()
        return t

    t = consumer_start('eng.clair.>', clair_consumer_callback)

    slack_token = os.environ["SLACK_API_TOKEN"]
    rtm_client = slack.RTMClient(token=slack_token, auto_reconnect=True)
    rtm_client.start()

    t.join()


if __name__ == '__main__':
    run()
