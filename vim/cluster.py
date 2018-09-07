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
Adds functionality to pyVmomi.Vim.ClusterComputeResource
'''


import time
from pyVmomi import vim, vmodl


def vm(self):
    return self.find(vim.VirtualMachine)


def EnableHA_Task(self, datastore):
    '''
    Enable HA and heart beat with the data store
    :param cluster: the cluster, which is going to be HA-enabled
    :param datastore: the data store, which is going to heart beat with the cluster
    :return: None
    '''
    cluster_spec = vim.ClusterConfigSpecEx()
    ha_spec = vim.ClusterDasConfigInfo()
    ha_spec.enabled = True
    ha_spec.vmMonitoring = vim.ClusterDasConfigInfoVmMonitoringState.vmMonitoringDisabled
    ha_spec.hostMonitoring = vim.ClusterDasConfigInfoServiceState.enabled
    fp = vim.ClusterFailoverLevelAdmissionControlPolicy()
    fp.failoverLevel = 1
    ha_spec.admissionControlPolicy = fp
    ha_spec.admissionControlEnabled = True
    dvs = vim.ClusterDasVmSettings()
    dvs.isolationResponse = vim.ClusterDasVmSettingsIsolationResponse.none
    vtms = vim.ClusterVmToolsMonitoringSettings()
    dvs.vmToolsMonitoringSettings = vtms
    ha_spec.defaultVmSettings = dvs
    cluster_spec.dasConfig = ha_spec
    # Heartbeat datastore
    cluster_spec.dasConfig.heartbeatDatastore.append(datastore)
    return self.ReconfigureEx(cluster_spec, True)


def CreateResourcePool(self, name):
    '''
    Create a resource pool with name
    '''
    spec = vim.ResourceConfigSpec()
    spec.cpuAllocation = vim.ResourceAllocationInfo()
    spec.cpuAllocation.limit = -1
    spec.cpuAllocation.reservation = 0
    spec.cpuAllocation.expandableReservation = True
    spec.cpuAllocation.shares = vim.SharesInfo()
    spec.cpuAllocation.shares.level = vim.SharesInfo.Level.normal
    spec.cpuAllocation.shares.shares = 0
    spec.memoryAllocation = spec.cpuAllocation

    # Normally, this API would just attempt to create the resourcepool and let the
    # caller deal with any exceptions. But, our workflow commonly attempts to
    # create resourcepools that may already exist or be in the process of creation.
    # So, go ahead an handle that here.
    try:
        return [x for x in self.find(vim.ResourcePool) if x.name == name][0]
    except (vmodl.fault.ManagedObjectNotFound, IndexError):
        pass
    try:
        return self.resourcePool.CreateResourcePool(name=name, spec=spec)
    except vim.fault.DuplicateName:
        # Another caller has already created (or is creating) the resourcepool.
        # Wait for it to be created and then return it.
        while True:
            time.sleep(0.2)
            try:
                return [x for x in self.find(vim.ResourcePool) if x.name == name][0]
            except vmodl.fault.ManagedObjectNotFound:
                # The object has already been deleted or has not been completely created
                # Likely it hasn't been completely created ...
                continue
