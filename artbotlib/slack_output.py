import pprint
import traceback
import os


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
        if os.environ.get("RUN_ENV") == 'production':
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
        else:
            print("so.say:")
            print("---")
            print(text)
            print("---")

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
        if os.environ.get("RUN_ENV") == 'production':
            if not self.monitoring_channel_id:
                return
            try:
                msg = dict(
                    channel=self.monitoring_channel_id,
                    text=text,
                    **self.username_opts,
                )
                msg.update(msg_opts)
                self.web_client.chat_postMessage(**msg)
            except Exception:
                print("Error sending information to monitoring channel")
                traceback.print_exc()
        else:
            print("so.monitoring_say:")
            print("---")
            print(text)
            print("---")

    def monitoring_snippet(self, payload, intro=None, filename=None, filetype=None):
        if not self.monitoring_channel_id:
            return
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
        if os.environ.get("RUN_ENV") == 'production':
            return f"<@{self.from_user_id()}>"
        return "@developer"

    def from_user_id(self):
        return self.event.get("user", None)

    def from_channel(self):
        return self.event.get("channel", None)
