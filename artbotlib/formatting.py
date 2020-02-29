import re


def extract_plain_text(json_data):
    """
    Take data that looks like the following:

{'data': {'blocks': [{'block_id': 'a2J3',
                      'elements': [{'elements': [{'type': 'user',
                                                  'user_id': 'UTHKYT7FB'},
                                                 {'text': ' Which build of sdn '
                                                          'is in ',
                                                  'type': 'text'},
                                                 {'text': 'registry.svc.ci.openshift.org/ocp-s390x/release-s390x:4.4.0-0.nightly-s390
x-2020-02-21-235937',
                                                  'type': 'link',
                                                  'url': 'http://registry.svc.ci.openshift.org/ocp-s390x/release-s390x:4.4.0-0.nightl
y-s390x-2020-02-21-235937'}],
                                    'type': 'rich_text_section'}],
                      'type': 'rich_text'}],
                      ...

    and extract just the text parts to come up with:
    "Which build of sdn is in registry.svc.ci.openshift.org/ocp-s390x/release-s390x:4.4.0-0.nightly-s390x-2020-02-21-235937"
    """

    text = ""
    for block in json_data["data"]["blocks"]:
        for section in [el for el in block["elements"] if el["type"] == "rich_text_section"]:
            for element in [el for el in section["elements"] if "text" in el]:
                text += element["text"]

    # reformat to homogenize miscellaneous confusing bits
    return re.sub(r"\s+", " ", text).lstrip().rstrip(" ?").lower()
