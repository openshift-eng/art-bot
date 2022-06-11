import pytest
from unittest.mock import Mock
from artbotlib.pipeline_image_names import distgit_to_brew, brew_to_cdn, cdn_to_comet, distgit_is_available, \
    DistgitNotFound, CdnNotFound, DeliveryRepoNotFound


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
    expected = "redhat-openshift4-ose-console"

    assert actual == expected


def test_brew_to_cdn2():
    with pytest.raises(Exception) as e:
        brew_to_cdn("openshift-enterprise-console-container", "8Base-RHOSED-4.10")
    assert e.type == CdnNotFound


def test_cdn_to_comet1():
    actual = cdn_to_comet("redhat-openshift4-ose-console")
    expected = "openshift4/ose-console"

    assert actual == expected


def test_cdn_to_comet2():
    with pytest.raises(Exception) as e:
        cdn_to_comet("redhat-openshift4-ose-consoleeee")
    assert e.type == DeliveryRepoNotFound


def test_distgit_repo_availability1():
    actual = distgit_is_available("openshift-enterprise-cli")
    expected = True

    assert actual == expected


def test_distgit_repo_availability2():
    actual = distgit_is_available("booyah")
    expected = False

    assert actual == expected
