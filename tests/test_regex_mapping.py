from unittest.mock import patch

from flexmock import flexmock

from artbotlib.regex_mapping import map_command_to_regex
from artbotlib.slack_output import SlackDeveloperOutput


so = SlackDeveloperOutput()


class OutputInspector:
    def __init__(self):
        self.output = []

    def say(self, text):
        self.output.append(text)

    def reset(self):
        self.output.clear()


@patch('artbotlib.regex_mapping.greet_user')
def test_hello(greet_mock):
    """
    Verify that artbotlib.help.greet_user is called when the user says 'hello'
    """

    greet_mock.side_effect = lambda outputter: outputter.say('mock called')
    so_mock = flexmock(so)
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, 'hello', None)


@patch('artbotlib.regex_mapping.show_help')
def test_help(help_mock):
    """
    Verify that artbotlib.help.show_help is called when the user says 'help'
    """

    help_mock.side_effect = lambda outputter: outputter.say('mock called')
    so_mock = flexmock(so)
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, 'help', None)


@patch('artbotlib.regex_mapping.buildinfo_for_release')
def test_buildinfo_for_release(buildinfo_mock):
    """
    Verify that artbotlib.buildinfo.buildinfo_for_release is called for the correct queries
    """

    buildinfo_mock.side_effect = lambda outputter, **_: outputter.say('mock called')
    so_mock = flexmock(so)

    # Test valid queries: regex does not check the format of <release_img>,
    # so even queries like 'what builsfd of ironic is in 4.10' will call the function
    # The code will fail later, when trying to 'oc adm release info' an invalid release
    query = 'what build of ironic is in 4.10.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    query = 'what build of ironic is in quay.io/openshift-release-dev/ocp-release:4.12.0-ec.5-x86_64'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    query = 'what build of ironic is in 4.12.0-0.ci-2022-12-13-165927'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    query = 'what build of ironic is in registry.ci.openshift.org/ocp/release:4.12.0-0.ci-2022-12-13-165927'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.brew_list.list_component_data_for_release_tag')
def test_list_component_data_for_release_tag(brew_list_mock):
    """
    Verify that artbotlib.brew_list.list_component_data_for_release_tag is called for the correct queries
    """

    brew_list_mock.side_effect = lambda outputter, **_: outputter.say('mock called')
    so_mock = flexmock(so)

    # Test valid queries: regex does not check the format of <release_img>,
    # so even queries like 'what build of ironic is in 4.10' will call the function
    # The code will fail later, when trying to 'oc adm release info' an invalid release
    # This is a subject for functional tests
    query = 'what nvrs are associated with 4.10.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    query = 'what distgits are associated with 4.10.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    query = 'what commits are associated with 4.10.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    query = 'what catalogs are associated with 4.10.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    query = 'what images are associated with 4.10.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)


def test_invalid_component_types():
    """
    Verify that nothing is done for invalid data types
    """

    inspector = OutputInspector()

    map_command_to_regex(inspector, 'what rpms are associated with 4.10.10', None)
    assert "Sorry, the type of information you want about each component needs to be one of: " \
           "('nvr', 'distgit', 'commit', 'catalog', 'image')" in inspector.output


@patch('artbotlib.regex_mapping.kernel_info')
def test_kernel_info(kernel_info_mock):
    """
    Test valid/invalid queries for artbotlib.buildinfo.kernel_info()
    """

    kernel_info_mock.side_effect = lambda outputter, **_: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, 'what kernel is used in 4.10.10', None)

    # Valid
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, 'what kernel is used in 4.10.10 for arch amd64', None)

    # Invlid
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, 'what kernel is in 4.10.10', None)

    # Invalid
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, 'what kernel is used in 4.10.10 for amd64', None)


@patch('artbotlib.exectools.cmd_assert')
def test_list_images_in_major_minor(cmd_assert_mock):
    """
    Valid query: what images build in x.y
    Invalid query: what images build in z.y.z
    """

    so_mock = flexmock(so)
    cmd_assert_mock.return_value = (0, None, None)

    # Valid
    so_mock.should_receive('snippet').once()
    map_command_to_regex(so, 'what images build in 4.10', None)

    # Valid
    so_mock.should_receive('snippet').once()
    map_command_to_regex(so, 'what images build in 3.11', None)

    # Invalid - {major}.{minor}.{patch}
    so_mock.should_receive('snippet').never()
    map_command_to_regex(so, 'what images build in 4.10.1', None)

    # Invalid - {major}.{minor}.{patch}
    so_mock.should_receive('snippet').never()
    map_command_to_regex(so, 'what images build in 3.11.1', None)


@patch('artbotlib.brew_list.list_components_for_major_minor')
def test_list_components_for_major_minor(list_components_mock):
    """
    Valid query: what rpms were used in the latest image builds for 4.10
    Invalid query: what rpms were used in the latest image builds for 4.10.1
    """

    list_components_mock.side_effect = lambda outputter, **_: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, 'what rpms were used in the latest image builds for 4.10', None)

    # Invalid - {major}.{minor}.{patch}
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, 'what rpms were used in the latest image builds for 4.10.1', None)


@patch('artbotlib.brew_list.list_components_for_image')
def test_list_components_for_image(list_components_mock):
    """
    Valid query: 'what rpms are in image ose-installer-container-v4.10.0-202209241557.p0.gb7e59a8.assembly.stream'
    """

    list_components_mock.side_effect = lambda outputter, **_: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'what rpms are in image ose-installer-container-v4.10.0-202209241557.p0.gb7e59a8.assembly.stream'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'which rpms are in image ose-installer-container-v4.10.0-202209241557.p0.gb7e59a8.assembly.stream'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid query - missing 'image'
    query = 'what rpms are in ose-installer-container-v4.10.0-202209241557.p0.gb7e59a8.assembly.stream'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.brew_list.specific_rpms_for_image')
def test_specific_rpms_for_image(specific_components_mock):
    """
    Test valid/invalid queries for specific_rpms_for_image()
    """

    specific_components_mock.side_effect = lambda outputter, **_: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'what rpm ovn is in image ' \
            'ose-ovn-kubernetes-container-v4.7.0-202108160002.p0.git.9581e60.assembly.stream'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'image'
    query = 'what rpm ovn is in ose-ovn-kubernetes-container-v4.7.0-202108160002.p0.git.9581e60.assembly.stream'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'which rpms ovn, zlib are in image ' \
            'ose-ovn-kubernetes-container-v4.7.0-202108160002.p0.git.9581e60.assembly.stream'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'image'
    query = 'what rpms ovn, zlib are in ose-ovn-kubernetes-container-v4.7.0-202108160002.p0.git.9581e60.assembly.stream'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.alert_on_build_complete')
def test_alert_on_build_complete(alert_mock):
    """
    Test valid/invalid queries for alert_on_build_complete()
    """

    alert_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'alert when build 123456 completes'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert if build https://brewweb.engineering.redhat.com/brew/buildinfo?buildid=123456 completes'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'build'
    query = 'alert when https://brewweb.engineering.redhat.com/brew/buildinfo?buildid=123456 completes'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.pr_info')
def test_pr_info(pr_info_mock):
    """
    Test valid/invalid queries for pr_info()
    """

    pr_info_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'pr info https://github.com/openshift/ptp-operator/pull/281 in 4.12'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - wrong PR URL
    query = 'pr info https://github.com/openshift/ptp-operator/281 in 4.12'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'pr info https://github.com/openshift/ptp-operator/pull/281 component ptp-operator in 4.12'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - component before PR url
    query = 'pr info component ptp-operator https://github.com/openshift/ptp-operator/pull/281 in 4.12'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'pr info https://github.com/openshift/ptp-operator/pull/281 component ptp-operator in 4.12 for arch amd64'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - arch before version
    query = 'pr info https://github.com/openshift/ptp-operator/pull/281 component ptp-operator for arch amd64 in 4.12'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.elliott.image_list')
def test_image_list_advisory(image_list_mock):
    """
    Test valid/invalid queries for elliott.image_list()
    """

    image_list_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'image list for advisory 79678'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image list of advisory 79678'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image list advisory 79678'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'advisory'
    query = 'image list 79678'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing advisory ID
    query = 'image list for advisory'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.brew_list.list_uses_of_rpms')
def test_list_uses_of_rpms(uses_mock):
    """
    Test valid/invalid queries for brew_list.list_uses_of_rpms()
    """

    uses_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'where in 4.10 is the ovn rpm used'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - {major}.{minor}.{patch}
    query = 'where in 4.10.1 is the ovn rpm used'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'where in 4.10 is the ovn package used'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'where in 4.10 are the rpm1,rpm2,rpm3 rpms used'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - spaces between rpm names
    query = 'where in 4.10 are the rpm1, rpm2, rpm3 rpms used'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.translate_names')
def test_translate_names(translate_mock):
    """
    Test valid/invalid queries for translation.translate_names()
    """

    translate_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'what is the brew-image for distgit ironic'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing component name
    query = 'what is the brew-image for distgit'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'what is the brew-image for dist-git ironic'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'what is the brew-component for dist-git ironic'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - invalid name 'brew component'
    query = 'what is the brew component for dist-git ironic'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - invalid name 'invalid-name'
    query = 'what is the brew-component for invalid-name ironic'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'what is the brew-component for dist-git ironic in 4.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - {major}.{minor}.{patch}
    query = 'what is the brew-component for dist-git ironic in 4.10.1'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.pipeline_from_github')
def test_pipeline_from_github(pipeline_mock):
    """
    Test valid/invalid queries for pipeline_image_names.pipeline_from_github()
    """

    pipeline_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'image pipeline for github https://github.com/openshift/oc'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'pipeline for github https://github.com/openshift/oc'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - `www`
    query = 'image pipeline for github https://www.github.com/openshift/oc'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid
    query = 'image pipeline for github http://github.com/openshift/oc'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - ssh
    query = 'image pipeline for github git@github.com:openshift/oc.git'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for github https://github.com/openshift/oc.git'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for github https://github.com/openshift/oc in 4.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - {major}.{minor}.{patch}
    query = 'image pipeline for github https://github.com/openshift/oc in 4.10.1'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.pipeline_from_distgit')
def test_pipeline_from_distgit(pipeline_mock):
    """
    Test valid/invalid queries for pipeline_image_names.pipeline_from_distgit()
    """

    pipeline_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'image pipeline for distgit ironic'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'pipeline for distgit ironic'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for distgit ironic in 4.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - {major}.{minor}.{patch}
    query = 'image pipeline for distgit ironic in 4.10.1'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for distgit containers/ironic'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'distgit'
    query = 'image pipeline for ironic'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for distgit containers/ironic in 4.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.pipeline_from_brew')
def test_pipeline_from_brew(pipeline_mock):
    """
    Test valid/invalid queries for pipeline_image_names.pipeline_from_brew()
    """

    pipeline_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'image pipeline for package ironic-container'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'pipeline for package ironic-container'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for package ironic-container in 4.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - {major}.{minor}.{patch}
    query = 'image pipeline for package ironic-container in 4.10.1'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'in' before version
    query = 'image pipeline for package ironic-container 4.10'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'package'
    query = 'image pipeline for ironic-container in 4.10'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.pipeline_from_cdn')
def test_pipeline_from_cdn(pipeline_mock):
    """
    Test valid/invalid queries for pipeline_image_names.pipeline_from_cdn()
    """

    pipeline_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'image pipeline for cdn <name>'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'pipeline for cdn <name>'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for cdn <name> in 4.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - {major}.{minor}.{patch}
    query = 'image pipeline for cdn <name> in 4.10.1'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'in' before version
    query = 'image pipeline for cdn <name> 4.10'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'cdn'
    query = 'image pipeline for <name> in 4.10'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.pipeline_from_delivery')
def test_pipeline_from_delivery(pipeline_mock):
    """
    Test valid/invalid queries for pipeline_image_names.pipeline_from_delivery()
    """

    pipeline_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'image pipeline for image registry.redhat.io/openshift4/name'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for image openshift4/name'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for image name'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'pipeline for image registry.redhat.io/openshift4/name'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'image pipeline for image registry.redhat.io/openshift4/name in 4.10'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - {major}.{minor}.{patch}
    query = 'image pipeline for image registry.redhat.io/openshift4/name in 4.10.1'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'in' before version
    query = 'image pipeline for image registry.redhat.io/openshift4/name 4.10'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing 'image'
    query = 'image pipeline for registry.redhat.io/openshift4/name'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.nightly_color_status')
def test_nightly_color_status(pipeline_mock):
    """
    Test valid/invalid queries for pipeline_image_names.nightly_color_status()
    """

    pipeline_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'alert if https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 stops being blue'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert when https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 stops being blue'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert on https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 stops being blue'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert if https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 fails'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert if https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 is rejected'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert if https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 is red'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert if https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 is accepted'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert if https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 is green'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Invalid - 'has failed'
    query = 'alert if https://amd64.ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 has failed'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)

    # Invalid - missing arch
    query = 'alert if https://ocp.releases.ci.openshift.org/releasestream/4.13.0-0.ci/release/' \
            '4.13.0-0.ci-2022-12-19-111818 stops being blue'
    so_mock.should_receive('say').never()
    map_command_to_regex(so_mock, query, None)


@patch('artbotlib.regex_mapping.first_prow_job_succeedes')
def test_first_prow_job_succeedes(pipeline_mock):
    """
    Test valid/invalid queries for prow.first_prow_job_succeedes()
    """

    pipeline_mock.side_effect = lambda outputter, *_, **__: outputter.say('mock called')
    so_mock = flexmock(so)

    # Valid
    query = 'alert when first prow job in https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/' \
            'release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344 ' \
            'https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/' \
            'release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344 succeedes'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert when first prow job in https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/' \
            'release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344 succeedes'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert when first prow job in       https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/' \
            'release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344 succeedes'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)

    # Valid
    query = 'alert when first prow job in       https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/' \
            'release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344     ' \
            'https://prow.ci.openshift.org/view/gs/origin-ci-test/logs/' \
            'release-openshift-origin-installer-e2e-azure-upgrade/1612684208528953344 succeedes'
    so_mock.should_receive('say').once()
    map_command_to_regex(so_mock, query, None)
