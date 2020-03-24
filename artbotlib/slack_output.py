import pprint
import traceback


class SlackOutput:

    def __init__(self, web_client, request_payload, target_channel_id, monitoring_channel_id, thread_ts):
        self.web_client = web_client
        self.request_payload = request_payload
        self.target_channel_id = target_channel_id
        self.thread_ts = thread_ts
        self.monitoring_channel_id = monitoring_channel_id
        self.said_something = False

    def say(self, msg):
        print(f"Responding back through: {self.target_channel_id}")
        self.said_something = True
        self.web_client.chat_postMessage(
            channel=self.target_channel_id,
            text=msg,
            thread_ts=self.thread_ts
        )

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
            thread_ts=self.thread_ts
        )
        print("Response: ")
        pprint.pprint(r)

    def monitoring_say(self, msg):
        try:
            self.web_client.chat_postMessage(
                channel=self.monitoring_channel_id,
                text=msg
            )
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
        return self.request_payload.get("data").get("user", None)

    def from_channel(self):
        return self.request_payload.get("data").get("channel", None)
