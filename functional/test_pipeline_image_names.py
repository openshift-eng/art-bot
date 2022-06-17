import pytest
from artbotlib.pipeline_image_names import distgit_to_brew, brew_to_cdn, cdn_to_comet, distgit_is_available, \
    DistgitNotFound, CdnFromBrewNotFound, DeliveryRepoNotFound, get_brew_id, CdnNotFound, BrewIdNotFound, \
    get_image_stream_tag, get_delivery_repo_id


def test_distgit_to_brew_1():
    actual = distgit_to_brew("openshift-enterprise-console", version="4.11")
    expected = "openshift-enterprise-console-container"

    assert actual == expected


def test_distgit_to_brew_2():
    actual = distgit_to_brew("egress-router-cni", version="4.11")
    expected = "ose-egress-router-cni-container"

    assert actual == expected


def test_distgit_to_brew_3():
    with pytest.raises(Exception) as e:
        distgit_to_brew("openshift-enterprise-console", version="4.00")
    assert e.type == DistgitNotFound


def test_brew_to_cdn1():
    actual = brew_to_cdn("openshift-enterprise-console-container", "8Base-RHOSE-4.10")
    expected = ["redhat-openshift4-ose-console"]

    assert actual == expected


def test_brew_to_cdn2():
    with pytest.raises(Exception) as e:
        brew_to_cdn("openshift-enterprise-console-container", "8Base-RHOSED-4.10")
    assert e.type == CdnFromBrewNotFound


def test_cdn_to_comet1():
    actual = cdn_to_comet("redhat-openshift4-ose-console")
    expected = "openshift4/ose-console"

    assert actual == expected


def test_cdn_to_comet2():
    with pytest.raises(Exception) as e:
        cdn_to_comet("redhat-openshift4-ose-consoleeee")
    assert e.type == DeliveryRepoNotFound or e.type == CdnNotFound


def test_distgit_repo_availability1():
    actual = distgit_is_available("openshift-enterprise-cli")
    expected = True

    assert actual == expected


def test_distgit_repo_availability2():
    actual = distgit_is_available("booyah")
    expected = False

    assert actual == expected


def test_get_brew_id1():
    actual = get_brew_id("openshift-enterprise-console-container")
    expected = 69142

    assert actual == expected


def test_get_brew_id2():
    with pytest.raises(Exception) as e:
        get_brew_id("openshift-enterprise-console-container-booyah")
    assert e.type == BrewIdNotFound


def test_get_delivery_repo_id():
    actual = get_delivery_repo_id("openshift4/ose-cli")
    expected = "5cd9ba3f5a13467289f4d51d"

    assert actual == expected


def test_check_for_payload1():
    actual = get_image_stream_tag("ose-metallb", "4.10")
    expected = None

    assert actual == expected


def test_check_for_payload2():
    actual = get_image_stream_tag("openshift-enterprise-console", "4.10")
    expected = "console"

    assert actual == expected
