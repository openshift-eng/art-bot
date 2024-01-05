from datetime import datetime

from artbotlib.util import koji_client_session


def get_event_ts(so, brew_event: id):
    try:
        result = koji_client_session().getEvent(brew_event)
        timestamp = datetime.utcfromtimestamp(result['ts'])
        so.say(f'Brew event {brew_event} correponds to timestamp {timestamp}')

    except Exception as e:
        so.say('Sorry, something went wrong when retrieving brew event timestamp. ')
        so.monitoring_say(f'Failed retrieving timestamp for Brew event {brew_event}: {e}')
