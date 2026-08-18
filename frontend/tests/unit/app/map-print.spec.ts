import { describe, expect, it } from "vitest";

import { createAggregateLegend } from "../../../app/utils/mapLegend";
import {
  createMapPrintDescription,
  createMapPrintImage,
  MAP_PRINT_PAGE_HEIGHT,
  MAP_PRINT_PAGE_WIDTH,
} from "../../../app/utils/mapPrint";

function parsePrintImage(source: string): SVGSVGElement {
  expect(source).toMatch(/^data:image\/svg\+xml;charset=utf-8,/);
  const svgSource = decodeURIComponent(source.slice(source.indexOf(",") + 1));
  const document = new DOMParser().parseFromString(svgSource, "image/svg+xml");
  expect(document.querySelector("parsererror")).toBeNull();
  return document.documentElement as unknown as SVGSVGElement;
}

function numericAttribute(element: Element, name: string, fallback = 0): number {
  const value = element.getAttribute(name);
  return value === null ? fallback : Number(value);
}

function expectSvgGeometryToStayOnPage(svg: SVGSVGElement): void {
  for (const element of svg.querySelectorAll("rect, image")) {
    const x = numericAttribute(element, "x");
    const y = numericAttribute(element, "y");
    const width = numericAttribute(element, "width");
    const height = numericAttribute(element, "height");
    expect(x, element.outerHTML).toBeGreaterThanOrEqual(0);
    expect(y, element.outerHTML).toBeGreaterThanOrEqual(0);
    expect(x + width, element.outerHTML).toBeLessThanOrEqual(
      MAP_PRINT_PAGE_WIDTH,
    );
    expect(y + height, element.outerHTML).toBeLessThanOrEqual(
      MAP_PRINT_PAGE_HEIGHT,
    );
  }

  for (const element of svg.querySelectorAll("line")) {
    for (const x of [
      numericAttribute(element, "x1"),
      numericAttribute(element, "x2"),
    ]) {
      expect(x, element.outerHTML).toBeGreaterThanOrEqual(0);
      expect(x, element.outerHTML).toBeLessThanOrEqual(MAP_PRINT_PAGE_WIDTH);
    }
    for (const y of [
      numericAttribute(element, "y1"),
      numericAttribute(element, "y2"),
    ]) {
      expect(y, element.outerHTML).toBeGreaterThanOrEqual(0);
      expect(y, element.outerHTML).toBeLessThanOrEqual(MAP_PRINT_PAGE_HEIGHT);
    }
  }

  for (const element of svg.querySelectorAll("circle")) {
    const cx = numericAttribute(element, "cx");
    const cy = numericAttribute(element, "cy");
    const radius = numericAttribute(element, "r");
    expect(cx - radius, element.outerHTML).toBeGreaterThanOrEqual(0);
    expect(cx + radius, element.outerHTML).toBeLessThanOrEqual(
      MAP_PRINT_PAGE_WIDTH,
    );
    expect(cy - radius, element.outerHTML).toBeGreaterThanOrEqual(0);
    expect(cy + radius, element.outerHTML).toBeLessThanOrEqual(
      MAP_PRINT_PAGE_HEIGHT,
    );
  }

  for (const element of svg.querySelectorAll("text")) {
    const x = numericAttribute(element, "x");
    const y = numericAttribute(element, "y");
    const fontSize = numericAttribute(element, "font-size");
    const approximateWidth = (element.textContent?.length ?? 0) * fontSize * 0.52;
    const anchor = element.getAttribute("text-anchor") ?? "start";
    const left =
      anchor === "end"
        ? x - approximateWidth
        : anchor === "middle"
          ? x - approximateWidth / 2
          : x;
    const right =
      anchor === "end"
        ? x
        : anchor === "middle"
          ? x + approximateWidth / 2
          : x + approximateWidth;
    expect(left, element.outerHTML).toBeGreaterThanOrEqual(0);
    expect(right, element.outerHTML).toBeLessThanOrEqual(
      MAP_PRINT_PAGE_WIDTH,
    );
    expect(y - fontSize, element.outerHTML).toBeGreaterThanOrEqual(0);
    expect(y, element.outerHTML).toBeLessThanOrEqual(MAP_PRINT_PAGE_HEIGHT);
  }
}

describe("map print image compositor", () => {
  it("bounds a tall phone map, long status, every legend, and full attribution on one fixed page", () => {
    const choropleth = createAggregateLegend(
      "choropleth",
      987,
      "police district",
    );
    const hotSpots = createAggregateLegend(
      "street-hot-spots",
      4_321,
      "street block",
    );
    expect(choropleth).not.toBeNull();
    expect(hotSpots).not.toBeNull();

    const status = Array.from(
      { length: 80 },
      (_, index) => `status-token-${index + 1}`,
    ).join(" ");
    const dataAttribution =
      "Shooting-victim records: Philadelphia Police Department via OpenDataPhilly.";
    const basemapAttribution =
      "Sources: Esri, HERE, Garmin, FAO, NOAA, USGS, © OpenStreetMap contributors, and the GIS User Community.";
    const options = {
      aggregateLegends: [choropleth!, hotSpots!],
      basemapAttribution,
      dataAttribution,
      fatalCount: 17_701,
      mapImage: "data:image/png;base64,tall-phone-map-390x844",
      nonfatalCount: 52_019,
      showHeatLegend: true,
      showPointLegend: true,
      status,
      title: "Philadelphia shooting-victim map — all available years",
    };
    const description = createMapPrintDescription(options);
    const source = createMapPrintImage(options);

    const svg = parsePrintImage(source);
    expect(svg.getAttribute("width")).toBe("1450");
    expect(svg.getAttribute("height")).toBe("1800");
    expect(svg.getAttribute("viewBox")).toBe("0 0 1450 1800");
    expect(svg.querySelector("title")?.textContent).toBe(
      "Philadelphia shooting-victim map — all available years",
    );
    expect(svg.querySelector("desc")?.textContent).toBe(description);
    expect(description).toContain(status);
    expect(description).toContain("Fatal: 17,701. Nonfatal: 52,019.");
    expect(description).toContain(choropleth!.accessibleLabel);
    expect(description).toContain(hotSpots!.accessibleLabel);
    expect(description).toContain(dataAttribution);
    expect(description).toContain(basemapAttribution);
    expect(svg.textContent).toContain("Fatal — 17,701");
    expect(svg.textContent).toContain("Nonfatal — 52,019");
    expect(svg.textContent).toContain(
      "Density: brighter areas indicate a greater concentration of mapped records.",
    );
    expect(svg.textContent).toContain("Shooting victims by police district");
    expect(svg.textContent).toContain("Shooting victims per street block");
    expect(svg.textContent).toContain(dataAttribution);
    expect(svg.textContent).toContain(basemapAttribution);
    expect(
      Array.from(svg.querySelectorAll("text"), (text) => text.textContent).some(
        (text) => text?.includes("No matching victims"),
      ),
    ).toBe(true);

    const statusLines = Array.from(svg.querySelectorAll("text")).filter(
      (element) => element.textContent?.includes("status-token-"),
    );
    expect(statusLines.length).toBeGreaterThan(2);
    expect(statusLines.map((line) => line.textContent).join(" ")).toBe(status);

    const map = svg.querySelector("image");
    expect(map).not.toBeNull();
    expect(map?.getAttribute("href")).toBe(
      "data:image/png;base64,tall-phone-map-390x844",
    );
    expect(map?.getAttribute("preserveAspectRatio")).toBe("xMidYMid meet");
    const targetWidth = numericAttribute(map!, "width");
    const targetHeight = numericAttribute(map!, "height");
    const containScale = Math.min(targetWidth / 390, targetHeight / 844);
    expect(390 * containScale).toBeLessThanOrEqual(targetWidth);
    expect(844 * containScale).toBeLessThanOrEqual(targetHeight);
    expect(390 * containScale).toBeLessThan(targetWidth);
    expect(844 * containScale).toBeCloseTo(targetHeight, 5);

    expectSvgGeometryToStayOnPage(svg);
  });

  it("rejects a non-PNG map source instead of creating a blank page", () => {
    expect(() =>
      createMapPrintImage({
        aggregateLegends: [],
        basemapAttribution: "Basemap source",
        dataAttribution: "Data source",
        fatalCount: 0,
        mapImage: "data:image/jpeg;base64,not-a-png",
        nonfatalCount: 0,
        showHeatLegend: false,
        showPointLegend: false,
        status: "No records",
        title: "Philadelphia shooting-victim map",
      }),
    ).toThrow("The map image must be a PNG data URL.");
  });
});
