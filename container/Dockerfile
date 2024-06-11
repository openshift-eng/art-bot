FROM registry.fedoraproject.org/fedora:38
LABEL name="art-bot" \
  description="art-bot container image" \
  maintainer="OpenShift Automated Release Tooling (ART) Team <aos-team-art@redhat.com>"

# This build will need to be run inside the firewall to access internal resources.
# Install Red Hat IT Root CA and RCM repos, runtime dependencies, and upgrade pip
RUN curl -o /etc/pki/ca-trust/source/anchors/RH-IT-Root-CA.crt --fail -L \
    https://certs.corp.redhat.com/certs/2015-IT-Root-CA.pem \
 && curl -o /etc/pki/ca-trust/source/anchors/2022-IT-Root-CA.pem --fail -L \
    https://certs.corp.redhat.com/certs/2022-IT-Root-CA.pem \
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
 && dnf clean all \
    # upgrade pip
 && pip3 install --upgrade pip

# Install OpenShift Client
ARG OC_VERSION=candidate
RUN wget -O /tmp/openshift-client-linux-"$OC_VERSION".tar.gz https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"$OC_VERSION"/openshift-client-linux-amd64-rhel8.tar.gz \
  && tar -C /usr/local/bin -xzf  /tmp/openshift-client-linux-"$OC_VERSION".tar.gz oc kubectl \
  && rm /tmp/openshift-client-linux-"$OC_VERSION".tar.gz

# Create a non-root user - see https://aka.ms/vscode-remote/containers/non-root-user.
ARG USERNAME=dev
# On Linux, replace with your actual UID, GID if not the default 1000
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid "$USER_GID" "$USERNAME" \
 && useradd --uid "$USER_UID" --gid "$USER_GID" -m "$USERNAME" \
 && mkdir -p /workspaces/art-bot /workspaces/{elliott,doozer}{,-working-dir} \
    /home/"$USERNAME"/.config/{elliott,doozer,art-bot} /home/"$USERNAME"/.docker \
 && chown -R "${USER_UID}:${USER_GID}" /home/"$USERNAME" /workspaces \
 && chmod -R 0755 /home/"$USERNAME" \
 && chmod -R 0777 /workspaces \
 && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/"$USERNAME" \
 && chmod 0440 /etc/sudoers.d/"$USERNAME"

# Set work directory
WORKDIR /workspaces/art-bot

# Fixes issue "ERROR: Cannot uninstall requests 2.25.1, RECORD file not found. Hint: The package was installed by rpm."
RUN rpm -e --nodeps python3-requests

# Clone art-tools and run install.sh script
RUN git clone https://github.com/openshift-eng/art-tools.git art-tools \
 && cd art-tools \
 && ./install.sh

# Install dependencies from requirements.txt
COPY requirements.txt ./
RUN pip3 install --upgrade -r requirements.txt

# Install art-bot and default configs
COPY container/krb5-redhat.conf /etc/krb5.conf
COPY . /tmp/art-bot
RUN cp -r /tmp/art-bot/{artbotlib,art-bot.py,art_bot_dev.py} . \
 && cp /tmp/art-bot/container/doozer-settings.yaml /home/"$USERNAME"/.config/doozer/settings.yaml \
 && cp /tmp/art-bot/container/elliott-settings.yaml /home/"$USERNAME"/.config/elliott/settings.yaml \
 && rm -rf /tmp/art-bot

# Set non-root user
USER "$USER_UID"
