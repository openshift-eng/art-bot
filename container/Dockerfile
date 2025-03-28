FROM registry.fedoraproject.org/fedora:41
LABEL name="art-bot" \
  description="art-bot container image" \
  maintainer="OpenShift Automated Release Tooling (ART) Team <aos-team-art@redhat.com>"

# This build will need to be run inside the firewall to access internal resources.
# Install Red Hat IT Root CA and RCM repos, runtime dependencies, and upgrade pip
# Install Red Hat IT Root CA and RCM repos, runtime dependencies, and upgrade pip
RUN curl -o /etc/pki/ca-trust/source/anchors/Current-IT-Root-CAs.pem --fail -L \
    https://certs.corp.redhat.com/certs/Current-IT-Root-CAs.pem \
 && update-ca-trust extract \
 && curl -o /etc/yum.repos.d/rcm-tools-fedora.repo https://download.devel.redhat.com/rel-eng/RCMTOOLS/rcm-tools-fedora.repo \
 && dnf install -y \
    # runtime dependencies
    krb5-workstation git rsync \
    python3.11 python3-certifi python3-rpm python3-rhmsg \
    # development dependencies
    gcc krb5-devel python3.11-devel python3-pip \
    # rust and maturin for pydantic-core build
    rust cargo \
    # other tools
    bash-completion vim tmux wget curl iputils procps-ng psmisc net-tools iproute \
    # install brewkoji
    koji brewkoji \
 && dnf clean all \
    # install pip manually for python3.11
 && curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py \
 && python3.11 get-pip.py \
 && rm get-pip.py \
    # Install maturin for building Rust extensions
 && pip install maturin


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

# Set non-root user
USER "$USER_UID"

# Create a virtual environment
RUN python3.11 -m venv venv \
  # upgrade pip
  && /workspaces/art-bot/venv/bin/python -m pip install --upgrade pip

# Clone art-tools and install dependencies
RUN git clone https://github.com/openshift-eng/art-tools.git art-tools \
 && cd art-tools \
 && /workspaces/art-bot/venv/bin/python -m pip install artcommon/ -e doozer/ -e elliott/ -e pyartcd/ -e ocp-build-data-validator/ \
 && cd .. \
 && rm -rf art-tools
