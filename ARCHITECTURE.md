# ARCHITECTURE.md — all-platforms-all-models-check

设计契约。opencode 生成代码时,类/方法签名、数据流必须与本文一一对应。

## 一、目录结构

```
all-platforms-all-models-check/
├── AGENTS.md              # 开发规矩(已定)
├── ARCHITECTURE.md        # 本文件
├── README.md              # 运行说明(opencode 补)
├── src/
│   ├── base_adapter.py     # 抽象基类(公共逻辑)
│   ├── protocol_openai.py  # OpenAI 兼容协议子类
│   ├── protocol_anthropic.py # Anthropic 协议子类
│   ├── generic_adapter.py  # 通用平台适配器(读 config 实例化)
│   ├── scheduler.py        # 多平台并发调度
│   ├── collector.py        # 步骤① 采集
│   ├── tester.py           # 步骤② 测试
│   ├── reporter.py         # 步骤③ 单平台汇报
│   ├── aggregator.py       # 步骤④ 全平台汇总
│   ├── diff.py             # 步骤⑤ 差异对比
│   ├── config_loader.py    # config 加载 + schema 校验
│   └── main.py             # CLI 入口(argparse 编排)
├── config/
│   └── platforms.yaml      # 平台差异点声明(enable/proxy/protocols/base_url/... )
├── results/                # 产物(不入库)
└── tests/                  # 自测
```

## 二、类图

```
AbstractBaseAdapter (ABC)
  ├── 公共(已实现): _http_client, _request(), _inject_proxy(), _with_timeout(),
  │                  _retry(), _parse_response(), _save_result(), concurrency 属性
  ├── 抽象(子类实现): collect_models(), _build_url(), _build_payload(),
  │                  _parse_ok(), _extract_error()
  └── 协议回退: test_model(model_id) -> 按 self.protocols 顺序尝试, 单模型粒度

OpenAICompatAdapter(AbstractBaseAdapter)
  └── 实现: _build_url(/chat/completions 兼容 /v1 结尾或不结尾),
            _build_payload({model,messages}), _parse_ok(choices[0].message.content),
            _extract_error(code/message)

AnthropicAdapter(AbstractBaseAdapter)
  └── 实现: _build_url(/v1/messages), header anthropic-version,
            _build_payload({model,max_tokens,messages}), _parse_ok(content[0].text),
            错误兼容 str/dict

GenericPlatformAdapter(OpenAICompatAdapter 或 AnthropicAdapter)
  └── __init__(config: dict): 从 config 读 base_url/api_key_format/proxy/concurrency/
            model_filters/protocols/fallback_triggers, 运行时装配, 不写平台专属逻辑
```

## 三、接口契约(签名)

```python
# base_adapter.py
class AbstractBaseAdapter(ABC):
    def __init__(self, name: str, concurrency: int = 8, proxy: str | None = None,
                 timeout: int = 30, retry: int = 1): ...
    @abstractmethod
    def collect_models(self) -> list[str]: ...
    @abstractmethod
    def _build_url(self) -> str: ...
    @abstractmethod
    def _build_payload(self, model_id: str) -> dict: ...
    @abstractmethod
    def _parse_ok(self, resp: dict) -> str | None: ...
    @abstractmethod
    def _extract_error(self, resp: dict) -> tuple[str, str]: ...
    def test_model(self, model_id: str) -> dict:  # 含协议回退, 返回 {model,status,http_code,response,elapsed}
    def should_skip(self, model_id: str) -> bool:  # 按 model_filters 正则

# scheduler.py
class Scheduler:
    def __init__(self, adapters: list[AbstractBaseAdapter]): ...
    def run_parallel(self) -> dict[str, list[dict]]:  # 线程池同时跑多平台

# config_loader.py
def load_platforms(path: str) -> list[dict]:  # 校验 schema, 过滤 enabled
def validate_schema(cfg: dict) -> None:  # 缺必填字段即抛错并指名平台
```

## 四、数据流

```
config/platforms.yaml
   │ (config_loader 过滤 enabled)
   ▼
Scheduler 实例化各 GenericPlatformAdapter(带各自 concurrency/proxy/protocols)
   │ 步骤① collector.collect_models() → results/<platform>_models.json
   │ 步骤② tester.test_model() 并发 → results/<platform>.json (all_results/ok/fail)
   │ 步骤③ reporter → results/<platform>_report.md
   │ 步骤④ aggregator → results/summary.json
   │ 步骤⑤ diff vs results/baseline.json → 差异报告; 写回 baseline
```

## 五、config schema (platforms.yaml)

每平台一段,字段:
- `name` (str, 必填)
- `enabled` (bool, 必填)
- `protocols` (list[str], 必填, 如 ["openai"] 或 ["openai","anthropic"])
- `base_url` (str, 必填, 支持模板变量)
- `auth` (dict, 必填): `key_index` / `key_split`(如 tab_split_first) 等提取规则
- `proxy` (str|null, 必填: 代理 URL 或 null 直连)
- `concurrency` (int, 必填)
- `model_filters` (list[str] 正则, 可选: 跳过非 chat 模型)
- `fallback_triggers` (list[str] 错误码/消息, 可选: 自定义回退触发)

## 六、参数化 (main.py argparse)

- `--platform X` (可多次): 只跑指定平台
- `--platform X --model Y`: 只跑 X 的 Y
- `--model Y`: 跨平台按采集索引找 Y 所属平台, 单独测
- 默认: 全平台全模型
- `--no-diff`: 跳过差异步骤
