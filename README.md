# 逐字自动输入 v1.0.0

> 作者：**PakLua**　|　版本：**v1.0.0**　|　平台：Windows 10 / 11（x64）

一个把文本**逐字符模拟键盘输入**到目标输入框的小工具。适用于各类禁止粘贴的在线输入框
（在线作业、表单、问卷、后台录入等）：它不是往剪贴板里塞内容，而是模拟真人敲键盘，
所以"禁止粘贴"对它是无效的。

**完全离线**：程序不联网、不上传任何内容、不收集任何使用数据，也不需要安装任何运行库。

---

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 逐字模拟输入 | 基于 Windows `SendInput`，与真人敲键盘在系统层面完全一致 |
| 不抢焦点 | 你先点一下目标输入框，之后按 F9 即可，不用切回本程序窗口 |
| 速度可调 | 慢 / 标准 / 快 / 极速 四档预设 + 0–200 毫秒/字 精细滑块 |
| 真人节奏抖动 | 在设定速度上做 ±30% 随机浮动，输入节奏更像真人 |
| 倒计时开始 | 0–30 秒可调，留出切换到目标窗口的时间 |
| 换行处理 | 跳过换行 / 转为空格 / 发送回车 三种方式 |
| 文本整理 | 一键去除 Markdown 符号（`**`、`#`、`` ` `` 等）、删除空行、适配自动编号编辑器 |
| 实时统计 | 字数、行数、实际输入字符数、预计耗时 |
| 进度与日志 | 倒计时圆环、进度条、剩余时间、可折叠运行日志 |
| 设置记忆 | 速度、开关、窗口位置自动保存，下次打开即恢复 |
| 导入 / 导出 | 支持从 txt 导入、导出为 txt |

## 使用方法

1. 把要录入的内容粘贴到「要输入的内容」框（可以直接粘带 Markdown 格式的文本）
2. 用鼠标点一下目标网页的输入框，让光标停在里面
3. 回到本程序，点「开始输入」或直接按 **F9**
4. 倒计时结束后，程序就会一个字一个字地把内容敲进去

### 快捷键

| 按键 | 作用 |
| --- | --- |
| `F9` | 开始输入 |
| `F8` | 中断并从头重新输入 |
| `Esc` | 紧急停止 |
| `Ctrl+Enter` | 在文本框内直接开始 |

> 关闭程序或按 Esc 可随时中止输入，是安全的。

## 系统要求

- Windows 10 / 11（64 位）
- 无需安装 Python 或 .NET 等运行库（已内置）

## 下载哪个版本

| 文件 | 说明 |
| --- | --- |
| `AutoInput_v1.0.0.exe` | **单文件版**，下载即用，首次启动稍慢（要自解压） |
| `AutoInput_v1.0.0_portable.zip` | **目录版**，解压后运行里面的 exe，**启动更快**，适合经常使用 |
| `AutoInput_v1.0.0_source.py` | 完整源码（Python 3.10+，仅用标准库），可自行审阅或修改 |

> 发布附件为什么是英文名？因为 **GitHub 会静默丢弃 Release 附件名里的非 ASCII 字符**
> （实测：上传 `中文名测试.txt` 会变成 `_.txt`）。程序界面本身是中文的，不受影响。

## 隐私说明

- **完全不联网**：源码中没有任何网络请求代码，可用抓包工具验证
- **不收集数据**：没有统计、没有埋点、没有自动更新回传
- **只写一个配置文件**：`%APPDATA%\PakLua\AutoInput\settings.json`，
  保存的是速度、开关状态和窗口位置，**不保存你输入的任何文本**
- 文本导入/导出只在你手动操作时读写你指定的文件

## 安全性 / 扫描报告

- VirusTotal 多引擎扫描报告：
  https://www.virustotal.com/gui/file/ec2aa0fa8282558ec3a01e80fd58d18d8fed06d36edec3fc601d081ff4bdd0af
- 发布包校验值见 Release 附件中的 `SHA256.txt`（**每次构建的哈希不同，以当次发布为准**）
- 如果杀软报毒，多半是误报，原因与处理见下文「常见问题」

## 免责声明

- 本软件是**输入辅助工具**，不提供任何答案或内容，也不针对任何特定平台
- 请**勿用于考试、测验、竞赛等需要本人独立完成的场景**；由此产生的一切后果（包括但不限于
  账号处罚、成绩作废、纪律处分）由使用者自行承担
- 请在遵守目标网站服务条款和当地法律法规的前提下使用
- 本软件按"现状"提供，作者不对使用效果及任何间接损失承担责任

## 常见问题

**Q：Windows 提示"已保护你的电脑 / 未知发布者"？**
A：因为程序没有购买代码签名证书，这是 SmartScreen 的正常提示。点「更多信息」→「仍要运行」即可。
担心安全可以先看源码（已随包提供），或把 exe 上传 VirusTotal 查看多引擎扫描结果。

**Q：杀毒软件报毒？**
A：PyInstaller 打包 + 模拟键盘输入的程序容易被启发式规则误报。这是**误报**——
程序不含任何网络代码。可以加入杀软白名单，或直接使用源码自行运行。

**Q：按 F9 没反应 / 打不进字？**
A：按顺序检查：① 目标输入框是否真的处于光标激活状态（先点一下）；② 倒计时是否结束；
③ 是否有输入法处于"中文候选"状态（建议切到英文或直接关闭输入法）；④ 权限较高的窗口
（以管理员身份运行的程序）需要用管理员身份运行本程序。

**Q：输入速度多快合适？**
A：默认 10 毫秒/字很快，一般不会触发异常；如果目标网页有输入频率检测或卡顿，调慢到
50–120 毫秒/字更稳妥。

**Q：设置存在哪？想恢复默认？**
A：`%APPDATA%\PakLua\AutoInput\settings.json`，删除该文件即恢复默认设置。

## 更新日志

### v1.0.0

- 首个正式版本
- 全新界面：圆角卡片、自定义按钮 / 开关 / 分段控件、倒计时圆环与进度条
- 速度预设 + 精细调节，实时字数 / 预计耗时统计
- 文本整理：去 Markdown、删空行、适配自动编号编辑器
- 高 DPI 感知，高分屏不模糊
- 设置自动记忆、文本导入导出、可折叠日志

## 文件校验（SHA256）

下载后可用下面的命令校验文件完整性：

```powershell
Get-FileHash .\逐字自动输入_v1.0.0.exe -Algorithm SHA256
```

每个 Release 都附带 `SHA256.txt`，里面是**当次构建产物**的校验值（PyInstaller 的产物不是逐字节可复现的，
换一台机器/换一次构建哈希就会变，所以不要照抄本文档里的数字，**以 Release 附件为准**）：

```powershell
# 下载 Release 里的 SHA256.txt 后，在本目录执行：
Get-FileHash .\逐字自动输入_v1.0.0.exe -Algorithm SHA256
# 比对 SHA256.txt 中对应行的值
```

---

如有问题或建议，欢迎反馈给我。

---

# 开发者部分

## 目录结构

```
.
├─ src/逐字自动输入.py         主程序（单文件，仅用 Python 标准库）
├─ assets/app.ico              图标
├─ assets/version_info.txt     exe 文件属性（版本/作者/版权）
├─ assets/界面截图.png          界面截图
├─ build.ps1                   一键打包脚本（单文件版 + 便携版 + SHA256）
└─ .github/workflows/release.yml   推 tag 自动构建并发布 Release
```

## 从源码运行

```powershell
python src\逐字自动输入.py
```

需要 Python 3.10+（tkinter 随官方 Python 一起安装，无需额外依赖）。

## 自己打包

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

脚本会自动：读取源码里的版本号 → 安装 PyInstaller → 打包单文件版和便携版 →
生成 `dist/SHA256.txt`。产物全部在 `dist/` 目录。

> 注意：PyInstaller 每次打包的二进制并非逐字节可复现，**重新打包后哈希会变**，
> 发布时请以当次 `dist/SHA256.txt` 为准。

> 提示：`build.ps1` 含中文，已保存为 **UTF-8 with BOM**。用编辑器改过之后请保持该编码，
> 否则 Windows PowerShell 5.1 会把中文读成乱码并报语法错误（用 PowerShell 7 / pwsh 则无此限制）。

## 发布新版本

1. 修改 `src/逐字自动输入.py` 里的 `APP_VERSION`
2. 同步更新本 README 的更新日志与校验值
3. 提交并打 tag：

   ```powershell
   git add -A
   git commit -m "release: v1.0.1"
   git tag v1.0.1
   git push origin main --tags
   ```

4. GitHub Actions 会自动打包并把 exe / zip / 源码 / SHA256 上传到对应 Release

## 开机自启（可选）

把便携版的快捷方式放到下面这个目录即可：

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

## 已知限制

- 只能往"当前有焦点的窗口"输入，程序不读屏、不操作其他进程
- 目标程序若以管理员权限运行，本程序也需要以管理员身份运行
- 中文输入法处于候选状态时可能干扰输入，建议切换到英文输入法

## CI 常见坑（都踩过，记录下来省事）

### 1. PyInstaller 的 `--specpath` 会改变相对路径的基准 ⭐

**症状**：Actions 里打包失败，日志末尾是 `Compress-Archive: The path 'dist/xxx_便携版' does not exist`。

**原因**：一旦指定 `--specpath build`，`--add-data` / `--icon` / `--version-file` 里的**相对路径**
会被解析成"相对于 spec 目录"，于是 PyInstaller 去找 `build/assets/app.ico` 而不是 `assets/app.ico`，
找不到资源就退出（非 0），`dist` 里自然没有产物；报错却出现在后面的压缩步骤，很容易看错方向。

**正确写法**：这些参数一律用**绝对路径**（workflow 里用 `$env:GITHUB_WORKSPACE` 拼）：

```powershell
$root  = $env:GITHUB_WORKSPACE
$icon  = Join-Path $root "assets/app.ico"
$vfile = Join-Path $root "assets/version_info.txt"
$src   = Join-Path $root "src/逐字自动输入.py"

python -m PyInstaller --noconfirm --clean --windowed `
  --icon $icon --add-data "$icon;." --version-file $vfile `
  --onefile --name "AutoInput" `
  --distpath "$root/dist" --workpath "$root/build" --specpath "$root/build" $src
```

### 2. 构建阶段尽量别让中文参与"生成文件名"

构建时用 ASCII 名字（`AutoInput` / `AutoInputPortable`），**打包完成后再用 `Move-Item` 改成中文名**。
这样即使 runner 的语言环境、控制台编码不同，也不会出现"目录名对不上"的问题。

### 3. PowerShell 脚本要存成 UTF-8 with BOM

`build.ps1` 含中文，如果保存成 **UTF-8 无 BOM**，Windows PowerShell 5.1 会按 GBK 读取 → 中文变乱码 →
语法错误（`The string is missing the terminator`）。用 PowerShell 7（pwsh）则没有这个问题。

### 4. Actions 里要"失败即停"

PowerShell 默认**不会**因为原生命令返回非 0 就中断，所以要显式检查：

```powershell
python -m PyInstaller ... ; if ($LASTEXITCODE -ne 0) { throw "打包失败 (exit $LASTEXITCODE)" }
```

并在压缩前打印目录内容，出问题时日志里能直接看到实际产物：

```powershell
Get-ChildItem -LiteralPath $dist | Select-Object Name, Length | Format-Table
```

### 5. GitHub 直连不稳时给 git 挂代理

如果 `git push` 报 `Recv failure: Connection was reset`，给 GitHub 单独配代理（不影响其它站点）：

```powershell
git config --global http.https://github.com/.proxy http://127.0.0.1:7890
```

取消：

```powershell
git config --global --unset http.https://github.com/.proxy
```

### 6. 重新打 tag 让 CI 用新代码重跑

改了 workflow 之后，旧 tag 指向的还是旧提交，需要把 tag 挪到新提交再推：

```powershell
git push --delete origin v1.0.0   # 删远程 tag
git tag -d v1.0.0                 # 删本地 tag
git tag v1.0.0                    # 指向当前 HEAD
git push origin v1.0.0            # 重新触发构建
```

### 7. GitHub Release 附件名不能含中文 ⭐

**症状**：Release 里的附件变成 `_v1.0.0.exe`、`_._v1.0.0.py` 这种残缺名字。

**原因**：GitHub 服务端会**静默丢弃附件名中的非 ASCII 字符**（实测上传
`中文名测试_测试.txt`，GitHub 返回的名字是 `_.txt`）。这与 `.gitignore`、CI 配置都无关，
是平台限制；本地文件名正常，只是上传后被改写。

**做法**：发布附件一律用英文名（`AutoInput_v1.0.0.exe` 等），中文名放在
Release 标题、描述和程序界面里；`SHA256.txt` 里的名字也要跟着用英文名，避免校验时对不上。
