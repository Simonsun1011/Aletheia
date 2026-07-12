"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { TopNav, Card, Stat, Empty, Skeleton } from "@/components/ui";
import { toast } from "@/components/toast";
import { num } from "@/lib/format";

type Bucket = {
  bucket: string;
  n: number;
  hit_rate: number | null;
};

type Calibration = {
  jtype: string | null;
  n: number;
  hits: number;
  hit_rate: number | null;
  confidence_buckets: Bucket[];
  warning?: string;
};

function ratePct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

const JTYPES = ["", "action", "market_reaction", "causal", "fact"];
const SMALL_N = 20;

export default function CalibrationPage() {
  const [jtype, setJtype] = useState("");
  const [data, setData] = useState<Calibration | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (jt: string) => {
    setLoading(true);
    try {
      const q = jt ? `?jtype=${encodeURIComponent(jt)}` : "";
      const body = await apiGet<Calibration>(`/reviews/calibration${q}`);
      setData(body);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh(jtype);
  }, [jtype, refresh]);

  const smallSample = !!data && data.n < SMALL_N;

  return (
    <main>
      <TopNav />
      <h1>校准</h1>
      <p className="page-intro">
        按判断类型统计命中率与置信度分桶（仅已复盘链条）。服务端只算数字，不作评价性文案。
      </p>

      <div className="inline-form">
        <div className="inline-field">
          <label htmlFor="jt">判断类型</label>
          <select id="jt" value={jtype} onChange={(e) => setJtype(e.target.value)}>
            {JTYPES.map((j) => (
              <option key={j || "all"} value={j}>
                {j || "全部"}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading && !data ? (
        <Card title="汇总">
          <Skeleton lines={3} />
        </Card>
      ) : (
        data && (
          <>
            <Card title="汇总">
              {smallSample && (
                <div className="note-warn">
                  样本量 N={data.n}（&lt;{SMALL_N}）——统计意义有限，仅供参考。
                </div>
              )}
              <div className="stat-grid">
                <Stat
                  value={num(data.n)}
                  label="样本量 N"
                  tone={smallSample ? "warn" : undefined}
                />
                <Stat value={num(data.hits)} label="命中数" />
                <Stat value={ratePct(data.hit_rate)} label="命中率" />
              </div>
            </Card>

            <Card title="置信度分桶">
              {data.confidence_buckets.length === 0 ? (
                <Empty>暂无分桶数据——复盘更多判断后在此显示。</Empty>
              ) : (
                <table className="numeric">
                  <thead>
                    <tr>
                      <th>分桶</th>
                      <th>N</th>
                      <th>命中率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.confidence_buckets.map((b) => (
                      <tr key={b.bucket} className={b.n < SMALL_N ? "warn-row" : undefined}>
                        <td style={{ textAlign: "left" }}>{b.bucket}</td>
                        <td>{num(b.n)}</td>
                        <td>{ratePct(b.hit_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="muted" style={{ marginTop: "var(--s3)" }}>
                黄底行表示该桶样本量 N&lt;{SMALL_N}，统计意义有限。
              </p>
            </Card>
          </>
        )
      )}
    </main>
  );
}
