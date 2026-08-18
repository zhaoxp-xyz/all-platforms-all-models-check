# all-platforms-all-models-check

全平台全模型 LLM API 可用性检查工具。按平台采集模型列表 → 逐模型实测对话 → 生成单平台报告 + 全平台汇总 → 与基线做差异对比。

## 特性

- **配置驱动**:平台差异点(base_url / 协议 / 并发 / 代理 / key)全部进 `config/`,新增/删除平台 = 改配置,零代码改动。
- **立体拆分**:`AbstractBaseAdapter`(抽象基类)+ 协议子类(`OpenAICompatAdapter` / `AnthropicAdapter`)+ `GenericPlatformAdapter`(通用适配器,从配置实例化),无平铺重写、无平台名硬编码。
- **协议动态回退**:`test_model()` 按平台 `protocols` 顺序尝试,遇协议不可达类错误自动下一协议(单模型粒度)。
- **并发在实例层**:各平台独立 `concurrency`,调度器线程池同时跑多平台,一个平台崩溃不影响其他。
- **五步编排**:采集(collect)→ 测试(test)→ 报告(report)→ 汇总(aggregate)→ 差异对比(diff,首日建基线,之后报差异)。

## 依赖

- Python 3.9+
- `requests` + `PyYAML`(见 `requirements.txt`)

## 安装

```bash
git clone https://github.com/zhaoxp-xyz/all-platforms-all-models-check.git
cd all-platforms-all-models-check
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

平台配置在 `config/platforms.yaml`(已脱敏, `api_key` 为占位符 `REPLACE_WITH_YOUR_API_KEY`)。

**两种用法**:

1. **直接编辑 `config/platforms.yaml`**:把每个平台的 `api_key` 替换成你的真实 key。
2. **本地真 key 不入库**(推荐):复制为 `config/platforms.local.yaml`(已被 `.gitignore` 忽略),填入真实 key,程序优先读 `platforms.local.yaml`。

```bash
cp config/platforms.yaml config/platforms.local.yaml
# 编辑 config/platforms.local.yaml, 填入真实 api_key
```

配置字段说明(每个平台条目):

| 字段 | 说明 |
|---|---|
| `name` | 平台名(唯一, 用于结果文件名) |
| `enabled` | 是否启用(true/false) |
| `protocols` | 协议尝试顺序, 如 `[openai]` / `[anthropic, openai]` |
| `base_url` | API 基址(不含 `/v1`, 代码自动拼 `/v1/models` 与 `/v1/chat/completions`) |
| `auth.type` | 固定 `api_key` |
| `auth.api_key` | 真实 key(或占位符) |
| `proxy` | 代理 URL;内网平台填 `null` 直连,外网填 `http://192.168.31.81:8890` 等 |
| `concurrency` | 该平台并发数 |
| `model_filters` | 模型名正则白名单,空 `[]` = 测全部 |
| `fallback_triggers` | 触发协议回退的错误码,如 `["400","401","404"]` |
| `timeout` / `retry` | 单请求超时(秒)/ 重试次数 |

## 使用

```bash
# 全平台全模型(五步完整流程, 首日建 baseline)
python3 -m src.main

# 指定平台
python3 -m src.main --platform freellmapi-40

# 指定平台 + 模型
python3 -m src.main --platform freellmapi-40 --model agnes-2.0-flash

# 跳过差异对比(不更新 baseline)
python3 -m src.main --no-diff
```

## 结果产物(`results/`, 不入库)

- `<platform>_models.json` — 采集到的模型列表
- `<platform>.json` — 测试结果(all_results / ok / fail)
- `<platform>_report.md` — 单平台汇报
- `summary.json` — 全平台汇总
- `baseline.json` — 差异基线(首次运行自动建立)

## 架构

```
src/
  base_adapter.py        # AbstractBaseAdapter: HTTP/代理/超时/重试/解析/结果写入
  protocol_openai.py     # OpenAICompatAdapter
  protocol_anthropic.py  # AnthropicAdapter
  generic_adapter.py     # GenericPlatformAdapter: 从 config 实例化, 不焊死平台
  config_loader.py       # 加载 config/platforms.yaml (顶层 list)
  collector.py           # Step1 采集
  tester.py              # Step2 测试
  reporter.py            # Step3 单平台报告
  scheduler.py           # 线程池多平台并发编排
  aggregator.py          # Step4 汇总
  diff.py                # Step5 差异对比(基线)
  main.py                # CLI 入口
```

开发契约见 `AGENTS.md`(立体拆分 / 配置驱动 / 协议回退)与 `ARCHITECTURE.md`(类图与签名)。

## 部署(作为每日巡检)

本项目可作为每日平台可用性巡检的运行体。示例 systemd timer / cron:

```cron
# 每日 04:30 全量检查
30 4 * * * cd /path/to/all-platforms-all-models-check && /path/to/.venv/bin/python -m src.main >> /var/log/apamc.log 2>&1
```

注意:外网平台需在能出网的机器上运行,或配置 `proxy` 指向可用代理(如 `http://192.168.31.81:8890`)。
