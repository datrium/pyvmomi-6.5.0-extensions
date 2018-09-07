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
Adds functionality to pyVmomi.Vim.ManagedObject
'''

from pyVmomi import vim


def si(self):
    return vim.ServiceInstance("ServiceInstance", self._stub)


def _find(self, klasses, path=None, attrs=[]):
    ''' Find managed objects of types klasses. You can also specify attributes you want
    to fetch, per klass. The attributes get passed to the property collector, so that the
    values are cached.

    This method is private. t is exposed publicly through :py:func:`.find`.

    :param klasses: pyVmomi.Vim classes to find during traversal
    :type klasses: list
    :param path: path to start the traversal (if None, the current managed object is the start)
    :type path: string or None
    :param attrs: properties per class to fetch during traversal
    :type attrs: list of lists

    '''
    if not isinstance(klasses, list):
        klasses = [klasses]
        attrs = [attrs]

    if not len(klasses) == len(attrs):
        msg = 'Number of classes should be same as number of attribute sets requested'
        raise ValueError(msg)

    propspecs = []
    for i in range(len(klasses)):
        next_klass = klasses[i]
        next_attrs = attrs[i]
        propspec = vim.PropertySpec()
        propspec.type = next_klass
        propspec.all = False
        propspec.pathSet = next_attrs
        propspecs.append(propspec)

    if path is None:
        path = self
    if isinstance(path, basestring):
        path = self.si.content.searchIndex.FindByInventoryPath(path)

    viewManager = self.si.content.viewManager
    view = viewManager.CreateContainerView(path, klasses, True)
    objspec = vim.ObjectSpec()
    objspec.obj = view
    objspec.skip = not bool(attrs)

    tspec = vim.TraversalSpec()
    tspec.name = 'traverseEntities'
    tspec.type = vim.ContainerView
    tspec.path = 'view'
    tspec.skip = False
    objspec.selectSet = [tspec]

    pfspec = vim.PropertyFilterSpec()
    pfspec.objectSet = [objspec]
    pfspec.propSet = propspecs

    pc = self.si.content.propertyCollector
    result = pc.RetrieveProperties([pfspec])
    view.DestroyView()
    return result


def find(self, klass, path=None, attrs=[]):
    if not isinstance(klass, list):
        klass = [klass]
        attrs = [attrs]
    results = _find(self, klass, path=path, attrs=attrs)
    return [x.obj for x in results]


def path(self):
    if self == self.si.content.rootFolder:
        return ''
    return self.parent.path + '/' + self.name
