#
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

import patched
import sys
import vc
from pyVmomi import vim


# Proxy pyVmomi objects through this vim namespace
class Proxy(object):
    _instance = None
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Proxy, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        self.vc = vc
        self.vim = vim

    def __getattr__(self, attr):
        if attr == 'VC':
            return getattr(self.vc, attr)
        return getattr(self.vim, attr)

# The hack is to make this module's attribute lookups go through the proxy class
# example:
# >>> import vim
# >>> vim.VC
# <class 'vim.vc.VC'>
# >>> vim.HostSystem
# <class 'pyVmomi.VmomiSupport.vim.HostSystem'>

sys.modules[__name__] = Proxy()
