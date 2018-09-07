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
Adds functionality to pyVmomi.Vim objects. This should be called
early in the import list (and generally in the entry point) so
that callers get the adidtional functionality.
'''


import ssl
import threading
from pyVmomi import vim
from pyVmomi.StubAdapterAccessorImpl import StubAdapterAccessorMixin
from pyVmomi.SoapAdapter import SoapStubAdapter, SessionOrientedStub, StubAdapterBase
import pyVmomi.VmomiSupport


import mo
vim.ManagedEntity.si = property(mo.si)
vim.ManagedEntity.find = mo.find
vim.ManagedEntity._find = mo._find
vim.ManagedEntity.path = property(mo.path)

import hostsystem
vim.HostSystem.cpuUtilization = property(hostsystem.cpuUtilization)
vim.HostSystem.cpuAvailable = property(hostsystem.cpuAvailable)
vim.HostSystem.cpuTotal = property(hostsystem.cpuTotal)
vim.HostSystem.memUtilization = property(hostsystem.memUtilization)
vim.HostSystem.memAvailable = property(hostsystem.memAvailable)
vim.HostSystem.EnableVmotionNic = hostsystem.EnableVmotionNic
vim.HostSystem.ipaddr = hostsystem.ipaddr
vim.HostSystem.macaddr = hostsystem.macaddr
vim.HostSystem.Popen = hostsystem.Popen
vim.HostSystem.call = hostsystem.call
vim.HostSystem.check_call = hostsystem.check_call
vim.HostSystem.check_output = hostsystem.check_output
vim.HostSystem.get = hostsystem.get
vim.HostSystem.put = hostsystem.put
vim.HostSystem.events = property(hostsystem.events)
vim.HostSystem.tasks = property(hostsystem.tasks)
vim.HostSystem.AddVirtualSwitch = hostsystem.AddVirtualSwitch
vim.HostSystem.RemoveVirtualSwitch = hostsystem.RemoveVirtualSwitch
vim.HostSystem.QueryAdvConfig = hostsystem.QueryAdvConfig
vim.HostSystem.UpdateAdvConfig = hostsystem.UpdateAdvConfig

import vm
vim.VirtualMachine.GetNote = vm.GetNote
vim.VirtualMachine.SetNote = vm.SetNote
vim.VirtualMachine.Touch = vm.Touch
vim.VirtualMachine.GetDevices = vm.GetDevices
vim.VirtualMachine.GetDevicesOnController = vm.GetDevicesOnController
vim.VirtualMachine.GetDisksOnController = vm.GetDisksOnController
vim.VirtualMachine.GetDevicesOnControllers = vm.GetDevicesOnControllers
vim.VirtualMachine.GetDisksOnControllers = vm.GetDisksOnControllers
vim.VirtualMachine.disks = property(vm.disks)
vim.VirtualMachine.VirtualDeviceConfigSpec_AddController = vm.VirtualDeviceConfigSpec_AddController
vim.VirtualMachine.VirtualDeviceConfigSpec_AddDisk = vm.VirtualDeviceConfigSpec_AddDisk
vim.VirtualMachine.GetDiskControllerInfo = vm.GetDiskControllerInfo
vim.VirtualMachine.GetDisks = vm.GetDisks
vim.VirtualMachine.GetDiskFiles = vm.GetDiskFiles
vim.VirtualMachine.poweredOn = property(vm.poweredOn)
vim.VirtualMachine.ipaddr = property(vm.ipaddr)
vim.VirtualMachine.WaitForIp = vm.WaitForIp
vim.VirtualMachine.Popen = vm.Popen
vim.VirtualMachine.call = vm.call
vim.VirtualMachine.check_call = vm.check_call
vim.VirtualMachine.check_output = vm.check_output
vim.VirtualMachine.get = vm.get
vim.VirtualMachine.put = vm.put
vim.VirtualMachine.tasks = property(vm.tasks)
vim.VirtualMachine.events = property(vm.events)
vim.VirtualMachine.utilization = property(vm.utilization)
vim.VirtualMachine.AddDisk_Task = vm.AddDisk_Task
vim.VirtualMachine.RemoveDisk_Task = vm.RemoveDisk_Task
vim.VirtualMachine._Destroy_Task = vim.VirtualMachine.Destroy_Task  # store the original
vim.VirtualMachine.Destroy_Task = vm.Destroy_Task
vim.VirtualMachine.Destroy = vm.Destroy_Task
vim.VirtualMachine._PowerOffVM_Task = vim.VirtualMachine.PowerOffVM_Task  # store the original
vim.VirtualMachine.PowerOffVM_Task = vm.PowerOffVM_Task
vim.VirtualMachine.PowerOff = vm.PowerOffVM_Task
vim.VirtualMachine.AddDisks_Task = vm.AddDisks_Task
vim.VirtualMachine.AddDevices_Task = vm.AddDevices_Task
vim.VirtualMachine.ReserveResources_Task = vm.ReserveResources_Task
vim.VirtualMachine.CreateAndGetScreenshot = vm.CreateAndGetScreenshot
vim.VirtualMachine.AddPoolIPs_Task = vm.AddPoolIPs_Task
vim.VirtualMachine.AddPoolIPs = vm.AddPoolIPs
vim.VirtualMachine.GetPoolIPs = vm.GetPoolIPs
vim.VirtualMachine.DeletePoolIPs = vm.DeletePoolIPs
vim.VirtualMachine.PersistPoolIPs = vm.PersistPoolIPs
vim.VirtualMachine.NetworkConnect_Task = vm.NetworkConnect_Task
vim.VirtualMachine.RemoveNic_Task = vm.RemoveNic_Task

import task
vim.Task.wait = task.wait

import cluster
vim.ClusterComputeResource.vm = property(cluster.vm)
vim.ClusterComputeResource.EnableHA_Task = cluster.EnableHA_Task
vim.ClusterComputeResource.CreateResourcePool = cluster.CreateResourcePool


'''
Override SoapStubAdapter's monkey-patched _HTTPSConnection to overcome
a bug with __getattr__ where self._wrapped does not exist. In that case,
getattr(self._wrapped, item) enters infinite recursion.
'''
try:
    from pyVmomi.SoapAdapter import _HTTPSConnection
    del _HTTPSConnection.__getattr__
except (ImportError, AttributeError):
    pass


'''
Override the Soap/Stub Adapters to do the following:
1. don't store an explicit reference to the propertyCollector
2. disconnect on SoapStubAdapter __del__

When initiating a vim session, the underlying transport mechanism is the
SoapStubAdapter. All Managed Objects participating in the session have the
same SoapStubAdapter. The behavior that we want is that when the last Managed
Object goes out of scope, and python gc decides to clean it, to disconnect
from the session.

Normally, we would simply use the SoapStubAdapter.__del__ method to do this,
but pyVmomi creates circular references by having the SoapStubAdapter store
a cached reference to a propertyCollector -- which also stores a reference to
the stub. Because of this circular reference, python gc does not invoke the
__del__ methods, and instead sticks the SoapStubAdapter in its gc.garbage
list -- meaning the application programmer would need to handle these explicitly.

So, in order to avoid this, we override the SoapStubAdapter to not store an
explicit (for caching) reference to the properyCollector. At this point, when all
Managed Objects are out of scpoe, python's gc will clean the SoapStubAdapter,
and will invoke the __del__ method, which does the explicit disconnect.

An script that shows the original and our modified behavior is:

    #!/usr/bin/env python
    import vim
    import gc

    def vms():
        vc = vim.VC('davcenter01')
        print vc.si._stub
        vm = vc.vm('anupam')
        print vm
        print vc.find(vim.ClusterComputeResource)

    vms()
    gc.collect()
    print gc.garbage
    vms()
    gc.collect()
    print gc.garbage
    vms()
    gc.collect()
    print gc.garbage


With the only modification being a print statement in the SoapStubAdapter.__del__
method, we see the following behavior:

    $ /tmp/foo.py
    <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x100c2eb90>
    'vim.VirtualMachine:vm-1810'
    ['vim.ClusterComputeResource:domain-c32', 'vim.Clus...]
    []
    <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x100c2ec20>
    'vim.VirtualMachine:vm-1810'
    ['vim.ClusterComputeResource:domain-c32', 'vim.Clus...]
    [<pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x100c2eb90>]
    <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x100c2e128>
    'vim.VirtualMachine:vm-1810'
    ['vim.ClusterComputeResource:domain-c32', 'vim.Clus...]
    [<pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x100c2eb90>, <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x100c2ec20>]


With out complete modificaiton, we see this output:
    $ /tmp/foo.py
    <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x10ffc1050>
    'vim.VirtualMachine:vm-1810'
    ['vim.ClusterComputeResource:domain-c32', 'vim.Clus...]
    []
    disconnect from <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x10ffc1050>
    <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x10ffc1710>
    'vim.VirtualMachine:vm-1810'
    ['vim.ClusterComputeResource:domain-c32', 'vim.Clus...]
    []
    disconnect from <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x10ffc1710>
    <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x10ff3e368>
    'vim.VirtualMachine:vm-1810'
    ['vim.ClusterComputeResource:domain-c32', 'vim.Clus...]
    []
    disconnect from <pyVmomi.SoapAdapter.SoapStubAdapter instance at 0x10ff3e368>
'''
def InvokeAccessor(self, mo, info):
    filterSpec = self._pcType.FilterSpec(
        objectSet=[self._pcType.ObjectSpec(obj=mo, skip=False)],
        propSet=[self._pcType.PropertySpec(all=False, type=mo.__class__, pathSet=[info.name])],
    )
    si = self._siType("ServiceInstance", self)
    pc = si.RetrieveContent().propertyCollector
    objset = pc.RetrieveContents([filterSpec])
    if objset:
        obj = objset[0]
        if obj and obj.propSet:
            return obj.propSet[0].val
    return None
StubAdapterAccessorMixin.InvokeAccessor = InvokeAccessor


def SoapStubAdapter__del__(self):
    try:
        si = self._siType("ServiceInstance", self)
        si.content.sessionManager.Logout()
    except:
        # usually when program exits, base classes and modules may get torn down before us
        # and in cases where this is not on exit and we fail, just ignore the failure; the
        # implication is that we will leak vsphere connections; they eventually timeout so
        # this is not a major issue.
        pass
SoapStubAdapter.__del__ = SoapStubAdapter__del__


def _SetWsdlMethod(ns, wsdlName, inputMM):
    pyVmomi.VmomiSupport._wsdlMethodNSs.add(ns)
    curMM = pyVmomi.VmomiSupport._wsdlMethodMap.get( (ns, wsdlName) )
    # if inputMM is a list
    if isinstance(inputMM, list):
        if curMM is None:
            pyVmomi.VmomiSupport._wsdlMethodMap[(ns, wsdlName)] = inputMM
            return inputMM
        elif isinstance(curMM, list):
            # Datrium change. Allow the method map to be overridden here.
            # raise RuntimeError(
            #     "Duplicate wsdl method %s %s (new class %s vs existing %s)" % \
            #     (ns, wsdlName, inputMM[0], curMM[0]))
            pyVmomi.VmomiSupport._wsdlMethodMap[(ns, wsdlName)] = inputMM
            return inputMM
        else:
            return curMM
    # if inputMM is a ManagedMethod
    else:
        if curMM is None or isinstance(curMM, list):
            pyVmomi.VmomiSupport._wsdlMethodMap[(ns, wsdlName)] = inputMM
            return inputMM
        else:
            return curMM


def CreateManagedType(vmodlName, wsdlName, parent, version, props, methods):
    with pyVmomi.VmomiSupport._lazyLock:
        dic = [vmodlName, wsdlName, parent, version, props, methods]
        names = vmodlName.split(".")
        if pyVmomi.VmomiSupport._allowCapitalizedNames:
            vmodlName = ".".join(name[0].lower() + name[1:] for name in names)

        pyVmomi.VmomiSupport._AddToDependencyMap(names)
        typeNs = pyVmomi.VmomiSupport.GetWsdlNamespace(version)

        if methods:
            for meth in methods:
                _SetWsdlMethod(typeNs, meth[1], dic)

        pyVmomi.VmomiSupport._managedDefMap[vmodlName] = dic
        pyVmomi.VmomiSupport._wsdlDefMap[(typeNs, wsdlName)] = dic
        pyVmomi.VmomiSupport._wsdlTypeMapNSs.add(typeNs)


# Expose SyncConfiguration()
CreateManagedType("vim.host.FirmwareSystem", "HostFirmwareSystem",
    "vmodl.ManagedObject", "vim.version.version2", None,
    [("resetToFactoryDefaults", "ResetFirmwareToFactoryDefaults", "vim.version.version2", (),
        (0, "void", "void"), "Host.Config.Firmware", ["vim.fault.InvalidState", ]),
    ("backupConfiguration", "BackupFirmwareConfiguration", "vim.version.version2", (),
        (0, "string", "string"), "Host.Config.Firmware", None),
    ("queryConfigUploadURL", "QueryFirmwareConfigUploadURL", "vim.version.version2", (),
        (0, "string", "string"), "Host.Config.Firmware", None),
    ("restoreConfiguration", "RestoreFirmwareConfiguration", "vim.version.version2",
        (("force", "boolean", "vim.version.version2", 0, None),), (0, "void", "void"),
        "Host.Config.Firmware", ["vim.fault.InvalidState", "vim.fault.FileFault",
        "vim.fault.MismatchedBundle", "vim.fault.InvalidBundle", ]),
    # Datrium change. Append SyncConfiguration method.
    ("syncConfiguration", "SyncFirmwareConfiguration", 'vim.version.version2', (),
        (0, 'void', 'void'), 'Host.Config.Firmware', ['vim.fault.TooManyWrites'])])


# Monkey patch pyVmomi.vim.get_ssl_context() so that pyVmomi.vim clients can
# set the verify_mode of ssl connections.
def get_ssl_context(verify_mode=ssl.CERT_NONE, check_hostname=False):
    try:
        sslContext = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        sslContext.verify_mode = verify_mode
        sslContext.check_hostname = check_hostname
        sslContext.load_default_certs()
        return dict(sslContext=sslContext)
    except AttributeError:
        return dict()
vim.get_ssl_context = get_ssl_context
