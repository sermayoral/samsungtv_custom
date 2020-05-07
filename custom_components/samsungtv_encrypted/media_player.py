"""Support for interface with an Samsung TV."""
import asyncio
from datetime import timedelta
import logging
import socket
import voluptuous as vol
import wakeonlan
import subprocess
import urllib.request

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
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Samsung TV platform."""
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
        udn = discovery_info.get("udn")
        if udn and udn.startswith("uuid:"):
            uuid = udn[len("uuid:") :]
    else:
        _LOGGER.warning("Cannot determine device")
        return

    # Only add a device once, so discovered devices do not override manual config.
    ip_addr = socket.gethostbyname(host)
    if ip_addr not in known_devices:
        # known_devices.add(ip_addr)
        add_entities([SamsungTVDevice(host, port, name, timeout, mac, uuid, token, sessionid, key_power_off)])
        _LOGGER.info("Samsung TV %s:%d added as '%s'", host, port, name)
    else:
        _LOGGER.info("Ignoring duplicate Samsung TV %s:%d", host, port)


class SamsungTVDevice(MediaPlayerEntity):
    """Representation of a Samsung TV."""

    def __init__(self, host, port, name, timeout, mac, uuid, token, sessionid, key_power_off):
        """Initialize the Samsung device."""
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
        # Generate a configuration for the Samsung library
        self._config = {
            "name": "HomeAssistant",
            "description": name,
            "id": "ha.component.samsung",
            "port": port,
            "host": host,
            "timeout": timeout,
        }
        self._sourcelist = {}
        self._selected_source = None
        self._urns = ('urn:schemas-upnp-org:service:RenderingControl:1', 'urn:samsung.com:service:MainTVAgent2:1')
        self._upnp_paths = None  # a tuple with upnp paths ('/_smp17_', '/_smp4_')
        self._upnp_ports = None  # a tuple with upnp ports (7676, 7676)

    def update(self):
        """Update state of device."""
        self.send_key("KEY")
        if self._state == STATE_ON:
            if not self._upnp_paths:
                self._upnp_ports, self._upnp_paths = self.discoverSSDP(timeout=2)
            if self._upnp_paths:
                current_volume = self.SendSOAP(self._upnp_ports[0], self._upnp_paths[0], self._urns[0], 'GetVolume',
                                              '<InstanceID>0</InstanceID><Channel>Master</Channel>', 'currentvolume')
                if current_volume:
                    self._volume = int(current_volume) / 100
                if not bool(self._sourcelist):
                    self._sourcelist = self.getSourceList()
                if bool(self._sourcelist):
                    selected_source = self.SendSOAP(self._upnp_ports[1], self._upnp_paths[1], self._urns[1],
                                                    'GetCurrentExternalSource', '', 'currentexternalsource')
                    if selected_source:
                        self._selected_source = selected_source

    def pingTV(self):
        """ping TV"""
        cmd = ['ping', '-c1', '-W2', self._host]
        response = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        stdout, stderr = response.communicate()
        if response.returncode == 0:
            return True
        else:
            return False

    def get_remote(self):
        """Create or return a remote control instance."""
        if self._remote is None:
            # We need to create a new instance to reconnect.
            self._remote = self._remote_class(self._host, self._port, self._token, self._sessionid)

        return self._remote

    def send_key(self, key):
        """Send a key to the tv and handles exceptions."""
        if self._power_off_in_progress() and key not in ("KEY_POWER", "KEY_POWEROFF"):
            _LOGGER.info("TV is powering off, not sending command: %s", key)
            return
        # first try pinging the TV
        if not self.pingTV():
            self._state = STATE_OFF
            # self.get_remote().close()
            self._remote = None
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
            self._state = STATE_OFF

    def _power_off_in_progress(self):
        return (
            self._end_of_power_off is not None
            and self._end_of_power_off > dt_util.utcnow()
        )

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
        if self._mac:
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
        self.send_key("KEY_VOLUP")

    def volume_down(self):
        """Volume down media player."""
        self.send_key("KEY_VOLDOWN")

    def mute_volume(self, mute):
        """Send mute command."""
        self.send_key("KEY_MUTE")

    def media_play_pause(self):
        """Simulate play pause media player."""
        if self._playing:
            self.media_pause()
        else:
            self.media_play()

    def media_play(self):
        """Send play command."""
        self._playing = True
        self.send_key("KEY_PLAY")

    def media_pause(self):
        """Send media pause command to media player."""
        self._playing = False
        self.send_key("KEY_PAUSE")

    def media_next_track(self):
        """Send next track command."""
        self.send_key("KEY_FF")

    def media_previous_track(self):
        """Send the previous track command."""
        self.send_key("KEY_REWIND")

    def select_source(self, source):
        """Select input source."""
        if source not in self._sourcelist:
            _LOGGER.error("Unsupported source: {}".format(source))
            return

        self.SendSOAP(self._upnp_ports[1], self._upnp_paths[1], self._urns[1], 'SetMainTVSource',
                      '<Source>'+source+'</Source><ID>' + self._sourcelist[source] + '</ID><UiID>0</UiID>','')

    def set_volume_level(self, volume):
        """Volume up the media player."""
        volset = str(round(volume * 100))

        self.SendSOAP(self._upnp_ports[0], self._upnp_paths[0], self._urns[0], 'SetVolume',
                      '<InstanceID>0</InstanceID><DesiredVolume>' + volset + '</DesiredVolume><Channel>Master</Channel>',
                      '')

    async def async_play_media(self, media_type, media_id, **kwargs):
        """Support changing a channel."""
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
        if self._mac:
            wakeonlan.send_magic_packet(self._mac)
        else:
            self.send_key("KEY_POWERON")

    async def async_select_source(self, source):
        """Select input source."""
        # await self.hass.async_add_job(self.send_key, self._sourcelist[source])
        await self.hass.async_add_job(self.select_source, source)

    def SendSOAP(self, port, path, urn, service, body, XMLTag):
        CRLF = "\r\n"
        xmlBody = '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.' \
                   'xmlsoap.org/soap/encoding/">'
        xmlBody += '<s:Body>'
        xmlBody += '<u:{service} xmlns:u="{urn}">{body}</u:{service}>'
        xmlBody += '</s:Body>'
        xmlBody += '</s:Envelope>'
        xmlBody = xmlBody.format(urn=urn, service=service, body=body)

        soapRequest = "POST {path} HTTP/1.0%s" % (CRLF)
        soapRequest += "HOST: {host}:{port}%s" % (CRLF)
        soapRequest += "CONTENT-TYPE: text/xml;charset=\"utf-8\"%s" % (CRLF)
        soapRequest += "CONTENT-LENGTH: {cont_len}%s" % (CRLF)
        soapRequest += "SOAPACTION: \"{urn}#{service}\"%s" % (CRLF)
        soapRequest += "%s" % (CRLF)
        soapRequest += "{xml}%s" % (CRLF)
        soapRequest = soapRequest.format(host=self._config['host'], port=port, xml=xmlBody, path=path,
                                         urn=urn, service=service, cont_len=len(xmlBody))

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        response_xml = ''
        _LOGGER.debug("Samsung TV sending: %s", soapRequest)

        try:
            client.connect((self._config['host'], port))
            client.send(bytes(soapRequest, 'utf-8'))
            while True:
                data_buffer = client.recv(4096)
                if not data_buffer: break
                response_xml += str(data_buffer)
        except socket.error as error:
            _LOGGER.debug('Error sending upnp soap request. Got {}'.format(error))
            return

        response_xml = self.xmlBytesToStr(bytes(response_xml, 'utf-8'))
        _LOGGER.debug("Samsung TV received: %s", response_xml)
        if XMLTag:
            soup = BeautifulSoup(str(response_xml), 'lxml')
            xml_values = soup.find_all(XMLTag)
            xml_values_names = [xmlValue.string for xmlValue in xml_values]
            if len(xml_values_names) == 1:
                return xml_values_names[0]
            else:
                return xml_values_names
        else:
            return response_xml[response_xml.find('<s:Envelope'):]

    def xmlBytesToStr(self, xml_bytes):
        response_xml = xml_bytes.decode(encoding="utf-8")
        response_xml = response_xml.replace("&lt;", "<")
        response_xml = response_xml.replace("&gt;", ">")
        return response_xml.replace("&quot;", "\"")

    def discoverSSDP(self, timeout=5):
        upnp_ports = [None] * len(self._urns)
        upnp_paths = [None] * len(self._urns)
        for entry in scan(timeout):
            if entry.location is None:
                continue
            if entry.location.startswith('http://{}'.format(self._config['host'])):
                for i in range(len(self._urns)):
                    if entry.st == self._urns[i]:
                        upnp_ports[i] = int(entry.location.split(':')[2].split('/')[0])
                        upnp_paths[i] = self.getPathFromUrlSsdp(entry.location, i)
                if None not in upnp_paths:
                    for i in range(len(self._urns)):
                        _LOGGER.info('{} uPNP service detected in http://{}{}'
                                     .format(self._urns[i].split(':')[3], entry.location.split('/')[2], upnp_paths[i]))
                    return tuple(upnp_ports), tuple(upnp_paths)
        return None, None

    def getPathFromUrlSsdp(self, url, i, timeout=2):
        try:
            file = urllib.request.urlopen(url, timeout=timeout)
            data = file.read()
            file.close()
            response_xml = self.xmlBytesToStr(data)
            soup = BeautifulSoup(response_xml, 'lxml')
            services = soup.find_all('service')
            for service in services:
                upnp_service = service.find('servicetype').string
                if upnp_service == self._urns[i]:
                    return service.find('controlurl').string
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            _LOGGER.debug('Could not access at {}. Got {}'.format(url, error))
        except socket.timeout:
            _LOGGER.debug('Timeout accesing at {}'.format(url))
        return None

    def getSourceList(self):
        sources = {}
        source_names = self.SendSOAP(self._upnp_ports[1], self._upnp_paths[1], self._urns[1], 'GetSourceList', '', 'sourcetype')
        if source_names:
            source_ids = self.SendSOAP(self._upnp_ports[1], self._upnp_paths[1], self._urns[1], 'GetSourceList', '', 'id')
            if source_ids:
                sources_connected = self.SendSOAP(self._upnp_ports[1], self._upnp_paths[1], self._urns[1], 'GetSourceList', '', 'connected')
                if sources_connected:
                    del source_ids[0]
                    j = 0;
                    for i in range(len(sources_connected)):
                        if sources_connected[i].lower() != 'yes':
                            del source_names[i - j]
                            del source_ids[i - j]
                            j = j + 1
                    sources = dict(zip(source_names, source_ids))
        _LOGGER.debug('Sourcelist available is '.format(sources))
        return sources
