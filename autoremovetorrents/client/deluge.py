import time
from deluge_client import DelugeRPCClient
from deluge_client.client import DelugeClientException
from ..torrent import Torrent
from ..torrentstatus import TorrentStatus
from ..exception.loginfailure import LoginFailure
from ..exception.remotefailure import RemoteFailure
from ..exception.deletionfailure import DeletionFailure

# Default port of Delgue
DEFAULT_PORT = 58846

class Deluge(object):
    def __init__(self, host):
        # Host
        self._host = host
        # RPC Client
        self._client = None
        # Torrent Properties Cache
        self._torrent_cache = {}
        # Cache Valid Time
        self._refresh_expire_time = 30
        # Last Time of Refreshing Cache
        self._last_refresh = 0
    
    # Login to Deluge
    def login(self, username, password):
        # Split IP(or domain name) and port
        splits = self._host.split(':')
        host = splits[0] if len(splits) > 0 else ''
        port = int(splits[1]) if len(splits) > 1 else DEFAULT_PORT

        # Create RPC client and connect to Deluge
        self._client = DelugeRPCClient(host, port, username, password, decode_utf8 = True)
        try:
            self._client.connect()
        except DelugeClientException as e:
            # Display class name of the exception if there is no error messages
            raise LoginFailure(e.args[0].split('\n')[0] if len(e.args) > 0 else e.__class__.__name__)
    
    # A caller to call deluge api; includes exception processing
    def _call(self, method, *args, **kwargs):
        try:
            return self._client.call(method, *args, **kwargs)
        except DelugeClientException as e:
            # Raise our own exception
            raise RemoteFailure(e.args[0].split('\n')[0] if len(e.args) > 0 else e.__class__.__name__)
    
    # Get Deluge version
    def version(self):
        funcs = {
            1: 'daemon.info',        # For Deluge 1.x, use daemon.info
            2: 'daemon.get_version', # For Deluge 2.x, use daemon.get_version
        }
        ver = self._call(funcs[self._client.deluge_version])
        return ('Deluge %s' % ver)

    # Get API version
    def api_version(self):
        # Returns the protocol version
        return self._client.deluge_protocol_version if self._client.deluge_protocol_version is not None else 'not provided'

    # Get torrent list
    def torrents_list(self):
        # Save hashes
        torrents_hash = []
        # Get torrent list (and their properties)
        torrent_list = self._call('core.get_torrents_status', {}, [
            'active_time',
            'all_time_download',
            'download_payload_rate',
            'finished_time',
            'hash',
            'name',
            'num_peers',
            'num_seeds',
            'progress',
            'ratio',
            'seeding_time',
            'state',
            'time_added',
            'time_since_transfer',
            'total_peers',
            'total_seeds',
            'total_size',
            'total_uploaded',
            'trackers',
            'upload_payload_rate',
        ])
        # Save properties to cache
        self._torrent_cache = torrent_list
        self._last_refresh = time.time()
        # Return torrent hashes
        for h in torrent_list:
            torrents_hash.append(h)
        return torrents_hash
    
    # Get Torrent Properties
    def torrent_properties(self, torrent_hash):
        # Check cache expiration
        if time.time() - self._last_refresh > self._refresh_expire_time:
            self.torrents_list()
        # Extract properties
        torrent = self._torrent_cache[torrent_hash]
        # Create torrent object
        torrent_obj = Torrent()
        torrent_obj.hash = torrent['hash']
        torrent_obj.name = torrent['name']
        torrent_obj.tracker = [tracker['url'] for tracker in torrent['trackers']]
        torrent_obj.status = Deluge._judge_status(torrent['state'])
        torrent_obj.size = torrent['total_size']
        torrent_obj.ratio = torrent['ratio']
        torrent_obj.uploaded = torrent['total_uploaded']
        torrent_obj.create_time = int(torrent['time_added'])
        torrent_obj.seeding_time = torrent['seeding_time']
        torrent_obj.upload_speed = torrent['upload_payload_rate']
        torrent_obj.download_speed = torrent['download_payload_rate']
        torrent_obj.seeder = torrent['total_seeds']
        torrent_obj.connected_seeder = torrent['num_seeds']
        torrent_obj.leecher = torrent['total_peers']
        torrent_obj.connected_leecher = torrent['num_peers']
        torrent_obj.average_upload_speed = torrent['total_uploaded'] / torrent['active_time'] if torrent['active_time'] > 0 else 0
        if 'finished_time' in torrent:
            download_time = torrent['active_time'] - torrent['finished_time']
            torrent_obj.average_download_speed = torrent['all_time_download'] / download_time if download_time > 0 else 0
        if 'time_since_transfer' in torrent:
            # Set the last active time of those never active torrents to timestamp 0
            torrent_obj.last_activity = torrent['time_since_transfer'] if torrent['time_since_transfer'] > 0 else 0
        torrent_obj.progress = torrent['progress'] / 100 # Accept Range: 0-1

        return torrent_obj
    
    # Judge Torrent Status
    @staticmethod
    def _judge_status(state):
        return {
            'Allocating': TorrentStatus.Unknown, # Ignore this state
            'Checking': TorrentStatus.Checking,
            'Downloading': TorrentStatus.Downloading,
            'Error': TorrentStatus.Error,
            'Moving': TorrentStatus.Unknown, # Ignore this state
            'Paused': TorrentStatus.Paused,
            'Queued': TorrentStatus.Queued,
            'Seeding': TorrentStatus.Uploading,
        }[state]
    
    # Remove Torrent
    def remove_torrent(self, torrent_hash):
        try:
            self._call('core.remove_torrent', torrent_hash, False)
        except RemoteFailure as e:
            raise DeletionFailure('Cannot delete torrent %s. Reason: %s.' % (torrent_hash, e.args[0]))
    
    # Remove Torrent and Data
    def remove_data(self, torrent_hash):
        try:
            self._call('core.remove_torrent', torrent_hash, True)
        except RemoteFailure as e:
            raise DeletionFailure('Cannot delete torrent %s and its data. Reason: %s.' % (torrent_hash, e.args[0]))
