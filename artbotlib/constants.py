from string import Template

RHCOS_BASE_URL = "https://releases-rhcos-art.apps.ocp-virt.prod.psi.redhat.com"

COLOR_MAPS = {
    'Accepted': 'Green',
    'Rejected': 'Red'
}
BREW_TASK_STATES = {
    "Success": "success",
    "Failure": "failure"
}

TWELVE_HOURS = 60 * 60 * 12

FIVE_MINUTES = 60 * 5

BREW_URL = 'https://brewweb.engineering.redhat.com/brew'

CGIT_URL = 'https://pkgs.devel.redhat.com/cgit'

COMET_URL = 'https://comet.engineering.redhat.com/containers/repositories'

ERRATA_TOOL_URL = 'https://errata.devel.redhat.com'

GITHUB_API_OPENSHIFT = "https://api.github.com/repos/openshift"

ART_DASH_API_ROUTE = "http://art-dash-server-art-build-dev.apps.ocp4.prod.psi.redhat.com/api/v1"

RELEASE_CONTROLLER_URL = Template('https://${arch}.ocp.releases.ci.openshift.org')

PROW_BASE_URL = 'https://prow.ci.openshift.org'

# Release Controller and RHCOS browser call arches in different ways;
# these two dictionaries easily map names from/to one namespace to the other
RC_ARCH_TO_RHCOS_ARCH = {
    'amd64': 'x86_64',
    'arm64': 'aarch64',
    'ppc64le': 'ppc64le',
    's390x': 's390x'
}

RHCOS_ARCH_TO_RC_ARCH = {
    'x86_64': 'amd64',
    'aarch64': 'arm64',
    'ppc64le': 'ppc64le',
    's390x': 's390x'
}
