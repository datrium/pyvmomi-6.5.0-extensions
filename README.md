# pyvmomi-6.5.0-extensions

A set of extensions enabled by monkey-patching [VMware's pyVmomi 6.5](https://github.com/vmware/pyvmomi/tree/v6.5.0).


## Install
```
pip install --process-dependency-links https://github.com/datrium/pyvmomi-6.5.0-extensions/archive/master.zip#egg=pyvmomi-6.5.0-extensions
```

On MacOS, you might encounter the following `ERROR`:
```
ImportError: pycurl: libcurl link-time ssl backend (openssl) is different from compile-time ssl backend (none/other)
```

If so, [Google It](http://bit.ly/2MWuMuT). This seems to work, assuming you've `homebrew install openssl`:
```
export PYCURL_SSL_LIBRARY=openssl
export LDFLAGS="-L/usr/local/opt/openssl/lib"
export CPPFLAGS="-I/usr/local/opt/openssl/include"
pip install --process-dependency-links https://github.com/datrium/pyvmomi-6.5.0-extensions/archive/master.zip#egg=pyvmomi-6.5.0-extensions

```


## Usage
```
>>> import vim
>>> vc = vim.VC(host, username=..., password=...)
>>> vc.vms()
['vim.VirtualMachine:vm-123',
 'vim.VirtualMachine:vm-120',
  ...
 'vim.VirtualMachine:vm-48',
 'vim.VirtualMachine:vm-129']
>>>
>>> vm = vc.vm(...)
>>> vm.name
'vm-01'
>>> vm.ipaddr
'10.80.8.124'
>>> vm.check_output('echo subprocess over ssh', username=..., password=...)
'subprocess over ssh\r\n'

```

There are a few _major_ benefits/reasons to use these pyvmomi extensions.

1. adds a `find()` to `ManagedObject`s.
2. hides the complexity of `PropertyCollector`s; and destroys instances when done
3. adds [subprocess](https://docs.python.org/2/library/subprocess.html) style methods to `HostSystem`s and `VirtualMachine`s
4. adds `ImportOVF()` to a `VC` instance
