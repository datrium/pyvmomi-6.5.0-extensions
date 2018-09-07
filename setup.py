#!/usr/bin/env python
#
# Copyright (c) 2013-2018 Datrium Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from setuptools import setup

setup(
    name="pyvmomi-6.5.0-extensions",
    version="1.0",
    description='Datrium\'s PyVmomi 6.5.0 Extensions',
    author='Kyle Harris <kyle@datrium.com>, Anupam Garg <angarg@gmail.com>',
    packages=['vim',],
    dependency_links=[
        'https://github.com/datrium/dalibs/archive/master.zip#egg=dalibs-1.0',
    ],
    install_requires=[
        'dalibs==1.0',
        'pyvmomi>=6.5,<6.7',
        'pycurl==7.43.0',
        'PyYAML==3.13',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
    keywords='pyvmomi pyvim vim vsphere vmware virtual esx',
    project_urls={
        'Bug Reports': 'https://github.com/datrium/pyvmomi-6.5.0-extensions/issues',
        'Source': 'https://github.com/datrium/pyvmomi-6.5.0-extensions',
    },
)
