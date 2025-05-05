import requests

from artbotlib.constants import SLACK_SUMMARIZER


def summarize_thread(so, thread_url: str):
    url = f"{SLACK_SUMMARIZER}/summarize-url"
    params = {
        "url": thread_url
    }
    response = requests.get(url, params=params)

    if response.status_code != 200:
        so.say(f'Failed getting summary for thread {thread_url}. Please contact @.team-ocp-automated-release-tooling')
        return

    so.say(f'Here\'s the summary for thread {thread_url}:\n\n{response.json()["summary"]}')


def summarize_art_attention_threads(so):
    url = f"{SLACK_SUMMARIZER}/summarize-art-attention"
    response = requests.get(url)

    if response.status_code != 200:
        so.say('Failed getting summary for ART threads. Please contact @.team-ocp-automated-release-tooling')
        return
    summaries = response.json()

    so.say('Here are the ART important threads summarized:')
    for item in summaries:
        so.say(f'- {item["permalink"]}:\n{item["summary"]}\n\n')
