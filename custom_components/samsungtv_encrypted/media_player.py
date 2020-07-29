"""Support for interface with an Samsung TV."""
import asyncio
from datetime import timedelta
import logging
import socket
import voluptuous as vol
import wakeonlan
import subprocess
import urllib.request
import ipaddress
import xmltodict
import json
import re

from .PySmartCrypto.pysmartcrypto import PySmartCrypto
from bs4 import BeautifulSoup
from netdisco.ssdp import scan

from homeassistant.components.media_player import MediaPlayerEntity, PLATFORM_SCHEMA, DEVICE_CLASS_TV
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_CHANNEL,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_STEP,
    SUPPORT_VOLUME_SET,
    MEDIA_TYPE_URL,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_PLAYLIST,
    MEDIA_TYPE_MUSIC,
    MEDIA_TYPE_APP
)
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TIMEOUT,
    STATE_OFF,
    STATE_ON,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.script import Script
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

MEDIA_TYPE_KEY = "send_key"
DEFAULT_NAME = "Samsung TV Remote"
DEFAULT_PORT = 8080
DEFAULT_TIMEOUT = 2
DEFAULT_KEY_POWER_OFF = "KEY_POWEROFF"
KEY_PRESS_TIMEOUT = 1.2
KNOWN_DEVICES_KEY = "samsungtv_known_devices"
# SOURCES = {"TV": "KEY_TV", "HDMI": "KEY_HDMI"}
# CONF_SOURCELIST = "sourcelist"
# CONF_APPLIST = "applist"
CONF_TOKEN = "token"
CONF_SESSIONID = "sessionid"
CONF_KEY_POWER_OFF = "key_power_off"
CONF_TURN_ON_ACTION = "turn_on_action"
MIN_TIME_BETWEEN_FORCED_SCANS = timedelta(seconds=2)
MIN_TIME_BETWEEN_SCANS = timedelta(seconds=10)

SUPPORT_SAMSUNGTV = (
    SUPPORT_PAUSE
    | SUPPORT_VOLUME_STEP
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_VOLUME_SET
    | SUPPORT_PREVIOUS_TRACK
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_NEXT_TRACK
    | SUPPORT_TURN_OFF
    | SUPPORT_PLAY
    | SUPPORT_PLAY_MEDIA
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_MAC): cv.string,
        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
        # vol.Optional(CONF_SOURCELIST): cv.string,
        # vol.Optional(CONF_APPLIST): cv.string,
        vol.Optional(CONF_TOKEN): cv.string,
        vol.Optional(CONF_SESSIONID): cv.string,
        vol.Optional(CONF_KEY_POWER_OFF, default=DEFAULT_KEY_POWER_OFF): cv.string,
        vol.Optional(CONF_TURN_ON_ACTION, default=None): cv.SCRIPT_SCHEMA,
    }
)

# Set URN globals
RENDERINGCONTROL = 'urn:schemas-upnp-org:service:RenderingControl:1'
CONNECTIONMANAGER = 'urn:schemas-upnp-org:service:ConnectionManager:1'
AVTRANSPORT = 'urn:schemas-upnp-org:service:AVTransport:1'
DIAL = 'urn:dial-multiscreen-org:service:dial:1'
MAINTVAGENT = 'urn:samsung.com:service:MainTVAgent2:1'
MULTISCREENSERVICE = 'urn:samsung.com:service:MultiScreenService:1'

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Samsung TV platform."""
    _LOGGER.debug("function setup_platform")
    known_devices = hass.data.get(KNOWN_DEVICES_KEY)
    if known_devices is None:
        known_devices = set()
        hass.data[KNOWN_DEVICES_KEY] = known_devices

    uuid = None

    # if config.get(CONF_SOURCELIST) is not None:
    #     sourcelist = json.loads(config.get(CONF_SOURCELIST))
    # else:
    #     sourcelist = SOURCES
    # 
    # if config.get(CONF_APPLIST) is not None:
    #     applist = config.get(CONF_APPLIST).split(", ")
    # else:
    #     applist = []

    # Is this a manual configuration?
    if config.get(CONF_HOST) is not None:
        host = config.get(CONF_HOST)
        port = config.get(CONF_PORT)
        name = config.get(CONF_NAME)
        mac = config.get(CONF_MAC)
        timeout = config.get(CONF_TIMEOUT)
        token = config.get(CONF_TOKEN)
        sessionid = config.get(CONF_SESSIONID)
        key_power_off = config.get(CONF_KEY_POWER_OFF)
        turn_on_action = config.get(CONF_TURN_ON_ACTION)
        if turn_on_action:
            turn_on_action = Script(hass, turn_on_action)
    elif discovery_info is not None:
        tv_name = discovery_info.get("name")
        model = discovery_info.get("model_name")
        host = discovery_info.get("host")
        name = f"{tv_name} ({model})"
        port = DEFAULT_PORT
        timeout = DEFAULT_TIMEOUT
        token = "0"
        sessionid = "0"
        key_power_off = DEFAULT_KEY_POWER_OFF
        mac = None
        turn_on_action = None
        udn = discovery_info.get("udn")
        if udn and udn.startswith("uuid:"):
            uuid = udn[len("uuid:") :]
    else:
        _LOGGER.warning("Cannot determine device")
        return

    try:
        ipaddress.ip_address(host)
    except:
        host = socket.gethostbyname(host)
    # Only add a device once, so discovered devices do not override manual config.
    if host not in known_devices:
        # known_devices.add(ip_addr)
        add_entities([SamsungTVDevice(host, port, name, timeout, mac, uuid, token, sessionid, key_power_off, turn_on_action)])
        _LOGGER.info("Samsung TV %s:%d added as '%s'", host, port, name)
    else:
        _LOGGER.info("Ignoring duplicate Samsung TV %s:%d", host, port)

class UPnPService:
    """A UPnP Device"""

    def __init__(self, host, port, urn, control_path, scpd_path, eventsub_path):
        """Initialise the UPnP device"""
        _LOGGER.debug('UPnPService {} __init__ '.format(urn))
        self._host = host
        self._port = port
        self._urn = urn
        self._control_path = control_path
        self._scpd_path = scpd_path
        self._eventsub_path = eventsub_path

        xml_description = urllib.request.urlopen("http://{}:{}{}".format(host, port, scpd_path)).read()
        description = json.loads(json.dumps(xmltodict.parse(xml_description)))
        self._vars = self.__getVars(description['scpd']['serviceStateTable']['stateVariable'])
        self._methods = self.__getMethods(description['scpd']['actionList']['action'])

        def __genQuerySoap(method):
            def __querySoapWrapper(args = {}):
                return self.__querySoap(method, args)
            return __querySoapWrapper

        for method in self._methods:
            setattr(self, method, __genQuerySoap(method))

    def __getVars(self, vars):
        """Get the argument map for the UPnP device"""
        _LOGGER.debug('UPnPService {} getVars'.format(self._urn))
        if isinstance(vars, (dict)): vars = [vars]
        var_map = {}
        for var in vars:
            var_map[var['name']] = { 'type': var['dataType'] }
            try: vals = var['allowsValueList']['allowedValue']
            except: continue
            if isinstance(vals, (dict)): vals = [vals]
            var_map[var['name']]['vals'] = vals
        return var_map

    def __getMethods(self, methods):
        """Get the methods the device contains"""
        _LOGGER.debug('UPnPService {} getMethods'.format(self._urn))
        if isinstance(methods, (dict)): methods = [methods]
        method_map = {}
        for method in methods:
            name = method['name'][0].lower() + method['name'][1:]
            method_map[name] = {
                'args': {},
                'attrs': {}
            }
            try: arg_list = method['argumentList']['argument']
            except: continue
            if isinstance(arg_list, (dict)): arg_list = [arg_list]
            for arg in arg_list:
                if arg['direction'] == 'in': method_map[name]['args'][arg['name']] = self._vars[arg['relatedStateVariable']]
                if arg['direction'] == 'out': method_map[name]['attrs'][arg['name']] = self._vars[arg['relatedStateVariable']]
        return method_map

    def __querySoap(self, method, args = {}):
        """Send a SOAP request"""
        _LOGGER.debug('UPnPService {} querySoap'.format(self._urn))

        method_name = method[0].upper() + method[1:]
        xml = self.__createXml(method_name, args)
        message = self.__compileSoap(method_name, xml)

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _LOGGER.debug("Sending: %s", xml)

        soap_response = ''
        try:
            client.connect((self._host, self._port))
            client.send(bytes(message, 'utf-8'))
            while True:
                data_buffer = client.recv(4096)
                if not data_buffer: break
                soap_response += str(data_buffer)
        except socket.error as error:
            _LOGGER.debug('Error sending upnp soap request. Got {}'.format(error))
            return

        return_tag = '{}Response'.format(method_name)
        soap_response = self.__sanitizeSoap(bytes(soap_response, 'utf-8'))
        xml_response = self.__extractTag(soap_response, 'u:{}'.format(return_tag)).replace('<?xml version="1.0" encoding="UTF-8" ?>', '')
        _LOGGER.debug("Samsung TV received: %s", xml_response)

        parsed = xmltodict.parse(xml_response)

        try: return parsed[return_tag]
        except: return parsed

    def __createXml(self, method, args):
        """Create the xml for sending via SOAP"""
        _LOGGER.debug('UPnPService {} createXml'.format(self._urn))
        xml = xmltodict.unparse({
            's:Envelope': {
                '@xmlns:s': 'http://schemas.xmlsoap.org/soap/envelope/',
                '@s:encodingStyle': 'http://schemas.xmlsoap.org/soap/encoding/',
                's:Body':{
                    'u:{}'.format(method): {
                        '@xmlns:u': self._urn,
                        **args
                    }
                }
            }
        }, full_document = False)
        return xml

    def __compileSoap(self, method, message):
        """Compile a SOAP message"""
        _LOGGER.debug('UPnPService {} compileSOAP'.format(self._urn))

        CRLF = "\r\n"
        soap_message = CRLF.join([
            'POST {} HTTP/1.0'.format(self._control_path),
            'HOST: {}:{}'.format(self._host, self._port),
            'CONTENT-TYPE: text/xml;charset="utf-8"',
            'CONTENT-LENGTH: {}'.format(len(message)),
            'SOAPACTION: "{}#{}"'.format(self._urn, method),
            '{}{}{}'.format(CRLF, message, CRLF)
        ])
        return soap_message

    def __sanitizeSoap(self, message):
        _LOGGER.debug('UPnPService {} sanitizeSoap'.format(self._urn))
        response = message.decode(encoding="utf-8")
        response = response.replace("&lt;", "<")
        response = response.replace("&gt;", ">")
        return response.replace("&quot;", "\"")

    def __extractTag(self, message, tag):
        _LOGGER.debug('UPnPService {} extractTag'.format(self._urn))
        start = message.rfind('<{}'.format(tag))
        if start == -1:
            _LOGGER.debug('Unable to find tag: {}'.format(tag))
            tag = 's:Fault'
            start = message.rfind('<{}'.format(tag))
        if start == -1:
            _LOGGER.debug('Unable to find tag: {}'.format(tag))
            return message
        end = message.find('</{}>'.format(tag)) + len(tag) + 3
        return self.__removeNamespaces(message[start:end])

    def __removeNamespaces(self, message):
        _LOGGER.debug('UPnPService {} removeNamespaces'.format(self._urn))
        namespaces = re.compile('<([a-z]+):')
        out = ''
        for match in namespaces.findall(message):
            out = message.replace('<{}:'.format(match), '<')
            out = out.replace(':{}='.format(match), '=')
            out = out.replace('</{}:'.format(match), '</')
            out = out.replace('>{}:'.format(match), '>')
        return out

class SamsungTVDevice(MediaPlayerEntity):
    """Representation of a Samsung TV."""

    def __init__(self, host, port, name, timeout, mac, uuid, token, sessionid, key_power_off, turn_on_action):
        """Initialize the Samsung device."""
        _LOGGER.debug("function __init__")
        # Save a reference to the imported classes
        self._host = host
        self._port = port
        self._token = token
        self._sessionid = sessionid
        self._key_power_off = key_power_off
        self._remote_class = PySmartCrypto
        self._name = name
        self._mac = mac
        self._uuid = uuid
        self._wol = wakeonlan
        # Assume that the TV is not muted
        self._muted = False
        self._volume = 0
        # Assume that the TV is in Play mode
        self._playing = True
        self._state = None
        self._remote = None
        # Mark the end of a shutdown command (need to wait 15 seconds before
        # sending the next command to avoid turning the TV back ON).
        self._end_of_power_off = None
        self._turn_on_action = turn_on_action
        # Generate a configuration for the Samsung library
        self._config = {
            "name": "HomeAssistant",
            "description": name,
            "id": "ha.component.samsung",
            "port": port,
            "host": host,
            "timeout": timeout,
            "turn_on_action": turn_on_action,
        }
        self._sourcelist = {}
        self._selected_source = None
        self._upnp_services = None
        self._channel = None
        self._renderingcontrol = None
        self._connectionmanager = None
        self._avtransport = None
        self._maintvagent = None

    def update(self):
        """Update state of device."""
        _LOGGER.debug("SamsungTVDevice update")
        self.send_key("KEY")
        if self._state != STATE_ON: return

        if not self._upnp_services:
            self._upnp_services = self.discoverSSDP(timeout=2)
        if not self._upnp_services:
            _LOGGER.warn('Unable to update')
            return

        self.updateRenderingControl()
        self.updateConnectionManager()
        self.updateAVTransport()
        self.updateMainTVAgent()

    def updateRenderingControl(self):
        """Update the rendering control."""
        _LOGGER.debug("SamsungTVDevice updateRenderingControl")
        if not self._renderingcontrol:
            try: dev = self._upnp_services[RENDERINGCONTROL]
            except:
                _LOGGER.warn('{} not found in upnp services'.format(RENDERINGCONTROL))
                return
            self._renderingcontrol = UPnPService(self._host, dev['port'], RENDERINGCONTROL, dev['control'], dev['scpd'], dev['eventsub'])
        try:
            self._volume = int(self._renderingcontrol.getVolume({'InstanceID': 0, 'Channel': 'Master'})['CurrentVolume']) / 100
        except:
            _LOGGER.warn('Unable to get volume')

    def updateConnectionManager(self):
        """Update the connection manager."""
        _LOGGER.debug("SamsungTVDevice updateConnectionManager")
        if not self._connectionmanager:
            try: dev = self._upnp_services[CONNECTIONMANAGER]
            except:
                _LOGGER.warn('{} not found in upnp services'.format(CONNECTIONMANAGER))
                return
            self._connectionmanager = UPnPService(self._host, dev['port'], CONNECTIONMANAGER, dev['control'], dev['scpd'], dev['eventsub'])

    def updateAVTransport(self):
        """Update the AV transport."""
        _LOGGER.debug("SamsungTVDevice updateAVTransport")
        if not self._avtransport:
            try: dev = self._upnp_services[AVTRANSPORT]
            except:
                _LOGGER.warn('{} not found in upnp services'.format(AVTRANSPORT))
                return
            self._avtransport = UPnPService(self._host, dev['port'], AVTRANSPORT, dev['control'], dev['scpd'], dev['eventsub'])

    def updateMainTVAgent(self):
        """Update the main tv agent."""
        _LOGGER.debug("SamsungTVDevice updateMainTVAgent")
        if not self._maintvagent:
            try: dev = self._upnp_services[MAINTVAGENT]
            except:
                _LOGGER.warn('{} not found in upnp services'.format(MAINTVAGENT))
                return
            self._maintvagent = UPnPService(self._host, dev['port'], MAINTVAGENT, dev['control'], dev['scpd'], dev['eventsub'])

        if not bool(self._sourcelist):
            self._sourcelist = self.getSourceList()
        if bool(self._sourcelist):
            try: self._selected_source = self._maintvagent.getCurrentExternalSource()['CurrentExternalSource']
            except: _LOGGER.warn('Unable to get selected source')

    def pingTV(self):
        """ping TV"""
        _LOGGER.debug("SamsungTVDevice pingTV")
        cmd = ['ping', '-c1', '-W2', self._host]
        response = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        stdout, stderr = response.communicate()
        if response.returncode == 0:
            return True
        else:
            return False

    def get_remote(self):
        """Create or return a remote control instance."""
        _LOGGER.debug("SamsungTVDevice get_remote")
        if self._remote is None:
            # We need to create a new instance to reconnect.
            self._remote = self._remote_class(self._host, self._port, self._token, self._sessionid)

        return self._remote

    def send_key(self, key):
        """Send a key to the tv and handles exceptions."""
        _LOGGER.debug("SamsungTVDevice send_key")
        if self._power_off_in_progress() and key not in ("KEY_POWER", "KEY_POWEROFF"):
            _LOGGER.info("TV is powering off, not sending command: %s", key)
            return
        # first try pinging the TV
        if not self.pingTV():
            self._set_state_off()
            return
        try:
            # recreate connection if connection was dead
            retry_count = 1
            for _ in range(retry_count + 1):
                try:
                    self.get_remote().control(key)
                    break
                except:
                    # BrokenPipe can occur when the commands is sent to fast
                    # WebSocketException can occur when timed out
                    self._remote = None
            self._state = STATE_ON
        except:
            # We got a response so it's on.
            self._state = STATE_ON
            self._remote = None
            _LOGGER.debug("Failed sending command %s", key, exc_info=True)
            return
        if self._power_off_in_progress():
            self._set_state_off()

    def _power_off_in_progress(self):
        _LOGGER.debug("SamsungTVDevice _power_off_in_progress")
        return (
            self._end_of_power_off is not None
            and self._end_of_power_off > dt_util.utcnow()
        )

    def _set_state_off(self):
        _LOGGER.debug("SamsungTVDevice _set_state_off")
        self._state = STATE_OFF
        self._sourcelist = {}
        self._selected_source = None
        self._upnp_services = None
        self._remote = None

    @property
    def device_class(self):
        """Set the device class to TV."""
        return DEVICE_CLASS_TV

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._muted

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def source(self):
        """Return the current input source."""
        return self._selected_source

    @property
    def source_list(self):
        """List of available input sources."""
        return list(self._sourcelist.keys())

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        if self._mac or self._turn_on_action:
            return SUPPORT_SAMSUNGTV | SUPPORT_TURN_ON
        return SUPPORT_SAMSUNGTV

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the device."""
        return self._uuid

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._volume

    def volume_up(self):
        """Volume up the media player."""
        _LOGGER.debug("SamsungTVDevice volume_up")
        self.send_key("KEY_VOLUP")

    def volume_down(self):
        """Volume down media player."""
        _LOGGER.debug("SamsungTVDevice volume_down")
        self.send_key("KEY_VOLDOWN")

    def mute_volume(self, mute):
        """Send mute command."""
        _LOGGER.debug("SamsungTVDevice mute_volume")
        self.send_key("KEY_MUTE")

    def media_play_pause(self):
        """Simulate play pause media player."""
        _LOGGER.debug("SamsungTVDevice media_play_pause")
        if self._playing:
            self.media_pause()
        else:
            self.media_play()

    def media_play(self):
        """Send play command."""
        _LOGGER.debug("SamsungTVDevice media_play")
        self._playing = True
        self.send_key("KEY_PLAY")

    def media_pause(self):
        """Send media pause command to media player."""
        _LOGGER.debug("SamsungTVDevice media_pause")
        self._playing = False
        self.send_key("KEY_PAUSE")

    def media_next_track(self):
        """Send next track command."""
        _LOGGER.debug("SamsungTVDevice media_next_track")
        self.send_key("KEY_FF")

    def media_previous_track(self):
        """Send the previous track command."""
        _LOGGER.debug("SamsungTVDevice media_previous_track")
        self.send_key("KEY_REWIND")

    def select_source(self, source):
        """Select input source."""
        _LOGGER.debug("SamsungTVDevice select_source")
        if source not in self._sourcelist:
            _LOGGER.error("Unsupported source: {}".format(source))
            return

        self._maintvagent.setMainTVSource({'Source': source, 'ID': self._sourcelist[source], 'UID': 0})

    def set_volume_level(self, volume):
        """Volume up the media player."""
        _LOGGER.debug("SamsungTVDevice set_volume_level")
        self._renderingcontrol.setVolume({'InstanceID': 0, 'Channel': 'Master', 'DesiredVolume': round(volume * 100)})

    async def async_play_media(self, media_type, media_id, **kwargs):
        """Support changing a channel."""
        _LOGGER.debug("SamsungTVDevice async_play_media")
        if media_type == MEDIA_TYPE_CHANNEL:
        # media_id should only be a channel number
            try:
                cv.positive_int(media_id)
            except vol.Invalid:
                _LOGGER.error("Media ID must be positive integer")
                return

            for digit in media_id:
                await self.hass.async_add_job(self.send_key, "KEY_" + digit)
                await asyncio.sleep(KEY_PRESS_TIMEOUT, self.hass.loop)
            await self.hass.async_add_job(self.send_key, "KEY_ENTER")
        elif media_type == MEDIA_TYPE_KEY:
            self.send_key(media_id)
        else:
            _LOGGER.error("Unsupported media type")
            return

    def turn_off(self):
        """Turn off media player."""
        _LOGGER.debug("SamsungTVDevice turn_off")
        self._end_of_power_off = dt_util.utcnow() + timedelta(seconds=15)

        self.send_key(self._key_power_off)
        # Force closing of remote session to provide instant UI feedback
        try:
            self.get_remote().close()
            self._remote = None
        except OSError:
            _LOGGER.debug("Could not establish connection.")

    def turn_on(self):
        """Turn the media player on."""
        _LOGGER.debug("SamsungTVDevice turn_on")
        if self._turn_on_action:
            self._turn_on_action.run()
        elif self._mac:
            wakeonlan.send_magic_packet(self._mac)
        else:
            self.send_key("KEY_POWERON")

    async def async_select_source(self, source):
        """Select input source."""
        _LOGGER.debug("SamsungTVDevice async_select_source")
        while self._sourcelist == {}:
            await self.hass.async_add_job(self.update)

        await self.hass.async_add_job(self.select_source, source)

    def discoverSSDP(self, timeout=5):
        _LOGGER.debug("SamsungTVDevice discoverSSDP")
        services = {}
        for e in scan(timeout):
            try: path = e.location.replace('/', ':').split(':')
            except: continue

            try: st_map = e.st.split(':')
            except: continue

            if path[3] != self._config['host']: continue
            if st_map[0] != 'urn' or st_map[2] != 'device': continue

            try: svc_list = e.description['device']['serviceList']['service']
            except:
                _LOGGER.debug('{} has no service list'.format(e.st))
                continue

            if isinstance(svc_list, (dict)): svc_list = [svc_list]
            for svc in svc_list:
                if svc['serviceType'] in services.keys(): continue
                services[svc['serviceType']] = {
                    'port': int(path[4]),
                    'control': svc['controlURL'],
                    'eventsub': svc['eventSubURL'],
                    'scpd': svc['SCPDURL']
                }

        for k, v in services.items():
            _LOGGER.info('%s uPNP service detected at http://%s:%s%s', k.split(':')[3], self._config['host'], v['port'], v['control'])
        return services

    def getSourceList(self):
        _LOGGER.debug("SamsungTVDevice getSourceList")

        source_list = self._maintvagent.getSourceList()['SourceList']['SourceList']
        sources = [ dict(s) for s in source_list['Source'] if s['Connected'] == 'Yes' ]
        source_names = [ s['SourceType'] for s in sources ]
        source_ids = [ s['ID'] for s in sources ]

        sources = dict(zip(source_names, source_ids))
        _LOGGER.debug('Sourcelist available is {}'.format(sources))
        return sources