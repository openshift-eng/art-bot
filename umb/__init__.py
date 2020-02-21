from rhmsg.activemq.consumer import AMQConsumer

DEFAULT_CA_CHAIN = "/etc/pki/ca-trust/source/anchors/RH-IT-Root-CA.crt"

RH_UMB_URLS = {
    'dev': (
        'amqps://messaging-devops-broker01.dev1.ext.devlab.redhat.com:5671',
        'amqps://messaging-devops-broker02.dev1.ext.devlab.redhat.com:5671',
    ),
    'qa': (
        'amqps://messaging-devops-broker01.web.qa.ext.phx1.redhat.com:5671',
        'amqps://messaging-devops-broker02.web.qa.ext.phx1.redhat.com:5671',
    ),
    'stage': (
        'amqps://messaging-devops-broker01.web.stage.ext.phx2.redhat.com:5671',
        'amqps://messaging-devops-broker02.web.stage.ext.phx2.redhat.com:5671',
    ),
    'prod': (
        'amqps://messaging-devops-broker01.web.prod.ext.phx2.redhat.com:5671',
        'amqps://messaging-devops-broker02.web.prod.ext.phx2.redhat.com:5671',
    ),

}


def get_consumer(env, client_cert_path, client_key_path, ca_chain_path=DEFAULT_CA_CHAIN):
    return AMQConsumer(urls=RH_UMB_URLS[env], certificate=client_cert_path,
                       private_key=client_key_path, trusted_certificates=ca_chain_path)
