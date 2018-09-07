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

'''
This represents the entry point for access to vpshere.
A VC instance gives you access to a VC object, which has the
rootFolder. From the rootFolder, all other Vmomi objects are
accessible by their vsphere API:
http://pubs.vmware.com/vsphere-65/index.jsp?topic=%2Fcom.vmware.wssdk.apiref.doc%2Fright-pane.html
'''

import dalibs.retry
import deploy
import ssl
from pyVmomi import vim, vmodl, SoapStubAdapter
from pyVim.connect import VimSessionOrientedStub


class VC(object):
    def __init__(self, host, username=None, password=None, timeout=None, verify_mode=ssl.CERT_NONE):
        self.host = host
        self.username = username
        self.password = password
        xtra_kwargs = vim.get_ssl_context(verify_mode=verify_mode)
        soapStub = SoapStubAdapter(host=self.host, version='vim.version.version10', **xtra_kwargs)
        sessionStub = VimSessionOrientedStub(soapStub,
            VimSessionOrientedStub.makeUserLoginMethod(self.username, self.password))
        self.si = vim.ServiceInstance('ServiceInstance', sessionStub)

    def __getattr__(self, attr):
        ''' Proxy all missing requests to our ServiceInstance (si) '''
        return getattr(self.si, attr)

    def __getstate__(self):
        return {
            'host': self.host,
            'username': self.username,
            'password': self.password,
        }

    def __setstate__(self, state):
        host = state.pop('host')
        self.__init__(host, **state)

    def find(self, klass, path=None, attrs=[]):
        return self.content.rootFolder.find(klass, path=path, attrs=attrs)

    @property
    def apiType(self):
        return self.si.content.about.apiType

    @property
    def is_vc(self):
        return self.apiType == 'VirtualCenter'

    @property
    def is_esx(self):
        return self.apiType == 'HostAgent'

    def vms(self, path=None, attrs=[]):
        attrs += ['name', 'config.annotation', 'config.template', 'runtime.host', 'runtime.powerState']
        attrs = list(set(attrs))
        if path:
            path = self.content.searchIndex.FindByInventoryPath(path)
        return self.find(vim.VirtualMachine, path=path, attrs=attrs)

    def vm(self, name):
        attrs = ['name']
        for vm in self.content.rootFolder._find(vim.VirtualMachine, path=None, attrs=attrs):
            try:
                if vm.propSet[0].val == name:
                    return vm.obj
            except IndexError:
                # property collector did not get name
                continue
            except vmodl.fault.ManagedObjectNotFound:
                continue
        return None

    def ImportOVF(self, ovffile, **kwargs):
        if not ovffile.endswith('ovf'):
            raise Exception('Filename must end with .ovf: %s' % ovffile)
        ovf = deploy.OVF(self)
        ovf.importovf(ovffile, **kwargs)

    def GetVCPoolUsage(self, datacenter_name, pool_name):
        '''
        Returns a tuple of (available, [allocated ips])
        '''
        pm = self.content.ipPoolManager
        dc = [d for d in self.find(vim.Datacenter) if d.name == datacenter_name][0]
        pool = [p for p in pm.QueryIpPools(dc) if p.name == pool_name][0]
        # Unfortunately, QueryIpPools.{allocated,available}Ipv4Addresses return None.
        # So, we must derive the usage.
        # Format is "10.80.x.x#range". We don't support split ranges.
        info = pool.ipv4Config.range.split('#')
        assert len(info) == 2, 'Invalid IP Pool configuration: %s' % '#'.join(info)
        vcpool_ips = int(info[-1])
        allocated = [p.ipAddress for p in pm.QueryIPAllocations(dc, pool.id, 'VirtualCenter')]
        available = vcpool_ips - len(allocated)
        return (available, allocated)

    def RegisterVM(self, vc_datastore_name, vmx_path, vm_name):
        '''
        Register the VM at the specified path in the specified datastore and return
        the result VM object.
        '''
        vmx_path_on_esx = '[%s] %s' % (vc_datastore_name, vmx_path.lstrip('/'))
        datacenters = self.si.content.rootFolder.childEntity
        vm_folder = datacenters[0].vmFolder
        clusters = datacenters[0].hostFolder.childEntity
        pool = clusters[0].resourcePool
        vm_folder.RegisterVM_Task(vmx_path_on_esx, vm_name, asTemplate=False, pool=pool).wait()
        return self.vm(vm_name)

    def WaitForDatastore(self, datastore_name, timeout=30):
        '''
        Wait for VC to become aware of a particular datastore.
        '''
        msg = 'VC did not become aware of datastore "%s" in time' % datastore_name
        for _ in dalibs.retry.retry(timeout=timeout, sleeptime=1, message=msg):
            if datastore_name in [ds.name for ds in self.find(vim.Datastore)]:
                return
