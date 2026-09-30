<div align="center">

<img src="./logo.png" alt="MaaCR" width="200" />

# MaaCR

**皇室战争 · 一键长草小助手**

自动开游戏 · 自动进局 · 按策略下牌 · 结算循环 · 日常任务 · 三级自愈

[![Release](https://img.shields.io/github/v/release/yu-echo/MaaCR?style=flat-square&label=%E4%B8%8B%E8%BD%BD)](https://github.com/yu-echo/MaaCR/releases/latest)
[![License](https://img.shields.io/github/license/yu-echo/MaaCR?style=flat-square)](LICENSE)
[![MaaFramework](https://img.shields.io/badge/MaaFramework-%E9%A9%B1%E5%8A%A8-blue?style=flat-square)](https://github.com/MaaXYZ/MaaFramework)
[![Platform](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%20%7C%20MuMu%20%E6%A8%A1%E6%8B%9F%E5%99%A8-lightgrey?style=flat-square)]()
[![Stars](https://img.shields.io/github/stars/yu-echo/MaaCR?style=flat-square&logo=github)](https://github.com/yu-echo/MaaCR/stargazers)

</div>

---

基于 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 的皇室战争国服小助手，
图形界面用 **[MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)**。

**本项目是纯 JSON 流水线** —— 没有 Python、没有脚本、没有 `.py`，
全部逻辑都在 `assets/` 的节点 JSON 里，由框架自己解释。

> 只针对**国服（腾讯代理版）**和 **MuMu 模拟器 720×1280 竖屏**调过；
> 别的分辨率 / 别的模拟器 / 别的服没试过，也不保证。

## ⚠️ 先说清楚定位

> **它的目标是「快速刷完尽可能多的对局」**（刷宝箱 / 对局时长 / 卡牌大师进度），
> **不是上分**。所以「输」是设计的一部分，不是 bug。
>
> ⇒ **评估它好不好用，看的是「每局对战耗时」，不是胜率。**

## 功能列表

- [x] **对战**
  - [x] 自动进局、按优先级与圣水条件出牌、结算后自动开下一局
  - [x] 破塔后落点自动切到敌方半场深位，往国王塔压
- [x] **日常**
  - [x] 商店礼包（每日免费礼物 + 维护 / 异常补偿礼包，只领标着「免费！」的）
  - [x] 部落捐赠（只捐亮绿色的可捐请求）
  - [x] 请求卡牌（界面上可选要请求哪一张；冷却中自动跳过）
  - [x] 「日常一条龙」预设：启动 → 领商店礼包 →（自动战斗 + 部落捐赠）× N 轮 → 退游戏
- [x] **自愈**（认不出来的界面）
  - [x] 点底部导航回主界面 → 当弹层点一下 → 重启游戏（代价从低到高）
  - [x] 区分「认不出」和「真卡住」：只有画面**也定格了**才算卡住
- [x] **识别**（不依赖 OCR 认状态）
  - [x] 圣水条 / 敌塔血量 / 结算皇冠 / 手牌卡面

## 图形化界面

到 [Releases](https://github.com/yu-echo/MaaCR/releases/latest) 下载 **`-MFAA.zip`**，
**解压到纯英文路径**，双击里面的 **`MFAAvalonia.exe`**。

缺 .NET 就先跑一次 `install-deps-win.bat`，装完**重启电脑**。

> 同一个 Release 里还有 **`-PiCLI.zip`**：不带界面，只有 `MaaPiCli.exe`，
> 适合不想开界面、或想无头跑的人。

## 如何使用

**看 [使用说明](使用说明.md)** —— 三步跑起来（装依赖 → 准备模拟器 → 开始）。

模拟器准备、设备选择、命令行跑法这些细节在
**[1.1-快速开始](docs/zh_cn/1.1-快速开始.md)**；出问题看
**[5.1-常见问题](docs/zh_cn/5.1-常见问题.md)**。

## 从零开始学会写流程

**不用会编程** —— 这个项目的流程就是 JSON，「加一个功能」= 「加一个 JSON 节点」。

三篇教程在这里 → **[从零写一个新流程](docs/zh_cn/README.md#想从零写一个新流程)**：
写第一个节点 → 写一份日常流程 → 挂到界面上并验证。

> 新手最容易踩的三个坑：① 模板图必须从 **720×1280 无损截图**裁（缩放过的会认不到，且不报错）；
> ② `next` 列表**顺序即优先级**；③ 改完必须实跑一遍 —— CI 会做静态检查，但跑通才算数。

## 开发相关

**只有要改流程 / 改素材 / 自己出包才需要看这些。** 只是想拿它打游戏，看上面几节就够了。

| 想看什么 | 去哪 |
| --- | --- |
| 源码结构、两种调试方式、改完怎么验证 | [3.1-从源码跑](docs/zh_cn/3.1-从源码跑.md) |
| **改行为之前先看**（出牌优先级 / 落点 / 换卡组） | [2.3-调策略](docs/zh_cn/2.3-调策略.md) |
| 识别怎么工作、怎么加新锚点 | [2.1-识别原理](docs/zh_cn/2.1-识别原理.md) |
| 日常任务两条流程的判据 | [2.2-日常任务](docs/zh_cn/2.2-日常任务.md) |
| 框架语义陷阱 | [3.2-迁移对照](docs/zh_cn/3.2-迁移对照.md) |
| 自己打一个发布包 | [3.3-打包发布](docs/zh_cn/3.3-打包发布.md) |

> 完整索引与编号约定：[`docs/zh_cn/README.md`](docs/zh_cn/README.md)
> （编号体例跟 [MaaFramework 官方文档](https://github.com/MaaXYZ/MaaFramework/tree/main/docs/zh_cn) 一致）。

## 路线图

- [x] 阶段 1：最小闭环（主界面 → 进对战 → 出牌 → 结算 → 循环）
- [x] 阶段 2：导航容错 + 未知界面自愈 + 重启游戏
- [x] 阶段 3：日常任务——商店免费项、部落捐赠
- [x] 阶段 4：日常一条龙
- [x] 阶段 5：**去 Python**：删掉 Agent 与全部脚本，改成纯 JSON 流水线
- [ ] 阶段 6：补锚点（商店各子标签、社交页、训练日预览页），减少走兜底路径
- [ ] 阶段 7：防守判断（识别己方半场的血条 → 有敌人先防守），把胜率拉起来
- [ ] 多分辨率支持（坐标改按比例存 + 模板按分辨率分目录）

## 鸣谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！
桌面图形界面由 **[MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)** 提供。

参考过的项目：

- [MaaPracticeBoilerplate](https://github.com/MaaXYZ/MaaPracticeBoilerplate) —— 目录约定、资源组织的参考
- [syoius/MaaYuan](https://github.com/syoius/MaaYuan) —— `interface.json` 写法与打包布局的参考
- [Coxwtwo/MaaTOT](https://github.com/Coxwtwo/MaaTOT) —— README 与 CI 组织形式的参考
- [kqcoxn/MaaPipelineEditor](https://github.com/kqcoxn/MaaPipelineEditor) —— 可视化改流水线用的编辑器

感谢以下开发者对本项目作出的贡献：

<a href="https://github.com/yu-echo/MaaCR/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=yu-echo/MaaCR&max=1000&columns=15&anon=1" />
</a>

## License

[MIT](LICENSE)
