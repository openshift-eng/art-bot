Build and run the art-bot container with podman
-----------------------------------------------

This assumes rootless podman on Linux. YMMV for docker.
Officially there is no podman-compose. There's a github project for it to try.

This demonstrates usage for a user lmeyer with uid/gid 3668 (as assigned in ldap).

Configure art-bot's runtime settings by copying settings.yaml to `~/.config/art-bot/settings.yaml` and editing.

To build, from the context of the top level of the repo:

    $ podman build --build-arg USERNAME=lmeyer --build-arg USER_UID=3668 -f container/Dockerfile -t art-bot .

To run, use a script like (this is specific to user lmeyer, much is optional and you'll want to vary):

    #!/bin/bash
    
    # this is where everything is checked out
    OPENSHIFT=$HOME/openshift
    CONTAINER=$OPENSHIFT/art-bot/container
    
    podman run -it --rm \
        --uidmap 0:10000:1000 --uidmap=3668:0:1 \
        -v $HOME/.config/art-bot/:/home/$USER/.config/art-bot/:ro,cached,z \
        -v ${KRB5CCNAME#FILE:}:/tmp/krb5cc:ro,cached \
        -v $HOME/.ssh:/home/$USER/.ssh:ro,cached,z \
        -v $HOME/.docker/config.json:/home/$USER/.docker/config.json:ro,cached,z \
        -v $HOME/.gitconfig:/home/$USER/.gitconfig:ro,cached,z \
        -v $HOME/.vim/:/home/$USER/.vim/:ro,cached,z \
        -v $HOME/.vimrc:/home/$USER/.vimrc:ro,cached,z \
        -v $CONTAINER/krb5-redhat.conf:/etc/krb5.conf.d/krb5-redhat.conf:ro,cached,z \
        -v $CONTAINER/brewkoji.conf:/etc/koji.conf.d/brewkoji.conf:ro,cached,z \
        -v $CONTAINER/doozer-settings.yaml:/home/$USER/.config/doozer/settings.yaml:ro,cached,z \
        -v $CONTAINER/elliott-settings.yaml:/home/$USER/.config/elliott/settings.yaml:ro,cached,z \
        -v $OPENSHIFT/art-bot/:/workspaces/art-bot/:cached,z \
        -v $OPENSHIFT/doozer/:/workspaces/doozer/:cached,z \
        -v $OPENSHIFT/elliott/:/workspaces/elliott/:cached,z \
        art-bot

- The `uidmap` bit there maps userspaces around so that the files mounted in show up with the
  same uid inside the container as out. You'll have a different uid and possible a different
  namespace range, this may take tweaking.
- If your user has a kerberos ticket it can be mounted into the container so you don't have
  to kinit all the time inside the container.
- Beware: the ~/.ssh mount will change selinux context on that dir, which generally has the
  effect of preventing sshd from seeing your public keys and logging you in if you ssh into
  your system. If that's a problem for you, then clone the directory and mount that.

That build includes a lot of slow installs that usually do not need to be repeated.
To simply update art-bot and its deps, build on top of the initial build:

    $ podman build --build-arg USERNAME=lmeyer --build-arg USER_UID=3668 -f container/Dockerfile.latest -t art-bot .

To install dev dependencies (for running tests), also build on top of the initial build:

    $ podman build --build-arg USERNAME=lmeyer --build-arg USER_UID=3668 -f container/Dockerfile.dev -t art-bot:dev .



