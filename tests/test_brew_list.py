import flexmock
from mock import Mock
import pytest
from unittest.mock import patch, MagicMock

from artbotlib import brew_list, constants, rhcos


@pytest.mark.parametrize("params, expected",
                         [
                             [("4.5",), f"{constants.RHCOS_BASE_URL}/storage/releases/rhcos-4.5"],
                             [("4.5", "s390x"), f"{constants.RHCOS_BASE_URL}/storage/releases/rhcos-4.5-s390x"],
                         ]
                         )
def test_rhcos_release_url(params, expected):
    assert expected == rhcos.rhcos_release_url(*params)


@pytest.mark.parametrize("params, expected",
                         [
                             [("4.2", "spam"), f"{constants.RHCOS_BASE_URL}/storage/releases/rhcos-4.2/spam"],
                             [("4.5", "eggs"), f"{constants.RHCOS_BASE_URL}/storage/releases/rhcos-4.5/eggs/x86_64"],
                             [("4.5", "bacon", "s390x"),
                              f"{constants.RHCOS_BASE_URL}/storage/releases/rhcos-4.5-s390x/bacon/s390x"],
                         ]
                         )
def test_rhcos_build_url(params, expected):
    assert expected == rhcos.rhcos_build_url(*params)


@patch("requests.get")
def test_get_raw_group_config(get):
    get.return_value.text = '{"vars": {"MAJOR": 4, "MINOR": 10 }}'
    assert brew_list._get_raw_group_config("4.10") == {"vars": {"MAJOR": 4, "MINOR": 10}}


@patch("requests.get")
def test_get_et_config(get):
    get.return_value.text = """
    brew_tag_product_version_mapping:
        rhaos-{MAJOR}.{MINOR}-rhel-7-candidate: RHEL-7-OSE-{MAJOR}.{MINOR}
        rhaos-{MAJOR}.{MINOR}-rhel-8-candidate: OSE-{MAJOR}.{MINOR}-RHEL-8
    """
    replace_vars = {"MAJOR": 4, "MINOR": 10}
    assert brew_list._get_et_config("4.10", replace_vars=replace_vars) == {
        "brew_tag_product_version_mapping": {
            "rhaos-4.10-rhel-7-candidate": "RHEL-7-OSE-4.10",
            "rhaos-4.10-rhel-8-candidate": "OSE-4.10-RHEL-8",
        }
    }


@patch("artbotlib.brew_list._get_et_config")
@patch("artbotlib.brew_list._get_raw_group_config")
def test_tags_for_version(_get_raw_group_config: Mock, _get_et_config: Mock):
    major, minor = 4, 10
    _get_raw_group_config.return_value = {"vars": {"MAJOR": major, "MINOR": minor}}
    replace_vars = _get_raw_group_config.return_value["vars"]
    _get_et_config.return_value = {
        "brew_tag_product_version_mapping": {
            f"rhaos-{major}.{minor}-rhel-7-candidate": f"RHEL-7-OSE-{major}.{minor}",
            f"rhaos-{major}.{minor}-rhel-8-candidate": f"OSE-{major}.{minor}-RHEL-8",
        }
    }
    assert sorted(["rhaos-4.10-rhel-8-candidate", "rhaos-4.10-rhel-7-candidate"]) == sorted(brew_list._tags_for_version("4.10"))
    _get_raw_group_config.assert_called_once_with("openshift-4.10")
    _get_et_config.assert_called_once_with("openshift-4.10", replace_vars=replace_vars)


def _urlopen_cm(mock_urlopen, content, rc=200):
    cm = MagicMock()
    cm.getcode.return_value = rc
    cm.read.return_value = content
    cm.__enter__.return_value = cm
    mock_urlopen.return_value = cm


@patch('urllib.request.urlopen')
@pytest.mark.parametrize("content, expected",
                         [
                             [b'{ "builds": [] }', None],
                             [b'{ "builds": ["spam", "eggs", "bacon"] }', "spam"],
                             [b'{ "builds": [ {"id": "cleese"} ] }', "cleese"],
                         ]
                         )
def test_find_latest_rhcos_build_id(mock_urlopen, content, expected):
    so = MagicMock()
    _urlopen_cm(mock_urlopen, content)
    assert expected == brew_list._find_latest_rhcos_build_id(so, "dummy")


@patch('urllib.request.urlopen')
@pytest.mark.parametrize("content, expected",
                         [
                             [b'{ }', set()],
                             [
                                 b'''{
                                       "rpmostree.rpmdb.pkglist" : [
                                         [
                                           "NetworkManager",
                                           "1",
                                           "1.20.0",
                                           "5.el8_1",
                                           "x86_64"
                                         ],
                                         [
                                           "NetworkManager-libnm",
                                           "1",
                                           "1.20.0",
                                           "5.el8_1",
                                           "x86_64"
                                         ]
                                       ]
                                     }''',
                                 {"NetworkManager-1.20.0-5.el8_1", "NetworkManager-libnm-1.20.0-5.el8_1"},
                             ],
                         ]
                         )
def test_find_latest_rhcos_build_rpms(mock_urlopen, content, expected):
    so = MagicMock()
    flexmock.flexmock(brew_list, _find_latest_rhcos_build_id="dummy")
    _urlopen_cm(mock_urlopen, content)
    assert expected == brew_list._find_rhcos_build_rpms(so, "m_m")


@pytest.mark.parametrize("pkg_name, tag1_builds, tag2_builds, tag1_rpms, tag2_rpms, expected",
                         [
                             (
                                 "spam",
                                 [dict(build_id="id1")],
                                 [dict(build_id="id2")],
                                 [dict(name="spam"), dict(name="spam-devel")],
                                 [dict(name="python3-spam")],
                                 dict(spam={"spam", "spam-devel", "python3-spam"}),
                             ),
                             (
                                 "spam", [], [],
                                 [dict(name="spam"), dict(name="spam-devel")], [],
                                 dict(spam={"spam", "spam-devel"}),
                             ),
                         ]
                         )
def test_find_rpms_in_packages(pkg_name, tag1_builds, tag2_builds, tag1_rpms, tag2_rpms, expected):
    koji_api = flexmock.flexmock()
    koji_api.should_receive("getLatestBuilds").and_return(tag1_builds).and_return(tag2_builds)
    koji_api.should_receive("listBuildRPMs").and_return(tag1_rpms).and_return(tag2_rpms)
    # in the case where no builds are tagged, these will be hit to find a build
    koji_api.should_receive("getPackage").and_return(dict(id="dummy"))
    koji_api.should_receive("listBuilds").and_return([dict(build_id="dummy")])

    assert expected == brew_list._find_rpms_in_packages(koji_api, [pkg_name], "4.3")


@pytest.mark.parametrize("rpm_nvrs, rpms_search, expected_rpms4img, expected_rpms",
                         [
                             (
                                 ["spam-1.0-1.el8", "bacon-eggs-2.3-4.el7"],  # rpms from rhcos build
                                 {"spam", "bacon"},  # rpms we're looking for
                                 dict(RHCOS={"spam-1.0-1.el8"}),  # filtered first by second
                                 {"spam"},  # rpms we saw
                             ),
                         ]
                         )
def test_index_rpms_in_rhcos(rpm_nvrs, rpms_search, expected_rpms4img, expected_rpms):
    rpms_for_image = {}
    rpms_seen = set()
    brew_list._index_rpms_in_rhcos(rpm_nvrs, rpms_search, rpms_for_image, rpms_seen)
    assert expected_rpms4img == rpms_for_image
    assert expected_rpms == rpms_seen


@pytest.mark.parametrize("rpms_for_image_nvr, rpms_search, expected_rpms4img, expected_rpms",
                         [
                             (
                                 dict(  # images and the rpms that are in them
                                     image1=["SpAm-1.0-1.el8.noarch", "bacon-eggs-2.3-4.el7.noarch"],
                                     image2=["SpAm-2.0-1.el8.noarch", "eggs-3.4-5.el7.noarch"],
                                     image3=["john-2.0-1.el8.noarch", "cleese-3.4-5.el7.noarch"],
                                 ),
                                 {"spam", "bacon", "eggs"},  # rpms we're looking for, lowercase
                                 dict(  # filtered by search set, arch removed
                                     image1={"SpAm-1.0-1.el8"},
                                     image2={"SpAm-2.0-1.el8", "eggs-3.4-5.el7"},
                                 ),
                                 {"spam", "eggs"},  # rpms we saw
                             ),
                         ]
                         )
def test_index_rpms_in_images(rpms_for_image_nvr, rpms_search, expected_rpms4img, expected_rpms):
    rpms_for_image = {}
    rpms_seen = set()
    image_nvrs = rpms_for_image_nvr.keys()
    (
        flexmock.flexmock(brew_list).should_receive("brew_list_components")
        .and_return(rpms_for_image_nvr[nvr] for nvr in image_nvrs).one_by_one()
    )

    brew_list._index_rpms_in_images(image_nvrs, rpms_search, rpms_for_image, rpms_seen)
    assert expected_rpms4img == rpms_for_image
    assert expected_rpms == rpms_seen


class MockSlackOutput:
    def __init__(self):
        self.said = ""
        self.said_monitoring = ""

    def say(self, msg):
        self.said += msg

    def monitoring_say(self, msg):
        self.said_monitoring += msg

    def snippet(self, payload, intro, filename):
        self.said += f"{intro}\n{payload}"


@pytest.fixture
def so():
    return MockSlackOutput()


def test_list_uses_of_rpms_invalid_name(so):
    brew_list.list_uses_of_rpms(so, ",,,,", "4", "0", search_type="RPM")
    assert "Invalid RPM name" in so.said


def test_list_uses_of_rpms_brew_failure(so):
    flexmock.flexmock(brew_list.util).should_receive("koji_client_session").and_raise(Exception("bork"))
    brew_list.list_uses_of_rpms(so, "spam", "4", "0")
    assert "bork" in so.said_monitoring
    assert "Failed to connect to brew" in so.said


def test_list_uses_of_rpms_unknown_packages(so):
    flexmock.flexmock(brew_list.util).should_receive("koji_client_session").and_return(object())
    flexmock.flexmock(brew_list).should_receive("_find_rpms_in_packages").and_return({})
    brew_list.list_uses_of_rpms(so, "spam", "4", "0", "package")
    assert "Could not find any package" in so.said


@pytest.mark.parametrize("names, rpms_for_package, rpms_for_image, rhcos_rpms, expect_to_say, expect_not_to_say",
                         [
                             (  # basic search by package
                                 "spam,eggs",  # names the user is searching for
                                 dict(spam=["spam-eggs", "spam-sausage"], eggs=["eggs"]),
                                 # rpms built for pkgs (for a package search)
                                 dict(imgspam=["sausage-4.0-1.el8.noarch"]),  # images containing rpms
                                 ["sausage-4.0-1.el8.noarch"],  # rpms in rhcos
                                 ["nothing in 4.0 uses that"],
                                 # should see this (none of the search rpms were present)
                                 ["sausage"],  # should not see
                             ),
                             (  # package search where some but not all are missing
                                 "spam,eggs,bacon",  # names the user is searching for
                                 dict(spam=["spam-eggs", "spam-sausage"], bacon=["bacon"]),
                                 # rpms built for pkgs (for a package search)
                                 dict(imgspam=["spam-eggs-4.0-1.el8.noarch"]),  # images containing rpms
                                 ["sausage-4.0-1.el8.noarch"],  # rpms in rhcos
                                 [  # should see
                                     "Could not find package(s) ['eggs'] in brew",
                                     "package spam includes rpm(s): {'spam-eggs'}",
                                     "imgspam uses {'spam-eggs",
                                 ],
                                 ["spam-sausage"],  # should not see
                             ),
                             (  # basic search by rpm
                                 "spam,eggs",  # names the user is searching for
                                 None,  # not a pkg search, names are rpm names
                                 dict(imgspam=["spam-4.0-1.el8.noarch"]),  # images containing rpms
                                 ["eggs-4.0-1.el8", "baked-beans-4-1.el8"],  # rpms in rhcos
                                 ["imgspam uses {'spam-4.0-1.el8'}", "RHCOS uses {'eggs-4.0-1.el8'}"],
                                 # should see these
                                 ["baked-beans"],  # should not see
                             ),
                         ]
                         )
def test_list_uses_of_pkgs(so, names, rpms_for_package, rpms_for_image, rhcos_rpms, expect_to_say, expect_not_to_say):
    major, minor = "4", "0"
    search_type = "package" if rpms_for_package else "rpm"

    flexmock.flexmock(brew_list.util).should_receive("koji_client_session").and_return(object())
    flexmock.flexmock(brew_list).should_receive("_find_rpms_in_packages").and_return(rpms_for_package)
    flexmock.flexmock(brew_list).should_receive("latest_images_for_version").and_return(rpms_for_image.keys())
    flexmock.flexmock(brew_list, brew_list_components=lambda nvr: rpms_for_image[nvr])
    flexmock.flexmock(brew_list).should_receive("_find_rhcos_build_rpms").and_return(rhcos_rpms)

    brew_list.list_uses_of_rpms(so, names, major, minor, search_type)
    for phrase in expect_to_say:
        assert phrase in so.said
    for phrase in expect_not_to_say:
        assert phrase not in so.said
