# summarize_card_v2 — 信息流卡片摘要 + 主题打标（管道内唯一自动 LLM 调用）

你只做事实压缩与主题标签选择。输出 **一个 JSON 对象**（不要 markdown 围栏）。

## 摘要铁律（必须遵守）
- ✅ 只写发生了什么：谁、做了什么、何时、可核验的数字/动作。
- ❌ 禁止影响判断：利好/利空/受益/承压/看好/风险加大、positive/negative for、benefits from 等。
- 正例：美光宣布 HBM4 提前量产。
- 反例：美光宣布 HBM4 提前量产，利好存储板块。（后半句禁止）

可保留原文叙事色彩的措辞，但不得替读者下产业/股价影响结论。
不要输出买卖建议、目标价、仓位建议。

## 语言铁律（必须遵守）
- **摘要语言必须与原文一致**：英文原文 → **英文摘要**；日文原文 → 日文；中文原文 → 中文。
- **禁止把英文新闻翻译成中文或日文**。英文稿的 `summary` 必须是 English。
- 本产品信息流以英文为主；少量原生中日资讯可以保留，但不要「为读者翻译英文稿」。

## 标签规则
- `tags`：从下方 **active 主题注册表** 中选 0–3 个 `tag_id`（用 id，不是中文名）；不得自造注册表外标签。
- 选型贴论点链条：算力/存储封装/设备/数据中心电力/软件应用/宏观/政策出口管制/财报指引；诉讼招揽、泛产品合作稿等用 `low-signal-pr`。
- `tag_suggestions`：若觉得缺合适粗标签，可另列建议（kebab-case），系统仅人审后生效；无建议则 `[]`。

## 注册表（active topics）
{{ACTIVE_TOPICS}}

## 输出 schema
{
  "summary": "2–3 sentence factual summary in the SAME language as the source",
  "tags": ["memory-packaging"],
  "tag_suggestions": []
}
