# 打包与发布

面向改代码的人。只想下载来用的话，看 [README 的使用说明](../../../README.md#使用说明)。

**一句话流程**：打一个 `v*` 标签推上去 → 工作流产出 `MaaCR-win-x86_64-<标签>.zip` → 自动建 Release。

```bash
git tag v0.1.1
git push origin v0.1.1
```

分支上也可以手动触发 `install` 工作流（Actions 页面 → Run workflow），
但那一次只会产出带 `-ci.` 的预览包，不建 Release —— 用来验证打包链路本身。

---

## 一、产物长什么样

发布包的目录结构和源码仓库**不一样**，而且必须不一样：MFAAvalonia 只认「自己旁边那个
`interface.json`」，所以 `interface.json` 必须和 `MFAAvalonia.exe` 同层。

```
MaaCR-win-x86_64-vX.Y.Z/
├── MFAAvalonia.exe / *.dll / *.json      ← MFAAvalonia 的 win-x64 发布包，平铺在这里
├── interface.json                        ← 改写过的（见第二节）
├── resource/                             ← assets/resource
├── agent/                                ← agent/
├── tools/                                ← tools/（不含 ci/）
├── python/                               ← 自带 Python + MaaFw / opencv-python / numpy
├── runtimes/win-x64/native/              ← MaaFramework 原生库（.NET 认这个布局）
├── libs/MaaAgentBinary/                  ← Agent 子进程通信用的二进制
├── plugins/win-x64/                      ← MaaFramework 插件（有就带）
├── install-deps-win.bat                  ← 装 .NET 10 桌面运行时
├── docs/zh_cn/                           ← 文档，让 README 里的链接在包里也点得开
├── README.md
└── LICENSE
```

谁负责哪一段：

| 谁 | 干什么 |
| --- | --- |
| `.github/workflows/install.yml` | 下载上游 → 平铺 MFAAvalonia 到 `install/` → 调下面两个脚本 → 出 zip → 建 Release |
| `tools/ci/setup_embed_python.py` | 把 Python 装进 `install/python/` |
| `tools/install.py` | 复制资源/代码/文档，并改写 `install/interface.json` 的路径 |

**为什么只出 Windows 包**：`tools/preflight.py` 是 MuMu + Windows 专属，全部模板与坐标也是
按 720×1280 量的。出别的平台的包等于发一个确定不能用的东西。

---

## 二、`interface.json` 的路径改写（最要紧的一节）

MFAAvalonia 解析这几个字段时，**基准目录不是同一个**。这一点官方文档没写清楚，
写错了不会报错、只会「点开始没反应」或者直接 `pretask failed`。

（下面这张表是从 MFAAvalonia `v2.16.1` 的源码读出来的，不是猜的：
`MaaProcessor.cs` 的 `ExecutePreTasks`、`AgentHelper.cs` 的 `StartAgentsAsync`、
`MaaInterface.cs` 的 `ReplacePlaceholder`。）

| 字段 | 相对谁解析 | 会不会走 PATH 查找 |
| --- | --- | --- |
| `agent.child_exec` | 数据目录（= `MFAAvalonia.exe` 所在目录） | 会（找不到路径时当命令名处理） |
| `agent.child_args` | 同上 | 不适用 |
| `pretask.exec` | 数据目录 **`/resource/base`** | **不会** |
| `pretask.args` | `pretask` 的工作目录（同样是 `resource/base`） | 不适用 |

发布包里「数据目录」就是包根，于是 `tools/install.py` 把它改成：

```jsonc
"agent": {
    "child_exec": "python/python.exe",          // -> 包根/python/python.exe
    "child_args": ["-u", "agent/main.py"]       // -> 包根/agent/main.py
},
"pretask": {
    "exec": "../../python/python.exe",          // 相对 resource/base -> 包根/python/python.exe
    "args": ["../../tools/preflight.py"]        // 相对 resource/base -> 包根/tools/preflight.py
}
```

注意 `agent` 那边是**相对包根**两段，`pretask` 那边是**相对 `resource/base`** ——
两者差的正是 `resource/base` 这两层。这是最容易改错的地方。

### 2.1 `pretask.exec` 不走 PATH

`ReplacePlaceholder(exec, ResourceBase)` 在没有 `{PROJECT_DIR}` 占位符时执行的是
`Path.Combine(ResourceBase, exec)`。所以写 `"python"` 会拼成
`…/resource/base/python` 这样一个**不存在的文件**，`Process.Start` 直接失败，
MFAAvalonia 报 `pretask failed` 并中止启动。

官方文档写的是「可以是系统 `PATH` 中的可执行文件，例如 `"python"`」，与实现对不上 ——
所以仓库里的 `assets/interface.json` 用的是绝对路径壳：

```jsonc
"exec": "C:/Windows/System32/cmd.exe",
"args": ["/c", "python", "../../../tools/preflight.py"]
```

`cmd.exe` 走绝对路径一定在，真正要跑的命令交给它，由它去 PATH 里找 `python`。
（对照：`sunyink/MFABD2` 用的是 `"../../../.venv/Scripts/python.exe"`，
`AkumaYUC/MaaXA` 用绝对的 `powershell.exe` —— 两个真实项目都在绕同一个坑。）

### 2.2 `resource/base/` 这个空目录必须存在

`ProcessStartInfo.WorkingDirectory` 被设成了 `resource/base`。**目录不存在时
`Process.Start` 会直接抛「目录名无效」**，压根走不到执行那一步。

所以 `assets/resource/base/.gitkeep` 不是垃圾文件，删了 pretask 就永远起不来。
（对照：`AkumaYUC/MaaXA` 的 `assets/resource/base/` 里也只有一个 `.gitkeep`。）

`tools/validate.py` 会把这两件事都挡住：`pretask.exec` 写了相对/命令名会报错，
`resource/base` 不存在也会报错。

---

## 三、自带 Python 是怎么装的

`tools/ci/setup_embed_python.py`，四步：

1. 下 `python-3.11.x-embed-amd64.zip`（官方 embed 版，不写注册表、不碰系统 PATH）；
2. **改写 `python311._pth`**：放开 `import site` 并补上 `Lib\site-packages`。
   embed 版默认不跑 `site.py`，不做这一步的话 pip 装完的东西 `import` 不到，
   表现是「明明装了却 `ModuleNotFoundError`」；
3. 下 `get-pip.py` 用自带 Python 跑一遍装上 pip；
4. `pip install -r agent/requirements.txt`，然后 `import MaaFw, cv2, numpy` 验一次。

想换 Python 版本：`python tools/ci/setup_embed_python.py install 3.12.8`。

**网络不通 / 慢得像卡死**：`python.org` 在国内实测能连上但传输极慢，加个环境变量优先走镜像：

```bash
MAACR_USE_CN_MIRROR=1 python tools/ci/setup_embed_python.py install
# pip 装依赖想换源就用 pip 自己的变量（脚本不干预）
MAACR_USE_CN_MIRROR=1 PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    python tools/ci/setup_embed_python.py install
```

CI 跑在 GitHub 的机器上，这两个变量都不用设，走官方源。

下载过程会实时打进度（每 3 秒一行，带速度），长时间没输出就是真卡住了，不是脚本没在干活。

---

## 四、锁上游版本

`install.yml` 顶部两个环境变量：

```yaml
env:
  MAAFW_VERSION: ""     # 留空 = 用 MaaXYZ/MaaFramework 的 latest
  MFAA_VERSION: ""      # 留空 = 用 MaaXYZ/MFAAvalonia 的 latest
```

平时留空跟着上游走。万一上游某版把什么改坏了，填上具体版本号（如 `v5.13.1` / `v2.16.1`）
就能先发出一个可用的包，不用等上游修。

---

## 五、本地试跑（不用等 CI）

`tools/install.py` 只做「复制 + 改一行 JSON」，不下载任何东西，所以要先把料备齐：

```bash
# 1) 备料：MaaFramework 解压到 deps/，MFAAvalonia 平铺到 install/
#    和 CI 里一样，从两边的 release 页面下 MAA-win-x86_64-*.zip 与 MFAAvalonia-*-win-x64.zip

# 2) 装自带 Python（会联网；只想验组装流程的话可以跳过）
python tools/ci/setup_embed_python.py install

# 3) 组装
python tools/install.py v0.0.0-local

# 4) 看一眼结果
python tools/validate.py
```

出包之后**先看 `install/interface.json` 里那四个路径字段**是不是第二节表格里那样，
再看 `install/resource/base/` 在不在。这两处对了，剩下的就是 MFAAvalonia 自己的事。

---

## 六、踩过的坑（都是第一次真跑 CI 才暴露的）

### 6.1 非中文 Windows 上，入口脚本会崩在第一行日志

Python 的 `stdout` 默认按**系统代码页**编码：中文 Windows 是 GBK，扛得住中文；
英文 / 西欧 Windows 是 **cp1252**，`print()` 任何中文都直接 `UnicodeEncodeError`
把进程打死。

这条在 CI 上的表现极具误导性：`setup_embed_python.py` 崩在「下载」之前，
报出来却像是「这个源不行」，很容易误判成网络问题；`preflight.py` /
`agent/main.py` 崩在第一行，看起来像「Agent 压根没启动」。

所以本仓库的 5 个入口 —— `agent/main.py`、`tools/preflight.py`、`tools/validate.py`、
`tools/install.py`、`tools/ci/setup_embed_python.py` —— 开头都有一段：

```python
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
```

**新加入口时照抄这段。** 本地测法：`PYTHONIOENCODING=cp1252 python 你的脚本.py`。

### 6.2 `upload-artifact` 默认不收隐藏文件

`resource/base/` 里只有一个 `.gitkeep`。`actions/upload-artifact@v4` 默认
`include-hidden-files: false`，而**空目录也不会被存进产物** —— 两个因素叠加，
解压出来就没有 `resource/base/`，pretask 的工作目录不存在，
「环境准备」直接报「目录名无效」，等于把第二节修掉的坑原样还回去。

已经给上传步骤加上 `include-hidden-files: true`，并在 `tools/install.py` 里加了
`verify_layout()`：8 条关键路径逐条核对，缺一条就中止打包。

---

## 七、还没验证的地方

这一套已经走通「分支构建（`-ci.` 预览包）」与「正式发版（v0.1.0）」两条路，
下面这些是已经确认过的：

- [x] ~~上游 zip 里 `MFAAvalonia.exe` 是否真在压缩包根~~ —— **在**。
      平铺之后 `install/` 顶层就是：
      `DependencySetup_依赖库安装_win.bat`、`MFAAvalonia.deps.json`、
      `MFAAvalonia.dll`、`MFAAvalonia.exe`、`MFAAvalonia.runtimeconfig.json`、
      `MaaAgentBinary`、`libloader.dll`、`libs`、`plugins`
- [x] ~~MFAAvalonia 的 zip 里有没有同名 `resource/` 跟我们的资源打架~~ —— **没有**，它不带 `resource/`
- [x] ~~自带 Python 的 `pip install` 在 CI 里能不能通~~ —— **通了**
      （MaaFw 5.13.1 / opencv-python 5.0.0.93 / numpy 2.4.6）
- [x] ~~打包脚本能不能在 windows runner 上跑完~~ —— **能**
- [x] ~~上传 / 打包两个环节会不会把 `resource/base/` 弄丢~~ —— **没丢**，
      已用 Range 请求直接读发布出去的 zip 的中央目录确认过，`resource/base/.gitkeep` 在

还剩这些，只有真在用户机器上跑才能确认：

- [ ] 发布包在**干净 Windows** 上解压 → 双击 → 真的能起（含缺 .NET 时的 `install-deps-win.bat`）
- [ ] `pretask` 在**发布包布局**下能找到 `python/python.exe` 并跑起来
      （本地已按完全相同的层数与工作目录验证过，但没在真机上端到端跑）
- [ ] 用户机器上 MuMu 的 `adb` 能不能被 `preflight.py` 找到（现在找不到也不致命，会放行）

> 顺带一提：MFAAvalonia 自己带了一个 `DependencySetup_依赖库安装_win.bat`（也是装 .NET 的）。
> 我们那个 `install-deps-win.bat` 是重复造轮子，但名字更直白、README 里直接点了它，
> 先留着；哪天想精简可以去一个。

---

## 八、参考

- [MaaPracticeBoilerplate 的 install.yml](https://github.com/MaaXYZ/MaaPracticeBoilerplate/blob/main/.github/workflows/install.yml)
  —— 本仓库工作流的骨架（tag 计算、changelog、release 三段照搬）
- [syoius/MaaYuan](https://github.com/syoius/MaaYuan) —— 自带 Python 与 `interface.json`
  路径改写的参考（它的 `install4release.py`）
- [ProjectInterface V2 文档](https://maafw.xyz/docs/3.3-ProjectInterfaceV2)
  —— 字段定义；但 `pretask` 的路径基准要以上游源码为准
