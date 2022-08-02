import subprocess


def do_kinit():
    """
    Function performs kinit with the already mounted keytab
    :return: None
    """

    keytab_file = "/tmp/keytab/keytab"
    kinit_request = subprocess.Popen(["kinit", "-kt", keytab_file, "ocp-build/buildvm.openshift.eng.bos.redhat.com@IPA.REDHAT.COM"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = kinit_request.communicate()
    if error:
        print(f"Kerberos error: {error}")

