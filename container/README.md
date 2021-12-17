# Build and run the art-bot container with podman

## Production

Normally art-bot runs as an OpenShift workload in our ocp4 space (see
https://github.com/openshift-eng/art-docs/blob/master/infra/art-bot.md). The
container is built initially from `Dockerfile` and then code-only updates can
be added with `Dockerfile.latest` (skipping all the RPM installs etc).
Credentials and config are mounted in as secrets and configmaps.

## Development

The easiest way to test out changes quickly on the bot is to run it in a dev
mode container with appropriate external content mounted in; once this is set
up you can just stop and start to test changes, without having to rebuild the
container or even `pip install` the code.

Additionally, the bot should be configured to answer to a different name. It
uses the same slack app credentials but if addressed with a name that's not its
own, it ignores queries. This way, when you talk to @art-bot-dev then @art-bot
will not answer, and vice versa. So you can test out new stuff in situ without
making a lot of noise.

### Creating the container

This doc assumes rootless podman on Linux. YMMV for docker or docker-compose.
Officially there is no podman-compose. There's a github project to try for that.

The following demonstrates usage for a user `lmeyer` with uid/gid 3668 (as assigned in ldap).

* Configure art-bot's runtime settings by copying settings.yaml to
  `~/.config/art-bot/settings.yaml` and editing. You'll want to get the rest of
  the contents of that conf dir from our ocp4 deployment, bitwarden, etc - these
  are never to be committed in git.

* To build, from the context of the top level of this repo:

    $ podman build --build-arg USERNAME=lmeyer --build-arg USER_UID=3668 -f container/Dockerfile -t art-bot .

  This will give you a container that runs as your own user ID, which simplies
  (somewhat) using the resources mounted in from your home directory.

* The initial build includes a lot of slow installs that usually do not need to be repeated.
  To simply update art-bot and its deps, build on top of the initial build:

    $ podman build --build-arg USERNAME=lmeyer --build-arg USER_UID=3668 -f container/Dockerfile.latest -t art-bot .

* You can also build a dev container on top of this that has extra content for running tests:

    $ podman build --build-arg USERNAME=lmeyer --build-arg USER_UID=3668 -f container/Dockerfile.dev -t art-bot:dev .

To simplify these steps, here is a script that takes a parameter to build these:

```
#!/bin/bash -x
base_cmd="podman build --build-arg USERNAME=lmeyer --build-arg USER_UID=3668"

if [[ "$1" == base ]]; then
    $base_cmd -f container/Dockerfile -t art-bot:latest .
elif [[ "$1" == dev ]]; then
    $base_cmd -f container/Dockerfile.dev -t art-bot:dev .
else  # default is to just run an update
    $base_cmd -f container/Dockerfile.latest -t art-bot:latest .
fi
```

### Using the container

To run, use a script like the following:

(again specific to user `lmeyer`; much is optional and you will want to vary
according to your own layout / OS)

```
#!/bin/bash

# this is where you have checked out all the repos you need
OPENSHIFT=$HOME/openshift
# and presumably under that, this repo
CONTAINER=$OPENSHIFT/art-bot/container

# if you have a kerberos keytab you can mount in, make a copy because kerberos
# doesn't like the selinux context change when it gets mounted.
cp -a "${KRB5CCNAME#FILE:}"{,_artbot}

podman run -it --rm \
    --uidmap 0:10000:1000 --uidmap=3668:0:1 \
    -v $HOME/.config/art-bot/:/home/$USER/.config/art-bot/:ro,cached,z \
    -v ${KRB5CCNAME#FILE:}_artbot:/tmp/krb5cc:ro,cached \
    -v $HOME/.ssh:/home/$USER/.ssh:ro,cached,z \
    -v $HOME/.docker/config.json:/home/$USER/.docker/config.json:ro,cached,z \
    -v $HOME/.gitconfig:/home/$USER/.gitconfig:ro,cached,z \
    -v $HOME/.vim/:/home/$USER/.vim/:ro,cached,z \
    -v $HOME/.vimrc:/home/$USER/.vimrc:ro,cached,z \
    -v $CONTAINER/krb5-redhat.conf:/etc/krb5.conf.d/krb5-redhat.conf:ro,cached,z \
    -v $CONTAINER/doozer-settings.yaml:/home/$USER/.config/doozer/settings.yaml:ro,cached,z \
    -v $CONTAINER/elliott-settings.yaml:/home/$USER/.config/elliott/settings.yaml:ro,cached,z \
    -v $OPENSHIFT/art-bot/:/workspaces/art-bot/:cached,z \
    -v $OPENSHIFT/doozer/:/workspaces/doozer/:cached,z \
    -v $OPENSHIFT/elliott/:/workspaces/elliott/:cached,z \
        art-bot  # or artbot:dev
```

- The `uidmap` bit there maps container userspaces around so that the files
  mounted in show up with the same uid inside the container as outside. You'll
  have a different uid and possibly a different namespace range, so this may take
  tweaking. This is critical for the mounts to work as intended though.
- It's simplest to initialize $HOME/.config/art-bot/ by copying it from the
  `container/` directory in this repo and modifying `settings.yaml` according
  to the comments inside.
- `KRB5CCNAME`: If your login writes a kerberos ticket in a file (not the default, must be
  configured) it can be mounted into the container so you don't have to kinit
  all the time inside the container (but then you must restart the container when it expires).
- Beware: the ~/.ssh mount will change selinux context on that dir, which generally has the
  effect of preventing sshd from seeing your public keys and logging you in if you ssh into
  your system. If that's a problem for you, then clone the directory and mount that.
  There's probably not much actual use for this.
- Many of these are just conveniences to make the container feel like home.
- By mounting in the source code for art-bot, elliott, and doozer, you can
  experiment with changes to all of these without any commits or rebuilds. Of
  course, that means you need to keep them checked out the way you want them.

#### Running

Inside the container you should just be able to:

`./art-bot.py`

Do heed the bit in `settings.yaml` about disabling UMB first. Then you can just
hit ctrl-C to kill it and start it again.

#### Talking to the bot

It's easiest when testing to just DM the bot. You'll need to add the `art-bot` app in slack to do that.

For things that require actually being in a channel, you can just talk to it in
one of the configured "friendly" channels where it listens, or create your own
private channel and invite it there.

You'll need to address the bot by its dev name configured in settings.yaml to get a dev response. So typically:

> sosiouxme:
> hello @art-bot-dev
>
> art-bot-dev:
> Howdy, @sosiouxme

Actually this is "broken" at the moment, regular @art-bot also responds :eyeroll:

#### Testing

In a container that has the dev tools included, you can just run `pytest` to
run all available tests. This can be useful because you don't need to contend
with the slack event loop and such, but clearly we haven't made rigorous use of
it yet for actually testing functionality.
