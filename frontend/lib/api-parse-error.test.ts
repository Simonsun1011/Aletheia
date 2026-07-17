/**
 * Slice 11 A1 — parseError 只读扁平 envelope，不把整坨 JSON 丢给 toast。
 * 运行：node --experimental-strip-types --test frontend/lib/api-parse-error.test.ts
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseError } from "./api.ts";

function fakeRes(body: unknown, statusText = "Error"): Response {
  return {
    statusText,
    json: async () => body,
  } as Response;
}

describe("parseError", () => {
  it("reads flat contract envelope", async () => {
    const msg = await parseError(
      fakeRes({
        error: { code: "NOT_FOUND", message: "feed card missing", detail: {} },
      })
    );
    assert.equal(msg, "[NOT_FOUND] feed card missing");
  });

  it("does not stringify nested detail blobs into toast text", async () => {
    const msg = await parseError(
      fakeRes({
        detail: {
          error: { code: "NOT_FOUND", message: "nested", detail: {} },
        },
      })
    );
    assert.equal(msg, "Error");
    assert.ok(!msg.includes("{"));
    assert.ok(!msg.includes("NOT_FOUND"));
  });
});
