修改的文件
voice_llm_client.py — 核心改动
Change 1: 保守本地动作解析器

新增 check_simple_action_command(text, tracker=None) 函数
按 左臂/右臂 引用切分多动作片段，逐段解析
笛卡尔模式：臂 + 向?方向 + 数字 + 厘米 → move_cartesian JSON
关节模式：臂 + 关节N + (反转?)(旋转?) + 数字 + 度 → move_joint JSON
方向→轴→符号映射与 SYSTEM_PROMPT 严格一致
混合问答动作检测：解析残留文本 > 6 字 → MISS 走 LLM
所有命中 JSON 仍需经过 validate_and_fix_command()
Change 2: 短 TTL 健康/失败缓存 + HTTP Session 复用

check_ollama_available() — 5 秒 TTL 缓存，避免每次同步 HTTP GET
_is_service_failing() / _mark_service_failing() — 5 秒 TTL 失败缓存
Dify/Ollama 调用前检查失败缓存 → 快速返回 None（触发 fallback）
requests.Session() 单例复用 HTTP 连接池
voice_debug_tool.py
导入 check_simple_action_command
在 _process_text() 中，关键词检查后、LLM 调用前插入本地解析器
命中时设置 route="local_action", local_action_parser_hit=True
voice_qwen_llm.py
导入 check_simple_action_command
在 stop_and_recognize() 中，ROS 初始化后、健康检查前插入本地解析器
命中时跳过 Dify/Ollama，直接校验→发布
latency_metrics.py
LatencyTracker._meta 新增 local_action_parser_hit 默认字段
to_dict() 新增 local_action_parser_ms 耗时字段
测试结果
正例（命中本地 parser）5/5 ✅
样本	原延迟(p50)	现在	节省
左臂向上10厘米	2154ms	~0.2ms	2154ms
右臂向前5厘米	2154ms	~0.02ms	2154ms
左臂关节1旋转30度	2154ms	~0.01ms	2154ms
左臂关节3反转30度	2154ms	~0.02ms	2154ms
右臂向前5厘米左臂向上10厘米	2154ms	~0.02ms	2154ms
反例（MISS，继续走 Dify/Ollama）13/13 ✅
你是谁、介绍下自己、左臂旋转一圈、抬起左臂和右臂、和我握手、动动你的手掌、向上10厘米、左臂向上、帮我处理一下、你好、你是什么机器人然后右臂向上5厘米、先介绍一下自己再左臂向前5厘米

健康/失败缓存 ✅
健康检查 TTL 5s：首次调用查 Ollama，5s 内复用缓存
失败标记 TTL 5s：Dify/Ollama 失败后 5s 内快速返回
TTL 过期后自动重试