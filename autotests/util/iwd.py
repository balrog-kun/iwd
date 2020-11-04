#!/usr/bin/python3
from gi.repository import GLib

import dbus
import dbus.service
import dbus.mainloop.glib
import sys
import os
import threading
import time
import collections
import datetime
import weakref

from abc import ABCMeta, abstractmethod
from enum import Enum

from config import ctx

IWD_STORAGE_DIR =               '/tmp/iwd'
IWD_CONFIG_DIR =                '/tmp'

DBUS_OBJECT_MANAGER =           'org.freedesktop.DBus.ObjectManager'
DBUS_PROPERTIES =               'org.freedesktop.DBus.Properties'

IWD_SERVICE =                   'net.connman.iwd'
IWD_WIPHY_INTERFACE =           'net.connman.iwd.Adapter'
IWD_AGENT_INTERFACE =           'net.connman.iwd.Agent'
IWD_AGENT_MANAGER_INTERFACE =   'net.connman.iwd.AgentManager'
IWD_DEVICE_INTERFACE =          'net.connman.iwd.Device'
IWD_KNOWN_NETWORK_INTERFACE =   'net.connman.iwd.KnownNetwork'
IWD_NETWORK_INTERFACE =         'net.connman.iwd.Network'
IWD_WSC_INTERFACE =             'net.connman.iwd.SimpleConfiguration'
IWD_SIGNAL_AGENT_INTERFACE =    'net.connman.iwd.SignalLevelAgent'
IWD_AP_INTERFACE =              'net.connman.iwd.AccessPoint'
IWD_ADHOC_INTERFACE =           'net.connman.iwd.AdHoc'
IWD_STATION_INTERFACE =         'net.connman.iwd.Station'
IWD_P2P_INTERFACE =             'net.connman.iwd.p2p.Device'
IWD_P2P_PEER_INTERFACE =        'net.connman.iwd.p2p.Peer'
IWD_P2P_SERVICE_MANAGER_INTERFACE = 'net.connman.iwd.p2p.ServiceManager'
IWD_P2P_WFD_INTERFACE =         'net.connman.iwd.p2p.Display'

IWD_AGENT_MANAGER_PATH =        '/net/connman/iwd'
IWD_TOP_LEVEL_PATH =            '/'

class UnknownDBusEx(Exception): pass
class InProgressEx(dbus.DBusException): pass
class FailedEx(dbus.DBusException): pass
class AbortedEx(dbus.DBusException): pass
class NotAvailableEx(dbus.DBusException): pass
class InvalidArgumentsEx(dbus.DBusException): pass
class InvalidFormatEx(dbus.DBusException): pass
class AlreadyExistsEx(dbus.DBusException): pass
class NotFoundEx(dbus.DBusException): pass
class NotSupportedEx(dbus.DBusException): pass
class NoAgentEx(dbus.DBusException): pass
class NotConnectedEx(dbus.DBusException): pass
class NotConfiguredEx(dbus.DBusException): pass
class NotImplementedEx(dbus.DBusException): pass
class ServiceSetOverlapEx(dbus.DBusException): pass
class AlreadyProvisionedEx(dbus.DBusException): pass
class NotHiddenEx(dbus.DBusException): pass
class CanceledEx(dbus.DBusException):
    _dbus_error_name = 'net.connman.iwd.Error.Canceled'


_dbus_ex_to_py = {
    'Canceled' :            CanceledEx,
    'InProgress' :          InProgressEx,
    'Failed' :              FailedEx,
    'Aborted' :             AbortedEx,
    'NotAvailable' :        NotAvailableEx,
    'InvalidArguments' :    InvalidArgumentsEx,
    'InvalidFormat' :       InvalidFormatEx,
    'AlreadyExists' :       AlreadyExistsEx,
    'NotFound' :            NotFoundEx,
    'NotSupported' :        NotSupportedEx,
    'NoAgent' :             NoAgentEx,
    'NotConnected' :        NotConnectedEx,
    'NotConfigured' :       NotConfiguredEx,
    'NotImplemented' :      NotImplementedEx,
    'ServiceSetOverlap' :   ServiceSetOverlapEx,
    'AlreadyProvisioned' :  AlreadyProvisionedEx,
    'NotHidden' :           NotHiddenEx,
}


def _convert_dbus_ex(dbus_ex):
    ex_name = dbus_ex.get_dbus_name()
    ex_short_name = ex_name[ex_name.rfind(".") + 1:]
    if ex_short_name in _dbus_ex_to_py:
        return _dbus_ex_to_py[ex_short_name](dbus_ex)
    else:
        return UnknownDBusEx(ex_name + ': ' + dbus_ex.get_dbus_message())


class AsyncOpAbstract(object):
    __metaclass__ = ABCMeta

    _is_completed = False
    _exception = None

    def _success(self):
        self._is_completed = True

    def _failure(self, ex):
        self._is_completed = True
        self._exception = _convert_dbus_ex(ex)

    def _wait_for_async_op(self):
        context = ctx.mainloop.get_context()
        while not self._is_completed:
            context.iteration(may_block=True)

        self._is_completed = False
        if self._exception is not None:
            tmp = self._exception
            self._exception = None
            raise tmp


class IWDDBusAbstract(AsyncOpAbstract):
    __metaclass__ = ABCMeta

    _bus = dbus.SystemBus()

    def __init__(self, object_path = None, properties = None, service=IWD_SERVICE):
        self._object_path = object_path
        proxy = self._bus.get_object(service, self._object_path)
        self._iface = dbus.Interface(proxy, self._iface_name)
        self._prop_proxy = dbus.Interface(proxy, DBUS_PROPERTIES)

        if properties is None:
            self._properties = self._prop_proxy.GetAll(self._iface_name)
        else:
            self._properties = properties

        self._prop_proxy.connect_to_signal("PropertiesChanged",
                                           self._property_changed_handler,
                                           DBUS_PROPERTIES,
                                           path_keyword="path")

    def _property_changed_handler(self, interface, changed, invalidated, path):
        if interface == self._iface_name and path == self._object_path:
            for name, value in changed.items():
                self._properties[name] = value

    @abstractmethod
    def __str__(self):
        pass


class DeviceState(Enum):
    '''Conection state of a device'''
    connected =     'connected'
    disconnected =  'disconnected'
    connecting =    'connecting'
    disconnecting = 'disconnecting'
    roaming =       'roaming'

    def __str__(self):
        return self.value

    @classmethod
    def from_str(cls, string):
        return getattr(cls, string, None)


class NetworkType(Enum):
    '''Network security type'''
    open =  'open'
    psk =   'psk'
    eap =   '8021x'
    hotspot = 'hotspot'

    def __str__(self):
        return str(self.value)

    @classmethod
    def from_string(cls, string):
        type = None
        for attr in dir(cls):
            if (str(getattr(cls, attr)) == string):
                type = getattr(cls, attr)
                break
        return type


class SignalAgent(dbus.service.Object):
    def __init__(self, passphrase = None):
        self._path = '/test/agent/' + str(int(round(time.time() * 1000)))

        dbus.service.Object.__init__(self, dbus.SystemBus(), self._path)

    @property
    def path(self):
        return self._path

    @dbus.service.method(IWD_SIGNAL_AGENT_INTERFACE,
                         in_signature='', out_signature='')
    def Release(self):
        print("SignalAgent released")

    @dbus.service.method(IWD_SIGNAL_AGENT_INTERFACE,
                         in_signature='oy', out_signature='')
    def Changed(self, path, level):
        self.handle_new_level(str(path), int(level))

    @abstractmethod
    def handle_new_level(self, path, level):
        pass

class AdHocDevice(IWDDBusAbstract):
    '''
        Class represents an AdHoc device object: net.connman.iwd.AdHoc
    '''
    _iface_name = IWD_ADHOC_INTERFACE

    @property
    def started(self):
        return self._properties['Started']

    @property
    def connected_peers(self):
        return self._properties['ConnectedPeers']


class Device(IWDDBusAbstract):
    '''
        Class represents a network device object: net.connman.iwd.Device
        with its properties and methods
    '''
    _iface_name = IWD_DEVICE_INTERFACE

    def __init__(self, *args, **kwargs):
        self._wps_manager_if = None
        self._station_if = None
        self._station_props = None
        IWDDBusAbstract.__init__(self, *args, **kwargs)

    @property
    def _wps_manager(self):
        if self._wps_manager_if is None:
            _wps_manager_if =\
                dbus.Interface(self._bus.get_object(IWD_SERVICE,
                                                    self.device_path),
                               IWD_WSC_INTERFACE)
        return _wps_manager_if

    @property
    def _station(self):
        if self._station_if is None:
            self._station_if = dbus.Interface(self._bus.get_object(IWD_SERVICE,
                                                            self.device_path),
                                            IWD_STATION_INTERFACE)
        return self._station_if

    def _station_properties(self):
        if self._station_props is not None:
            return self._station_props

        if self._properties['Mode'] != 'station':
            self._prop_proxy.Set(IWD_DEVICE_INTERFACE, 'Mode', 'station')

        self._station_prop_if = \
                dbus.Interface(self._bus.get_object(IWD_SERVICE,
                                                            self.device_path),
                                                DBUS_PROPERTIES)

        self._station_props = self._station_prop_if.GetAll(IWD_STATION_INTERFACE)

        self._station_prop_if.connect_to_signal("PropertiesChanged",
                                        self.__station_property_changed_handler,
                                        DBUS_PROPERTIES, path_keyword="path")

        return self._station_props

    def __station_property_changed_handler(self, interface, changed,
                                                            invalidated, path):
        if interface == IWD_STATION_INTERFACE and path == self._object_path:
            for name, value in changed.items():
                self._station_props[name] = value

    @property
    def device_path(self):
        '''
            Device's dbus path.

            @rtype: string
        '''
        return self._object_path

    @property
    def name(self):
        '''
            Device's interface name.

            @rtype: string
        '''
        return self._properties['Name']

    @property
    def address(self):
        '''
            Interface's hardware address in the XX:XX:XX:XX:XX:XX format.

            @rtype: string
        '''
        return self._properties['Address']

    @property
    def state(self):
        '''
            Reflects the general network connection state.

            @rtype: object (State)
        '''
        props = self._station_properties()
        return DeviceState.from_str(props['State'])

    @property
    def connected_network(self):
        '''
            net.connman.iwd.Network object representing the
            network the device is currently connected to or to
            which a connection is in progress.

            @rtype: object (Network)
        '''
        props = self._station_properties()
        return props.get('ConnectedNetwork')

    @property
    def powered(self):
        '''
            True if the interface is UP. If false, the device's radio is
            powered down and no other actions can be performed on the device.

            @rtype: boolean
        '''
        return bool(self._properties['Powered'])

    @property
    def scanning(self):
        '''
        Reflects whether the device is currently scanning
        for networks.  net.connman.iwd.Network objects are
        updated when this property goes from true to false.

        @rtype: boolean
        '''
        props = self._station_properties()
        return bool(props['Scanning'])

    def scan(self):
        '''Schedule a network scan.

           Possible exception: BusyEx
                               FailedEx
        '''
        self._iface.Scan(dbus_interface=IWD_STATION_INTERFACE,
                               reply_handler=self._success,
                               error_handler=self._failure)

        self._wait_for_async_op()

    def disconnect(self):
        '''Disconnect from the network

           Possible exception: BusyEx
                               FailedEx
                               NotConnectedEx
        '''
        self._iface.Disconnect(dbus_interface=IWD_STATION_INTERFACE,
                               reply_handler=self._success,
                               error_handler=self._failure)

        self._wait_for_async_op()

    def get_ordered_networks(self, scan_if_needed = False):
        '''Return the list of networks found in the most recent
           scan, sorted by their user interface importance
           score as calculated by iwd.  If the device is
           currently connected to a network, that network is
           always first on the list, followed by any known
           networks that have been used at least once before,
           followed by any other known networks and any other
           detected networks as the last group.  Within these
           groups the maximum relative signal-strength is the
           main sorting factor.
        '''
        ordered_networks = []
        for bus_obj in self._station.GetOrderedNetworks():
            ordered_network = OrderedNetwork(bus_obj)
            ordered_networks.append(ordered_network)

        if len(ordered_networks) > 0:
            return ordered_networks
        elif not scan_if_needed:
            return None

        iwd = IWD.get_instance()

        self.scan()

        condition = 'obj.scanning'
        iwd.wait_for_object_condition(self, condition)
        condition = 'not obj.scanning'
        iwd.wait_for_object_condition(self, condition)

        for bus_obj in self._station.GetOrderedNetworks():
            ordered_network = OrderedNetwork(bus_obj)
            ordered_networks.append(ordered_network)

        if len(ordered_networks) > 0:
            return ordered_networks

        return None

    def get_ordered_network(self, network, scan_if_needed = False):
        '''Returns a single network from ordered network call, or None if the
           network wasn't found. If the network is not found an exception is
           raised, this removes the need to extra asserts in autotests.
        '''
        ordered_networks = self.get_ordered_networks(scan_if_needed)

        if not ordered_networks:
            raise Exception('Network %s not found' % network)

        for n in ordered_networks:
            if n.name == network:
                return n

        raise Exception('Network %s not found' % network)

    def wps_push_button(self):
        self._wps_manager.PushButton(dbus_interface=IWD_WSC_INTERFACE,
                                     reply_handler=self._success,
                                     error_handler=self._failure)
        self._wait_for_async_op()

    def wps_generate_pin(self):
        return self._wps_manager.GeneratePin()

    def wps_start_pin(self, pin):
        self._wps_manager.StartPin(pin, reply_handler=self._success,
                                        error_handler=self._failure)

    def wps_cancel(self):
        self._wps_manager.Cancel(dbus_interface=IWD_WSC_INTERFACE,
                                 reply_handler=self._success,
                                 error_handler=self._failure)
        self._wait_for_async_op()

    def register_signal_agent(self, signal_agent, levels):
        self._station.RegisterSignalLevelAgent(signal_agent.path,
                                        dbus.Array(levels, 'n'),
                                        dbus_interface=IWD_STATION_INTERFACE,
                                        reply_handler=self._success,
                                        error_handler=self._failure)
        self._wait_for_async_op()

    def unregister_signal_agent(self, signal_agent):
        self._station.UnregisterSignalLevelAgent(signal_agent.path,
                                        dbus_interface=IWD_STATION_INTERFACE,
                                        reply_handler=self._success,
                                        error_handler=self._failure)
        self._wait_for_async_op()

    def start_ap(self, ssid, psk=None):
        try:
            self._prop_proxy.Set(IWD_DEVICE_INTERFACE, 'Mode', 'ap')
        except Exception as e:
            raise _convert_dbus_ex(e)

        self._ap_iface = dbus.Interface(self._bus.get_object(IWD_SERVICE,
                                            self.device_path),
                                            IWD_AP_INTERFACE)
        if psk:
            self._ap_iface.Start(ssid, psk, reply_handler=self._success,
                                    error_handler=self._failure)
        else:
            self._ap_iface.StartProfile(ssid, reply_handler=self._success,
                                    error_handler=self._failure)
        self._wait_for_async_op()

    def stop_ap(self):
        self._prop_proxy.Set(IWD_DEVICE_INTERFACE, 'Mode', 'station')

    def connect_hidden_network(self, name):
        '''Connect to a hidden network
           Possible exception: BusyEx
                               FailedEx
                               InvalidArgumentsEx
                               NotConfiguredEx
                               NotConnectedEx
                               NotFoundEx
                               ServiceSetOverlapEx
        '''
        self._iface.ConnectHiddenNetwork(name,
                               dbus_interface=IWD_STATION_INTERFACE,
                               reply_handler=self._success,
                               error_handler=self._failure)
        self._wait_for_async_op()

    def connect_hidden_network_async(self, name, reply_handler, error_handler):
        '''Connect to a hidden network
           Possible exception: BusyEx
                               FailedEx
                               InvalidArgumentsEx
                               NotConfiguredEx
                               NotConnectedEx
                               NotFoundEx
                               ServiceSetOverlapEx
        '''
        self._iface.ConnectHiddenNetwork(name,
                               dbus_interface=IWD_STATION_INTERFACE,
                               reply_handler=reply_handler,
                               error_handler=error_handler)

    def start_adhoc(self, ssid, psk=None):
        self._prop_proxy.Set(IWD_DEVICE_INTERFACE, 'Mode', 'ad-hoc')
        self._adhoc_iface = dbus.Interface(self._bus.get_object(IWD_SERVICE,
                                            self.device_path),
                                            IWD_ADHOC_INTERFACE)
        if not psk:
            self._adhoc_iface.StartOpen(ssid, reply_handler=self._success,
                                        error_handler=self._failure)
        else:
            self._adhoc_iface.Start(ssid, psk, reply_handler=self._success,
                                        error_handler=self._failure)
        self._wait_for_async_op()

        return AdHocDevice(self.device_path)

    def stop_adhoc(self):
        self._prop_proxy.Set(IWD_DEVICE_INTERFACE, 'Mode', 'station')

    def __str__(self, prefix = ''):
        return prefix + 'Device: ' + self.device_path + '\n'\
               + prefix + '\tName:\t\t' + self.name + '\n'\
               + prefix + '\tAddress:\t' + self.address + '\n'\
               + prefix + '\tState:\t\t' + str(self.state) + '\n'\
               + prefix + '\tPowered:\t' + str(self.powered) + '\n'\
               + prefix + '\tConnected net:\t' + str(self.connected_network) +\
                                                                            '\n'


class Network(IWDDBusAbstract):
    '''Class represents a network object: net.connman.iwd.Network'''
    _iface_name = IWD_NETWORK_INTERFACE

    @property
    def name(self):
        '''
            Network SSID.

            @rtype: string
        '''
        return self._properties['Name']

    @property
    def connected(self):
        '''
            Reflects whether the device is connected to this network.

            @rtype: boolean
        '''
        return bool(self._properties['Connected'])

    def connect(self, wait=True):
        '''
            Connect to the network. Request the device implied by the object
            path to connect to specified network.

			Possible exception: AbortedEx
                                BusyEx
                                FailedEx
                                NoAgentEx
                                NotSupportedEx
                                TimeoutEx

            @rtype: void
        '''

        self._iface.Connect(dbus_interface=self._iface_name,
                            reply_handler=self._success,
                            error_handler=self._failure)

        if wait:
            self._wait_for_async_op()

    def __str__(self, prefix = ''):
        return prefix + 'Network:\n' \
                + prefix + '\tName:\t' + self.name + '\n' \
                + prefix + '\tConnected:\t' + str(self.connected)


class KnownNetwork(IWDDBusAbstract):
    '''Class represents a known network object: net.connman.iwd.KnownNetwork'''
    _iface_name = IWD_KNOWN_NETWORK_INTERFACE

    def forget(self):
        '''
        Removes information saved by IWD about this network
        causing it to be treated as if IWD had never connected
        to it before.
        '''
        self._iface.Forget(dbus_interface=self._iface_name,
                               reply_handler=self._success,
                               error_handler=self._failure)
        self._wait_for_async_op()

    @property
    def name(self):
        '''Contains the Name (SSID) of the network.'''
        return str(self._properties['Name'])

    @property
    def type(self):
        '''Contains the type of the network.'''
        return NetworkType(self._properties['Type'])

    @property
    def last_connected_time(self):
        '''
        Contains the last time this network has been connected to.
        If the network is known, but has never been successfully
        connected to, this attribute is set to None.

        @rtype: datetime
        '''
        if 'LastConnectedTime' not in self._properties:
            return None

        val = self._properties['LastConnectedTime']
        return datetime.datetime.strptime(val, "%Y-%m-%dT%H:%M:%SZ")

    def __str__(self, prefix = ''):
        return prefix + 'Known Network:\n' \
                + prefix + '\tName:\t' + self.name + '\n' \
                + prefix + '\tType:\t' + str(self.type) + '\n' \
                + prefix + '\tLast connected:\t' + str(self.last_connected_time)

class OrderedNetwork(object):
    '''Represents a network found in the scan'''

    _bus = dbus.SystemBus()

    def __init__(self, o_n_tuple):
        self._network_object = Network(o_n_tuple[0])
        self._network_proxy = dbus.Interface(self._bus.get_object(IWD_SERVICE,
                                        o_n_tuple[0]),
                                        DBUS_PROPERTIES)
        self._properties = self._network_proxy.GetAll(IWD_NETWORK_INTERFACE)

        self._name = self._properties['Name']
        self._signal_strength = o_n_tuple[1]
        self._type = NetworkType.from_string(str(self._properties['Type']))

    @property
    def network_object(self):
        '''
            net.connman.iwd.Network object representing the network.

            @rtype: Network
        '''
        return self._network_object

    @property
    def name(self):
        '''
            Device's interface name.

            @rtype: string
        '''
        return self._name

    @property
    def signal_strength(self):
        '''
            Network's maximum signal strength expressed in 100 * dBm.
            The value is the range of 0 (strongest signal) to
            -10000 (weakest signal)

            @rtype: number
        '''
        return self._signal_strength

    @property
    def type(self):
        '''
            Contains the type of the network.

            @rtype: NetworkType
        '''
        return self._type

    def __str__(self):
        return 'Ordered Network:\n'\
                '\tName:\t\t' + self._name + '\n'\
                '\tNetwork Type:\t' + str(self._type) + '\n'\
                '\tSignal Strength:'\
                    + ('None' if self.signal_strength is None else\
                        str(self.signal_strength)) + '\n'\
                '\tObject: \n' + self.network_object.__str__('\t\t')

agent_count = 0

class PSKAgent(dbus.service.Object):

    def __init__(self, passphrases=[], users=[]):
        global agent_count

        if type(passphrases) != list:
            passphrases = [passphrases]
        self.passphrases = passphrases
        if type(users) != list:
            users = [users]
        self.users = users
        self._path = '/test/agent/%s' % agent_count

        agent_count += 1

        dbus.service.Object.__init__(self, dbus.SystemBus(), self._path)

    @property
    def path(self):
        return self._path

    @dbus.service.method(IWD_AGENT_INTERFACE, in_signature='', out_signature='')
    def Release(self):
        print("Agent released")

    @dbus.service.method(IWD_AGENT_INTERFACE, in_signature='s',
                                                               out_signature='')
    def Cancel(self, reason):
        print("Cancel: " + reason)


    @dbus.service.method(IWD_AGENT_INTERFACE, in_signature='o',
                                                              out_signature='s')
    def RequestPassphrase(self, path):
        print('Requested PSK for ' + path)

        if not self.passphrases:
            raise CanceledEx("canceled")

        return self.passphrases.pop(0)

    @dbus.service.method(IWD_AGENT_INTERFACE, in_signature='o',
                                                              out_signature='s')
    def RequestPrivateKeyPassphrase(self, path):
        print('Requested private-key passphrase for ' + path)

        if not self.passphrases:
            raise CanceledEx("canceled")

        return self.passphrases.pop(0)

    @dbus.service.method(IWD_AGENT_INTERFACE, in_signature='o',
                                                             out_signature='ss')
    def RequestUserNameAndPassword(self, path):
        print('Requested the user name and password for ' + path)

        if not self.users:
            raise CanceledEx("canceled")

        return self.users.pop(0)

    @dbus.service.method(IWD_AGENT_INTERFACE, in_signature='os',
                                                              out_signature='s')
    def RequestUserPassword(self, path, req_user):
        print('Requested the password for ' + path + ' for user ' + req_user)

        if not self.users:
            raise CanceledEx("canceled")

        user, passwd = self.users.pop(0)
        if user != req_user:
            raise CanceledEx("canceled")

        return passwd


class P2PDevice(IWDDBusAbstract):
    _iface_name = IWD_P2P_INTERFACE

    def __init__(self, *args, **kwargs):
        self._discovery_request = False
        self._peer_dict = {}
        IWDDBusAbstract.__init__(self, *args, **kwargs)

    @property
    def name(self):
        return str(self._properties['Name'])

    @name.setter
    def name(self, name):
        self._prop_proxy.Set(self._iface_name, 'Name', name)

    @property
    def enabled(self):
        return bool(self._properties['Enabled'])

    @enabled.setter
    def enabled(self, enabled):
        self._prop_proxy.Set(self._iface_name, 'Enabled', enabled)

    @property
    def discovery_request(self):
        return self._discovery_request

    @discovery_request.setter
    def discovery_request(self, req):
        if self._discovery_request == bool(req):
            return

        if bool(req):
            self._iface.RequestDiscovery()
        else:
            self._iface.ReleaseDiscovery()

        self._discovery_request = bool(req)

    def get_peers(self):
        old_dict = self._peer_dict
        self._peer_dict = {}

        for path, rssi in self._iface.GetPeers():
            self._peer_dict[path] = old_dict[path] if path in old_dict else P2PPeer(path)
            self._peer_dict[path].rssi = rssi

        return self._peer_dict


class P2PPeer(IWDDBusAbstract):
    _iface_name = IWD_P2P_PEER_INTERFACE

    @property
    def name(self):
        return str(self._properties['Name'])

    @property
    def category(self):
        return str(self._properties['DeviceCategory'])

    @property
    def subcategory(self):
        return str(self._properties['DeviceSubcategory'])

    @property
    def connected(self):
        return bool(self._properties['Connected'])

    @property
    def connected_interface(self):
        return str(self._properties['ConnectedInterface'])

    @property
    def connected_ip(self):
        return str(self._properties['ConnectedIP'])

    def connect(self, wait=True, pin=None):
        if pin is None:
            self._iface.PushButton(dbus_interface=IWD_WSC_INTERFACE,
                            reply_handler=self._success,
                            error_handler=self._failure)
        else:
            self._iface.StartPin(pin,
                            dbus_interface=IWD_WSC_INTERFACE,
                            reply_handler=self._success,
                            error_handler=self._failure)

        if wait:
            self._wait_for_async_op()
            return (self.connected_interface, self.connected_ip)

    def disconnect(self):
        self._iface.Disconnect()


class DeviceList(collections.Mapping):
    def __init__(self, iwd):
        self._dict = {}
        self._p2p_dict = {}

        iwd._object_manager.connect_to_signal("InterfacesAdded",
                                               self._interfaces_added_handler)
        iwd._object_manager.connect_to_signal("InterfacesRemoved",
                                               self._interfaces_removed_handler)

        objects = iwd._object_manager.GetManagedObjects()

        for path in objects:
            for interface in objects[path]:
                if interface == IWD_DEVICE_INTERFACE:
                    self._dict[path] = Device(path, objects[path][interface])
                elif interface == IWD_P2P_INTERFACE:
                    self._p2p_dict[path] = P2PDevice(path, objects[path][interface])

    def __getitem__(self, key):
        return self._dict.__getitem__(key)

    def __iter__(self):
        return self._dict.__iter__()

    def __len__(self):
        return self._dict.__len__()

    def __delitem__(self, key):
        self._dict.pop(key).remove()

    def _interfaces_added_handler(self, path, interfaces):
        if IWD_DEVICE_INTERFACE in interfaces:
            self._dict[path] = Device(path, interfaces[IWD_DEVICE_INTERFACE])
        elif IWD_P2P_INTERFACE in interfaces:
            self._p2p_dict[path] = P2PDevice(path, interfaces[IWD_P2P_INTERFACE])

    def _interfaces_removed_handler(self, path, interfaces):
        if IWD_DEVICE_INTERFACE in interfaces:
            del self._dict[path]
        elif IWD_P2P_INTERFACE in interfaces:
            del self._p2p_dict[path]

    @property
    def p2p_dict(self):
        return self._p2p_dict


class IWD(AsyncOpAbstract):
    '''
        Start an IWD instance. By default IWD should already be running, but
        some tests do require starting IWD using this constructor (by passing
        start_iwd_daemon=True)
    '''
    _bus = dbus.SystemBus()

    _object_manager_if = None
    _agent_manager_if = None
    _iwd_proc = None
    _devices = None
    _instance = None
    psk_agent = None

    def __init__(self, start_iwd_daemon = False, iwd_config_dir = '/tmp'):
        if start_iwd_daemon and ctx.is_process_running('iwd'):
            raise Exception("IWD requested to start but is already running")

        if start_iwd_daemon:
            self._iwd_proc = ctx.start_iwd(iwd_config_dir)

        tries = 0
        while not self._bus.name_has_owner(IWD_SERVICE):
            if not ctx.args.gdb:
                if tries > 200:
                    if start_iwd_daemon:
                        ctx.stop_process(self._iwd_proc)
                        self._iwd_proc = None
                    raise TimeoutError('IWD has failed to start')
                tries += 1
            time.sleep(0.1)

        self._devices = DeviceList(self)

        # Weak to make sure the test's reference to @self is the only counted
        # reference so that __del__ gets called when it's released
        IWD._instance = weakref.ref(self)

    def __del__(self):
        if self.psk_agent:
            self.unregister_psk_agent(self.psk_agent)

        self._object_manager_if = None
        self._agent_manager_if = None
        self._known_networks = None
        self._devices = None

        if self._iwd_proc is not None:
            ctx.stop_process(self._iwd_proc)
            self._iwd_proc = None

    @property
    def _object_manager(self):
        if self._object_manager_if is None:
            self._object_manager_if = \
                       dbus.Interface(self._bus.get_object(IWD_SERVICE,
                                                           IWD_TOP_LEVEL_PATH),
                                      DBUS_OBJECT_MANAGER)
        return self._object_manager_if

    @property
    def _agent_manager(self):
        if self._agent_manager_if is None:
            self._agent_manager_if =\
                dbus.Interface(self._bus.get_object(IWD_SERVICE,
                                                    IWD_AGENT_MANAGER_PATH),
                               IWD_AGENT_MANAGER_INTERFACE)
        return self._agent_manager_if

    def wait_for_object_condition(self, obj, condition_str, max_wait = 50):
        self._wait_timed_out = False
        def wait_timeout_cb():
            self._wait_timed_out = True
            return False

        try:
            timeout = GLib.timeout_add_seconds(max_wait, wait_timeout_cb)
            context = ctx.mainloop.get_context()
            while not eval(condition_str):
                context.iteration(may_block=True)
                if self._wait_timed_out and ctx.args.gdb == None:
                    raise TimeoutError('[' + condition_str + ']'\
                                       ' condition was not met in '\
                                       + str(max_wait) + ' sec')
        finally:
            if not self._wait_timed_out:
                GLib.source_remove(timeout)

    def wait(self, time):
        self._wait_timed_out = False
        def wait_timeout_cb():
            self._wait_timed_out = True
            return False

        try:
            timeout = GLib.timeout_add(int(time * 1000), wait_timeout_cb)
            context = ctx.mainloop.get_context()
            while not self._wait_timed_out:
                context.iteration(may_block=True)
        finally:
            if not self._wait_timed_out:
                GLib.source_remove(timeout)

    @staticmethod
    def clear_storage(storage_dir=IWD_STORAGE_DIR):
        os.system('rm -rf ' + storage_dir + '/*')
        os.system('rm -rf ' + storage_dir + '/hotspot/*')
        os.system('rm -rf ' + storage_dir + '/ap/*')

    @staticmethod
    def create_in_storage(file_name, file_content):
        fo = open(IWD_STORAGE_DIR + '/' + file_name, 'w')

        fo.write(file_content)
        fo.close()

    @staticmethod
    def copy_to_storage(source, storage_dir=IWD_STORAGE_DIR):
        import shutil

        assert not os.path.isabs(source)

        shutil.copy(source, storage_dir)

    @staticmethod
    def copy_to_hotspot(source):
        import shutil

        assert not os.path.isabs(source)

        if not os.path.exists(IWD_STORAGE_DIR + "/hotspot"):
            os.mkdir(IWD_STORAGE_DIR + "/hotspot")

        shutil.copy(source, IWD_STORAGE_DIR + "/hotspot")

    @staticmethod
    def copy_to_ap(source):
        if not os.path.exists(IWD_STORAGE_DIR + "/ap"):
            os.mkdir(IWD_STORAGE_DIR + "/ap")

        IWD.copy_to_storage(source, IWD_STORAGE_DIR + '/ap/')

    @staticmethod
    def remove_from_storage(file_name):
        os.system('rm -rf ' + IWD_STORAGE_DIR + '/\'' + file_name + '\'')

    def list_devices(self, wait_to_appear = 0, max_wait = 50, p2p = False):
        if not wait_to_appear:
            return list(self._devices.values() if not p2p else self._devices.p2p_dict.values())

        self._wait_timed_out = False
        def wait_timeout_cb():
            self._wait_timed_out = True
            return False

        try:
            timeout = GLib.timeout_add_seconds(max_wait, wait_timeout_cb)
            context = ctx.mainloop.get_context()
            while len(self._devices) < wait_to_appear:
                context.iteration(may_block=True)
                if self._wait_timed_out:
                    raise TimeoutError('IWD has no associated devices')
        finally:
            if not self._wait_timed_out:
                GLib.source_remove(timeout)

        return list(self._devices.values() if not p2p else self._devices.p2p_dict.values())[:wait_to_appear]

    def list_p2p_devices(self, *args, **kwargs):
        return self.list_devices(*args, **kwargs, p2p=True)

    def list_known_networks(self):
        '''Returns the list of KnownNetwork objects.'''
        objects = self._object_manager.GetManagedObjects()
        known_network_list = []

        for path in objects:
            for interface in objects[path]:
                if interface == IWD_KNOWN_NETWORK_INTERFACE:
                    known_network_list.append(
                            KnownNetwork(path, objects[path][interface]))

        return known_network_list

    def register_psk_agent(self, psk_agent):
        self._agent_manager.RegisterAgent(
                                     psk_agent.path,
                                     dbus_interface=IWD_AGENT_MANAGER_INTERFACE,
                                     reply_handler=self._success,
                                     error_handler=self._failure)
        self._wait_for_async_op()
        self.psk_agent = psk_agent

    def unregister_psk_agent(self, psk_agent):
        self._agent_manager.UnregisterAgent(
                                     psk_agent.path,
                                     dbus_interface=IWD_AGENT_MANAGER_INTERFACE,
                                     reply_handler=self._success,
                                     error_handler=self._failure)
        self._wait_for_async_op()
        self.psk_agent = None

    @staticmethod
    def get_instance():
        return IWD._instance()
