# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals
from setuptools import setup, find_packages

with open('./requirements.txt') as f:
    INSTALL_REQUIRES = f.read().splitlines()


setup(
    name="art-bot",
    author="AOS ART Team",
    author_email="aos-team-art@redhat.com",
    version="0.0.1",
    description="Slack bot for helping out the ART team",
    long_description="Slack bot for helping out the ART team",
    url="https://github.com/openshift/art-bot",
    license="Apache License, Version 2.0",
    packages=find_packages(exclude=["tests", "tests.*", "functional_tests", "functional_tests.*"]),
    include_package_data=True,
    entry_points={},
    install_requires=INSTALL_REQUIRES,
    test_suite='tests',
    dependency_links=[],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Environment :: Console",
        "Operating System :: POSIX",
        "License :: OSI Approved :: Apache Software License",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "Natural Language :: English",
    ]
)
