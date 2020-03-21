FROM fedora:31
LABEL name="art-bot" \
  description="art-bot container image" \
  maintainer="OpenShift Automated Release Tooling (ART) Team <aos-team-art@redhat.com>"

# the build will need to run inside the firewall to access internal resources.
# install Red Hat IT Root CA and RCM repos
RUN curl -o /etc/pki/ca-trust/source/anchors/RH-IT-Root-CA.crt --fail -L \
    https://password.corp.redhat.com/RH-IT-Root-CA.crt \
 && update-ca-trust extract \
 && curl -o /etc/yum.repos.d/rcm-tools-fedora.repo https://download.devel.redhat.com/rel-eng/RCMTOOLS/rcm-tools-fedora.repo \
 && dnf install -y \
    # runtime dependencies
    krb5-workstation python-bugzilla-cli git rsync docker \
    python3 python3-certifi python3-rpm python3-rhmsg \
    # development dependencies
    gcc krb5-devel libgit2-devel openssl-devel krb5-devel \
    python3-devel python3-pip \
    # other tools
    bash-completion vim tmux procps-ng psmisc wget net-tools iproute \
    # install brewkoji
    koji brewkoji \
 && dnf clean all

ARG OC_VERSION=candidate
# include oc client
RUN wget -O /tmp/openshift-client-linux-"$OC_VERSION".tar.gz https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"$OC_VERSION"/openshift-client-linux.tar.gz \
  && tar -C /usr/local/bin -xzf  /tmp/openshift-client-linux-"$OC_VERSION".tar.gz oc kubectl \
  && rm /tmp/openshift-client-linux-"$OC_VERSION".tar.gz

# Create a non-root user - see https://aka.ms/vscode-remote/containers/non-root-user.
ARG USERNAME=dev
# On Linux, replace with your actual UID, GID if not the default 1000
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Create the "dev" user
RUN groupadd --gid "$USER_GID" "$USERNAME" \
 && useradd --uid "$USER_UID" --gid "$USER_GID" -m "$USERNAME" \
 # give it access to its files
 && mkdir -p /workspaces/{art-bot,.docker,.config} \
 && mkdir -p /workspaces/{elliott,doozer}{,-working-space} \
 && chown -R "${USER_UID}:${USER_GID}" /home/"$USERNAME" /workspaces \
 && chmod 0755 /home/"$USERNAME" \
 # and allow it passwordless sudo
 && echo "$USERNAME" ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/"$USERNAME" \
 && chmod 0440 /etc/sudoers.d/"$USERNAME"

# Preinstall dependencies
COPY ./ /workspaces/art-bot/
USER "$USER_UID"
WORKDIR /workspaces/art-bot
RUN pip3 install --user rh-doozer rh-elliott
RUN pip3 install --user -r ./requirements.txt

