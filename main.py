import vdf
import os.path
import argparse
import subprocess
import gevent.monkey
from steam.client import SteamClient
from steam.client.cdn import CDNClient
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
        except SteamError:
            pass
    print(
        f'app_id: {app_id:<8}{"":<10}depot_id: {depot_id:<8}{"":<10}manifest_gid: {manifest_gid:20}{"":<10}DecryptionKey: {DecryptionKey.hex()}')
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


parser = argparse.ArgumentParser()
parser.add_argument('-u', '--username', required=False)
parser.add_argument('-p', '--password', required=False)
parser.add_argument('-a', '--app-id', required=False)
parser.add_argument('-l', '--list-apps', action='store_true', required=False)

if __name__ == '__main__':
    steam = SteamClient()
    args = parser.parse_args()
    if args.username and args.password:
        steam.cli_login(args.username, args.password)
    else:
        steam.cli_login()
    appids = []
    depotids = []
    packages_info = []
    packages = list(
        map(lambda l: {'packageid': l.package_id, 'access_token': l.access_token}, steam.licenses.values()))
    if packages:
        for package_id, info in steam.get_product_info(packages=packages)['packages'].items():
            if info['depotids'] and 0 < info['billingtype'] < 12:
                appids.extend(list(info['appids'].values()))
                depotids.extend(list(info['depotids'].values()))
                packages_info.append((list(info['appids'].values()), list(info['depotids'].values())))
    cdn = CDNClient(steam)
    if args.app_id:
        appids = {int(app_id) for app_id in args.app_id.split(',')}
    fresh_resp = steam.get_product_info(appids)
    if args.list_apps:
        for app_id in appids:
            app = fresh_resp['apps'][app_id]
            if 'common' in app and app['common']['type'].lower() == 'game':
                print(app_id, app['common']['name'])
        exit()
    for app_id in appids:
        app = fresh_resp['apps'][app_id]
        if 'common' in app and app['common']['type'].lower() == 'game':
            result_list = []
            for depot_id, depot in fresh_resp['apps'][app_id]['depots'].items():
                if 'manifests' in depot and 'public' in depot['manifests'] and int(
                        depot_id) in cdn.licensed_depot_ids:
                    result_list.append(gevent.spawn(get_manifest, cdn, app_id, depot_id, depot['manifests']['public']))
            gevent.joinall(result_list)
