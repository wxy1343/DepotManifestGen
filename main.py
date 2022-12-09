import vdf
import logging
import os.path
import argparse
import subprocess
import gevent.monkey
from pathlib import Path
from steam.client import SteamClient
from steam.client.cdn import CDNClient
from steam.enums import EResult
from steam.exceptions import SteamError
from steam.protobufs.content_manifest_pb2 import ContentManifestSignature


def get_manifest(cdn, app_id, depot_id, manifest_gid):
    path = f'depots/{app_id}/{depot_id}_{manifest_gid}.manifest'
    if os.path.exists(path):
        return
    while True:
        try:
            manifest_code = cdn.get_manifest_request_code(app_id, depot_id, manifest_gid)
            manifest = cdn.get_manifest(app_id, depot_id, manifest_gid, decrypt=False,
                                        manifest_request_code=manifest_code)
            DecryptionKey = cdn.get_depot_key(manifest.app_id, manifest.depot_id)
            break
        except SteamError as e:
            logging.warning(
                f'{"":<10}app_id: {app_id:<8}{"":<10}depot_id: {depot_id:<8}{"":<10}manifest_gid: {manifest_gid:20}{"":<10}error: {e.message} result: {str(e.eresult)}')
            if e.eresult == EResult.AccessDenied:
                return
            gevent.idle()
    logging.info(
        f'{"":<10}app_id: {app_id:<8}{"":<10}depot_id: {depot_id:<8}{"":<10}manifest_gid: {manifest_gid:20}{"":<10}DecryptionKey: {DecryptionKey.hex()}')
    manifest.decrypt_filenames(DecryptionKey)
    manifest.signature = ContentManifestSignature()
    for mapping in manifest.payload.mappings:
        mapping.filename = mapping.filename.rstrip('\x00 \n\t')
        mapping.chunks.sort(key=lambda x: x.sha)
    manifest.payload.mappings.sort(key=lambda x: x.filename.lower())
    if not os.path.exists(f'depots/{app_id}'):
        os.makedirs(f'depots/{app_id}')
    if os.path.isfile(f'depots/{app_id}/config.vdf'):
        with open(f'depots/{app_id}/config.vdf') as f:
            d = vdf.load(f)
    else:
        d = vdf.VDFDict({'depots': {}})
    d['depots'][depot_id] = {'DecryptionKey': DecryptionKey.hex()}
    d = {'depots': dict(sorted(d['depots'].items()))}
    with open(f'depots/{app_id}/config.vdf', 'w') as f:
        vdf.dump(d, f, pretty=True)
    with open(path, 'wb') as f:
        f.write(manifest.serialize(compress=False))
    manifest.metadata.crc_clear = int(
        subprocess.check_output(['calc_crc_clear', f'depots/{app_id}/{depot_id}_{manifest_gid}.manifest']).strip())
    with open(path, 'wb') as f:
        f.write(manifest.serialize(compress=False))
    return app_id, depot_id, manifest_gid


class MySteamClient(SteamClient):
    credential_location = str(Path().absolute())
    _LOG = logging.getLogger('DepotManifestGen')
    sentry_path = None

    def __init__(self):
        SteamClient.__init__(self)

    def _handle_update_machine_auth(self, message):
        SteamClient._handle_update_machine_auth(self, message)

    def _handle_login_key(self, message):
        SteamClient._handle_login_key(self, message)
        with open(f'{self.username}.key', 'w') as f:
            f.write(steam.login_key)

    def _handle_logon(self, msg):
        SteamClient._handle_logon(self, msg)

    def _get_sentry_path(self, username):
        if self.sentry_path:
            return self.sentry_path
        else:
            return SteamClient._get_sentry_path(self, username)


parser = argparse.ArgumentParser()
parser.add_argument('-u', '--username', required=True)
parser.add_argument('-p', '--password', required=False, default='')
parser.add_argument('-a', '--app-id', required=False)
parser.add_argument('-l', '--list-apps', action='store_true', required=False)
parser.add_argument('-s', '--sentry-path', '--ssfn', required=False)
parser.add_argument('-k', '--login-key', required=False)
parser.add_argument('-f', '--two-factor-code', required=False)
parser.add_argument('-A', '--auth-code', required=False)
parser.add_argument('-i', '--login-id', required=False)
parser.add_argument('-c', '--cli', action='store_true', required=False)
parser.add_argument('-L', '--level', required=False, default='INFO')

if __name__ == '__main__':
    args = parser.parse_args()
    if args.level:
        level = logging.getLevelName(args.level.upper())
    else:
        level = logging.INFO
    logging.basicConfig(format='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s', level=level)
    steam = MySteamClient()
    if args.sentry_path:
        steam.sentry_path = args.sentry_path
    login_key_path = Path(steam.credential_location) / f'{args.username}.key'
    steam.username = args.username
    result = None
    if not args.login_key and login_key_path.exists():
        with login_key_path.open() as f:
            steam.login_key = f.read()
        result = steam.relogin()
        if result == EResult.InvalidPassword:
            login_key_path.unlink(missing_ok=True)
    if result != EResult.OK:
        if args.cli:
            result = steam.cli_login(args.username, args.password)
        else:
            result = steam.login(args.username, args.password, args.login_key, args.auth_code, args.two_factor_code,
                                 args.login_id)
    if result != EResult.OK:
        logging.error(f'Login failure reason: {result.__repr__()}')
        exit(result)
    appids = []
    appids_all = set()
    depotids = []
    packages_info = []
    packages = list(
        map(lambda l: {'packageid': l.package_id, 'access_token': l.access_token}, steam.licenses.values()))
    if packages:
        for package_id, info in steam.get_product_info(packages=packages)['packages'].items():
            if info['depotids'] and 1 < info['billingtype'] < 12:
                appids_all.update(list(info['appids'].values()))
                appids.extend(list(info['appids'].values()))
                depotids.extend(list(info['depotids'].values()))
                packages_info.append((list(info['appids'].values()), list(info['depotids'].values())))
    cdn = CDNClient(steam)
    if args.app_id:
        appids = {int(app_id) for app_id in args.app_id.split(',')}
        appids_all.update(appids)
    fresh_resp = steam.get_product_info(appids)
    if args.list_apps:
        for app_id in appids_all:
            app = fresh_resp['apps'][app_id]
            if 'common' in app and app['common']['type'].lower() == 'game':
                logging.info("%s %s", app_id, app['common']['name'])
        exit()
    for app_id in appids:
        app = fresh_resp['apps'][app_id]
        if 'common' in app and app['common']['type'].lower() == 'game':
            result_list = []
            for depot_id, depot in fresh_resp['apps'][app_id]['depots'].items():
                if 'manifests' in depot and 'public' in depot['manifests'] and int(
                        depot_id) in cdn.licensed_depot_ids:
                    result_list.append(gevent.spawn(get_manifest, cdn, app_id, depot_id, depot['manifests']['public']))
                    gevent.idle()
            gevent.joinall(result_list)
