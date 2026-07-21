# 飞书向导截图维护

## 步骤与资源

- 步骤 1：`1.png`
- 步骤 2：`2-1.png`、`2-2.png`
- 步骤 3：`3-1.png`、`3-2.png`
- 步骤 4：`4-1.png`、`4-2.png`、`4-3.png`
- 步骤 5：`5-1.png`、`5-2.png`（版本管理与发布）
- 步骤 6：`6-1.png`、`6-2.png`、`6-3.png`、`6-4.png`（新建多维表格，最后一张为创建后的空白表格）
- 步骤 7：`7-1.png`、`7-2.png`、`7-3.png`（添加文档应用并设为可管理）
- 步骤 8：`8.png`（复制 Base 链接）
- 步骤 9：创建工作台并同步，不需要操作截图

资源清单是 `screenshot-manifest.json`。前端静态资源必须与清单同名，图片 alt 文本应来自清单的 `altText`，并与截图当前内容一致。

## 标注脚本

Pillow 只用于文档资源处理，不是 JobPicky 运行依赖：

```powershell
python -m pip install Pillow
python scripts/annotate_feishu_guide.py --placeholders
python scripts/annotate_feishu_guide.py
```

默认从 `docs/feishu-guide/raw/` 读取原图，输出到包内静态资源目录。清单中的坐标采用 `[x, y, width, height]` 归一化比例；`annotations` 支持红色圆角框、编号和可选 `arrow`，`redactions` 支持 `cover` 与 `blur`。凭据、token 和身份信息优先使用不可恢复的 `cover`，不要只用轻度模糊。

## 更新时间与检查周期

手动截图替换日期：2026-07-21。正式截图应在飞书开放平台或多维表格出现明显导航、权限名称、文档应用入口变化时更新；版本发布前至少抽查步骤 1、4、6、7、8。

飞书 UI 变化检查清单：

- 开放平台入口仍为 `https://open.feishu.cn/app`；
- 创建企业自建应用、凭证与基础信息、权限管理入口仍可定位；
- 当前代码调用的最小权限仍为 `bitable:app`；
- 添加文档应用与“可管理”权限入口仍存在；
- `/base/` 链接仍可直接解析；
- 向导文字、编号、alt 与新截图一致；
- 18 张资源均能在离线页面加载和放大。

敏感信息审查清单：

- 企业名称、姓名、头像、手机号、邮箱、文件名已移除；
- App ID、App Secret、tenant token、Base token 已实色遮盖或替换；
- 表格内容不含真实岗位、备注或个人求职状态；
- 最终图片元数据不包含敏感路径或账号信息；
- `raw/` 原图、Cookie、浏览器 storage state 和本地数据库未被 Git 跟踪；
- 处理后的截图在 100% 缩放下逐张目视复核。
