# tag_card_v1 — 信息流卡片独立主题打标

只根据标题与首段分类，不做摘要，不做影响判断。只输出一个 JSON 对象，不要 markdown 围栏。

`tags` 必须从下方 active 主题注册表选 0–3 个 tag_id。`tag_suggestions` 可列缺失的粗标签建议（kebab-case），无则为空数组。

## active 主题注册表
{{ACTIVE_TOPICS}}

## 输出
{"tags": ["memory-packaging"], "tag_suggestions": []}
