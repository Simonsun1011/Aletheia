/**
 * Slice 7 term-matching 验收（node:test + strip-types）。
 * 运行：node --experimental-strip-types --test frontend/lib/glossary-match.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  bilingualTitle,
  buildMatcher,
  findAllMatches,
} from "./glossary-match.ts";

/** 精简词典：覆盖任务书用例所需词条 */
const TERMS = [
  { term: "PE", aliases: ["市盈率"] },
  { term: "Forward PE", aliases: ["远期市盈率"] },
  { term: "EPS", aliases: ["每股收益"] },
  { term: "SEC", aliases: ["美国证监会"] },
  { term: "ASIC", aliases: [] },
  { term: "布林带", aliases: ["Bollinger Bands"] },
  { term: "动量", aliases: ["Momentum"] },
  { term: "HBM", aliases: [] },
  { term: "自由现金流", aliases: ["FCF", "Free Cash Flow"] },
  { term: "隐含波动率", aliases: ["Implied Volatility", "IV"] },
  { term: "VIX", aliases: ["波动率指数", "恐慌指数"] },
  { term: "GPU", aliases: [] },
  {
    term: "Fear & Greed Index",
    aliases: ["恐惧与贪婪指数", "恐慌贪婪指数"],
  },
];

const matcher = buildMatcher(TERMS);

function canons(text: string): string[] {
  return findAllMatches(matcher, text).map((h) => h.canonical);
}

function surfaces(text: string): string[] {
  return findAllMatches(matcher, text).map((h) => h.surface);
}

describe("glossary-match acceptance", () => {
  it("due to performance issues → 无 PE", () => {
    assert.deepEqual(canons("due to performance issues"), []);
  });

  it("wait a sec / second half → 无 SEC", () => {
    assert.deepEqual(canons("wait a sec"), []);
    assert.deepEqual(canons("second half"), []);
  });

  it("the PE ratio expanded → 命中 PE", () => {
    assert.deepEqual(canons("the PE ratio expanded"), ["PE"]);
  });

  it("市盈率处于高位 → 市盈率 surface，canonical=PE", () => {
    const hits = findAllMatches(matcher, "市盈率处于高位");
    assert.equal(hits.length, 1);
    assert.equal(hits[0].surface, "市盈率");
    assert.equal(hits[0].canonical, "PE");
  });

  it("EPS grew 20% → EPS；EPScore / eps lower → 无", () => {
    assert.deepEqual(canons("EPS grew 20%"), ["EPS"]);
    assert.deepEqual(canons("EPScore"), []);
    assert.deepEqual(canons("eps lower"), []);
  });

  it("a basic chip → 无 ASIC；Forward PE is high → Forward PE", () => {
    assert.deepEqual(canons("a basic chip"), []);
    assert.deepEqual(canons("Forward PE is high"), ["Forward PE"]);
    assert.deepEqual(surfaces("Forward PE is high"), ["Forward PE"]);
  });

  it("Bollinger Bands / momentum → 别名解析到中文 canonical", () => {
    assert.deepEqual(canons("Bollinger Bands squeeze"), ["布林带"]);
    assert.deepEqual(canons("strong momentum here"), ["动量"]);
  });

  it("中文/混排：布林带 / HBM", () => {
    assert.deepEqual(canons("布林带口收窄"), ["布林带"]);
    assert.deepEqual(canons("HBM供给紧张"), ["HBM"]);
  });

  it("FCF / IV → 别名解析", () => {
    assert.deepEqual(canons("FCF turned positive"), ["自由现金流"]);
    assert.deepEqual(canons("IV crush"), ["隐含波动率"]);
  });

  it("恐惧与贪婪指数 / Fear & Greed Index 互为别名", () => {
    assert.deepEqual(canons("Fear & Greed Index rose"), [
      "Fear & Greed Index",
    ]);
    assert.deepEqual(canons("恐惧与贪婪指数回落"), ["Fear & Greed Index"]);
  });

  it("双语标题：VIX · 波动率指数（有分隔符）", () => {
    const t = bilingualTitle("VIX", ["波动率指数", "恐慌指数"]);
    assert.equal(t.display, "VIX · 波动率指数");
    assert.notEqual(t.display, "VIX恐慌指数");
  });

  it("双语标题：布林带 · Bollinger Bands", () => {
    const t = bilingualTitle("布林带", ["Bollinger Bands"]);
    assert.equal(t.display, "布林带 · Bollinger Bands");
  });

  it("左词边界：FY27EPS / myVIX / 1GPU → 空（前缀粘连不得命中）", () => {
    assert.deepEqual(canons("FY27EPS"), []);
    assert.deepEqual(canons("myVIX"), []);
    assert.deepEqual(canons("1GPU"), []);
    assert.deepEqual(canons("Q1EPS guidance"), []);
    assert.deepEqual(canons("H100GPU demand"), []);
    // 对照：空格分隔仍命中
    assert.deepEqual(canons("the VIX spiked"), ["VIX"]);
    assert.deepEqual(canons("EPS beat"), ["EPS"]);
    assert.deepEqual(canons("GPU shortage"), ["GPU"]);
  });
});
