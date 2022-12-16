import pytest
from artbotlib import exceptions, constants
from artbotlib import pipeline_image_util as img_util


def test_availability_github1():
    test_repo = "coredns"
    response = img_util.github_repo_is_available(test_repo)

    assert response


def test_availability_github2():
    test_repo = "coredns1234"
    response = img_util.github_repo_is_available(test_repo)

    assert not response


def test_github_to_distgit1():
    test_repo = "cluster-resource-override-admission-operator"
    response = img_util.github_to_distgit(test_repo, "4.10")
    assert 'clusterresourceoverride-operator' in response


def test_github_to_distgit2():
    test_repo = "cluster-resource-override-admission-operator1234"

    with pytest.raises(Exception) as e:
        _ = img_util.github_to_distgit(test_repo, "4.10")
    assert e.type == exceptions.DistgitFromGithubNotFound


def test_distgit_repo_availability1():
    response = img_util.distgit_is_available("openshift-enterprise-cli")

    assert response


def test_distgit_repo_availability2():
    response = img_util.distgit_is_available("booyah")

    assert response is not None


def test_distgit_to_github1():
    distgit = "clusterresourceoverride-operator"
    actual = img_util.distgit_to_github(distgit, "4.10")
    expected = "cluster-resource-override-admission-operator"

    assert actual == expected


def test_distgit_to_github2():
    distgit = "clusterresourceoverride-operator1234"

    with pytest.raises(Exception) as e:
        _ = img_util.distgit_to_github(distgit, "4.10")
    assert e.type == exceptions.GithubFromDistgitNotFound


def test_distgit_to_brew_1():
    actual = img_util.distgit_to_brew("openshift-enterprise-console", version="4.11")
    expected = "openshift-enterprise-console-container"

    assert actual == expected


def test_distgit_to_brew_2():
    actual = img_util.distgit_to_brew("egress-router-cni", version="4.11")
    expected = "ose-egress-router-cni-container"

    assert actual == expected


def test_distgit_to_brew_3():
    with pytest.raises(Exception) as e:
        img_util.distgit_to_brew("openshift-enterprise-console", version="4.00")
    assert e.type == exceptions.DistgitNotFound


def test_distgit_delivery():
    actual = img_util.distgit_to_delivery("clusterresourceoverride-operator", "4.10", "8Base-RHOSE-4.10")
    expected = f"""Production brew builds: <{constants.BREW_URL}/packageinfo?packageID=73711|*ose-clusterresourceoverride-operator-container*>
Bundle Component: *ose-clusterresourceoverride-operator-metadata-component*
Bundle Distgit: *clusterresourceoverride-operator-bundle*
CDN repo: <{constants.ERRATA_TOOL_URL}/product_versions/1625/cdn_repos/12950|*redhat-openshift4-ose-clusterresourceoverride-rhel8-operator*>
Delivery (Comet) repo: <{constants.COMET_URL}/5f6d2a2049dbe0cdd0373f29|*openshift4/ose-clusterresourceoverride-rhel8-operator*>\n\n"""

    assert actual == expected


def test_brew_is_available1():
    test_repo = "ose-clusterresourceoverride-operator-container"
    response = img_util.brew_is_available(test_repo)

    assert response


def test_brew_is_available2():
    test_repo = "ose-clusterresourceoverride-operator-container1234"
    response = img_util.brew_is_available(test_repo)

    assert not response


def test_brew_to_github():
    actual = img_util.brew_to_github("ose-clusterresourceoverride-operator-container", "4.10")
    expected = f"""Upstream GitHub repository: <https://github.com/openshift/cluster-resource-override-admission-operator|*openshift/cluster-resource-override-admission-operator*>
Private GitHub repository: <https://github.com/openshift-priv/cluster-resource-override-admission-operator|*openshift-priv/cluster-resource-override-admission-operator*>
Production dist-git repo: <{constants.CGIT_URL}/containers/clusterresourceoverride-operator|*clusterresourceoverride-operator*>
Bundle Component: *ose-clusterresourceoverride-operator-metadata-component*
Bundle Distgit: *clusterresourceoverride-operator-bundle*\n"""

    assert actual == expected


def test_get_brew_id1():
    actual = img_util.get_brew_id("openshift-enterprise-console-container")
    expected = 69142

    assert actual == expected


def test_get_brew_id2():
    with pytest.raises(Exception) as e:
        _ = img_util.get_brew_id("openshift-enterprise-console-container-booyah")
    assert e.type == exceptions.BrewIdNotFound


def test_brew_to_cdn1():
    actual = img_util.brew_to_cdn("openshift-enterprise-console-container", "8Base-RHOSE-4.10")
    expected = ["redhat-openshift4-ose-console"]

    assert actual == expected


def test_brew_to_cdn2():
    with pytest.raises(Exception) as e:
        _ = img_util.brew_to_cdn("openshift-enterprise-console-container123", "8Base-RHOSE-4.10")
    assert e.type == exceptions.CdnFromBrewNotFound


def test_brew_to_delivery():
    actual = img_util.brew_to_delivery("ose-clusterresourceoverride-operator-container", "8Base-RHOSE-4.10")
    expected = f"""CDN repo: <{constants.ERRATA_TOOL_URL}/product_versions/1625/cdn_repos/12950|*redhat-openshift4-ose-clusterresourceoverride-rhel8-operator*>
Delivery (Comet) repo: <{constants.COMET_URL}/5f6d2a2049dbe0cdd0373f29|*openshift4/ose-clusterresourceoverride-rhel8-operator*>\n\n"""

    assert actual == expected


def test_doozer_brew_distgit():
    response = img_util.doozer_brew_distgit("4.10")

    assert len(response) == 209


def test_brew_to_distgit():
    actual = img_util.brew_to_distgit("ose-clusterresourceoverride-operator-container", "4.10")
    expected = "clusterresourceoverride-operator"

    assert actual == expected


def test_cdn_is_available1():
    response = img_util.cdn_is_available("redhat-openshift4-ose-clusterresourceoverride-rhel8-operator")

    assert response


def test_cdn_is_available2():
    response = img_util.cdn_is_available("not-a-cdn-repo1234")

    assert not response


def test_get_cdn_repo_details1():
    response = img_util.get_cdn_repo_details("redhat-openshift4-ose-clusterresourceoverride-rhel8-operator")
    assert response is not None


def test_get_cdn_repo_details2():
    with pytest.raises(Exception) as e:
        _ = img_util.get_cdn_repo_details("not-a-cdn-repo1234")
    assert e.type == exceptions.CdnNotFound


def cdn_to_delivery1():
    actual = img_util.cdn_to_delivery("redhat-openshift4-ose-console")
    expected = "openshift4/ose-console"

    assert actual == expected


def cdn_to_delivery2():
    with pytest.raises(Exception) as e:
        _ = img_util.cdn_to_delivery("redhat-openshift4-ose-consoleeee")
    assert e.type == exceptions.DeliveryRepoNotFound or e.type == exceptions.CdnNotFound


def test_get_cdn_repo_id():
    actual = img_util.get_cdn_repo_id("redhat-openshift4-ose-clusterresourceoverride-rhel8-operator")
    expected = 12950

    assert actual == expected


def test_cdn_to_brew():
    actual = img_util.cdn_to_brew("redhat-openshift4-ose-clusterresourceoverride-rhel8-operator")
    expected = "ose-clusterresourceoverride-operator-container"

    assert actual == expected


def test_get_variant_id():
    actual = img_util.get_variant_id("redhat-openshift4-ose-cli-alt-rhel8", "8Base-RHOSE-4.10")
    expected = 3678

    assert actual == expected


def test_get_product_id():
    actual = img_util.get_product_id(3678)
    expected = 1625

    assert actual == expected


def test_cdn_to_github():
    actual = img_util.cdn_to_github("redhat-openshift4-ose-cli-alt-rhel8", "4.10")
    expected = f"""Production brew builds: <{constants.BREW_URL}/packageinfo?packageID=79953|*openshift-enterprise-cli-alt-container*>
Upstream GitHub repository: <https://github.com/openshift/oc|*openshift/oc*>
Private GitHub repository: <https://github.com/openshift-priv/oc|*openshift-priv/oc*>
Production dist-git repo: <{constants.CGIT_URL}/containers/openshift-enterprise-cli-alt|*openshift-enterprise-cli-alt*>
Payload tag: *cli-alt* \n"""
    assert actual == expected


def test_delivery_repo_is_available1():
    response = img_util.delivery_repo_is_available("openshift4/ose-cli-alt-rhel8")

    assert response


def test_delivery_repo_is_available2():
    response = img_util.delivery_repo_is_available("openshift4/not-a-cdn-repo-1321")

    assert not response


def test_brew_from_delivery():
    actual = img_util.brew_from_delivery("openshift4/ose-cli-alt-rhel8")
    expected = "openshift-enterprise-cli-alt-container"

    assert actual == expected


def test_brew_to_cdn_delivery1():
    actual = img_util.brew_to_cdn_delivery("openshift-enterprise-cli-alt-container", "8Base-RHOSE-4.10",
                                           "openshift4/ose-cli-alt-rhel8")
    expected = "redhat-openshift4-ose-cli-alt-rhel8"

    assert actual == expected


def test_get_delivery_repo_id1():
    actual = img_util.get_delivery_repo_id("openshift4/ose-cli-alt-rhel8")
    expected = "607eb032438128431dac0858"

    assert actual == expected


def test_get_image_stream_tag1():
    actual = img_util.get_image_stream_tag("ose-metallb", "4.10")
    expected = None

    assert actual == expected


def test_get_image_stream_tag2():
    actual = img_util.get_image_stream_tag("openshift-enterprise-console", "4.10")
    expected = "console"

    assert actual == expected


def distgit_github_mappings():
    response = img_util.distgit_github_mappings("4.10")
    assert len(response) == 209


def test_require_bundle_build1():
    response = img_util.require_bundle_build("clusterresourceoverride-operator", "4.10")

    assert response


def test_require_bundle_build2():
    response = img_util.require_bundle_build("openshift-enterprise-cli-alt", "4.10")

    assert not response


def test_get_bundle_override1():
    response = img_util.get_bundle_override("special-resource-operator", "4.10")

    assert response


def test_get_bundle_override2():
    response = img_util.get_bundle_override("clusterresourceoverride-operator", "4.10")

    assert not response
