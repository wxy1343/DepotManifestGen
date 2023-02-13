# steam仓库清单文件生成

## 参数

* `-u, --username`: 账号
* `-p, --password`: 密码
* `-a, --app-id`: 仅爬取指定`appid`
* `-l, --list-apps`: 是否仅打印app信息
* `-s, --sentry-path, --ssfn`: `ssfn`文件路径
* `-k, --login-key`: 登录密钥
* `-f, --two-factor-code`: `2fa`验证码
* `-A, --auth-code`: 邮箱验证码
* `-i, --login-id`: 登录id
* `-c, --cli`: 交互式登录
* `-L, --level`: 日志,默认`INFO`
* `-C, --credential-location`: 账户凭据存储路径,默认`client`
* `-r, --remove-old`: 爬取到新的清单后是否删除旧的

## 清单文件简介

* `appid`: 游戏id
* `depot`: 用于存放游戏文件的仓库
* `depot_id`: 仓库编号，通常是`appid`的递增编号，一个`appid`可以有多个`depot_id`，例如`dlc`，`语言`等仓库
* `manifest`: 记录每个仓库文件的清单
* `manifest_gid`: 仓库清单的编号，类似于`commit id`
* `DecryptionKey`: 仓库密钥，用于解密仓库清单文件
* 具体可以查看`https://steamdb.info/app/{app_id}/depots/`

## 清单文件的位置

* `Steam\depotcache`

## 清单文件的作用

* 用于steam游戏的下载
* 参考项目[DepotDownloader](https://github.com/SteamRE/DepotDownloader)

## 清单文件生成

* 依赖项目[steam](https://github.com/ValvePython/steam)

```python
from steam.protobufs.content_manifest_pb2 import ContentManifestSignature

# 获取manifest_code
manifest_code = cdn.get_manifest_request_code(app_id, depot_id, manifest_gid)
# 通过manifest_code获取manifest对象
manifest = cdn.get_manifest(app_id, depot_id, manifest_gid, decrypt=False, manifest_request_code=manifest_code)
# 获取DecryptionKey
DecryptionKey = cdn.get_depot_key(manifest.app_id, manifest.depot_id)
# 通过DecryptionKey解密manifest
manifest.decrypt_filenames(DecryptionKey)
# 清空signature
manifest.signature = ContentManifestSignature()
for mapping in manifest.payload.mappings:
    # 删除文件名结尾特殊字符
    mapping.filename = mapping.filename.rstrip('\x00 \n\t')
    # 通过区块sha排序
    mapping.chunks.sort(key=lambda x: x.sha)
# 对文件名排序
manifest.payload.mappings.sort(key=lambda x: x.filename.lower())
# 通过payload计算crc_clear
manifest.metadata.crc_clear = crc32(manifest.payload.size + manifest.payload)
```

* `crc_clear`计算
    * ~~通过对steam逆向分析后找到了计算`crc_clear`算法，具体代码在`calc_crc_clear.c`~~
    * ~~分析得出steam是对`ContentManifestPayload`部分进行了`crc`计算，具体过程没搞懂，只复制了汇编代码~~
    * 对`ContentManifestPayload`的长度和数据打包后使用`crc32`计算得到
    * 参考[Manifest CRC Generation](https://cs.rin.ru/forum/viewtopic.php?t=124734)

## steam导入清单文件后下载游戏

* 把程序运行完后生成的`.manifest`文件复制到`Steam\depotcache`目录下
* 把生成的`config.vdf`文件里的`depots`合并到`Steam\config\config.vdf`文件
* 使用[steamtools](https://steamtools.net/)等工具解锁游戏后可以正常下载