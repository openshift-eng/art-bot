#!/usr/bin/python3

import os
import slack
import pprint
import re
import koji
import shlex
import subprocess
import logging
from fcntl import fcntl, F_GETFL, F_SETFL
from os import O_NONBLOCK, read
import time
import json
import datetime
from multiprocessing.pool import ThreadPool
import traceback

MONITORING_CHANNEL = 'GTDLQU9LH'  # art-bot-monitoring
BOT_FRIENDLY_CHANNELS = 'GDBRP5YJH'  # channels we allow the bot to talk directly in instead of DM'ing user back
BOT_ID = 'UTHKYT7FB'
AT_BOT_ID = f'<@{BOT_ID}>'

logger = logging.getLogger()


class SlackOutput:

    def __init__(self, say, snippet,
                 monitoring_say, monitoring_snippet,
                 request_payload):
        self.say_func = say
        self.snippet_func = snippet
        self.monitoring_say_func = monitoring_say
        self.monitoring_snippet_func = monitoring_snippet
        self.request_payload = request_payload

    def say(self, msg):
        self.say_func(msg)

    def snippet(self, payload, intro=None, filename=None, filetype=None):
        self.snippet_func(payload=payload, intro=intro, filename=filename, filetype=filetype)

    def monitoring_say(self, msg):
        self.monitoring_say_func(msg)

    def monitoring_snippet(self, payload, intro=None, filename=None, filetype=None):
        self.monitoring_snippet_func(payload=payload, intro=intro, filename=filename, filetype=filetype)

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

How-to information
- How can I get ART to build a new image?

Release status:
- What images do you build for {major}.{minor}?

ART internal
- What (commits|catalogs|distgits|nvrs|images) are associated with {release-tag}
- What rpms are used in {image-nvr}?
- What rpms were used in the latest images builds for {major}.{minor}? 
""")


def show_how_to_add_a_new_image(so):
    so.say('You can find documentation for that process here: https://mojo.redhat.com/docs/DOC-1179058#jive_content_id_Getting_Started')


def cmd_gather(cmd, set_env=None, cwd=None, realtime=False):
    """
    Runs a command and returns rc,stdout,stderr as a tuple.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param cmd: The command and arguments to execute
    :param cwd: The directory from which to run the command
    :param set_env: Dict of env vars to set for command (overriding existing)
    :param realtime: If True, output stdout and stderr in realtime instead of all at once.
    :return: (rc,stdout,stderr)
    """

    if not isinstance(cmd, list):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd

    cmd_info = '[cwd={}]: {}'.format(cwd, cmd_list)

    env = os.environ.copy()
    if set_env:
        cmd_info = '[env={}] {}'.format(set_env, cmd_info)
        env.update(set_env)

    # Make sure output of launched commands is utf-8
    env['LC_ALL'] = 'en_US.UTF-8'

    logger.debug("Executing:cmd_gather {}".format(cmd_info))
    try:
        proc = subprocess.Popen(
            cmd_list, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        logger.error("Subprocess errored running:\n{}\nWith error:\n{}\nIs {} installed?".format(
            cmd_info, exc, cmd_list[0]
        ))
        return exc.errno, "", "Subprocess errored running:\n{}\nWith error:\n{}\nIs {} installed?".format(
            cmd_info, exc, cmd_list[0]
        )

    if not realtime:
        out, err = proc.communicate()
        rc = proc.returncode
    else:
        out = b''
        err = b''

        # Many thanks to http://eyalarubas.com/python-subproc-nonblock.html
        # setup non-blocking read
        # set the O_NONBLOCK flag of proc.stdout file descriptor:
        flags = fcntl(proc.stdout, F_GETFL)  # get current proc.stdout flags
        fcntl(proc.stdout, F_SETFL, flags | O_NONBLOCK)
        # set the O_NONBLOCK flag of proc.stderr file descriptor:
        flags = fcntl(proc.stderr, F_GETFL)  # get current proc.stderr flags
        fcntl(proc.stderr, F_SETFL, flags | O_NONBLOCK)

        rc = None
        while rc is None:
            output = None
            try:
                output = read(proc.stdout.fileno(), 256)
                logging.info(f'{cmd_info} stdout: {out.rstrip()}')
                out += output
            except OSError:
                pass

            error = None
            try:
                error = read(proc.stderr.fileno(), 256)
                logging.warning(f'{cmd_info} stderr: {error.rstrip()}')
                out += error
            except OSError:
                pass

            rc = proc.poll()
            time.sleep(0.0001)  # reduce busy-wait

    # We read in bytes representing utf-8 output; decode so that python recognizes them as unicode strings
    out = out.decode('utf-8')
    err = err.decode('utf-8')
    logger.debug(
        "Process {}: exited with: {}\nstdout>>{}<<\nstderr>>{}<<\n".
        format(cmd_info, rc, out, err))
    return rc, out, err


def cmd_assert(so, cmd, set_env=None, cwd=None, realtime=False):
    """
    A cmd_gather invocation, but if it fails, it will notify the
    alert the monitoring channel and the requesting user with
    information about the failure.
    :return:
    """

    error_id = f'{so.from_user_id()}.{int(time.time()*1000)}'

    def send_cmd_error(rc, stdout, stderr):
        intro = f'Error running command (for user={so.from_user_mention()} error-id={error_id}): {cmd}'
        payload = f"rc={rc}\n\nstdout={stdout}\n\nstderr={stderr}\n"
        so.monitoring_snippet(intro=intro, filename='cmd_error.log', payload=payload)

    try:
        rc, stdout, stderr = cmd_gather(cmd, set_env, cwd, realtime)
    except subprocess.CalledProcessError as exec:
        send_cmd_error(exec.returncode, exec.stdout, exec.stderr)
        raise
    except:
        send_cmd_error(-1000, '', traceback.format_exc())
        raise

    if rc:
        logging.warning(f'error-id={error_id} . Non-zero return code from: {cmd}\nStdout:\n{stdout}\n\nStderr:\n{stderr}\n')
        send_cmd_error(rc, stdout, stderr)
        so.say(f'Sorry, but I encountered an error. Details have been sent to the ART team. Mention error-id={error_id} when requesting support.')
        raise IOError(f'Non-zero return code from: {cmd}')

    return rc, stdout, stderr


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


def please_notify_art_team_of_error(so, payload):
    dt = datetime.datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
    so.snippet(payload=payload,
               intro='Sorry, I encountered an error. Please contact @art-team with the following details.',
               filename=f'error-details-{dt}.txt')


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

        said_something = False

        def say(thing):
            nonlocal said_something
            print(f'Responding back through: {target_channel_id}')
            said_something = True
            web_client.chat_postMessage(
                channel=target_channel_id,
                text=thing,
                thread_ts=thread_ts
            )

        def snippet(payload, intro=None, filename=None, filetype=None):
            nonlocal said_something
            said_something = True
            print('Called with payload: {}'.format(payload))
            print(f'Responding back through: {target_channel_id}')
            r = web_client.files_upload(
                initial_comment=intro,
                channels=target_channel_id,
                content=payload,
                filename=filename,
                filetype=filetype,
                thread_ts=thread_ts
            )
            print('Response: ')
            pprint.pprint(r)

        def monitoring_say(thing):
            try:
                web_client.chat_postMessage(
                    channel=MONITORING_CHANNEL,
                    text=thing
                )
            except:
                print('Error sending information to monitoring channel')
                traceback.print_exc()

        def monitoring_snippet(payload, intro=None, filename=None, filetype=None):
            try:
                print('Called with monitoring payload: {}'.format(payload))
                r = web_client.files_upload(
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

        monitoring_say(f"<@{user_id}> asked: {data['text']}")

        so = SlackOutput(say=say, snippet=snippet, monitoring_say=monitoring_say, monitoring_snippet=monitoring_snippet, request_payload=payload)

        print(f'Gating {from_channel} {direct_message_channel_id} {am_i_mentioned}')

        # We only want to respond if in a DM channel or we are mentioned specifically in another channel
        if from_channel == direct_message_channel_id or am_i_mentioned:

            if re.match(r'^help$', text, re.I):
                show_help(so)

            m = re.match(r'^what rpms are used in (?P<nvr>[\w.-]+)$', text, re.I)
            if m:
                list_components_for_image(so, **m.groupdict())

            m = re.match(r'^what images do you build for (?P<major>\d)\.(?P<minor>\d+)$', text, re.I)
            if m:
                list_images_in_major_minor(so, **m.groupdict())

            if re.match(r'^How can I get ART to build a new image$', text, re.I):
                show_how_to_add_a_new_image(so)

            m = re.match(r'^What rpms were used in the latest images builds for (?P<major>\d)\.(?P<minor>\d+)$', text, re.I)
            if m:
                list_components_for_major_minor(so, **m.groupdict())

            m = re.match(r'^What (?P<data_type>[\w.-]+) are associated with (?P<release_tag>[\w.-]+)$', text, re.I)
            if m:
                list_component_data_for_release_tag(so, **m.groupdict())

            if not said_something:
                say("Sorry, I don't know how to help with that. Type 'help' to see what I can do.")
    except:
        print('Error responding to message:')
        pprint.pprint(payload)
        traceback.print_exc()
        raise


if not os.environ.get('SLACK_API_TOKEN', None):
    print('You must export SLACK_API_TOKEN into the environment. You can find this in bitwarden.')
    exit(1)

slack_token = os.environ["SLACK_API_TOKEN"]
rtm_client = slack.RTMClient(token=slack_token, auto_reconnect=True)
rtm_client.start()

