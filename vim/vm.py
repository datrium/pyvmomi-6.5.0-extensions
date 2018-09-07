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
Adds functionality to pyVmomi.Vim.VirtualMachine
'''


import dalibs.retry
import dalibs.ssh
import datetime
import os
import re
import requests
import urllib
import yaml
from pyVmomi import vim, vmodl


def GetNote(self):
    s = yaml.load(self.config.annotation)
    if s is None or not isinstance(s, dict):
        return {}
    return s


def SetNote(self, value):
    if not isinstance(value, dict):
        raise ValueError('vim.VirtualMachine.annotate expects to be a dictionary.')
    config = vim.VirtualMachineConfigSpec()
    config.annotation = yaml.dump(value, default_flow_style=False)
    t = self.ReconfigVM_Task(config)
    t.wait(timeout=240)


def Touch(self):
    notes = self.GetNote()
    notes['touched_at'] = datetime.datetime.now()
    self.SetNote(notes)


def utilization(self):
    unshared = 0
    for usage in self.storage.perDatastoreUsage:
        unshared += usage.unshared / 1024.0 / 1024.0 / 1024.0  # bytes => GB
    return {
        'cpu': self.summary.quickStats.overallCpuUsage / 1024.0,  # MHz => GHz
        'mem': self.summary.quickStats.guestMemoryUsage / 1024.0,  # MB => GB
        'disk': unshared,  # GB
    }


def GetDevices(self, deviceType=vim.VirtualDevice):
    '''
    Get all virtual devices of the specified type (e.g., VirtualDevice,
    VirtualController, VirtualDisk, VirtualUSB, VirtualSCSIController,
    Virtual, ParaVirtualSCSIController, VirtualLsiLogicSCSIController,
    VirtualLsiLogicSASController).
    '''
    return [c for c in self.config.hardware.device if isinstance(c, deviceType)]


def GetDevicesOnController(self, controller, deviceType=vim.VirtualDevice):
    '''
    Get all the devices of the specified type on the provide controller device.
    '''
    return [d for d in self.GetDevices(deviceType) if d.key in controller.device]


def GetDisksOnController(self, controller):
    '''
    Get all disk devices on the provided controller device.
    '''
    return self.GetDevicesOnController(controller, vim.VirtualDisk)


def GetDevicesOnControllers(self, controllerType=vim.VirtualController,
                            deviceType=vim.VirtualDevice, busNumber=None, unitNumber=None):
    '''
    Get all devices of the provided type on all controllers of the provided type. busNumber and/or
    unitNumber can be used to limit the devices returned.
    '''
    controllers = [c for c in self.GetDevices(controllerType)
                   if busNumber is None or c.busNumber == busNumber]
    return [d for c in controllers for d in self.GetDevicesOnController(c, deviceType)
            if unitNumber is None or d.unitNumber == unitNumber]


def GetDisksOnControllers(self, controllerType=vim.VirtualController, busNumber=None,
                            unitNumber=None):
    '''
    Get all disk devices of the provided type on all controllers of the porvided type.
    busNumber and/or unitNumber can be used to limit the devices returned.
    '''
    return self.GetDevicesOnControllers(controllerType, vim.VirtualDisk, busNumber, unitNumber)


def disks(self):
    '''
    Get a list of all disk devices.
    '''
    return self.GetDisksOnControllers()


def VirtualDeviceConfigSpec_AddController(self, controllerType, busNumber):
    '''
    Get a VirtualDeviceConfigSpec to create a virtual disk controller of the specified
    controller type using the provide bus number.
    '''
    existing_controller = [c for c in self.GetDevices(controllerType) if c.busNumber == busNumber]
    assert len(existing_controller) == 0, "Controller already exists %s" % existing_controller[0]
    config = vim.VirtualDeviceConfigSpec()
    config.operation = vim.VirtualDeviceConfigSpecOperation.add
    config.device = controllerType()
    if isinstance(config.device, vim.VirtualSCSIController):
        config.device.sharedBus = getattr(vim.VirtualSCSIController.Sharing, 'noSharing')
    config.device.key = -((busNumber + 1) * 100) - 1
    config.device.busNumber = busNumber
    return config


def VirtualDeviceConfigSpec_AddDisk(self, datastore, controller, unitNumber, diskMode, sizeInGB=None,
                                  fileName=None):
    '''
    Get a VirtualDeviceConfigSpec to create a a virtual disk device on the provided controller
    with the provided unitNumber and diskMode (e.g., VirtualDiskMode.persistent/nonpersistent/
    independent_nonpersistent/independent_persistent). The files of the VM are (or will be) on
    the provided datastore. To create a new disk file, the disk size must be specified. To
    use an existing disk file, a file path must be specified.
    '''
    assert sizeInGB == 0 or fileName == None
    assert sizeInGB != 0 or fileName != None
    config = vim.VirtualDeviceConfigSpec()
    config.operation = vim.VirtualDeviceConfigSpecOperation.add
    config.device = vim.VirtualDisk()
    config.device.key = -unitNumber - 1
    config.device.backing = vim.VirtualDiskFlatVer2BackingInfo()
    config.device.backing.diskMode = diskMode
    if fileName:
        if fileName.startswith('['):
            config.device.backing.fileName = fileName
        else:
            config.device.backing.fileName = '[%s] %s' % (datastore.name, fileName)
    else:
        config.fileOperation = vim.VirtualDeviceConfigSpecFileOperation.create
        config.device.backing.fileName = '[%s]' % datastore.name
        config.device.backing.thinProvisioned = True
        config.device.capacityInKB = sizeInGB * 1024 * 1024
    config.device.controllerKey = controller.key
    config.device.unitNumber = unitNumber
    return config


def GetDisks(self):
    '''
    Get all the disks in the virtual machine.
    '''
    return [d for d in self.config.hardware.device if isinstance(d, vim.VirtualDisk)]


def GetDiskFiles(self):
    '''
    Get all the files that comprise the virtual disks of the VM.
    '''
    return [d.backing.fileName for d in self.GetDisks()]


def poweredOn(self):
    '''
    Is this VM in the powered on state?
    '''
    return self.runtime.powerState == vim.VirtualMachinePowerState.poweredOn


def WaitForIp(self, timeout=300):
    '''
    Wait for the IP address of the VM to be visible to VMware tools.
    '''
    for _ in dalibs.retry.retry(timeout=timeout, sleeptime=1):
        if self.ipaddr:
            return


def ipaddr(self):
    if self.guest and self.guest.ipAddress:
        return self.guest.ipAddress
    return None


def Popen(self, *args, **kwargs):
    return dalibs.ssh.Popen(self.ipaddr, *args, name=self.ipaddr, **kwargs)


def call(self, *args, **kwargs):
    return dalibs.ssh.call(self.ipaddr, *args, name=self.ipaddr, **kwargs)


def check_call(self, *args, **kwargs):
    return dalibs.ssh.check_call(self.ipaddr, *args, name=self.ipaddr, **kwargs)


def check_output(self, *args, **kwargs):
    return dalibs.ssh.check_output(self.ipaddr, *args, name=self.ipaddr, **kwargs)


def get(self, src, dst, *args, **kwargs):
    return dalibs.ssh.get(self.ipaddr, src, dst, *args, name=self.ipaddr, **kwargs)


def put(self, src, dst, *args, **kwargs):
    return dalibs.ssh.put(self.ipaddr, src, dst, *args, name=self.ipaddr, **kwargs)


def tasks(self):
    spec = vim.TaskFilterSpec()
    spec.entity = vim.TaskFilterSpec.ByEntity()
    spec.entity.entity = self
    spec.entity.recursion = 'self'
    spec.eventChainId = []
    collector = self.si.content.taskManager.CreateCollectorForTasks(spec)
    try:
        return collector.latestPage
    except Exception:
        return []
    finally:
        collector.DestroyCollector()


def events(self):
    spec = vim.EventFilterSpec()
    spec.entity = vim.EventFilterSpec.ByEntity()
    spec.entity.entity = self
    spec.entity.recursion = 'self'
    spec.eventTypeId = []
    collector = self.si.content.eventManager.CreateCollectorForEvents(spec)
    try:
        return collector.latestPage
    except Exception:
        return []
    finally:
        collector.DestroyCollector()


def RemoveDisk_Task(self, disk, controller=None):
    # Default to the last controller.
    if not controller:
        controller = [x for x in self.config.hardware.device
                      if isinstance(x, vim.VirtualSCSIController)][-1]
    spec = vim.VirtualMachineConfigSpec()
    spec.deviceChange.append(vim.VirtualDeviceConfigSpec())
    spec.deviceChange[0].device = vim.VirtualDisk()
    spec.deviceChange[0].device.controllerKey = disk.controllerKey
    spec.deviceChange[0].operation = vim.VirtualDeviceConfigSpecOperation()
    spec.deviceChange[0].operation = 'remove'
    spec.deviceChange[0].device.key = disk.key
    return self.ReconfigVM_Task(spec)


def GetDiskControllerInfo(self, controller_type):
    '''
    Get basic info about disk controllers of the provided type. This information is
    encoded in a dictionary with the following fields.

      device_type_str: string representation of device type (e.g., 'scsi', 'ide', 'sata').
      abs_controller_type: abstract controller type.
      n_bus_numbers: number of bus numbers.
      n_unit_numbers: number of unit numbers.
      invalid_unit_numbers: list of invalid unit numbers.
    '''
    if issubclass(controller_type, vim.VirtualSCSIController):
        return dict(device_type_str = "scsi",
                    abs_controller_type = vim.VirtualSCSIController,
                    n_bus_numbers = 4,                              # ESX3.5 - ESX6.5
                    n_unit_numbers = 16,                            # ESX6.0
                    invalid_unit_numbers = [7])
    elif issubclass(controller_type, vim.VirtualIDEController):
        return dict(device_type_str = "ide",
                    abs_controller_type = vim.VirtualIDEController,
                    n_bus_numbers = 2,                              # ESX6.0
                    n_unit_numbers = 2,                             # ESX6.0
                    invalid_unit_numbers = [])
    elif issubclass(controller_type, vim.VirtualSATAController):
        return dict(device_type_str = "sata",
                    abs_controller_type = vim.VirtualSATAController,
                    n_bus_numbers = 4,                              # ESX5.5 -
                    n_unit_numbers = 30,                            # ESX6.0
                    invalid_unit_numbers = [])
    assert True, 'Unknown controller_type (%s) provided' % controller_type


def AddDisk_Task(self, gbytes=0, ssd=False, fileName=None, diskMode=vim.VirtualDiskMode.persistent,
                 controllerType=vim.VirtualLsiLogicController, busNumber=0, unitNumber=0, noAlts=False):
    '''
    Return a task for adding a disk to a VM.

    Argument summary.

       gbytes: if > 0, a new disk is created of this size (fileName most be None).
       ssd: should new disk be an SSD?
       fileName: existing .vmdk disk file to use for new disk (gbytes must be 0).
       diskMode: mode of disk to be created.
       controllerType: kind of disk to create.
       busNumber: bus to start looking for an available slot.
       unitNumber: unit number (device number) to start looking for an available slot.
       noAlts: fail if busNumber and unitNumber are not available in specified controller;
        when noAlts is False, we look for an available slot after the provided bus/unit.
    '''

    assert fileName is None or gbytes == 0
    assert fileName is not None or gbytes != 0

    info = self.GetDiskControllerInfo(controllerType)
    device_type_str = info['device_type_str']
    abs_controller_type = info['abs_controller_type']
    n_bus_numbers = info['n_bus_numbers']
    n_unit_numbers = info['n_unit_numbers']
    invalid_unit_numbers = info['invalid_unit_numbers']

    if noAlts:
        assert busNumber is not None and unitNumber is not None
        n_bus_numbers = busNumber + 1
        n_unit_numbers = unitNumber + 1

    controllers = self.GetDevices(abs_controller_type)
    results = None
    for bus_number in range(busNumber, n_bus_numbers):
        controller = [c for c in controllers if c.busNumber == bus_number]
        start_unit_number = unitNumber if bus_number == busNumber else 0
        if len(controller) == 0:
            results = bus_number, start_unit_number
            break
        controller = controller[0]
        for unit_number in range(start_unit_number, n_unit_numbers):
            if (unit_number not in invalid_unit_numbers and
                len(self.GetDevicesOnControllers(abs_controller_type, busNumber=bus_number, unitNumber=unit_number)) == 0):
                results = controller, unit_number
                break
        if results is not None:
            break

    if results is None:
        if noAlts:
            raise Exception('Specified busNumber(%d) and unitNumber(%d) are not available' % (busNumber, unitNumber))
        else:
            raise Exception('No more disk devices can be created after busNumber(%d) and unitNumber(%d)' % (busNumber, unitNumber))

    spec = vim.VirtualMachineConfigSpec()
    spec.deviceChange = []
    assert len(results) == 2, "Unexpected results values: %s" % results
    controller, unit_number = results
    if issubclass(type(controller), vim.VirtualController):
        busNumber = controller.busNumber
    else:
        assert type(controller) == int, "Unexpected results values: %s" % results
        busNumber = controller
        controller_config = self.VirtualDeviceConfigSpec_AddController(controllerType, busNumber)
        spec.deviceChange.append(controller_config)
        controller = controller_config.device

    datastore = self.disks[-1].backing.datastore
    disk_config = self.VirtualDeviceConfigSpec_AddDisk(datastore, controller, unit_number,
                                                     diskMode, gbytes, fileName)
    spec.deviceChange.append(disk_config)
    if ssd:
        spec.extraConfig = [
            vim.OptionValue(key='disk.enableVirtualSSD', value='TRUE'),
            vim.OptionValue(key='%s%s:%s.virtualSSD' % (device_type_str, busNumber, unit_number), value='1')
        ]

    task = self.ReconfigVM_Task(spec)
    if self.si.content.about.apiType == 'VirtualCenter':
        dev_node_string = '%s%d:%d' % (device_type_str, busNumber, unit_number)
        msg = vmodl.LocalizableMessage()
        msg.key = "dev_node_string"
        msg.message = dev_node_string
        task.SetTaskDescription(msg)

    return task


def PowerOffVM_Task(self):
    '''
    Override a VirtualMachine's PowerOffVM_Task in order to first answer any known
    questions.

    In patched.py, the original PowerOffVM_Task should be stored under _PowerOffVM_Task()
    '''
    if self.runtime.question:
        if self.runtime.question.message[0].id == 'msg.hbacommon.outofspace':
            self.AnswerVM(self.runtime.question.id, '1')  # key 1 is always Cancel
        if self.runtime.question.message[0].id == 'msg.serial.file.open':
            self.AnswerVM(self.runtime.question.id, '1')  # 0 append, 1 replace, 2 cancel
        if self.runtime.question.message[0].id == 'msg.hbacommon.locklost':
            self.AnswerVM(self.runtime.question.id, '0')  # 0 ok
    return self._PowerOffVM_Task()


def Destroy_Task(self):
    '''
    Override a VirtualMachine's Destroy_Task in order to first answer any known
    questions. Also, attempt to poweroff the vm if it is on.

    In patched.py, the original Destroy_Task should be stored under _Destroy_Task()
    '''
    if self.runtime.question:
        if self.runtime.question.message[0].id == 'msg.hbacommon.outofspace':
            self.AnswerVM(self.runtime.question.id, '1')  # key 1 is always Cancel
        if self.runtime.question.message[0].id == 'msg.serial.file.open':
            self.AnswerVM(self.runtime.question.id, '1')  # 0 append, 1 replace, 2 cancel
        if self.runtime.question.message[0].id == 'msg.hbacommon.locklost':
            self.AnswerVM(self.runtime.question.id, '0')  # 0 ok
    try:
        if self.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
            t = self.PowerOffVM_Task()
            t.wait()
    except vim.fault.InvalidPowerState:
        pass  # already off
    return self._Destroy_Task()


def CreateAndGetScreenshot(self, localpath, username, password, timeout=None):
    '''
    Uses VirtualMachine's CreateScreenshot_Task and python requests to reallocate
    screenshot files from datastore to local, removes files from datastore after transfer

    '''
    raise Exception('Disabled because this leak vCenter sessions')

    def check_status_code(s):
        if str(s.status_code)[0] != '2':
            raise requests.exceptions.SSLError('Failure: HTTP Status Code {}'.format(s.status_code))

    url = 'https://{}/folder'.format(self.si._stub.soapStub.pool[0][0].host)
    check_auth = requests.get(url, auth=(username, password), verify=False)
    check_status_code(check_auth)
    screenshot = self.CreateScreenshot_Task()
    screenshot.wait(timeout=timeout)
    datacenter = self.datastore[0]
    while datacenter.parent.name != 'Datacenters':
        datacenter = datacenter.parent
    datastore = self.datastore[0].name.replace('-', '%252d')
    url += '/%s' % screenshot.info.result.split()[1]
    url += '?dcPath=%s' % datacenter.name
    url += '&dsName=%s' % datastore
    if os.path.isdir(localpath):
        localpath = os.path.join(localpath, screenshot.info.entityName)
    output = requests.get(url, auth=(username, password), verify=False) # requests needs cert, use verify=False for now
    check_status_code(output)
    with open(localpath, 'wb') as s:
        s.write(output.content)
    remove = requests.delete(url, auth=(username, password), verify=False)
    check_status_code(remove)
    return localpath


def ReserveResources_Task(self, resources):
    '''
    Reserve cpu and memory resources

    Valid keys and values:
    ncpus - number of virtual cpus
    mem - memory size in MB, this is also the reservation
    cpu - cpu reservation in MHz

    TODO(kyle) consider splitting size and reservations
    '''
    spec = vim.VirtualMachineConfigSpec()
    spec.memoryMB = resources['mem']
    spec.numCPUs = resources['ncpus']
    spec.extraConfig = []
    spec.cpuAllocation = vim.ResourceAllocationInfo()
    spec.cpuAllocation.limit = -1
    spec.cpuAllocation.reservation = resources['cpu']
    spec.cpuAllocation.expandableReservation = True
    spec.cpuAllocation.shares = vim.SharesInfo()
    spec.cpuAllocation.shares.level = vim.SharesInfo.Level.normal
    spec.cpuAllocation.shares.shares = 0
    spec.memoryAllocation = vim.ResourceAllocationInfo()
    spec.memoryAllocation.limit = -1
    spec.memoryAllocation.reservation = resources['mem']
    spec.memoryAllocation.expandableReservation = True
    spec.memoryAllocation.shares = vim.SharesInfo()
    spec.memoryAllocation.shares.level = vim.SharesInfo.Level.normal
    spec.memoryAllocation.shares.shares = 0
    spec.memoryReservationLockedToMax = True
    return self.ReconfigVM_Task(spec)


def AddDevices_Task(self, devices):
    '''
    Add multiple devices in a single task

    Devices is a list of device mappings

    Supported devices and values:
    scsi - the value specifies the type of sharing: physical, virtual, no
    nic - the value specifies the portgroup(s) for connection
    nictype - a mapping to the nic list specifying the nictype, default is E1000
              or the last nictype specified (if len(nic) != len(nictype).

    For example,
    nic = ['vlan1550', 'private_network1', 'private_network2']
    nictype = ['VirtualE1000', 'VirtualVmxnet3']

    results in

    E1000 attached to vlan1550
    Vmxnet3 attached to private_network1
    Vmxnet3 attached to private_network2
    '''
    spec = vim.VirtualMachineConfigSpec()
    spec.deviceChange = []
    # Unique negative keys for this operation, VC will generate the permanent ones.
    key = -1
    if 'scsi' in devices:
        sharing = devices['scsi'] + 'Sharing'
        controller = [x for x in self.config.hardware.device
                      if isinstance(x, vim.VirtualSCSIController)][-1]
        config = vim.VirtualDeviceConfigSpec()
        config.operation = vim.VirtualDeviceConfigSpecOperation.add
        config.device = vim.VirtualLsiLogicController()
        config.device.key = key
        key -= 1
        config.device.busNumber = controller.busNumber + 1
        config.device.unitNumber = controller.unitNumber + 1
        config.device.sharedBus = getattr(vim.VirtualSCSIController.Sharing, sharing)
        spec.deviceChange.append(config)
    if 'nic' in devices:
        # The value is a list of portgroup names ([device.backing]).
        backings = devices['nic']
        if not isinstance(backings, (tuple, list)):
            # Convert single backing to a list to maintain backwards compatibility.
            backings = [backings]
        # nictype is a list mapping to the nic list above specifying virtual nic type.
        nictype = devices.get('nictype', ['VirtualE1000'])
        if not isinstance(nictype, (tuple, list)):
            # Convert single nictype to a list to maintain backwards compatibility.
            nictype = [nictype]
        # Make sure this is a 1:1 mapping between nic and nictype.
        defaulttype = nictype[-1]
        for i in range(len(nictype), len(backings)):
            nictype.append(defaulttype)
        for i, backing in enumerate(backings):
            config = vim.VirtualDeviceConfigSpec()
            config.operation = vim.VirtualDeviceConfigSpecOperation.add
            config.device = getattr(vim, nictype[i])()
            config.device.key = key
            key -= 1
            config.device.backing = vim.VirtualEthernetCard.NetworkBackingInfo()
            config.device.backing.deviceName = backing
            spec.deviceChange.append(config)
    return self.ReconfigVM_Task(spec)


def AddDisks_Task(self, disks):
    '''
    Add multiple disks in a single task

    Disks is a list of disk mappings

    Supported disks and values:
    mode - provisioning mode, thin or thick
    gbytes - size in GB
    ssd - the disk should be marked as SSD
    backing - a fileName for backing the disk, used for sharing disks, overrides dsname
    dsname - datastore name, overrides dsprefix
    dsprefix - the datastore prefix, the dsname is derived from dsprefix + " (hostname)",
               for example "datastore1 (colo-esx10)". The default datastore is derived using
               dsprefix "datatstore1"
    '''
    spec = vim.VirtualMachineConfigSpec()
    controller = [x for x in self.config.hardware.device
        if isinstance(x, vim.VirtualSCSIController)][-1]
    unitNumber = len([x for x in self.disks if x.controllerKey == controller.key])
    spec.extraConfig = []
    spec.deviceChange = []
    for disk in disks:
        if unitNumber == 7:  # scsi ID 7 is invalid
            unitNumber = unitNumber + 1
        config = vim.VirtualDeviceConfigSpec()
        config.operation = vim.VirtualDeviceConfigSpecOperation.add
        config.device = vim.VirtualDisk()
        config.device.key = (unitNumber * -1) - 1  # a unique negative number for this disk
        config.device.backing = vim.VirtualDiskFlatVer2BackingInfo()
        config.device.backing.diskMode = vim.VirtualDiskMode.persistent
        if disk.get('backing'):
            config.device.backing.fileName = disk['backing']
        else:
            dsname = disk.get('dsname')
            config.fileOperation = vim.VirtualDeviceConfigSpecFileOperation.create
            config.device.backing.fileName = '[%s]' % dsname
            config.device.backing.thinProvisioned = True
            if disk.get('mode', 'thin') == 'thick':
                config.device.backing.thinProvisioned = False
                config.device.backing.eagerlyScrub = True
            config.device.capacityInKB = disk['gbytes'] * 1024 * 1024
        config.device.controllerKey = controller.key
        config.device.unitNumber = unitNumber
        spec.deviceChange.append(config)
        if disk.get('ssd'):
            spec.extraConfig += [
                vim.OptionValue(key='disk.enableVirtualSSD', value='TRUE'),
                vim.OptionValue(
                    key='scsi%s:%s.virtualSSD' % (controller.busNumber, unitNumber),
                    value='1')
            ]
        unitNumber = unitNumber + 1
    return self.ReconfigVM_Task(spec)


def AddPoolIPs_Task(self, qty=1, network='VM Network', persist=True):
    '''
    AddPoolIPs() is now a blocking call. Maintain backwards compatibility with Task version.
    '''
    return AddPoolIPs(self, qty, network, persist)


def AddPoolIPs(self, qty=1, network='VM Network', persist=True):
    '''
    Add Pool IPs

    Update the VM config to enable acquiring IP(s) via IP Pools and add qty number of IPs.
    This may be called multiple times to acquire and append more IPs.
    Persist will power on to acquire the IPs, update vAppConfig to persist them, then
    power back down.
    VC must have the pool configured and associated with the specified network.
    '''
    assert self.runtime.powerState == vim.VirtualMachine.PowerState.poweredOff
    spec = vim.VirtualMachineConfigSpec()
    spec.vAppConfig = vim.VmConfigSpec()
    spec.vAppConfig.ipAssignment = vim.VAppIPAssignmentInfo()
    # fixedAllocatedPolicy should provide a sticky IP, but it seems to change with every powerOn.
    fixed = vim.VAppIPAssignmentInfoIpAllocationPolicy.fixedAllocatedPolicy
    IPv4 = vim.VAppIPAssignmentInfoProtocols.IPv4
    ovfenv = vim.VAppIPAssignmentInfoAllocationSchemes.ovfenv
    spec.vAppConfig.ipAssignment.ipAllocationPolicy = fixed
    spec.vAppConfig.ipAssignment.ipProtocol = IPv4
    spec.vAppConfig.ipAssignment.supportedIpProtocol = [IPv4]
    spec.vAppConfig.ipAssignment.supportedAllocationScheme = [ovfenv]
    spec.vAppConfig.property = []
    # Find last key if this is an update.
    last = 0
    properties = self.config.vAppConfig.property
    if properties:
        last = max([p.key for p in self.config.vAppConfig.property]) + 1
    for i in range(last, last+qty):
        pspec = vim.VAppPropertySpec()
        pspec.info = vim.VAppPropertyInfo()
        pspec.info.key = i
        pspec.info.id = 'ipaddr%d' % i
        pspec.info.type = 'expression'
        pspec.info.userConfigurable = False
        # autoIp will acquire IPs from VC Pool. Once VM is powered on and IPs are acquired, this needs to
        # change to ip:network and value will be set according to the acquired IP.
        pspec.info.defaultValue = '${autoIp:%s}' % network
        pspec.operation = vim.ArrayUpdateOperation.add
        spec.vAppConfig.property.append(pspec)
    t = self.ReconfigVM_Task(spec)
    t.wait()
    if persist:
        self.PowerOnVM_Task().wait()
        PersistPoolIPs(self, network)
        self.PowerOffVM_Task().wait()
    # Maintain backwards compatibility with _Task().
    return t


def PersistPoolIPs(self, network='VM Network'):
    '''
    Persist the current IP settings back to vAppConfig.
    '''
    spec = vim.VirtualMachineConfigSpec()
    spec.vAppConfig = vim.VmConfigSpec()
    spec.vAppConfig.property = []
    for p in [p for p in self.config.vAppConfig.property if p.type == 'expression']:
        # p.typeReference returns a substring of str(vim.Network), so use re.match instead.
        m = re.match(r'\$\{autoIp:%s\}' % network, p.defaultValue)
        # VM must have been powered on previously with autoIp configured for value to be set.
        if m and p.value:
            pspec = vim.VAppPropertySpec()
            pspec.info = vim.VAppPropertyInfo()
            pspec.info.key = p.key
            pspec.info.type = 'ip:%s' % network
            pspec.info.defaultValue = p.value
            pspec.operation = vim.ArrayUpdateOperation.edit
            spec.vAppConfig.property.append(pspec)
    if spec.vAppConfig.property:
        self.ReconfigVM_Task(spec).wait()


def DeletePoolIPs(self):
    '''
    Delete All Pool IPs
    '''
    spec = vim.VirtualMachineConfigSpec()
    spec.vAppConfig = vim.VmConfigSpec()
    for p in self.config.vAppConfig.property:
        if p.type.startswith('ip') or p.defaultValue.startswith('${autoIp'):
            pspec = vim.VAppPropertySpec()
            pspec.removeKey = p.key
            pspec.operation = vim.ArrayUpdateOperation.remove
            spec.vAppConfig.property.append(pspec)
    if spec.vAppConfig.property:
        self.ReconfigVM_Task(spec).wait()


def GetPoolIPs(self):
    '''
    Get a list of IP Pool assigned IPs

    The IP is read from the OVF environment.
    '''
    ips = []
    for p in self.config.vAppConfig.property:
        if p.defaultValue.startswith('${autoIp') and p.value:
            # This only returns a value if VM is powered on.
            ips.append(p.value)
        elif p.type.startswith('ip') and p.defaultValue:
            # This returns a value regardless of powerState
            ips.append(p.defaultValue)
    return ips


def NetworkConnect_Task(self, label, connected=True, network='VM Network'):
    spec = vim.VirtualMachineConfigSpec()
    spec.deviceChange = []
    controller = [x for x in self.config.hardware.device
                  if isinstance(x, vim.VirtualEthernetCard) and x.deviceInfo.label == label][0]
    config = vim.VirtualDeviceConfigSpec()
    config.operation = vim.VirtualDeviceConfigSpecOperation.edit
    config.device = controller
    config.device.connectable = vim.VirtualDeviceConnectInfo()
    config.device.connectable.connected = connected
    config.device.connectable.startConnected = connected
    config.device.backing = vim.VirtualEthernetCard.NetworkBackingInfo()
    config.device.backing.deviceName = network
    spec.deviceChange.append(config)
    return self.ReconfigVM_Task(spec)


def RemoveNic_Task(self, label):
    spec = vim.VirtualMachineConfigSpec()
    spec.deviceChange = []
    controller = [x for x in self.config.hardware.device
                  if isinstance(x, (vim.VirtualE1000, vim.VirtualVmxnet3)) and
                  x.deviceInfo.label == label][0]

    config = vim.VirtualDeviceConfigSpec()
    config.operation = vim.VirtualDeviceConfigSpecOperation()
    config.operation = vim.VirtualDeviceConfigSpecOperation.remove
    config.device = controller
    spec.deviceChange.append(config)
    return self.ReconfigVM_Task(spec)


