from unittest.mock import MagicMock

from artbotlib import brew_list, util


def test_find_rpms_in_packages():
    koji_api = util.koji_client_session()

    pkg_names = ["cri-o", "skopeo", "glibc", "bogus-surely-never-there"]
    rpms_for_package = brew_list._find_rpms_in_packages(koji_api, pkg_names, "4.3")
    assert "cri-o" in rpms_for_package
    assert "cri-o" in rpms_for_package["cri-o"]
    assert "skopeo" in rpms_for_package
    assert "containers-common" in rpms_for_package["skopeo"]
    assert "glibc" in rpms_for_package
    assert "glibc-common" in rpms_for_package["glibc"]
    assert "bogus-surely-never-there" not in rpms_for_package


def test_find_rhcos_build_rpms():
    rpms = brew_list._find_rhcos_build_rpms(MagicMock(), "4.3")
    assert any(rpm.startswith("ostree-") for rpm in rpms)

    rpms = brew_list._find_rhcos_build_rpms(MagicMock(), "4.1", build_id="410.81.20200106.0")
    assert "openshift-hyperkube-4.1.30-202001030309.git.0.65f8a20.el8_0" in rpms

    rpms = brew_list._find_rhcos_build_rpms(MagicMock(), "4.3", arch="s390x")
    assert any(rpm.startswith("s390utils-base-") for rpm in rpms)
