import re

from artbotlib.slack_output import SlackOutput

from . import util


def extract_plain_text(json_data, alt_username=None):
    """
    Take data that looks like the following:

{'data': {'blocks': [{'block_id': 'a2J3',
                      'elements': [{'elements': [{'type': 'user',
                                                  'user_id': 'UTHKYT7FB'},
                                                 {'text': ' Which build of sdn '
                                                          'is in ',
                                                  'type': 'text'},
                                                 {'text': 'registry.ci.openshift.org/ocp-s390x/release-s390x:4.4.0-0.nightly-s390
x-2020-02-21-235937',
                                                  'type': 'link',
                                                  'url': 'http://registry.ci.openshift.org/ocp-s390x/release-s390x:4.4.0-0.nightl
y-s390x-2020-02-21-235937'}],
                                    'type': 'rich_text_section'}],
                      'type': 'rich_text'}],
                      ...

    and extract just the text parts to come up with:
    "Which build of sdn is in registry.ci.openshift.org/ocp-s390x/release-s390x:4.4.0-0.nightly-s390x-2020-02-21-235937"
    """

    text = ""
    for block in json_data["data"]["blocks"]:
        for section in [el for el in block["elements"] if el["type"] == "rich_text_section"]:
            for element in section["elements"]:
                if "text" in element:
                    text += element["text"]
                elif "url" in element:
                    text += element["url"]

    # reformat to homogenize miscellaneous confusing bits
    text = re.sub(r"\s+", " ", text).lstrip().rstrip(" ?").lower()

    # remove bare references to alt_username
    if alt_username:
        text = text.replace(f'@{alt_username} ', '')

    return text


def repeat_in_chunks(so: SlackOutput, name=None):
    """
    Repeat what the user says, one "sentence" at a time, in the indicated channel if specified.
    But only if the bot and the user are in the channel.
    """

    # remove the "@art-bot chunk to channel:" directive at the beginning.
    text = re.sub(r"^[^:]+:", "", so.event["text"])

    # split by eol and periods followed by a space. ignore formatting if possible.
    chunks = re.sub(r"(\S\S\.)(\s+|$)", r"\1\n", text, flags=re.M).splitlines()

    # find the requested channel
    if not name:
        channel_id = so.from_channel()
        name = "this channel"
    else:
        channel = util.lookup_channel(so.web_client, name)
        if not channel:
            so.say(f"This app must be added to channel {name} in order to speak there.")
            return
        channel_id = channel["id"]

        # make sure the user is also a member of the conversation
        def members_function(c):
            return so.web_client.conversations_members(channel=channel_id, cursor=c)

        if so.from_user_id() not in util.paginator(members_function, "members"):
            so.say(f"You must be a member of channel {name} to have me speak there.")
            return

    so.say(f"Sending that to {name}.")
    opts = dict(
        channel=channel_id,
        thread_ts=None,
        unfurl_links=False,
        unfurl_media=False,
    )
    so.say(f"{so.from_user_mention()} asked me to say:", **opts)
    # send one message per chunk to conversation.
    for chunk in chunks:
        if re.search(r"\S", chunk):  # slack doesn't like empty lines, skip those
            so.say(chunk, **opts)
