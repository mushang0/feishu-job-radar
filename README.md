# Feishu Job Radar

本地运行的 WebUI 求职工具：扫描岗位、按偏好匹配，并可将推荐同步到飞书工作台。

## 启动

~~~powershell
uvx --python 3.12 feishu-job-radar
~~~

启动后浏览器会自动打开配置页面。首次配置只需选择招聘类型、岗位方向、城市和可选关键词。

你可以选择“开始本地使用”，不配置飞书也能扫描和查看岗位；也可以选择“连接飞书”，测试凭据后自动创建或修复“求职工作台”并同步推荐岗位。

用户数据默认保存在：

~~~text
%LOCALAPPDATA%\FeishuJobRadar\
~~~

源码安装、开发环境、测试、打包和发布流程见 [DEVELOPER.md](DEVELOPER.md)。

项目使用 MIT License。
