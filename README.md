# Glados自动签到

## 2026-11 自动签到升级

脚本同步自 `Devilstore/Glados-Railgun-checkin` 的
`4d3e1e5baea76086c43d7c02c2401b5639d2d715`（2026-11-11）。
支持新版 challenge、设备平台匹配、域名探测及旧版 Cookie 配置。

- GitHub Actions 使用 Ubuntu 24.04 和 Python 3.13。
- 北京时间每天 09:18 自动运行一次；当天已签到属于正常结果。
- 默认达到 500 积分后兑换 100 天；不足时保留积分，不会使用现金购买套餐。
- 兑换只提交一次，网络结果不确定时不重放请求；成功后重新查询积分和剩余天数。
- 签到、配置或兑换失败会让任务变红；结果保存在每次运行的 Summary。
- Cookie 过期仍需重新登录并更新 `GLADOS_COOKIES`。脚本不会保存密码或自动重新登录。
- 保活步骤用于降低长期无仓库活动导致定时任务停用的风险，不删除运行记录。

`GLADOS_COOKIES` 推荐使用以下 JSON 数组格式。所有会话值只保存到 Actions Secret：

```json
[
  {
    "name": "主账号",
    "origin": "glados.one",
    "cookie": "gld:sess=...; gld:sess.sig=...",
    "user-agent": "提取 Cookie 时浏览器的完整 User-Agent"
  }
]
```

兼容原来的单 Cookie 和 `&` 分隔的多账号配置。不要将 Cookie 写入代码或提交到仓库。
`origin` 只接受脚本内置的 GLaDOS / Railgun 域名。

`GLADOS_EXCHANGE_PLAN` 可配置为 Secret 或 Repository Variable，Secret 优先；
支持 `plan100`、`plan200`、`plan500`，设置 `none` 关闭兑换。工作流未配置时使用
`plan500`；直接在本地运行脚本时，未配置则不兑换。
`PUSHDEER_SENDKEY` 和 `SERVERCHAN_SENDKEY` 为可选推送配置；没有配置时只记录 Actions 结果。

本地验证：

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## 食用方式：

### 注册一个GLaDOS的账号([注册地址](https://glados.space/landing/JJYJ2-8ZMY7-JRW8R-XFXHA))

#### 我的邀请码：([JJYJ2-8ZMY7-JRW8R-XFXHA](https://jjyj2-8zmy7-jrw8r-xfxha.glados.space))

### **Fork**本仓库

![图片加载失败](imgs/1.png)

### 添加**secret**

1. 跳转至自己的仓库的`Settings`->`Secrets and variables`->`Action`

2. 添加1个`repository secret`，命名为`GLADOS_COOKIES`，其值对应GLaDOS账号的cookie值中的有效部分（获取方式如下）

- 在GLaDOS的签到页面按`F12`

- 切换到`Network`页面下，刷新

![图片加载失败](imgs/2.png)

- 点击第一个选项卡后在`Request Headers`下找到`Cookie`，右键复制cookie的值即可

  > 参考格式：koa:sess=eyJ1c2xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxAwMH0=; koa:sess.sig=xJkOxxxxxxxxxxxxxxxtnM;

![图片加载失败](imgs/3.png)

- 多账号请在 `COOKIES` 中 添加多个 `cookies` 中间使用 `&`连接即可。（例如： `c1&c3&c3...`）

3. 配置积分兑换策略（非必须）

- 添加1个`repository secret`，命名为`GLADOS_EXCHANGE_PLAN`，配置自动兑换积分策略：

| 值 | 积分要求 | 兑换天数 |
|---|---------|---------|
| `plan100` | 100 积分 | 10 天 |
| `plan200` | 200 积分 | 30 天 |
| `plan500` | 500 积分 | 100 天 (默认) |

> 不配置时默认为 `plan500`，即积分达到 500 时自动兑换 100 天

4. 手机推送（非必须）

- 添加1个`repository secret`，命名为`PUSHDEER_SENDKEY`，其值对应 PushDeer key: ([获取地址](https://www.pushdeer.com/product.html))。

### 启用并验证 Actions

进入 `Actions` → `GLaDOS Check-in` → `Run workflow` 验证自动脚本。
此后由定时任务运行，无需给仓库点 Star。

![图片加载失败](imgs/4.png)

## 文件结构

```shell
│  checkin.py	# 签到脚本
│
├─.github
│  └─workflows
│          gladosCheck.yml	# Actions 配置文件
```

## 更新日志

- **2026-01**: 重构代码，添加log输出方便定位，支持新版网址，支持配置积分兑换策略。


## 问题排查与定位
- 大家可以通过查询 actions 中的 running checkin 日志快速定位问题，有其他问题提交issue。

  <img width="1684" height="844" alt="image" src="https://github.com/user-attachments/assets/45348a5f-43e4-45f5-8fdf-ce84d343b30d" />

## 声明

本项目不保证稳定运行与更新, 因GitHub相关规定可能会删库, 请注意备份








