# AGENTS.md — all-platforms-all-models-check

项目级开发规矩。所有 coding agent(含 opencode)生成本项目代码前必须通读并严格遵守。

## 一、架构铁律(面向对象立体拆分,禁止平铺)

1. **立体拆分,禁止平铺重写**:复用逻辑必须抽成独立引用封装(抽象基类),不得将现有脚本平铺成几个独立 .py 文件交差。
2. **抽象基类 + 协议子类 + 通用平台适配器**:
   - `BaseAdapter`(抽象基类):封装所有公共逻辑——HTTP 客户端(线程安全)、代理注入(每实例 `proxy`)、超时(可配)、重试(可配)、响应解析分发(按协议)、结果结构、写 `results/<platform>.json`。**不含任何具体平台 URL/key**。
   - 协议子类:`OpenAICompatAdapter` / `AnthropicAdapter`,各自实现协议细节(URL 拼接、header、body、响应解析)。
   - 平台层:**通用 `GenericPlatformAdapter`**,从 config 读取该平台所有差异点实例化,**不为每个平台建独立 .py 子类**(配置驱动)。
3. **子类只实现差异点**:任何子类不得重复基类的 HTTP/代理/超时/重试/结果写入逻辑。
4. **配置驱动,代码不焊死**:平台差异点(base_url 模板、api_key 提取规则、protocols 顺序、concurrency、model_filters)全部进 `config/`,**新增/删除/修改平台 = 改 config,不写/不改任何 .py**。代码层不得出现平台名硬编码(agnes/groq/omniroute 等只能出现在 config 与测试 fixture)。

## 二、协议动态回退(非静态绑定)

5. 不预先把平台焊死到某协议类。`test_model()` 按平台 `protocols` 顺序尝试:先主协议,遇"协议不可达"类错误(404 路由错 / 连接错 / 平台自定义触发码)自动下一协议重试。
6. **回退按单模型粒度**,不污染同平台其他模型。回退顺序与触发条件在 config 声明,不焊死在类里。

## 三、并发在实例层

7. 每个平台/适配器实例可配独立 `concurrency`。
8. 调度器(`Scheduler`)用线程池**同时跑多平台**,各平台按自身 concurrency 并发测模型;一个平台崩溃不影响其他。

## 四、多步骤执行顺序

9. 程序按固定步骤编排:① 平台模型采集(collect)→ ② 独立平台模型测试(test)→ ③ 单平台结果汇报(report)→ ④ 全平台汇总(aggregate)→ ⑤ 差异对比(diff,首日建基线,之后报差异)。

## 五、参数化

10. 支持 `--platform X`(指定平台)、`--platform X --model Y`(指定平台+模型)、`--model Y`(跨平台按采集索引找所属平台,单独汇总测试汇报)。**默认全平台全模型**。

## 六、目录与产物

11. 源码 `src/`,配置 `config/`,结果 `results/`(独立分离,不混)。
12. 结果文件:`results/<platform>_models.json`(采集)、`results/<platform>.json`(测试,含 all_results/ok/fail)、`results/<platform>_report.md`(单平台汇报)、`results/summary.json`(全平台汇总)、`results/baseline.json`(差异基线)。

## 七、验收底线(生成的代码必须可验证)

- 新增平台零代码(只改 config)
- 协议回退对单模型生效
- 代码无平台名硬编码
- 真 key 实测可用数与基线一致(agnes 4/7、opencode 4/7、nara 4/50、zhipu 1/14、omniroute 并发 50+/1587 等)
