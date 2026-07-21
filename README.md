# JobPicky

Your personalized job radar

懂你偏好的个性化岗位雷达：选择你的偏好，快速发现匹配岗位；飞书是可选的，连接后即可同步推荐。

## 启动

~~~powershell
uvx --python 3.12 jobpicky
~~~

启动后浏览器会自动打开配置页面；连接飞书后会自动创建或修复工作台并同步推荐。源码安装、开发环境、测试、打包和发布流程见 [DEVELOPER.md](DEVELOPER.md)。

## 可选的飞书集成

在 Web 页面打开“集成”，按八步图文向导连接飞书多维表格。你需要在[飞书开放平台](https://open.feishu.cn/app)创建企业自建应用，开通应用身份的“查看、评论、编辑和管理多维表格”（`bitable:app`），并把应用添加为目标 Base 的文档应用；若 Base 开启高级权限，还需授予“可管理”权限。

JobPicky 不需要飞书账号密码。不要把 App Secret 发到 Issue、日志或聊天中。断开连接只会停止后续同步，不会删除飞书工作台或已经同步的岗位；页面会让你单独确认是否清除本地凭据。表格同步与 Webhook 提醒是独立模块，本向导只配置表格同步。

截图采集、脱敏、替换和飞书 UI 变化后的维护方式见 [截图清单](docs/feishu-guide/SCREENSHOT_CHECKLIST.md) 与 [维护说明](docs/feishu-guide/MAINTENANCE.md)。
