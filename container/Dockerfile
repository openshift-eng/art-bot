FROM registry.fedoraproject.org/fedora:33
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
    krb5-workstation git rsync \
    python3 python3-certifi python3-rpm python3-rhmsg \
    # development dependencies
    gcc krb5-devel python3-devel python3-pip \
    # other tools
    bash-completion vim tmux wget curl iputils procps-ng psmisc net-tools iproute \
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
 # give access to its files
 && mkdir -p /workspaces/art-bot \
 && mkdir -p /workspaces/{elliott,doozer}{,-working-dir} \
 && mkdir -p /home/"$USERNAME"/.config/{elliott,doozer,art-bot} \
 && mkdir -p /home/"$USERNAME"/.docker \
 && chown -R "${USER_UID}:${USER_GID}" /home/"$USERNAME" /workspaces \
 && chmod -R 0755 /home/"$USERNAME" \
 && chmod -R 0777 /workspaces \
 # and allow it passwordless sudo
 && echo "$USERNAME" ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/"$USERNAME" \
 && chmod 0440 /etc/sudoers.d/"$USERNAME"

USER "$USER_UID"
WORKDIR /workspaces/art-bot

# install dependencies (allow even openshift's random user to see)
ENV PATH=/home/"$USERNAME"/.local/bin:/home/"$USERNAME"/bin:"$PATH"
COPY requirements.txt ./
RUN umask a+rx && pip3 install --upgrade \
    git+https://github.com/openshift/doozer.git#egg=rh-doozer \
    git+https://github.com/openshift/elliott.git#egg=rh-elliott \
    -r ./requirements.txt

# install art-bot and default configs
COPY container/krb5-redhat.conf /etc/krb5.conf.d/krb5-redhat.conf
COPY . /tmp/art-bot
USER 0
RUN cp -r /tmp/art-bot/{artbotlib,umb,art-bot.py} . \
 && cp /tmp/art-bot/container/doozer-settings.yaml /home/"$USERNAME"/.config/doozer/settings.yaml \
 && cp /tmp/art-bot/container/elliott-settings.yaml /home/"$USERNAME"/.config/elliott/settings.yaml \
 && cp /tmp/art-bot/settings.yaml /home/"$USERNAME"/.config/art-bot/settings.yaml \
 && rm -rf /tmp/art-bot
USER "$USER_UID"
