import pprint
import traceback


class SlackOutput:

    def __init__(self, web_client, event, target_channel_id, monitoring_channel_id, thread_ts, alt_username):
        self.web_client = web_client
        self.event = event
        self.target_channel_id = target_channel_id
        self.monitoring_channel_id = monitoring_channel_id
        self.thread_ts = thread_ts
        self.username_opts = dict(as_user=False, username=alt_username, icon_emoji=":hammer_and_wrench:") if alt_username else dict()
        self.said_something = False

    def say(self, text, **msg_opts):
        print(f"Responding back through: {self.target_channel_id}")
        self.said_something = True
        msg = dict(
            channel=self.target_channel_id,
            text=text,
            thread_ts=self.thread_ts,
            **self.username_opts,
        )
        msg.update(msg_opts)
        response = self.web_client.chat_postMessage(**msg)
        print(f"response ok: {response.get('ok')}\n")
        pprint.pprint(f"ok: {response.get('message')}")

    def snippet(self, payload, intro=None, filename=None, filetype=None):
        self.said_something = True
        print(f"Called with payload: {payload}")
        print(f"Responding back through: {self.target_channel_id}")
        r = self.web_client.files_upload(
            initial_comment=intro,
            channels=self.target_channel_id,
            content=payload,
            filename=filename,
            filetype=filetype,
            thread_ts=self.thread_ts,
        )
        print("Response: ")
        pprint.pprint(r)

    def monitoring_say(self, text, **msg_opts):
        try:
            msg = dict(
                channel=self.monitoring_channel_id,
                text=text,
                **self.username_opts,
            )
            msg.update(msg_opts)
            self.web_client.chat_postMessage(**msg)
        except:
            print("Error sending information to monitoring channel")
            traceback.print_exc()

    def monitoring_snippet(self, payload, intro=None, filename=None, filetype=None):
        try:
            print("Called with monitoring payload: {}".format(payload))
            r = self.web_client.files_upload(
                initial_comment=intro,
                channels=self.monitoring_channel_id,
                content=payload,
                filename=filename,
                filetype=filetype,
            )
            print("Response: ")
            pprint.pprint(r)
        except:
            print("Error sending snippet to monitoring channel")
            traceback.print_exc()

    def from_user_mention(self):
        return f"<@{self.from_user_id()}>"

    def from_user_id(self):
        return self.event.get("user", None)

    def from_channel(self):
        return self.event.get("channel", None)
