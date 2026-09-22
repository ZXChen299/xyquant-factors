# 第三方软件许可声明

本清单由 `scripts/generate_notices.py` 从与 `requirements-build.lock` 完全匹配的已安装包元数据生成。
版本、许可字段和项目链接均来自对应 wheel 的元数据；下列本地链接保留原始许可文本及版权声明，文件未经改写。

锁文件同时包含客户端依赖与构建工具，因此本表是构建环境清单，不表示每个包都被收录进可执行文件。
未声明许可字段时明确记录为未声明，以随包原文为准；本项目的 MIT 许可证不替代各第三方许可。

原始元数据字段、wheel 内来源路径及每份文本的 SHA-256 见 [许可来源清单](docs/licenses/inventory.json)。

## Python 运行环境

可执行文件使用 CPython 3.12.14。分发保留 [Python 安装目录原始 LICENSE.txt](docs/licenses/cpython-3.12.14/LICENSE.txt)，其中包含 Python 及随附组件的许可声明。

## 锁定的 Python 包

| 包 | 版本 | 元数据中的许可 | 来源与原文 |
|---|---|---|---|
| altgraph | 0.17.5 | MIT | [项目来源](https://github.com/ronaldoussoren/altgraph) · [LICENSE](docs/licenses/altgraph-0.17.5/altgraph-0.17.5.dist-info/LICENSE) |
| annotated-types | 0.8.0 | MIT | [项目来源](https://github.com/annotated-types/annotated-types) · [LICENSE](docs/licenses/annotated-types-0.8.0/annotated_types-0.8.0.dist-info/licenses/LICENSE) |
| anyio | 4.15.1 | MIT | [项目来源](https://github.com/agronholm/anyio) · [LICENSE](docs/licenses/anyio-4.15.1/anyio-4.15.1.dist-info/licenses/LICENSE) |
| attrs | 26.1.0 | MIT | [项目来源](https://github.com/python-attrs/attrs) · [LICENSE](docs/licenses/attrs-26.1.0/attrs-26.1.0.dist-info/licenses/LICENSE) |
| Authlib | 1.8.0 | BSD-3-Clause | [项目来源](https://github.com/authlib/authlib) · [LICENSE](docs/licenses/authlib-1.8.0/authlib-1.8.0.dist-info/licenses/LICENSE) |
| cffi | 2.1.1 | MIT-0 | [项目来源](https://github.com/python-cffi/cffi) · [LICENSE](docs/licenses/cffi-2.1.1/cffi-2.1.1.dist-info/licenses/LICENSE) |
| click | 8.5.0 | BSD-3-Clause | [项目来源](https://github.com/pallets/click/) · [LICENSE.txt](docs/licenses/click-8.5.0/click-8.5.0.dist-info/licenses/LICENSE.txt) |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause | [项目来源](https://github.com/pyca/cryptography/) · [1:LICENSE](docs/licenses/cryptography-50.0.1/cryptography-50.0.1.dist-info/licenses/LICENSE) · [2:LICENSE.APACHE](docs/licenses/cryptography-50.0.1/cryptography-50.0.1.dist-info/licenses/LICENSE.APACHE) · [3:LICENSE.BSD](docs/licenses/cryptography-50.0.1/cryptography-50.0.1.dist-info/licenses/LICENSE.BSD) |
| h11 | 0.16.0 | MIT | [项目来源](https://github.com/python-hyper/h11) · [LICENSE.txt](docs/licenses/h11-0.16.0/h11-0.16.0.dist-info/licenses/LICENSE.txt) |
| httpcore2 | 2.13.0 | BSD-3-Clause | [项目来源](https://github.com/pydantic/httpx2/blob/main/src/httpcore2) · [LICENSE.md](docs/licenses/httpcore2-2.13.0/httpcore2-2.13.0.dist-info/licenses/LICENSE.md) |
| httpx2 | 2.13.0 | BSD-3-Clause | [项目来源](https://github.com/pydantic/httpx2) · [LICENSE.md](docs/licenses/httpx2-2.13.0/httpx2-2.13.0.dist-info/licenses/LICENSE.md) |
| idna | 3.20 | BSD-3-Clause | [项目来源](https://github.com/kjd/idna) · [LICENSE.md](docs/licenses/idna-3.20/idna-3.20.dist-info/licenses/LICENSE.md) |
| joserfc | 1.7.5 | BSD-3-Clause | [项目来源](https://github.com/authlib/joserfc) · [LICENSE](docs/licenses/joserfc-1.7.5/joserfc-1.7.5.dist-info/licenses/LICENSE) |
| jsonschema | 4.26.0 | MIT | [项目来源](https://github.com/python-jsonschema/jsonschema) · [COPYING](docs/licenses/jsonschema-4.26.0/jsonschema-4.26.0.dist-info/licenses/COPYING) |
| jsonschema-specifications | 2025.9.1 | MIT | [项目来源](https://github.com/python-jsonschema/jsonschema-specifications) · [COPYING](docs/licenses/jsonschema-specifications-2025.9.1/jsonschema_specifications-2025.9.1.dist-info/licenses/COPYING) |
| mcp | 2.2.0 | MIT | [项目来源](https://github.com/modelcontextprotocol/python-sdk) · [LICENSE](docs/licenses/mcp-2.2.0/mcp-2.2.0.dist-info/licenses/LICENSE) |
| mcp-types | 2.2.0 | MIT | [项目来源](https://github.com/modelcontextprotocol/python-sdk) · [LICENSE](docs/licenses/mcp-types-2.2.0/mcp_types-2.2.0.dist-info/licenses/LICENSE) |
| opentelemetry-api | 1.44.0 | Apache-2.0 | [项目来源](https://github.com/open-telemetry/opentelemetry-python) · [LICENSE](docs/licenses/opentelemetry-api-1.44.0/opentelemetry_api-1.44.0.dist-info/licenses/LICENSE) |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | [项目来源](https://github.com/pypa/packaging) · [1:LICENSE](docs/licenses/packaging-26.3/packaging-26.3.dist-info/licenses/LICENSE) · [2:LICENSE.APACHE](docs/licenses/packaging-26.3/packaging-26.3.dist-info/licenses/LICENSE.APACHE) · [3:LICENSE.BSD](docs/licenses/packaging-26.3/packaging-26.3.dist-info/licenses/LICENSE.BSD) |
| pefile | 2024.8.26 | MIT | [项目来源](https://github.com/erocarrera/pefile) · [LICENSE](docs/licenses/pefile-2024.8.26/pefile-2024.8.26.dist-info/LICENSE) |
| pycparser | 3.0 | BSD-3-Clause | [项目来源](https://github.com/eliben/pycparser) · [LICENSE](docs/licenses/pycparser-3.0/pycparser-3.0.dist-info/licenses/LICENSE) |
| pydantic | 2.13.5 | MIT | [项目来源](https://github.com/pydantic/pydantic) · [LICENSE](docs/licenses/pydantic-2.13.5/pydantic-2.13.5.dist-info/licenses/LICENSE) |
| pydantic_core | 2.46.5 | MIT | [项目来源](https://github.com/pydantic/pydantic/tree/main/pydantic-core) · [LICENSE](docs/licenses/pydantic-core-2.46.5/pydantic_core-2.46.5.dist-info/licenses/LICENSE) |
| pyinstaller | 6.22.3 | GPLv2-or-later with a special exception which allows to use PyInstaller to build and distribute non-free programs (including commercial ones) | [项目来源](https://github.com/pyinstaller/pyinstaller) · [COPYING.txt](docs/licenses/pyinstaller-6.22.3/pyinstaller-6.22.3.dist-info/licenses/COPYING.txt) |
| pyinstaller-hooks-contrib | 2026.7 | 元数据未声明；见原始许可文本 | [项目来源](https://github.com/pyinstaller/pyinstaller-hooks-contrib) · [LICENSE](docs/licenses/pyinstaller-hooks-contrib-2026.7/pyinstaller_hooks_contrib-2026.7.dist-info/licenses/LICENSE) |
| PyJWT | 2.14.0 | MIT | [项目来源](https://github.com/jpadilla/pyjwt) · [1:AUTHORS.rst](docs/licenses/pyjwt-2.14.0/pyjwt-2.14.0.dist-info/licenses/AUTHORS.rst) · [2:LICENSE](docs/licenses/pyjwt-2.14.0/pyjwt-2.14.0.dist-info/licenses/LICENSE) |
| python-multipart | 0.0.32 | Apache-2.0 | [项目来源](https://github.com/Kludex/python-multipart) · [LICENSE.txt](docs/licenses/python-multipart-0.0.32/python_multipart-0.0.32.dist-info/licenses/LICENSE.txt) |
| pywin32 | 312 | PSF | [项目来源](https://github.com/mhammond/pywin32) · [1:license.txt](docs/licenses/pywin32-312/pywin32-312.dist-info/licenses/adodbapi/license.txt) · [2:License.txt](docs/licenses/pywin32-312/pywin32-312.dist-info/licenses/com/License.txt) · [3:LICENSE](docs/licenses/pywin32-312/pywin32-312.dist-info/licenses/com/win32comext/mapi/src/MAPIStubLibrary/LICENSE) · [4:README.txt](docs/licenses/pywin32-312/pywin32-312.dist-info/licenses/isapi/README.txt) · [5:License.txt](docs/licenses/pywin32-312/pywin32-312.dist-info/licenses/pythonwin/License.txt) · [6:License.txt](docs/licenses/pywin32-312/pywin32-312.dist-info/licenses/pythonwin/Scintilla/License.txt) · [7:LICENSE.txt](docs/licenses/pywin32-312/pywin32-312.dist-info/licenses/pythonwin/pywin/idle/LICENSE.txt) · [8:License.txt](docs/licenses/pywin32-312/pywin32-312.dist-info/licenses/win32/License.txt) |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | [项目来源](https://github.com/enthought/pywin32-ctypes) · [LICENSE.txt](docs/licenses/pywin32-ctypes-0.2.3/pywin32_ctypes-0.2.3.dist-info/LICENSE.txt) |
| referencing | 0.37.0 | MIT | [项目来源](https://github.com/python-jsonschema/referencing) · [COPYING](docs/licenses/referencing-0.37.0/referencing-0.37.0.dist-info/licenses/COPYING) |
| rpds-py | 2026.6.3 | MIT | [项目来源](https://github.com/crate-py/rpds) · [LICENSE](docs/licenses/rpds-py-2026.6.3/rpds_py-2026.6.3.dist-info/licenses/LICENSE) |
| setuptools | 84.0.0 | MIT | [项目来源](https://github.com/pypa/setuptools) · [1:LICENSE](docs/licenses/setuptools-84.0.0/setuptools-84.0.0.dist-info/licenses/LICENSE) · [2:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/autocommand-2.2.2.dist-info/LICENSE) · [3:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/backports.tarfile-1.2.0.dist-info/LICENSE) · [4:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/importlib_metadata-8.7.1.dist-info/licenses/LICENSE) · [5:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/jaraco.text-4.0.0.dist-info/LICENSE) · [6:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/jaraco_context-6.1.0.dist-info/licenses/LICENSE) · [7:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/jaraco_functools-4.4.0.dist-info/licenses/LICENSE) · [8:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/more_itertools-10.8.0.dist-info/licenses/LICENSE) · [9:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/packaging-26.0.dist-info/licenses/LICENSE) · [10:LICENSE.APACHE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/packaging-26.0.dist-info/licenses/LICENSE.APACHE) · [11:LICENSE.BSD](docs/licenses/setuptools-84.0.0/setuptools/_vendor/packaging-26.0.dist-info/licenses/LICENSE.BSD) · [12:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/platformdirs-4.4.0.dist-info/licenses/LICENSE) · [13:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/tomli-2.4.0.dist-info/licenses/LICENSE) · [14:LICENSE.txt](docs/licenses/setuptools-84.0.0/setuptools/_vendor/wheel-0.46.3.dist-info/licenses/LICENSE.txt) · [15:LICENSE](docs/licenses/setuptools-84.0.0/setuptools/_vendor/zipp-3.23.0.dist-info/licenses/LICENSE) |
| sse-starlette | 3.4.11 | BSD-3-Clause | [项目来源](https://github.com/sysid/sse-starlette) · [1:AUTHORS](docs/licenses/sse-starlette-3.4.11/sse_starlette-3.4.11.dist-info/licenses/AUTHORS) · [2:LICENSE](docs/licenses/sse-starlette-3.4.11/sse_starlette-3.4.11.dist-info/licenses/LICENSE) |
| starlette | 1.6.0 | BSD-3-Clause | [项目来源](https://github.com/Kludex/starlette) · [LICENSE.md](docs/licenses/starlette-1.6.0/starlette-1.6.0.dist-info/licenses/LICENSE.md) |
| tomlkit | 0.15.1 | MIT | [项目来源](https://github.com/python-poetry/tomlkit) · [LICENSE](docs/licenses/tomlkit-0.15.1/tomlkit-0.15.1.dist-info/licenses/LICENSE) |
| truststore | 0.10.4 | MIT | [项目来源](https://github.com/sethmlarson/truststore) · [LICENSE](docs/licenses/truststore-0.10.4/truststore-0.10.4.dist-info/licenses/LICENSE) |
| typing-inspection | 0.4.4 | MIT | [项目来源](https://github.com/pydantic/typing-inspection) · [LICENSE](docs/licenses/typing-inspection-0.4.4/typing_inspection-0.4.4.dist-info/licenses/LICENSE) |
| typing_extensions | 4.16.0 | PSF-2.0 | [项目来源](https://github.com/python/typing_extensions) · [LICENSE](docs/licenses/typing-extensions-4.16.0/typing_extensions-4.16.0.dist-info/licenses/LICENSE) |
| uvicorn | 0.53.0 | BSD-3-Clause | [项目来源](https://github.com/Kludex/uvicorn) · [LICENSE.md](docs/licenses/uvicorn-0.53.0/uvicorn-0.53.0.dist-info/licenses/LICENSE.md) |

## 构建工具的附加说明

PyInstaller 的原始 `COPYING.txt` 包含 Bootloader Exception 及运行时 hooks 的许可说明。
`pyinstaller-hooks-contrib` 的原始 `LICENSE` 区分标准构建 hooks 与运行时 hooks；请保留完整原文。
pywin32 和 setuptools 安装包包含多份附属组件声明，本清单逐份复制，不将它们全部替换为包级许可名称。

发布时应将本声明及 `docs/licenses/` 原文一并交付。修改依赖或 Python 版本后必须从新的构建环境重新生成。
