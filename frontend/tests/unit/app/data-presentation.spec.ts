import { describe, expect, it } from "vitest";

import { formatIsoDateInTimeZone } from "../../../app/utils/formatData";
import {
  formatPercentChange,
  sumCompleteAnnualCounts,
} from "../../../app/utils/formatStats";

describe("public data presentation", () => {
  it("uses Philadelphia's calendar date for citation access dates", () => {
    expect(
      formatIsoDateInTimeZone(
        new Date("2026-08-17T02:30:00Z"),
        "America/New_York",
      ),
    ).toBe("2026-08-16");
  });

  it("uses grammatical comparison phrases for any percentage", () => {
    expect(formatPercentChange(18)).toBe("an increase of 18%");
    expect(formatPercentChange(-18)).toBe("a decrease of 18%");
    expect(formatPercentChange(0)).toBe("no change");
  });

  it("does not publish a partial all-years homicide total", () => {
    expect(sumCompleteAnnualCounts([10, 8])).toBe(18);
    expect(sumCompleteAnnualCounts([10, null])).toBeNull();
    expect(sumCompleteAnnualCounts([])).toBeNull();
  });
});
