import { expect, test, type Locator, type Page } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

async function openDashboard(page: Page): Promise<Locator> {
  await mockNuxtExternalServices(page);
  await page.goto("./");

  const explorer = page.locator(".civic-dashboard-browser-explorer");
  await expect(explorer).toHaveAttribute("aria-busy", "false");
  await expect(page.locator(".maplibregl-canvas")).toHaveAttribute(
    "aria-label",
    /shooting-victim locations/,
  );

  const sidebar = page.getByRole("complementary", {
    name: "Map filters and controls",
  });
  await expect(sidebar).toBeVisible();
  return sidebar;
}

async function keyboardFocus(page: Page, locator: Locator) {
  // Chromium applies :focus-visible to script-focused controls when the latest
  // input modality was the keyboard. This avoids coupling the test to the full
  // MapLibre/sidebar tab order while still exercising the keyboard-only style.
  await page.keyboard.press("Tab");
  await locator.focus();
  await expect(locator).toBeFocused();
  await expect
    .poll(() =>
      locator.evaluate((element) => element.matches(":focus-visible")),
    )
    .toBe(true);
}

async function focusPaint(locator: Locator) {
  return locator.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      boxShadow: style.boxShadow,
      color: style.outlineColor,
      offset: Number.parseFloat(style.outlineOffset) || 0,
      style: style.outlineStyle,
      width: Number.parseFloat(style.outlineWidth) || 0,
    };
  });
}

test("expanded checkbox and range filters retain readable insets and density", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  const panels = sidebar.locator("details.civic-disclosure-panel");
  await expect(panels).toHaveCount(6);

  for (const index of [0, 1, 2]) {
    const panel = panels.nth(index);
    await panel.locator("summary").click();

    const layout = await panel.evaluate((element) => {
      const panelRect = element.getBoundingClientRect();
      const fieldset = element.querySelector("fieldset");
      const rows = Array.from(element.querySelectorAll("li"));
      const labels = Array.from(
        element.querySelectorAll<HTMLElement>(".usa-checkbox__label"),
      );
      if (!fieldset || rows.length === 0 || labels.length === 0) return null;

      const fieldsetStyle = getComputedStyle(fieldset);
      const rowRects = rows.map((row) => row.getBoundingClientRect());
      return {
        bottomInset: panelRect.bottom - rowRects.at(-1)!.bottom,
        labelFontSizes: labels.map((label) =>
          Number.parseFloat(getComputedStyle(label).fontSize),
        ),
        leftInset: Math.min(
          ...rowRects.map((rect) => rect.left - panelRect.left),
        ),
        padding: {
          bottom: Number.parseFloat(fieldsetStyle.paddingBottom),
          left: Number.parseFloat(fieldsetStyle.paddingLeft),
          right: Number.parseFloat(fieldsetStyle.paddingRight),
          top: Number.parseFloat(fieldsetStyle.paddingTop),
        },
        rightInset: Math.min(
          ...rowRects.map((rect) => panelRect.right - rect.right),
        ),
        rowHeights: rowRects.map((rect) => rect.height),
        topInset:
          rowRects[0].top -
          element.querySelector("summary")!.getBoundingClientRect().bottom,
      };
    });

    expect(layout).not.toBeNull();
    if (!layout) continue;

    expect(layout.padding.left).toBeGreaterThanOrEqual(16);
    expect(layout.padding.right).toBeGreaterThanOrEqual(16);
    expect(layout.padding.top).toBeGreaterThanOrEqual(8);
    expect(layout.padding.bottom).toBeGreaterThanOrEqual(12);
    expect(layout.leftInset).toBeGreaterThanOrEqual(16);
    expect(layout.rightInset).toBeGreaterThanOrEqual(16);
    expect(layout.topInset).toBeGreaterThanOrEqual(8);
    expect(layout.bottomInset).toBeGreaterThanOrEqual(12);
    expect(Math.min(...layout.rowHeights)).toBeGreaterThanOrEqual(30);
    expect(Math.min(...layout.labelFontSizes)).toBeGreaterThanOrEqual(15);
  }

  for (const index of [3, 4, 5]) {
    const panel = panels.nth(index);
    await panel.locator("summary").click();

    const layout = await panel.evaluate((element) => {
      const panelRect = element.getBoundingClientRect();
      const summaryRect = element
        .querySelector("summary")!
        .getBoundingClientRect();
      const fieldset = element.querySelector("fieldset")!;
      const fieldsetStyle = getComputedStyle(fieldset);
      const histogramRect = element
        .querySelector(".civic-dashboard-range-filter__histogram")!
        .getBoundingClientRect();
      const limits = Array.from(
        element.querySelectorAll<HTMLElement>(
          ".civic-dashboard-range-filter__limit",
        ),
      );
      const rangeRect = element
        .querySelector(".civic-dashboard-range-filter__dual-range")!
        .getBoundingClientRect();
      const trackRect = element
        .querySelector(".civic-dashboard-range-filter__dual-track")!
        .getBoundingClientRect();
      const labels = Array.from(
        element.querySelectorAll<HTMLElement>(
          ".civic-dashboard-range-filter__thumb-label",
        ),
      );
      const labelRects = labels.map((label) => label.getBoundingClientRect());

      return {
        gapAfterHistogram: rangeRect.top - histogramRect.bottom,
        histogramHeight: histogramRect.height,
        labelCenters: labelRects.map((rect) => rect.left + rect.width / 2),
        labelWeights: labels.map((label) =>
          Number.parseInt(getComputedStyle(label).fontWeight, 10),
        ),
        leftInset: histogramRect.left - panelRect.left,
        limitColors: limits.map(
          (limit) => getComputedStyle(limit).backgroundColor,
        ),
        limitWidths: limits.map(
          (limit) => limit.getBoundingClientRect().width,
        ),
        limitCenters: limits.map((limit) => {
          const rect = limit.getBoundingClientRect();
          return rect.left + rect.width / 2;
        }),
        padding: {
          bottom: Number.parseFloat(fieldsetStyle.paddingBottom),
          left: Number.parseFloat(fieldsetStyle.paddingLeft),
          right: Number.parseFloat(fieldsetStyle.paddingRight),
          top: Number.parseFloat(fieldsetStyle.paddingTop),
        },
        rightInset: panelRect.right - histogramRect.right,
        trackEndpoints: [trackRect.left, trackRect.right],
        topInset: histogramRect.top - summaryRect.bottom,
      };
    });

    expect(layout.padding.left).toBeGreaterThanOrEqual(16);
    expect(layout.padding.right).toBeGreaterThanOrEqual(16);
    expect(layout.padding.top).toBeGreaterThanOrEqual(12);
    expect(layout.padding.bottom).toBeGreaterThanOrEqual(12);
    expect(layout.leftInset).toBeGreaterThanOrEqual(16);
    expect(layout.rightInset).toBeGreaterThanOrEqual(16);
    expect(layout.topInset).toBeGreaterThanOrEqual(12);
    expect(layout.histogramHeight).toBeGreaterThanOrEqual(56);
    expect(layout.gapAfterHistogram).toBeGreaterThanOrEqual(8);
    expect(layout.limitWidths).toEqual([2, 2]);
    expect(layout.limitColors).toEqual([
      "rgb(255, 255, 255)",
      "rgb(255, 255, 255)",
    ]);
    expect(layout.limitCenters[0]).toBeCloseTo(
      layout.trackEndpoints[0] - 4,
      0,
    );
    expect(layout.limitCenters[1]).toBeCloseTo(
      layout.trackEndpoints[1] + 4,
      0,
    );
    expect(layout.labelCenters[0]).toBeCloseTo(layout.trackEndpoints[0], 1);
    expect(layout.labelCenters[1]).toBeCloseTo(layout.trackEndpoints[1], 1);
    expect(layout.labelWeights).toEqual([400, 400]);
  }
});

test("filter checkboxes use the production surface without a contextual reset", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  const mapLayers = sidebar.getByRole("group", { name: "Map layers" });
  const heatMap = mapLayers.getByRole("checkbox", { name: "Heat map" });

  const panels = sidebar.locator("details.civic-disclosure-panel");
  await panels.last().locator("summary").click();
  const excludeUnknown = panels
    .last()
    .getByRole("checkbox", { name: "Exclude unknown values" });

  for (const checkbox of [heatMap, excludeUnknown]) {
    const surface = await checkbox.evaluate((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const control = element.closest(".civic-checkbox-field");
      const label = document.querySelector<HTMLLabelElement>(
        `label[for="${element.id}"]`,
      );
      const labelRect = label?.getBoundingClientRect();
      return {
        appearance: style.appearance,
        backgroundColor: style.backgroundColor,
        backgroundImage: style.backgroundImage,
        backgroundSize: Number.parseFloat(style.backgroundSize),
        controlHeight: control?.getBoundingClientRect().height,
        height: rect.height,
        labelFor: label?.htmlFor,
        labelGap: labelRect ? labelRect.left - rect.right : null,
        width: rect.width,
      };
    });

    expect(surface.appearance).toBe("none");
    expect(surface.backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(surface.backgroundImage).toContain("%23ffffff");
    expect(surface.backgroundSize).toBeCloseTo(24, 0);
    expect(surface.controlHeight).toBeCloseTo(40, 0);
    expect(surface.width).toBeCloseTo(28, 0);
    expect(surface.height).toBeCloseTo(28, 0);
    expect(surface.labelFor).toBe(await checkbox.getAttribute("id"));
    expect(surface.labelGap).toBeCloseTo(0, 0);
  }

  await heatMap.check();
  await expect(heatMap).toBeChecked();
  expect(
    await heatMap.evaluate(
      (element) => getComputedStyle(element).backgroundImage,
    ),
  ).toContain("%237ab5e5");
  await expect(
    mapLayers.getByRole("button", { name: "Reset Map layers filter" }),
  ).toHaveCount(0);

  await sidebar
    .getByRole("combobox", { name: "Choropleth Layer" })
    .selectOption("zip-codes");
  await expect(heatMap).toBeDisabled();
  const checkedWhileDisabled = await heatMap.isChecked();
  await mapLayers
    .locator(`label[for="${await heatMap.getAttribute("id")}"]`)
    .click({ force: true });
  expect(await heatMap.isChecked()).toBe(checkedWhileDisabled);
});

test("inverse filter checkboxes return to native controls in forced colors", async ({
  page,
}) => {
  await page.emulateMedia({ forcedColors: "active" });
  const sidebar = await openDashboard(page);
  const panels = sidebar.locator("details.civic-disclosure-panel");
  await panels.last().locator("summary").click();

  const checkboxes = [
    sidebar
      .getByRole("group", { name: "Map layers" })
      .getByRole("checkbox", { name: "Heat map" }),
    panels
      .last()
      .getByRole("checkbox", { name: "Exclude unknown values" }),
  ];

  for (const checkbox of checkboxes) {
    const paint = await checkbox.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        appearance: style.appearance,
        backgroundImage: style.backgroundImage,
      };
    });

    expect(paint.appearance).toBe("auto");
    expect(paint.backgroundImage).toBe("none");
    await checkbox.check();
    await expect(checkbox).toBeChecked();
  }
});

test("choropleth opacity is a compact, legible keyboard-operable range", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  await sidebar
    .getByRole("combobox", { name: "Choropleth Layer" })
    .selectOption("zip-codes");

  const control = sidebar.locator(
    ".civic-dashboard-boundary-control--compact",
  );
  const label = control.locator(
    'label[for="dashboard-boundary-opacity"]',
  );
  const output = label.locator("output");
  const slider = control.getByRole("slider", { name: /^Opacity/ });

  await expect(label).toContainText("Opacity");
  await expect(output).toHaveText("50%");
  await expect(output).toBeVisible();
  await expect(slider).toHaveValue("0.5");
  await expect(slider).toHaveAttribute("aria-valuetext", "50%");

  const layout = await control.evaluate((element) => {
    const labelElement = element.querySelector<HTMLElement>(
      'label[for="dashboard-boundary-opacity"]',
    );
    const labelTextElement = labelElement?.querySelector<HTMLElement>("span");
    const outputElement = labelElement?.querySelector<HTMLElement>("output");
    const input = element.querySelector<HTMLInputElement>(
      "#dashboard-boundary-opacity",
    );
    if (!input || !labelElement || !labelTextElement || !outputElement) {
      return null;
    }

    const controlRect = element.getBoundingClientRect();
    const inputRect = input.getBoundingClientRect();
    const labelRect = labelElement.getBoundingClientRect();
    const textRect = labelTextElement.getBoundingClientRect();
    const outputRect = outputElement.getBoundingClientRect();
    const inputStyle = getComputedStyle(input);

    return {
      controlWidth: controlRect.width,
      inputBackground: inputStyle.backgroundColor,
      inputBackgroundImage: inputStyle.backgroundImage,
      inputHeight: inputRect.height,
      inputLeftInset: inputRect.left - controlRect.left,
      inputPaddingBottom: Number.parseFloat(inputStyle.paddingBottom),
      inputPaddingTop: Number.parseFloat(inputStyle.paddingTop),
      inputRightInset: controlRect.right - inputRect.right,
      inputWidth: inputRect.width,
      labelOutputCenterDelta: Math.abs(
        textRect.top + textRect.height / 2 -
          (outputRect.top + outputRect.height / 2),
      ),
      labelOutputGap: outputRect.left - textRect.right,
      outputRightInset: labelRect.right - outputRect.right,
    };
  });

  expect(layout).not.toBeNull();
  if (!layout) return;
  expect(layout.inputBackground).toBe("rgba(0, 0, 0, 0)");
  expect(layout.inputBackgroundImage).toBe("none");
  expect(layout.inputHeight).toBeGreaterThanOrEqual(24);
  expect(layout.inputHeight).toBeLessThanOrEqual(32);
  expect(layout.inputPaddingTop).toBeLessThanOrEqual(2);
  expect(layout.inputPaddingBottom).toBeLessThanOrEqual(2);
  expect(layout.inputWidth).toBeGreaterThanOrEqual(layout.controlWidth - 2);
  expect(Math.abs(layout.inputLeftInset)).toBeLessThanOrEqual(1);
  expect(Math.abs(layout.inputRightInset)).toBeLessThanOrEqual(1);
  expect(layout.labelOutputGap).toBeGreaterThanOrEqual(8);
  expect(layout.labelOutputCenterDelta).toBeLessThanOrEqual(2);
  expect(Math.abs(layout.outputRightInset)).toBeLessThanOrEqual(1);

  await keyboardFocus(page, slider);

  const pseudoPaint = await slider.evaluate((element) => {
    type Paint = {
      background: string;
      border: string;
      boxShadow: string;
      height: number | null;
      outline: string;
      selector: string;
      width: number | null;
    };

    const track: Paint[] = [];
    const thumb: Paint[] = [];
    const focusedThumb: Paint[] = [];
    const rootFontSize = Number.parseFloat(
      getComputedStyle(document.documentElement).fontSize,
    );
    const inputFontSize = Number.parseFloat(getComputedStyle(element).fontSize);
    const toPixels = (value: string): number | null => {
      if (!value) return null;
      if (value.endsWith("rem")) return Number.parseFloat(value) * rootFontSize;
      if (value.endsWith("em")) return Number.parseFloat(value) * inputFontSize;
      const parsed = Number.parseFloat(value);
      return Number.isFinite(parsed) ? parsed : null;
    };
    const componentScoped = (selector: string) =>
      selector.includes(".civic-range-field__input") ||
      selector.includes(".civic-dashboard-boundary-control--compact") ||
      selector.includes("#dashboard-boundary-opacity");
    const paint = (rule: CSSStyleRule, selector: string): Paint => ({
      background:
        rule.style.backgroundColor || rule.style.background || "transparent",
      border: rule.style.borderColor || rule.style.border || "none",
      boxShadow: rule.style.boxShadow || "none",
      height: toPixels(rule.style.height),
      outline: rule.style.outlineColor || rule.style.outline || "none",
      selector,
      width: toPixels(rule.style.width),
    });

    const inspectRules = (rules: CSSRuleList): void => {
      for (const rule of rules) {
        if (
          rule instanceof CSSMediaRule &&
          !window.matchMedia(rule.conditionText).matches
        ) {
          continue;
        }
        if (rule instanceof CSSStyleRule) {
          for (const selector of rule.selectorText.split(",")) {
            const normalized = selector.trim();
            if (!componentScoped(normalized)) continue;
            if (normalized.includes("::-webkit-slider-runnable-track")) {
              track.push(paint(rule, normalized));
            }
            if (!normalized.includes("::-webkit-slider-thumb")) continue;
            if (normalized.includes(":focus-visible")) {
              focusedThumb.push(paint(rule, normalized));
            } else if (!normalized.includes(":focus")) {
              thumb.push(paint(rule, normalized));
            }
          }
          continue;
        }
        if ("cssRules" in rule) {
          inspectRules((rule as CSSGroupingRule).cssRules);
        }
      }
    };

    for (const sheet of document.styleSheets) {
      try {
        inspectRules(sheet.cssRules);
      } catch {
        // Cross-origin stylesheets cannot style this locally scoped control.
      }
    }

    type Rgba = { alpha: number; blue: number; green: number; red: number };
    const parseColor = (value: string): Rgba | null => {
      const channels = value.match(/[\d.]+/g)?.map(Number);
      if (!channels || channels.length < 3) return null;
      return {
        alpha: channels[3] ?? 1,
        blue: channels[2],
        green: channels[1],
        red: channels[0],
      };
    };
    const resolveColor = (
      value: string,
      property: "background" | "border",
    ): Rgba | null => {
      if (!value || value === "none" || value === "transparent") return null;
      const probe = document.createElement("span");
      probe.style.position = "absolute";
      probe.style.visibility = "hidden";
      if (property === "background") probe.style.background = value;
      else probe.style.border = value;
      element.parentElement?.append(probe);
      const style = getComputedStyle(probe);
      const resolved =
        property === "background"
          ? style.backgroundColor
          : style.borderTopColor;
      probe.remove();
      return parseColor(resolved);
    };
    const composite = (foreground: Rgba, background: Rgba): Rgba => ({
      alpha: 1,
      blue:
        foreground.blue * foreground.alpha +
        background.blue * (1 - foreground.alpha),
      green:
        foreground.green * foreground.alpha +
        background.green * (1 - foreground.alpha),
      red:
        foreground.red * foreground.alpha +
        background.red * (1 - foreground.alpha),
    });
    const luminance = ({ blue, green, red }: Rgba): number => {
      const linear = (channel: number) => {
        const value = channel / 255;
        return value <= 0.04045
          ? value / 12.92
          : ((value + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue);
    };
    const contrast = (first: Rgba, second: Rgba): number => {
      const [lighter, darker] = [luminance(first), luminance(second)].sort(
        (left, right) => right - left,
      );
      return (lighter + 0.05) / (darker + 0.05);
    };
    const lastResolved = (
      paints: Paint[],
      property: "background" | "border",
    ): Rgba | null => {
      for (const candidate of [...paints].reverse()) {
        const resolved = resolveColor(candidate[property], property);
        if (resolved && resolved.alpha > 0) return resolved;
      }
      return null;
    };
    let ancestor = element.parentElement;
    let surface: Rgba | null = null;
    while (ancestor && !surface) {
      const candidate = parseColor(getComputedStyle(ancestor).backgroundColor);
      if (candidate && candidate.alpha > 0) surface = candidate;
      ancestor = ancestor.parentElement;
    }

    const trackBackground = lastResolved(track, "background");
    const thumbBackground = lastResolved(thumb, "background");
    const thumbBorder = lastResolved(thumb, "border");
    const paintedTrack =
      trackBackground && surface
        ? composite(trackBackground, surface)
        : trackBackground;
    const thumbContrasts = [thumbBackground, thumbBorder]
      .filter((color): color is Rgba => Boolean(color && paintedTrack))
      .map((color) => contrast(composite(color, paintedTrack!), paintedTrack!));

    return {
      contrast: {
        thumb: thumbContrasts.length ? Math.max(...thumbContrasts) : null,
        track:
          paintedTrack && surface ? contrast(paintedTrack, surface) : null,
      },
      focusedThumb,
      thumb,
      track,
    };
  });

  expect(
    pseudoPaint.track.some(
      ({ height }) => height !== null && height >= 3 && height <= 6,
    ),
  ).toBe(true);
  expect(
    pseudoPaint.track.some(
      ({ background, border }) =>
        background !== "transparent" || border !== "none",
    ),
  ).toBe(true);
  expect(
    pseudoPaint.thumb.some(
      ({ height, width }) =>
        height !== null &&
        height >= 16 &&
        height <= 20 &&
        width !== null &&
        width >= 16 &&
        width <= 20,
    ),
  ).toBe(true);
  expect(
    pseudoPaint.thumb.some(
      ({ background, border, boxShadow }) =>
        background !== "transparent" ||
        border !== "none" ||
        boxShadow !== "none",
    ),
  ).toBe(true);
  expect(
    pseudoPaint.focusedThumb.some(
      ({ boxShadow, outline }) =>
        boxShadow !== "none" || outline !== "none",
    ),
  ).toBe(true);
  expect(pseudoPaint.contrast.track).not.toBeNull();
  expect(pseudoPaint.contrast.track ?? 0).toBeGreaterThanOrEqual(3);
  expect(pseudoPaint.contrast.thumb).not.toBeNull();
  expect(pseudoPaint.contrast.thumb ?? 0).toBeGreaterThanOrEqual(3);

  await slider.press("End");
  await expect(slider).toHaveValue("0.5");
  await expect(slider).toHaveAttribute("aria-valuetext", "50%");
  await expect(output).toHaveText("50%");

  await slider.press("ArrowLeft");
  await expect(slider).toHaveValue("0.49");
  await expect(slider).toHaveAttribute("aria-valuetext", "49%");
  await expect(output).toHaveText("49%");
});

test("choropleth uses a real label and supports keyboard clearing", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  const boundary = sidebar.getByRole("combobox", {
    name: "Choropleth Layer",
  });
  const visibleOptions = boundary.locator("option:not([hidden])");

  await expect(
    sidebar.locator('label[for="dashboard-boundary-layer"]'),
  ).toBeVisible();
  await expect(visibleOptions).toHaveText([
    "Police Districts",
    "Council Districts",
    "ZIP Codes",
    "Neighborhoods",
    "PA House Districts",
    "PA Senate Districts",
    "School Catchments",
  ]);

  await boundary.focus();
  await boundary.press("z");
  await expect(boundary).toHaveValue("zip-codes");
  await expect(page).toHaveURL(/[?&]layers=zip-codes(?:&|$)/);

  const clear = sidebar.getByRole("button", {
    name: "Clear Choropleth Layer",
  });
  await expect(clear).toBeVisible();
  await boundary.press("Tab");
  await expect(clear).toBeFocused();
  await clear.press("Enter");

  await expect(boundary).toHaveValue("");
  await expect(clear).toHaveCount(0);
  await expect(boundary).toBeFocused();
  await expect(page).not.toHaveURL(/[?&]layers=/);
  await expect(
    sidebar.getByRole("checkbox", { name: "Point locations" }),
  ).toBeEnabled();
});

test("Hot spots only replaces an active choropleth by pointer and keyboard", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.route("**/streets?**", (route) =>
    route.fulfill({
      body: JSON.stringify({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: {
              type: "LineString",
              coordinates: [
                [-75.17, 39.95],
                [-75.15, 39.95],
              ],
            },
            properties: {
              block_label: "1200 BLOCK MARKET ST",
              block_number: 1200,
              segment_id: "segment-1",
              street_name: "MARKET ST",
            },
          },
        ],
      }),
      contentType: "application/json",
      headers: {
        "access-control-allow-origin": "http://127.0.0.1:4180",
      },
    }),
  );
  await page.goto("./?layers=zip-codes");

  const explorer = page.locator(".civic-dashboard-browser-explorer");
  await expect(explorer).toHaveAttribute("aria-busy", "false");
  const sidebar = page.getByRole("complementary", {
    name: "Map filters and controls",
  });
  const boundary = sidebar.getByRole("combobox", {
    name: "Choropleth Layer",
  });
  const opacity = sidebar.getByRole("slider", { name: "Opacity" });
  const hotSpots = sidebar.getByRole("checkbox", {
    name: "Hot spots by street block",
  });
  const onlyHotSpots = sidebar.getByRole("button", {
    name: "Select only Hot spots by street block for Map layers",
  });
  const hotSpotsRow = hotSpots.locator("..").locator("..");
  const mapFrame = page.locator(".civic-dashboard-point-map__frame");
  const legend = page.locator(
    '.civic-dashboard-point-map [data-map-legend="street-hot-spots"]',
  );

  async function expectActiveChoropleth() {
    await expect(boundary).toHaveValue("zip-codes");
    await expect(opacity).toBeVisible();
    await expect(hotSpots).toBeDisabled();
    await expect(onlyHotSpots).toBeEnabled();
  }

  async function expectOnlyHotSpots() {
    await expect
      .poll(() => new URL(page.url()).searchParams.get("layers"))
      .toBe("hot-spots-by-street-block");
    await expect(boundary).toHaveValue("");
    await expect(opacity).toHaveCount(0);
    await expect(hotSpots).toBeEnabled();
    await expect(hotSpots).toBeChecked();
    await expect(
      sidebar.getByRole("checkbox", { name: "Point locations" }),
    ).not.toBeChecked();
    await expect(
      sidebar.getByRole("checkbox", { name: "Heat map" }),
    ).not.toBeChecked();
    await expect(mapFrame).toHaveAttribute("aria-busy", "false");
    await expect(legend).toBeVisible();
    await expect(legend).toHaveAttribute(
      "aria-label",
      /Shooting victims per street block map legend/,
    );
  }

  await expectActiveChoropleth();
  await hotSpotsRow.hover();
  await onlyHotSpots.click();
  await expectOnlyHotSpots();

  await boundary.selectOption("zip-codes");
  await expectActiveChoropleth();
  await onlyHotSpots.focus();
  await expect(onlyHotSpots).toBeFocused();
  await onlyHotSpots.press("Enter");
  await expectOnlyHotSpots();
});

test("category-only and reset actions disclose without changing panel flow", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  const panel = sidebar
    .locator("details.civic-disclosure-panel")
    .first();
  await panel.locator("summary").click();

  const row = panel.locator(".civic-dashboard-checkbox-filter__list li").first();
  const checkbox = row.getByRole("checkbox");
  const only = row.getByRole("button", { name: /Select only .* for Gender/ });

  async function expectOnlyDisclosure(opacity: number, pointerEvents: string) {
    await expect
      .poll(() =>
        only.evaluate((element) => {
          const style = getComputedStyle(element);
          return {
            opacity: Number.parseFloat(style.opacity),
            pointerEvents: style.pointerEvents,
          };
        }),
      )
      .toEqual({ opacity, pointerEvents });
  }

  await expectOnlyDisclosure(0, "none");

  await row.hover();
  await expectOnlyDisclosure(1, "auto");

  await page.mouse.move(0, 0);
  await expectOnlyDisclosure(0, "none");

  await checkbox.focus();
  await expectOnlyDisclosure(1, "auto");

  const panelHeightBefore = (await panel.boundingBox())?.height;
  expect(panelHeightBefore).toBeDefined();
  await only.click();

  const reset = panel
    .locator("..")
    .getByRole("button", { name: "Reset Gender filter" });
  await expect(reset).toBeVisible();
  const [panelBox, summaryBox, summaryLabelBox, resetBox] = await Promise.all([
    panel.boundingBox(),
    panel.locator("summary").boundingBox(),
    panel.locator("summary").evaluate((element) => {
      const labelNode = Array.from(element.childNodes).find(
        (node) =>
          node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.trim()),
      );
      if (!labelNode) return null;
      const range = document.createRange();
      range.selectNodeContents(labelNode);
      const { bottom, left, right, top } = range.getBoundingClientRect();
      return { bottom, left, right, top };
    }),
    reset.boundingBox(),
  ]);
  expect(panelBox).not.toBeNull();
  expect(summaryBox).not.toBeNull();
  expect(summaryLabelBox).not.toBeNull();
  expect(resetBox).not.toBeNull();
  if (panelBox && summaryBox && summaryLabelBox && resetBox) {
    expect(panelBox.height).toBeCloseTo(panelHeightBefore!, 0);
    expect(resetBox.x).toBeGreaterThanOrEqual(summaryBox.x);
    expect(resetBox.x + resetBox.width).toBeLessThanOrEqual(
      summaryBox.x + summaryBox.width,
    );
    expect(resetBox.y).toBeGreaterThanOrEqual(summaryBox.y);
    expect(resetBox.y + resetBox.height).toBeLessThanOrEqual(
      summaryBox.y + summaryBox.height,
    );
    expect(resetBox.x).toBeGreaterThanOrEqual(summaryLabelBox.right + 4);
  }

  await reset.click();
  await expect(reset).toHaveCount(0);
});

test("desktop actions align and address search exposes one clear affordance", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  const resetAll = sidebar.getByRole("button", {
    name: "Reset All Filters",
  });
  const download = sidebar.getByRole("button", { name: "Download Data" });
  const actions = sidebar.locator(".civic-legacy-sidebar__actions");

  const [
    resetWidth,
    downloadWidth,
    resetBox,
    downloadBox,
    actionContentWidth,
  ] = await Promise.all([
    resetAll.evaluate((element) =>
      Number.parseFloat(getComputedStyle(element).width),
    ),
    download.evaluate((element) =>
      Number.parseFloat(getComputedStyle(element).width),
    ),
    resetAll.boundingBox(),
    download.boundingBox(),
    actions.evaluate((element) => {
      const style = getComputedStyle(element);
      return (
        element.clientWidth -
        Number.parseFloat(style.paddingLeft) -
        Number.parseFloat(style.paddingRight)
      );
    }),
  ]);
  expect(resetWidth).toBeCloseTo(downloadWidth, 1);
  expect(resetBox).not.toBeNull();
  expect(downloadBox).not.toBeNull();
  if (resetBox && downloadBox) {
    expect(resetBox.width).toBeCloseTo(downloadBox.width, 1);
    expect(resetBox.width).toBeCloseTo(actionContentWidth, 1);
    expect(downloadBox.width).toBeCloseTo(actionContentWidth, 1);
  }

  const addressSearch = page.locator(".civic-legacy-address-search");
  const input = addressSearch.getByRole("combobox", {
    name: "Search for an address in Philadelphia",
  });
  await input.fill("123 Market Street");

  const customClear = addressSearch.getByRole("button", {
    name: "Clear search",
  });
  await expect(customClear).toHaveCount(1);
  await expect(customClear).toHaveClass(
    /\bcivic-dashboard-address-search__clear\b/,
  );

  const nativeCancelSuppression = await input.evaluate((element) => {
    const style = getComputedStyle(
      element,
      "::-webkit-search-cancel-button",
    );
    const computedSuppressed =
      style.display === "none" ||
      style.getPropertyValue("-webkit-appearance") === "none" ||
      style.appearance === "none";

    // Chromium currently returns the input's styles instead of the vendor
    // pseudo-element's resolved styles. In that case, verify through the live
    // CSSOM that a matching, component-scoped suppression rule is loaded.
    let matchingRuleSuppressed = false;
    function inspectRules(rules: CSSRuleList): void {
      for (const rule of rules) {
        if (rule instanceof CSSStyleRule) {
          const suffix = "::-webkit-search-cancel-button";
          if (!rule.selectorText.includes(suffix)) continue;
          const baseSelector = rule.selectorText.replace(suffix, "").trim();
          if (
            element.matches(baseSelector) &&
            (rule.style.display === "none" ||
              rule.style.getPropertyValue("-webkit-appearance") === "none" ||
              rule.style.appearance === "none")
          ) {
            matchingRuleSuppressed = true;
          }
          continue;
        }

        if ("cssRules" in rule) {
          inspectRules((rule as CSSGroupingRule).cssRules);
        }
      }
    }

    for (const sheet of document.styleSheets) {
      try {
        inspectRules(sheet.cssRules);
      } catch {
        // Cross-origin stylesheets are irrelevant to this scoped component.
      }
    }

    return computedSuppressed || matchingRuleSuppressed;
  });
  expect(nativeCancelSuppression).toBe(true);
});

test("successful address results never announce a contradictory empty state", async ({
  page,
}) => {
  await openDashboard(page);
  let markRequestStarted!: () => void;
  let releaseResponse!: () => void;
  const requestStarted = new Promise<void>((resolve) => {
    markRequestStarted = resolve;
  });
  const responseReleased = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  await page.route("https://nominatim.openstreetmap.org/**", async (route) => {
    markRequestStarted();
    await responseReleased;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          address: {
            house_number: "1",
            neighbourhood: "Center City",
            postcode: "19107",
            road: "S Penn Square",
          },
          display_name: "Philadelphia City Hall, Philadelphia, Pennsylvania",
          lat: "39.9526",
          lon: "-75.1636",
          place_id: 101,
        },
        {
          address: {
            house_number: "1400",
            neighbourhood: "Center City",
            postcode: "19102",
            road: "John F Kennedy Boulevard",
          },
          display_name:
            "1400 John F Kennedy Boulevard, Philadelphia, Pennsylvania",
          lat: "39.9540",
          lon: "-75.1640",
          place_id: 102,
        },
      ]),
    });
  });

  const addressSearch = page.locator(".civic-legacy-address-search");
  const clear = addressSearch.getByRole("button", { name: "Clear search" });
  const loading = addressSearch.locator(
    ".civic-dashboard-address-search__loading",
  );
  await addressSearch
    .getByRole("combobox", { name: "Search for an address in Philadelphia" })
    .fill("City Hall");

  await requestStarted;
  await expect(loading).toBeVisible();
  await expect(clear).toHaveCount(0);
  releaseResponse();

  const results = addressSearch.getByRole("listbox", {
    name: "Address search results",
  });
  await expect(results).toBeVisible();
  await expect(results.getByRole("option")).toHaveCount(2);
  await expect(loading).toHaveCount(0);
  await expect(clear).toHaveCount(1);
  await expect(
    addressSearch.getByRole("status").filter({
      hasText: "No addresses found in Philadelphia",
    }),
  ).toHaveCount(0);
});

test("the modal download dialog wraps focus in both directions", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  await sidebar.getByRole("button", { name: "Download Data" }).click();

  const dialog = page.getByRole("dialog", { name: "Download Data" });
  await expect(dialog).toBeVisible();
  const first = dialog.getByRole("radio", { name: "Filtered Data" });
  const second = dialog.getByRole("radio", { name: "All Data" });
  const last = dialog.getByRole("button", {
    name: "Download GeoJSON",
  });
  const cancel = dialog.getByRole("button", { name: "Cancel" });
  const cancelBox = await cancel.boundingBox();
  expect(cancelBox).not.toBeNull();
  if (cancelBox) {
    expect(cancelBox.width).toBeGreaterThanOrEqual(40);
    expect(cancelBox.height).toBeGreaterThanOrEqual(40);
  }

  await first.focus();
  await page.keyboard.press("ArrowRight");
  await expect(second).toBeChecked();
  await page.keyboard.press("ArrowLeft");
  await expect(first).toBeChecked();

  await page.keyboard.press("Shift+Tab");
  await expect(last).toBeFocused();

  await last.focus();
  await page.keyboard.press("Tab");
  await expect(first).toBeFocused();
});

test("the download dialog keeps choices fixed and cancellation active while preparing", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  let markRequestStarted!: () => void;
  let releaseResponse!: () => void;
  const requestStarted = new Promise<void>((resolve) => {
    markRequestStarted = resolve;
  });
  const responseReleased = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  let downloadCount = 0;
  page.on("download", () => {
    downloadCount += 1;
  });

  await page.route("**/boundaries/police_districts", async (route) => {
    markRequestStarted();
    await responseReleased;
    await route
      .fulfill({
        body: JSON.stringify({ type: "FeatureCollection", features: [] }),
        contentType: "application/json",
        headers: { "access-control-allow-origin": "*" },
      })
      .catch(() => {});
  });

  await sidebar.getByRole("button", { name: "Download Data" }).click();
  const dialog = page.getByRole("dialog", { name: "Download Data" });
  const all = dialog.getByRole("radio", { name: "All Data" });
  const filtered = dialog.getByRole("radio", { name: "Filtered Data" });
  const csv = dialog.getByRole("radio", { name: "CSV" });
  const geojson = dialog.getByRole("radio", { name: "GeoJSON" });
  const aggregate = dialog.getByLabel("Aggregate By");
  const cancel = dialog.getByRole("button", { name: "Cancel" });
  const submit = dialog.locator(".civic-dashboard-download__submit");

  await dialog.locator('label[for="dashboard-download-all"]').click();
  await expect(all).toBeChecked();
  await aggregate.selectOption("police-districts");
  await submit.click();
  await requestStarted;

  await expect(dialog).toHaveAttribute("aria-busy", "true");
  await expect(submit).toHaveText("Preparing GeoJSON…");
  for (const control of [all, filtered, csv, geojson, aggregate, submit]) {
    await expect(control).toBeDisabled();
  }
  await expect(cancel).toBeEnabled();

  const cancelBackground = await cancel.evaluate(
    (element) => getComputedStyle(element).backgroundColor,
  );
  const submitBackground = await submit.evaluate(
    (element) => getComputedStyle(element).backgroundColor,
  );
  await cancel.hover();
  expect(
    await cancel.evaluate(
      (element) => getComputedStyle(element).backgroundColor,
    ),
  ).not.toBe(cancelBackground);
  await submit.hover();
  await expect
    .poll(() =>
      submit.evaluate((element) => getComputedStyle(element).backgroundColor),
    )
    .toBe(submitBackground);

  await dialog
    .locator('label[for="dashboard-download-filtered"]')
    .click({ force: true });
  await dialog
    .locator('label[for="dashboard-download-csv"]')
    .click({ force: true });
  await expect(all).toBeChecked();
  await expect(filtered).not.toBeChecked();
  await expect(geojson).toBeChecked();
  await expect(csv).not.toBeChecked();
  await expect(aggregate).toHaveValue("police-districts");

  await cancel.click();
  await expect(dialog).not.toBeVisible();
  await expect(
    sidebar.getByRole("button", { name: "Download Data" }),
  ).toBeFocused();
  releaseResponse();
  await page.waitForTimeout(100);
  expect(downloadCount).toBe(0);
});

test("forced colors leaves the selected download options unmistakable", async ({
  page,
}) => {
  await page.emulateMedia({ forcedColors: "active" });
  const sidebar = await openDashboard(page);
  await sidebar.getByRole("button", { name: "Download Data" }).click();

  const dialog = page.getByRole("dialog", { name: "Download Data" });
  const filtered = dialog.locator(
    'label[for="dashboard-download-filtered"]',
  );
  const all = dialog.locator('label[for="dashboard-download-all"]');

  const selectedPaint = await filtered.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      background: style.backgroundColor,
      border: style.borderColor,
      color: style.color,
      marker: getComputedStyle(element, "::after").content,
    };
  });
  const unselectedPaint = await all.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      background: style.backgroundColor,
      border: style.borderColor,
      color: style.color,
      marker: getComputedStyle(element, "::after").content,
    };
  });

  expect(selectedPaint.marker).toContain("✓");
  expect(unselectedPaint.marker).toBe("none");
  expect(selectedPaint.background).not.toBe(unselectedPaint.background);
  expect(selectedPaint.color).not.toBe(unselectedPaint.color);
  expect(selectedPaint.border).not.toBe(unselectedPaint.border);
});

test("pointer focus stays quiet while keyboard focus uses one coherent treatment", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  const genderPanel = sidebar
    .locator("details.civic-disclosure-panel")
    .first();
  const summary = genderPanel.locator("summary");

  await summary.click();
  await expect(summary).toBeFocused();
  expect(
    await summary.evaluate((element) => element.matches(":focus-visible")),
  ).toBe(false);
  expect((await focusPaint(summary)).style).toBe("none");

  await keyboardFocus(page, summary);
  const summaryPaint = await focusPaint(summary);

  const checkbox = genderPanel.getByRole("checkbox").first();
  await checkbox.click();
  await expect(checkbox).toBeFocused();
  expect(
    await checkbox.evaluate((element) => element.matches(":focus-visible")),
  ).toBe(false);
  expect((await focusPaint(checkbox)).style).toBe("none");

  await keyboardFocus(page, checkbox);
  const checkboxPaint = await focusPaint(checkbox);

  const mapControl = page.locator(".maplibregl-ctrl button").first();
  await expect(mapControl).toBeVisible();
  await keyboardFocus(page, mapControl);
  const mapControlPaint = await focusPaint(mapControl);

  for (const paint of [summaryPaint, checkboxPaint, mapControlPaint]) {
    expect(paint.style).toBe("solid");
    expect(paint.width).toBeGreaterThanOrEqual(2);
  }
  expect(checkboxPaint.color).toBe(summaryPaint.color);
  expect(mapControlPaint.color).toBe(summaryPaint.color);
  expect(checkboxPaint.width).toBe(summaryPaint.width);
  expect(mapControlPaint.width).toBe(summaryPaint.width);
  expect(checkboxPaint.offset).toBe(summaryPaint.offset);
  expect(mapControlPaint.offset).toBe(summaryPaint.offset);
  expect(summaryPaint.color).not.toBe("rgb(247, 209, 84)");
  expect(mapControlPaint.boxShadow).toBe("none");
});

test("the keyboard-focused map canvas paints its indicator inside the clipped map", async ({
  page,
}) => {
  await openDashboard(page);
  const canvas = page.locator(".maplibregl-canvas");
  await keyboardFocus(page, canvas);

  const focusVisibility = await canvas.evaluate((element) => {
    const mapView = element.closest<HTMLElement>(".civic-legacy-map-view");
    if (!mapView) return null;
    const clipRect = mapView.getBoundingClientRect();

    let candidate: HTMLElement | null = element as HTMLElement;
    while (candidate) {
      const style = getComputedStyle(candidate);
      const rect = candidate.getBoundingClientRect();
      const outlineWidth = Number.parseFloat(style.outlineWidth) || 0;
      const outlineOffset = Number.parseFloat(style.outlineOffset) || 0;
      const outwardPaint = Math.max(0, outlineWidth + outlineOffset);
      const hasOutline = style.outlineStyle !== "none" && outlineWidth >= 2;
      const outlineFitsClip =
        hasOutline &&
        rect.left - outwardPaint >= clipRect.left - 0.5 &&
        rect.top - outwardPaint >= clipRect.top - 0.5 &&
        rect.right + outwardPaint <= clipRect.right + 0.5 &&
        rect.bottom + outwardPaint <= clipRect.bottom + 0.5;
      const hasInsetShadow = style.boxShadow
        .split(/,(?![^()]*(?:\)|$))/)
        .some((shadow) => /\binset\b/.test(shadow) && shadow !== "none");

      if (outlineFitsClip || hasInsetShadow) {
        return {
          focusVisible: element.matches(":focus-visible"),
          hasVisibleIndicator: true,
        };
      }
      if (candidate === mapView) break;
      candidate = candidate.parentElement;
    }

    return {
      focusVisible: element.matches(":focus-visible"),
      hasVisibleIndicator: false,
    };
  });

  expect(focusVisibility).not.toBeNull();
  expect(focusVisibility?.focusVisible).toBe(true);
  expect(focusVisibility?.hasVisibleIndicator).toBe(true);
});
