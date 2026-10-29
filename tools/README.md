# 工具清单

版本为实机验证过的组合，不是最低要求。低于这些版本没有测过。

| 用途 | 工具 | 验证版本 | 必需 |
| :--- | :--- | :--- | :-: |
| 设备通信 | adb（platform-tools） | 1.0.41 / 37.0.1 | 是 |
| 设备端提权 | su | 依赖设备已 root | 国产 ROM 必需 |
| 清单解密与取件 | Python | 3.13.14 | 是 |
| Unity 资源导出 | UnityPy | 1.25.4 | 是 |
| 块解压 | zstandard（Python 包） | 0.25.0 | 是 |
| 图像处理 | Pillow | 12.3.0 | 是 |
| 清单查询 | sqlite3（Python 标准库） | 3.53.1 | 是 |
| 静态表反序列化 | .NET SDK | 8.0.401 | 否，仅取静态表时需要 |

两点容易走弯路：

不需要 `zstd` 命令行。Python 的 `zstandard` 包覆盖全部解压需求。

不需要系统安装 sqlite 命令行。Python 标准库自带，版本随解释器走。

## 安装

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

adb 单独下 platform-tools，把目录加进 PATH，或者用 `NIKKE_ADB` 环境变量指向可执行文件。

## 自检

```bash
adb version
python -c "import UnityPy, zstandard, PIL, sqlite3; print('ok')"
dotnet --version      # 只有取静态表才需要
```

四行都通过才能开工。`python -c` 那行报 ImportError 说明装到了别的解释器上，检查虚拟环境是否激活。

## Windows 上的两个坑

Python 子进程强制 UTF-8，否则中文控制台下 UnityPy 和 json 里的中文直接崩：

```
PYTHONIOENCODING=utf-8
PYTHONUTF8=1
```

Git Bash 里调 adb 先关掉路径转换，否则参数里的 `/storage/...` 会被改写成 Windows 路径：

```bash
export MSYS_NO_PATHCONV=1
```
