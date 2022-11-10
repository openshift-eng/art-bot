import subprocess
import os

def do_kinit():
    """
    Function performs kinit with the already mounted keytab.
    This function is executed only in production
    :return: None
    """
    if "OPENSHIFT_BUILD_NAMESPACE" in os.environ:   # check to see if the code is in production environment
        keytab_file = "/tmp/keytab/keytab"
        kinit_request = subprocess.Popen(["kinit", "-kt", keytab_file, "ocp-build/buildvm.openshift.eng.bos.redhat.com@IPA.REDHAT.COM"],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = kinit_request.communicate()
        if error:
            print(f"Kerberos error: {error}")
