import { describe, expect, it } from "vitest";

import {
  AGGREGATE_LEGEND_NOTE,
  AGGREGATE_ZERO_COLOR,
  AGGREGATE_ZERO_LABEL,
  boundaryMapColor,
  createAggregateLegend,
} from "../../../app/utils/mapLegend";

function serialized(value: unknown): string {
  return JSON.stringify(value);
}

describe("aggregate map legends", () => {
  it("uses a linear Reds scale and an explicit no-match class for boundaries", () => {
    const legend = createAggregateLegend(
      "choropleth",
      9,
      "police district",
    );

    expect(legend).not.toBeNull();
    expect(legend).toMatchObject({
      context: "police district",
      direction: "Darker red means more victims.",
      id: "choropleth",
      maximum: 9,
      minimum: 1,
      note: AGGREGATE_LEGEND_NOTE,
      scale: "linear",
      title: "Shooting victims by police district",
      zeroColor: AGGREGATE_ZERO_COLOR,
      zeroLabel: AGGREGATE_ZERO_LABEL,
    });
    expect(legend?.ticks).toEqual([
      { label: "1", position: 0, value: 1 },
      { label: "5", position: 0.5, value: 5 },
      { label: "9", position: 1, value: 9 },
    ]);
    expect(legend?.barStyle).toContain("rgb(255, 245, 240) 0%");
    expect(legend?.barStyle).toContain("rgb(103, 0, 13) 100%");
    expect(legend?.accessibleLabel).toContain("Linear scale from 1 to 9.");
    expect(legend?.accessibleLabel).toContain(
      "Gray means no matching victims.",
    );

    const paint = serialized(boundaryMapColor(legend!));
    expect(paint).toContain(serialized(AGGREGATE_ZERO_COLOR));
    expect(paint).toContain(serialized("rgb(255, 245, 240)"));
    expect(paint).toContain(serialized("rgb(103, 0, 13)"));
    expect(paint).not.toContain('"ln"');
  });

  it("uses a log Plasma scale for skewed street-block counts", () => {
    const legend = createAggregateLegend(
      "street-hot-spots",
      9,
      "street block",
    );

    expect(legend).not.toBeNull();
    expect(legend).toMatchObject({
      context: "street block",
      direction: "Brighter yellow means more victims.",
      id: "street-hot-spots",
      maximum: 9,
      minimum: 1,
      note: AGGREGATE_LEGEND_NOTE,
      scale: "log",
      title: "Shooting victims per street block",
      zeroColor: null,
      zeroLabel: null,
    });
    expect(legend?.ticks.map(({ label, value }) => ({ label, value }))).toEqual([
      { label: "1", value: 1 },
      { label: "3", value: 3 },
      { label: "9", value: 9 },
    ]);
    expect(legend?.ticks.map(({ position }) => position)).toEqual([
      0,
      expect.closeTo(0.5, 10),
      1,
    ]);
    expect(legend?.barStyle).toContain("#cc4778 0%");
    expect(legend?.barStyle).toContain("#f0f921 100%");
    expect(legend?.accessibleLabel).toContain("Logarithmic scale from 1 to 9.");
    expect(legend?.accessibleLabel).not.toContain("Gray");

    const paint = serialized(legend?.mapColor);
    expect(paint).toContain('"ln"');
    expect(paint).toContain(serialized("#cc4778"));
    expect(paint).toContain(serialized("#f0f921"));
  });

  it("positions rounded midpoint labels according to each scale", () => {
    const boundary = createAggregateLegend(
      "choropleth",
      3,
      "ZIP code",
    );
    const street = createAggregateLegend(
      "street-hot-spots",
      3,
      "street block",
    );

    expect(boundary?.ticks.map(({ label, position }) => ({ label, position })))
      .toEqual([
        { label: "1", position: 0 },
        { label: "2", position: 0.5 },
        { label: "3", position: 1 },
      ]);
    expect(street?.ticks.map(({ label }) => label)).toEqual(["1", "2", "3"]);
    expect(street?.ticks[1]?.position).toBeCloseTo(
      Math.log(2) / Math.log(3),
      10,
    );
  });

  it("collapses a single value to one centered tick and one honest color", () => {
    const boundary = createAggregateLegend(
      "choropleth",
      1,
      "neighborhood",
    );
    const street = createAggregateLegend(
      "street-hot-spots",
      1,
      "street block",
    );

    expect(boundary?.ticks).toEqual([{ label: "1", position: 0.5, value: 1 }]);
    expect(boundary?.mapColor).toBe("rgb(249, 105, 76)");
    expect(boundary?.barStyle).toBe("background: rgb(249, 105, 76);");
    expect(street?.ticks).toEqual([{ label: "1", position: 0.5, value: 1 }]);
    expect(street?.mapColor).toBe("#f89540");
    expect(street?.barStyle).toBe("background: #f89540;");
  });

  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY])(
    "omits a quantitative legend for invalid maximum %s",
    (maximum) => {
      expect(
        createAggregateLegend("choropleth", maximum, "police district"),
      ).toBeNull();
      expect(
        createAggregateLegend("street-hot-spots", maximum, "street block"),
      ).toBeNull();
    },
  );
});
