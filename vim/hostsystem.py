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
Adds functionality to pyVmomi.Vim.HostSystem
'''

import ast
import dalibs.decorators
import dalibs.ssh
from pyVmomi import vim, vmodl


@dalibs.decorators.cached
def ipaddr(self):
    for nic in self.config.virtualNicManagerInfo.netConfig:
        if nic.nicType == 'management':
            for vinc in nic.candidateVnic:
                if vinc.portgroup == 'Management Network':
                    return vinc.spec.ip.ipAddress


@dalibs.decorators.cached
def macaddr(self):
    for nic in self.config.virtualNicManagerInfo.netConfig:
        if nic.nicType == 'management':
            for vinc in nic.candidateVnic:
                if vinc.portgroup == 'Management Network':
                    return vinc.spec.mac


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


def cpuTotal(self):
    cpuspeed = float(self.summary.hardware.cpuMhz)
    numcores = float(self.summary.hardware.numCpuCores)
    return cpuspeed * numcores


def cpuUtilization(self):
    usage = float(self.summary.quickStats.overallCpuUsage)
    return (usage / self.cpuTotal) * 100.0  # percent


def cpuAvailable(self):
    # There may be a more efficient way to do this.
    reserved = 0
    for vm in self.vm:
        try:
            if vm.runtime.powerState == vim.VirtualMachine.PowerState.poweredOn:
                reserved += vm.config.cpuAllocation.reservation
        except vmodl.fault.ManagedObjectNotFound:
            pass
    # Note. This does take into account amount reserved by ESX.
    return int(self.cpuTotal) - reserved


def memUtilization(self):
    total = float(self.summary.hardware.memorySize / 1024 / 1024 / 1024)  # bytes => gb
    usage = float(self.summary.quickStats.overallMemoryUsage / 1024)  # mb => gb
    return (usage / total) * 100.0  # percent


def memAvailable(self):
    reserved = 0
    for vm in self.vm:
        try:
            if vm.runtime.powerState == vim.VirtualMachine.PowerState.poweredOn:
                reserved += vm.config.memoryAllocation.reservation
        except vmodl.fault.ManagedObjectNotFound:
            pass
    # Note. This does take into account amount reserved by ESX.
    return (self.summary.hardware.memorySize / 1024 / 1024) - reserved


def EnableVmotionNic(self, device=None):
    if device is None:
        device = self.config.vmotion.netConfig.candidateVnic[0].device
    self.configManager.vmotionSystem.SelectVnic(device=device)


def tasks(self):
    spec = vim.TaskFilterSpec()
    spec.entity = vim.TaskFilterSpec.ByEntity()
    spec.entity.entity = self
    spec.entity.recursion = vim.TaskFilterSpecRecursionOption.all
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


def AddVirtualSwitch(self, name, portgroup=None):
    '''
    Add a virtual switch and portgroup
    '''
    if portgroup is None:
        portgroup = name
    cm = self.configManager.networkSystem
    cm.AddVirtualSwitch(name)
    spec = vim.HostPortGroupSpec()
    spec.name = portgroup
    spec.vswitchName = name
    spec.policy = vim.HostNetworkPolicy()
    cm.AddPortGroup(spec)


def RemoveVirtualSwitch(self, name):
    '''
    Remove a virtual switch
    '''
    cm = self.configManager.networkSystem
    cm.RemoveVirtualSwitch(name)


def QueryAdvConfig(self, opt_key):
    '''
    Query the advanced config of the specific key
    '''
    adv_cfg_mgr = self.configManager.advancedOption
    adv_opt = adv_cfg_mgr.QueryOptions(opt_key);
    if adv_opt:
        return ast.literal_eval(adv_opt[0].value)
    else:
        return None

def UpdateAdvConfig(self, opt_key, opt_value):
    '''
    Update the advanced config of the specific key
    '''
    option = vim.option.OptionValue()
    option.key = opt_key
    option.value = str(opt_value).strip()
    self.configManager.advancedOption.UpdateOptions([option]);

