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


import dalibs.retry
import logging
import os
import pycurl
import sys
import time
from pyVmomi import vim


# Enable curl verbose to stderr.
curl_debug = 0


class OVFException(Exception):
    pass


class Container(object):
    ''' Generic class for attribute containment '''
    def __init__(self, attrs=[]):
        for a in attrs:
            setattr(self, a, None)


class LeaseProgress(object):
    ''' A class used by curl read callback. Also, provides lease progress updates. '''
    def __init__(self, lease, total, logger, fp):
        self.sent = float(0)
        self.total = total
        self.last = 0
        self.lease = lease
        self.logger = logger
        self.fp = fp

    def read(self, size):
        self.update(size)
        return self.fp.read(size)

    def update(self, size):
        self.sent += size
        percent = int((self.sent / self.total) * 100)
        if percent > 100:
            percent = 100
        if percent != self.last:
            if percent % 10 == 0:
                self.logger.debug('Transfer progress: %d' % percent)
            self.lease.HttpNfcLeaseProgress(percent)
            self.last = percent


class OVF(object):
    ''' Class for OVF operations '''

    def __init__(self, vc):
        self.vc = vc
        self.logger = logging.getLogger(__name__)

    def parse(self, ovffile):
        ''' Parse and load the ovf desctiptor. '''
        pdp = vim.OvfParseDescriptorParams()
        with open(ovffile, 'r') as f:
            ovf = f.read()
        ovf = unicode(ovf, errors='ignore')
        return ovf, self.vc.si.content.ovfManager.ParseDescriptor(ovf, pdp)

    def importovf(self, ovffile, **kwargs):
        last_exception = None
        for _ in dalibs.retry.retry(attempts=3, raises=False):
            try:
                return self._importovf(ovffile, **kwargs)
            except vim.fault.DuplicateName:
                raise
            except Exception as e:
                last_exception = e
                logging.exception('Import OVF failed, retrying')
        raise last_exception

    def _importovf(self, ovffile, **kwargs):
        ''' Import an OVF VM. See _set_params for support kwargs. '''
        self.logger.info('Importing OVFFile %s' % ovffile)

        # Validate ovffile.
        ovf, result = self.parse(ovffile)
        for w in result.warning:
            self.logger.warning(w.msg)
        if result.error:
            raise result.error[0]
        basedir = os.path.dirname(ovffile)

        # Load kwargs and create import spec params.
        params = self._set_params(**kwargs)
        if params.cisp is None:
            params.cisp = vim.OvfCreateImportSpecParams()
        if not params.cisp.entityName:
            params.cisp.entityName = params.name or result.defaultEntityName
        vmname = params.cisp.entityName
        self.logger.info('VM name is %s' % vmname)
        if not params.cisp.networkMapping:
            params.cisp.networkMapping = [
                vim.OvfNetworkMapping(name='VM Network', network=params.network)
            ]
        self.logger.info('Using network %s' % params.network.name)
        if params.cisp.diskProvisioning is None:
            params.cisp.diskProvisioning = params.provisioning
        self.logger.info('Provisioning is %s' % params.cisp.diskProvisioning)

        # Create import spec.
        spec = self.vc.si.content.ovfManager.CreateImportSpec(ovf, params.resourcepool,
            params.datastore, params.cisp)
        for w in spec.warning:
            self.logger.warning(w.msg)
        if spec.error:
            raise spec.error[0]

        # Start the import process.
        self.logger.debug('Running ImportVApp')
        lease = params.resourcepool.ImportVApp(spec=spec.importSpec, folder=params.folder,
            host=params.host)
        for _ in range(180):
            if lease.state == vim.HttpNfcLeaseState.ready:
                break
            elif lease.state == vim.HttpNfcLeaseState.error:
                raise lease.error
            time.sleep(1)
        else:
            lease.HttpNfcLeaseAbort()
            raise OVFException('OVF import timed out waiting to become ready: %s' % lease.state)

        # Push all files using HTTP.
        total, files = self._files(spec, lease, basedir)
        self.logger.info('Starting transfer')
        callback = LeaseProgress(lease, total, self.logger, None)

        for fi in files:
            self.logger.debug('Uploading %s to %s' % (fi.path, fi.url))
            try:
                if fi.create:
                    self._put(fi, callback)
                else:
                    self._post(fi, callback)
            except:
                lease.HttpNfcLeaseAbort()
                raise
            if lease.state == vim.HttpNfcLeaseState.error:
                lease.HttpNfcLeaseAbort()
                raise lease.error
        lease.HttpNfcLeaseComplete()
        self.logger.info('Transfer complete')
        for _ in dalibs.retry.retry(timeout=120, raises=False):
            vm = self.vc.vm(vmname)
            if vm is not None:
                assert vm.name == vmname
                return
        raise OVFException('Unable to find the VM %s' % vmname)

    def _files(self, spec, lease, basedir):
        ''' Generate a list of files to send and update ReadFunction params. '''
        total = 0
        files = []
        for fi in spec.fileItem:
            for d in lease.info.deviceUrl:
                if fi.deviceId == d.importKey:
                    f = Container()
                    f.key = d.importKey
                    # When self.vc is an ESX host, the hostname is '*'.
                    f.url = d.url.replace('https://*', 'https://%s' % self.vc.host)
                    f.create = fi.create
                    f.path = os.path.join(basedir, fi.path)
                    files.append(f)
                    total += os.path.getsize(f.path)
                    break
            else:
                lease.HttpNfcLeaseAbort()
                raise OVFException('Could not import %s' % fi.path)
        return total, files

    def _post(self, fi, callback):
        ''' Push a file using POST '''
        hdr = ['Content-Type: application/x-vnd.vmware-streamVmdk', 'Connection: Keep-Alive']
        with open(fi.path, 'rb') as f:
            callback.fp = f
            c = pycurl.Curl()
            c.setopt(pycurl.VERBOSE, curl_debug)
            c.setopt(pycurl.SSL_VERIFYPEER, 0)
            c.setopt(pycurl.SSL_VERIFYHOST, 0)
            c.setopt(pycurl.HTTPHEADER, hdr)
            c.setopt(pycurl.URL, fi.url)
            c.setopt(pycurl.POST, 1)
            c.setopt(pycurl.READFUNCTION, callback.read)
            c.setopt(pycurl.POSTFIELDSIZE_LARGE, os.path.getsize(fi.path))
            # Potential workaround for Bugs 8696 and 10697.
            c.setopt(pycurl.NOSIGNAL, 1)
            c.perform()
            c.close()

    def _put(self, fi, callback):
        ''' Push a file using PUT '''
        hdr = ['Content-Type: application/octet-stream', 'Overwrite: t', 'Connection: Keep-Alive']
        with open(fi.path, 'rb') as f:
            callback.fp = f
            c = pycurl.Curl()
            c.setopt(pycurl.VERBOSE, curl_debug)
            c.setopt(pycurl.SSL_VERIFYPEER, 0)
            c.setopt(pycurl.SSL_VERIFYHOST, 0)
            c.setopt(pycurl.HTTPHEADER, hdr)
            c.setopt(pycurl.URL, fi.url)
            c.setopt(pycurl.PUT, 1)
            c.setopt(pycurl.READFUNCTION, callback.read)
            # Potential workaround for Bugs 8696 and 10697.
            c.setopt(pycurl.NOSIGNAL, 1)
            c.perform()
            c.close()

    def _set_params(self, **kwargs):
        ''' Load kwargs into a params structure. '''
        known = ['name', 'datacenter', 'cluster', 'resourcepool', 'datastore', 'cisp',
            'provisioning', 'folder', 'host', 'network']
        params = Container(known)
        params.name = kwargs.get('name', None)
        # Default to 1st datacenter (this will exist even for single ESX)
        dc = kwargs.get('datacenter', None)
        if dc is None:
            dc = self.vc.find(vim.Datacenter)[0]
        params.datacenter = dc
        # Default to 1st cluster if it exists.
        cl = kwargs.get('cluster', None)
        if cl is None:
            clusters = dc.find(vim.ClusterComputeResource)
            if clusters:
                cl = clusters[0]
        params.cluster = cl
        # Default to top level resource pool of datacenter or cluster.
        rp = kwargs.get('resourcepool', None)
        if rp is None:
            if cl:
                rp = cl.resourcePool
            else:
                rp = dc.hostFolder.childEntity[0].resourcePool
        params.resourcepool = rp
        # Default to 1st datastore in cluster or datacenter.
        ds = kwargs.get('datastore', None)
        if ds is None:
            if cl:
                ds = cl.datastore[0]
            else:
                ds = dc.datastore[0]
        params.datastore = ds
        params.cisp = kwargs.get('cisp', None)
        params.provisioning = kwargs.get('provisioning', 'thin')
        folder = kwargs.get('folder', None)
        # Default to "vm" folder.
        if folder is None:
            folder = dc.vmFolder
        params.folder = folder
        # Default to None for host.
        host = kwargs.get('host', None)
        params.host = host

        # Default to 'VM Network'
        network = kwargs.get('network', 'VM Network')
        networks = []  # find networks, working from deepest node to the root
        for node in [host, cl, dc]:
            if node is not None:
                networks = node.network
                break
        for x in networks:  # choose the first matching network associated with this cluster
            if x.name == network:
                network = x
                break
        assert isinstance(network, vim.Network), 'No suitable network (%s) found!' % network
        params.network = network

        for k, v in params.__dict__.items():
            if hasattr(v, 'name'):
                self.logger.debug('%s name: %s' % (k, v.name))
            else:
                self.logger.debug('%s: %s' % (k, v))
        return params
