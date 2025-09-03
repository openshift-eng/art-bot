import random


def greet_user(so):
    greetings = ["Hi", "Hey", "Hello", "Howdy",
                 "What's up", "Yo", "Greetings", "G'day", "Mahalo"]
    so.say(f"{greetings[random.randint(1, len(greetings)) - 1]}, {so.from_user_mention()}")


def show_help(so):
    so.say("""Here are questions I can answer...

_*ART config:*_
* What images build in `major.minor`?
* What is the image pipeline for (github|distgit|package|cdn|image) `name` [in `major.minor`]?
* What is the (brew-image|brew-component) for dist-git `name` [in `major.minor`]?
* (go|golang) config for `major.minor` `major.minor2` `major.minor3` [with|including rhel version]

_*ART releases:*_
* Which build of `image_name` is in `release image name or pullspec`?
* What (commits|catalogs|distgits|nvrs|images|rpms) are associated with `release-tag`?
* Image list advisory `advisory_id`
* What kernel is used in `release image name or pullspec`?

_*ART release/Brew monitoring:*_
* Watch `release_url|brew_url|prow_job_url|github_pr_url`
* Alert (if|when|on) `release_url` (stops being blue|fails|is rejected|is red|is accepted|is green)
* Watch latest `major.minor`
* Alert (if|when|on) prow job `Prow job URL` completes
* Alert (if|when|on) build `Brew build URL|Brew build ID` completes
* Alert (if|when|on) task `Brew task URL|Brew task ID` completes

_*ART build info:*_
* Where in `major.minor` (is|are) the `name1,name2,...` (RPM|package) used?
* What rpms were used in the latest image builds for `major.minor`?
* What rpms are in image `image-nvr`?
* Which rpm `rpm1,rpm2,...` is in image `image-nvr`?
* pr info `GitHub PR URL` [component `name`] in `major.minor` [for `arch`]
* (go|golang) version (for|of) `nvr'
* timestamp (for|of) brew event `brew-event`
* mass rebuild status

_*misc:*_
* How can I get ART to build a new image?
* Chunk (to `channel`): something you want repeated a sentence/line at a time in channel.
""")
