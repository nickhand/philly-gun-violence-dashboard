import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

test("renders one quiet custom year selector at mobile width", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./");

  const yearSelect = page.getByLabel("Viewing data for");
  await expect(yearSelect).toBeVisible();
  await expect(yearSelect).toHaveValue("2026");

  const measureYearSelect = () =>
    yearSelect.evaluate((element) => {
      const select = element as HTMLSelectElement;
      const style = getComputedStyle(select);
      const selectedText = select.selectedOptions[0]?.textContent?.trim() ?? "";
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d");
      if (!context) return null;

      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const letterSpacing = Number.parseFloat(style.letterSpacing) || 0;
      const textWidth =
        context.measureText(selectedText).width +
        Math.max(0, selectedText.length - 1) * letterSpacing;
      const contentWidth =
        select.clientWidth -
        Number.parseFloat(style.paddingLeft) -
        Number.parseFloat(style.paddingRight);

      return {
        appearance: style.appearance,
        backgroundImage: style.backgroundImage,
        borderBottomStyle: style.borderBottomStyle,
        borderBottomWidth: Number.parseFloat(style.borderBottomWidth),
        borderLeftWidth: Number.parseFloat(style.borderLeftWidth),
        borderRadius: style.borderRadius,
        borderRightWidth: Number.parseFloat(style.borderRightWidth),
        borderTopWidth: Number.parseFloat(style.borderTopWidth),
        boxShadow: style.boxShadow,
        contentWidth,
        minWidth: Number.parseFloat(style.minWidth),
        renderedWidth: select.getBoundingClientRect().width,
        selectedText,
        textWidth,
      };
    });

  const visualContract = await measureYearSelect();

  expect(visualContract).not.toBeNull();
  expect(visualContract).toMatchObject({
    appearance: "none",
    borderBottomStyle: "solid",
    borderLeftWidth: 0,
    borderRadius: "0px",
    borderRightWidth: 0,
    borderTopWidth: 0,
    boxShadow: "none",
    minWidth: 72,
    renderedWidth: 72,
    selectedText: "2026",
  });
  expect(visualContract?.borderBottomWidth).toBeGreaterThan(0);
  expect(visualContract?.backgroundImage).not.toBe("none");
  expect(visualContract?.backgroundImage.match(/url\(/g)).toHaveLength(1);
  expect(visualContract?.contentWidth).toBeGreaterThan(
    visualContract?.textWidth ?? Number.POSITIVE_INFINITY,
  );

  const yearAlignment = await page.evaluate(() => {
    const header = document.querySelector<HTMLElement>(".civic-site-header")!;
    const bar = document.querySelector<HTMLElement>(".civic-legacy-year-bar")!;
    const form = bar.querySelector<HTMLFormElement>("form")!;
    const label = bar.querySelector<HTMLLabelElement>("label")!;
    const select = bar.querySelector<HTMLSelectElement>("select")!;
    const headerBounds = header.getBoundingClientRect();
    const formBounds = form.getBoundingClientRect();
    const labelBounds = label.getBoundingClientRect();
    const selectBounds = select.getBoundingClientRect();

    return {
      controlCenterDifference: Math.abs(
        labelBounds.top + labelBounds.height / 2 -
          (selectBounds.top + selectBounds.height / 2),
      ),
      gapAfterHeader: formBounds.top - headerBounds.bottom,
      paddingTop: Number.parseFloat(getComputedStyle(bar).paddingTop),
    };
  });

  expect(yearAlignment.paddingTop).toBe(6);
  expect(yearAlignment.gapAfterHeader).toBeGreaterThanOrEqual(6);
  expect(yearAlignment.controlCenterDifference).toBeLessThanOrEqual(1.5);

  await page.goto("./?year=All%20Years");
  await expect(yearSelect).toHaveValue("All Years");
  await expect(yearSelect).toHaveClass(
    /civic-legacy-year-bar__select--all/,
  );
  const allYearsContract = await measureYearSelect();
  expect(allYearsContract).not.toBeNull();
  expect(allYearsContract).toMatchObject({
    minWidth: 104,
    renderedWidth: 104,
    selectedText: "All Years",
  });
  expect(allYearsContract?.contentWidth).toBeGreaterThan(
    allYearsContract?.textWidth ?? Number.POSITIVE_INFINITY,
  );

  const selectBox = await yearSelect.boundingBox();
  expect(selectBox).not.toBeNull();
  await page.mouse.click(
    selectBox!.x + selectBox!.width / 2,
    selectBox!.y + selectBox!.height / 2,
  );
  await page.keyboard.press("Escape");
  await expect(yearSelect).toBeFocused();
  const pointerFocusPaint = await yearSelect.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      boxShadow: style.boxShadow,
      color: style.outlineColor,
      focusVisible: element.matches(":focus-visible"),
      offset: Number.parseFloat(style.outlineOffset),
      style: style.outlineStyle,
      width: Number.parseFloat(style.outlineWidth),
    };
  });
  expect(pointerFocusPaint.boxShadow).toBe("none");
  if (pointerFocusPaint.focusVisible) {
    // Chromium may legitimately expose :focus-visible for a pointer-focused
    // native select. When it does, it must be our one blue keyboard ring, not
    // an additional white native bezel.
    expect(pointerFocusPaint).toMatchObject({
      color: "rgb(36, 145, 255)",
      offset: 3,
      style: "solid",
      width: 3,
    });
  } else {
    expect(pointerFocusPaint.style).toBe("none");
    expect(pointerFocusPaint.width).toBe(0);
  }

  // Switch Chromium's input modality to keyboard before restoring focus. This
  // exercises the selector's keyboard-only focus treatment without coupling
  // the check to the dashboard's complete tab order.
  await page.keyboard.press("Tab");
  await yearSelect.focus();
  await expect(yearSelect).toBeFocused();
  expect(
    await yearSelect.evaluate((element) => element.matches(":focus-visible")),
  ).toBe(true);
  const keyboardFocusPaint = await yearSelect.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      boxShadow: style.boxShadow,
      color: style.outlineColor,
      offset: Number.parseFloat(style.outlineOffset),
      style: style.outlineStyle,
      width: Number.parseFloat(style.outlineWidth),
    };
  });
  expect(keyboardFocusPaint).toMatchObject({
    boxShadow: "none",
    color: "rgb(36, 145, 255)",
    offset: 3,
    style: "solid",
    width: 3,
  });
});

test("preserves the homepage hero summary type hierarchy without mobile overflow", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./");

  const summary = page.locator(
    ".civic-legacy-dashboard-header__summary--shooting",
  );
  await expect(
    page.locator(".civic-legacy-dashboard-header__summary--homicide"),
  ).toContainText("an increase of 25% from 2025");
  await expect(summary).toContainText(
    "This map shows the victims of gun violence:",
  );
  await page.evaluate(() => document.fonts.ready);

  const contract = await summary.evaluate((element) => {
    const fatal = element.querySelector<HTMLElement>(".fatal");
    const nonfatal = element.querySelector<HTMLElement>(".nonfatal");
    const date = element.querySelector<HTMLElement>(".date-color");
    if (!fatal || !nonfatal || !date) return null;

    const styleFor = (target: Element) => {
      const style = getComputedStyle(target);
      return {
        color: style.color,
        family: style.fontFamily
          .split(",")[0]
          ?.replace(/['"]/g, "")
          .trim(),
        weight: style.fontWeight,
      };
    };
    const summaryRect = element.getBoundingClientRect();
    const fontFaces: Array<{
      family: string;
      status: FontFace["status"];
      style: string;
      weight: string;
    }> | null =
      "fonts" in document && typeof document.fonts.forEach === "function"
        ? []
        : null;
    document.fonts?.forEach((face) => {
      if (fontFaces === null) return;
      fontFaces.push({
        family: face.family.replace(/['"]/g, "").trim(),
        status: face.status,
        style: face.style,
        weight: face.weight,
      });
    });

    return {
      date: styleFor(date),
      documentScrollWidth: document.documentElement.scrollWidth,
      fatal: styleFor(fatal),
      fontFaces,
      nonfatal: styleFor(nonfatal),
      summary: styleFor(element),
      summaryClientWidth: element.clientWidth,
      summaryLeft: summaryRect.left,
      summaryRight: summaryRect.right,
      summaryScrollWidth: element.scrollWidth,
      viewportWidth: window.innerWidth,
    };
  });

  expect(contract).not.toBeNull();
  expect(contract?.summary).toEqual({
    color: "rgb(255, 255, 255)",
    family: "Public Sans Web",
    weight: "300",
  });
  expect(contract?.nonfatal).toEqual({
    color: "rgb(229, 220, 142)",
    family: "Public Sans Web",
    weight: "300",
  });
  expect(contract?.fatal).toEqual({
    color: "rgb(255, 138, 138)",
    family: "Public Sans Web",
    weight: "300",
  });
  expect(contract?.date).toEqual({
    color: "rgb(178, 190, 181)",
    family: "Public Sans Web",
    weight: "300",
  });
  if (contract?.fontFaces !== null) {
    expect(contract?.fontFaces).toContainEqual({
      family: "Public Sans Web",
      status: "loaded",
      style: "normal",
      weight: "300",
    });
  }
  expect(contract?.summaryLeft).toBeGreaterThanOrEqual(0);
  expect(contract?.summaryRight).toBeLessThanOrEqual(
    contract?.viewportWidth ?? 0,
  );
  expect(contract?.summaryScrollWidth).toBeLessThanOrEqual(
    contract?.summaryClientWidth ?? 0,
  );
  expect(contract?.documentScrollWidth).toBeLessThanOrEqual(
    contract?.viewportWidth ?? 0,
  );
});

test("lets keyboard users cancel a mobile download while it is preparing", async ({
  page,
}) => {
  let releaseBoundary!: () => void;
  let markBoundaryStarted!: () => void;
  const boundaryStarted = new Promise<void>((resolve) => {
    markBoundaryStarted = resolve;
  });
  const boundaryGate = new Promise<void>((resolve) => {
    releaseBoundary = resolve;
  });
  let downloadCount = 0;
  page.on("download", () => {
    downloadCount += 1;
  });

  await mockNuxtExternalServices(page);
  await page.route("**/boundaries/police_districts", async (route) => {
    markBoundaryStarted();
    await boundaryGate;
    await route
      .fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ type: "FeatureCollection", features: [] }),
      })
      .catch(() => {});
  });
  await page.goto("./");
  await expect(page.locator(".civic-dashboard-browser-explorer")).toHaveAttribute(
    "aria-busy",
    "false",
  );

  const trigger = page.getByRole("button", { name: "Download Data" });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Download Data" });
  await dialog
    .getByLabel("Aggregate By")
    .selectOption("police-districts");
  await dialog.getByRole("button", { name: "Download GeoJSON" }).click();
  await boundaryStarted;
  await expect(dialog).toHaveAttribute("aria-busy", "true");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeEnabled();

  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  releaseBoundary();
  await page.waitForTimeout(100);
  expect(downloadCount).toBe(0);
});

test("keeps chart definitions accessible without shifting or overflowing cards", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./");

  const charts = page.locator("#charts");
  const outcomeCard = page.locator(
    ".civic-dashboard-category-chart--outcome",
  );
  const trigger = outcomeCard.getByRole("button", { name: "About Outcome" });
  const tooltip = outcomeCard.locator(".civic-info-tooltip__panel");
  await expect(trigger).toBeVisible();
  await page.evaluate(() => document.fonts.ready);

  const measureLayout = async () => {
    return charts.evaluate((section) => {
      const card = section.querySelector<HTMLElement>(
        ".civic-dashboard-category-chart--outcome",
      );
      const next = section.querySelector<HTMLElement>(
        ".civic-dashboard-category-chart--court",
      );
      if (!card || !next) {
        return {
          cardHeight: Number.NaN,
          nextOffset: Number.POSITIVE_INFINITY,
          sectionHeight: Number.NaN,
        };
      }
      return {
        cardHeight: card.offsetHeight,
        nextOffset: next.offsetTop - card.offsetTop,
        sectionHeight: section.scrollHeight,
      };
    });
  };
  const initialLayout = await measureLayout();

  await charts.focus();
  await page.keyboard.press("Tab");
  await expect(trigger).toBeFocused();
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("Fatal indicates");
  const tooltipId = await tooltip.getAttribute("id");
  expect(tooltipId).toBeTruthy();
  await expect(trigger).toHaveAttribute("aria-controls", tooltipId!);
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
  await expect(trigger).toHaveAttribute("aria-describedby", tooltipId!);
  await expect(tooltip).toHaveAttribute("role", "tooltip");

  const focusedLayout = await measureLayout();
  expect(focusedLayout.cardHeight).toBeCloseTo(initialLayout.cardHeight ?? -1, 1);
  expect(focusedLayout.nextOffset).toBeCloseTo(initialLayout.nextOffset, 1);
  expect(focusedLayout.sectionHeight).toBeCloseTo(
    initialLayout.sectionHeight ?? -1,
    1,
  );
  const mobileGeometry = await tooltip.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      clientWidth: element.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      left: rect.left,
      right: rect.right,
      scrollWidth: element.scrollWidth,
      viewportWidth: window.innerWidth,
    };
  });
  expect(mobileGeometry.left).toBeGreaterThanOrEqual(0);
  expect(mobileGeometry.right).toBeLessThanOrEqual(mobileGeometry.viewportWidth);
  expect(mobileGeometry.scrollWidth).toBeLessThanOrEqual(
    mobileGeometry.clientWidth + 1,
  );
  expect(mobileGeometry.documentScrollWidth).toBeLessThanOrEqual(
    mobileGeometry.viewportWidth,
  );

  await page.keyboard.press("Escape");
  await expect(tooltip).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  await charts.focus();
  await trigger.tap();
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toHaveAttribute("role", "dialog");
  await expect(tooltip).toHaveAttribute("aria-label", "Outcome information");
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(trigger).not.toHaveAttribute("aria-describedby");
  await trigger.tap();
  await expect(tooltip).not.toBeVisible();

  await trigger.tap();
  const close = outcomeCard.getByRole("button", {
    name: "Close Outcome information",
  });
  const closeBox = await close.boundingBox();
  expect(closeBox?.width).toBeGreaterThanOrEqual(44);
  expect(closeBox?.height).toBeGreaterThanOrEqual(44);
  await close.tap();
  await expect(tooltip).not.toBeVisible();
  await expect(trigger).toBeFocused();

  await trigger.tap();
  await expect(tooltip).toBeVisible();
  await page.touchscreen.tap(5, 5);
  await expect(tooltip).not.toBeVisible();
});

test("stacks the hydrated map and sidebar without mobile overflow", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./");

  await expect(page.locator(".civic-dashboard-browser-explorer")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await expect(page.locator(".maplibregl-canvas")).toHaveAttribute(
    "aria-label",
    /shooting-victim locations/,
  );

  const menuButton = page.getByRole("button", { name: "Menu" });
  const primaryNavigation = page.getByRole("navigation", {
    name: "Primary navigation",
  });
  await expect(menuButton).toBeVisible();
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");
  await expect(primaryNavigation).not.toBeVisible();
  await menuButton.click();
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");
  await expect(primaryNavigation).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");
  await expect(menuButton).toBeFocused();
  await menuButton.click();
  await page.mouse.click(10, 500);
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");

  const mapView = page.locator(".civic-legacy-map-view");
  const sidebar = page.getByRole("complementary", {
    name: "Map filters and controls",
  });
  const shootingSummary = page.locator(
    ".civic-legacy-dashboard-header__summary--shooting",
  );
  const addressSearch = page.locator(".civic-legacy-address-search");
  const addressOverlay = addressSearch.locator(
    ".civic-dashboard-address-search--overlay",
  );
  const resetButton = sidebar.getByRole("button", {
    name: "Reset All Filters",
  });
  const downloadButton = sidebar.getByRole("button", {
    name: "Download Data",
  });
  const sidebarActions = sidebar.locator(".civic-legacy-sidebar__actions");
  const categoryCards = page.locator(".civic-dashboard-category-chart");

  const [
    mapBox,
    sidebarBox,
    viewport,
    addressBox,
    addressOverlayBox,
    resetBox,
    downloadBox,
    actionContentWidth,
    categoryBoxes,
  ] = await Promise.all([
    mapView.boundingBox(),
    sidebar.boundingBox(),
    Promise.resolve(page.viewportSize()),
    addressSearch.boundingBox(),
    addressOverlay.boundingBox(),
    resetButton.boundingBox(),
    downloadButton.boundingBox(),
    sidebarActions.evaluate((element) => {
      const style = getComputedStyle(element);
      return (
        element.clientWidth -
        Number.parseFloat(style.paddingLeft) -
        Number.parseFloat(style.paddingRight)
      );
    }),
    categoryCards.evaluateAll((cards) =>
      cards.map((card) => {
        const { bottom, left, right, top } = card.getBoundingClientRect();
        return { bottom, left, right, top };
      }),
    ),
  ]);
  expect(mapBox).not.toBeNull();
  expect(sidebarBox).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(addressBox).not.toBeNull();
  expect(addressOverlayBox).not.toBeNull();
  expect(resetBox).not.toBeNull();
  expect(downloadBox).not.toBeNull();
  if (
    !mapBox ||
    !sidebarBox ||
    !viewport ||
    !addressBox ||
    !addressOverlayBox ||
    !resetBox ||
    !downloadBox
  ) {
    return;
  }

  expect(mapBox.height / viewport.height).toBeGreaterThan(0.55);
  expect(mapBox.height / viewport.height).toBeLessThan(0.65);
  expect(sidebarBox.y).toBeGreaterThanOrEqual(mapBox.y + mapBox.height - 1);
  expect(sidebarBox.height).toBeGreaterThanOrEqual(795);
  expect(sidebarBox.width / viewport.width).toBeGreaterThan(0.95);

  const summarySizing = await shootingSummary.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      fontSize: Number.parseFloat(style.fontSize),
      minHeight: Number.parseFloat(style.minHeight),
    };
  });
  expect(summarySizing.minHeight / summarySizing.fontSize).toBeCloseTo(6, 1);

  expect(addressOverlayBox.width).toBeCloseTo(200, 0);
  expect(addressBox.x - mapBox.x).toBeCloseTo(5, 0);
  expect(addressBox.y - mapBox.y).toBeCloseTo(5, 0);

  const attribution = page.locator(
    ".maplibregl-ctrl-attrib.maplibregl-compact",
  );
  const attributionButton = attribution.locator(
    ".maplibregl-ctrl-attrib-button",
  );
  const attributionText = attribution.locator(
    ".maplibregl-ctrl-attrib-inner",
  );
  await expect(attribution).not.toHaveClass(/maplibregl-compact-show/);
  await expect(attribution).not.toHaveAttribute("open", "");
  await expect(attributionButton).toBeVisible();
  await expect(attributionText).not.toBeVisible();
  const collapsedAttributionBox = await attribution.boundingBox();
  expect(collapsedAttributionBox).not.toBeNull();
  expect(collapsedAttributionBox?.width).toBeLessThanOrEqual(26);
  expect(collapsedAttributionBox?.height).toBeLessThanOrEqual(26);

  await attributionButton.click();
  await expect(attribution).toHaveClass(/maplibregl-compact-show/);
  await expect(attributionText).toBeVisible();
  await expect(attributionText).toContainText("OpenStreetMap");
  const expandedAttributionStyle = await attribution.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      backgroundColor: style.backgroundColor,
      color: style.color,
      mapWidth: element.closest(".maplibregl-map")?.clientWidth ?? 0,
      width: element.getBoundingClientRect().width,
    };
  });
  expect(expandedAttributionStyle).toMatchObject({
    backgroundColor: "rgb(255, 255, 255)",
    color: "rgb(23, 33, 38)",
  });
  expect(expandedAttributionStyle.width).toBeLessThanOrEqual(
    expandedAttributionStyle.mapWidth - 20,
  );
  await attributionButton.click();
  await expect(attributionText).not.toBeVisible();

  const printMapButton = page.getByRole("button", { name: "Print map" });
  const printMapContract = await printMapButton.evaluate((element) => {
    const button = element.getBoundingClientRect();
    const icon = element.querySelector("svg")?.getBoundingClientRect();
    const label = element.querySelector("span")?.getBoundingClientRect();
    const home = document
      .querySelector(".maplibregl-ctrl-home")
      ?.getBoundingClientRect();
    return {
      height: button.height,
      homeHeight: home?.height,
      homeWidth: home?.width,
      horizontalCenterDifference: home
        ? Math.abs(
            button.left + button.width / 2 - (home.left + home.width / 2),
          )
        : null,
      iconHeight: icon?.height,
      labelHeight: label?.height,
      labelWidth: label?.width,
      verticalGap: home ? button.top - home.bottom : null,
      width: button.width,
    };
  });
  expect(printMapContract).toMatchObject({
    height: 29,
    homeHeight: 29,
    homeWidth: 29,
    iconHeight: 20,
    labelHeight: 1,
    labelWidth: 1,
    width: 29,
  });
  expect(printMapContract.horizontalCenterDifference).toBeLessThanOrEqual(1);
  expect(printMapContract.verticalGap).toBeCloseTo(10, 0);

  expect(downloadBox.width).toBeCloseTo(resetBox.width, 1);
  expect(resetBox.width).toBeCloseTo(actionContentWidth, 1);
  expect(downloadBox.width).toBeCloseTo(actionContentWidth, 1);

  await downloadButton.click();
  const downloadDialog = page.getByRole("dialog", { name: "Download Data" });
  await expect(downloadDialog).toBeVisible();
  const mobileDialogBox = await downloadDialog.boundingBox();
  expect(mobileDialogBox).not.toBeNull();
  if (mobileDialogBox) {
    expect(mobileDialogBox.x).toBeGreaterThanOrEqual(16);
    expect(mobileDialogBox.x + mobileDialogBox.width).toBeLessThanOrEqual(
      viewport.width - 16,
    );
    expect(mobileDialogBox.height).toBeLessThanOrEqual(viewport.height - 32);
  }
  const optionRows = await downloadDialog
    .locator(".civic-dashboard-download__toggle")
    .evaluateAll((toggles) =>
      toggles.map((toggle) =>
        Array.from(toggle.children)
          .filter((child) => child instanceof HTMLLabelElement)
          .map((label) => {
            const { height, top, width } = label.getBoundingClientRect();
            return { height, top, width };
          }),
      ),
    );
  for (const [firstOption, secondOption] of optionRows) {
    expect(firstOption?.top).toBeCloseTo(secondOption?.top ?? -1, 1);
    expect(firstOption?.height).toBeCloseTo(secondOption?.height ?? -1, 1);
    expect(firstOption?.width).toBeCloseTo(secondOption?.width ?? -1, 1);
  }

  const submit = downloadDialog.locator(
    ".civic-dashboard-download__submit",
  );
  const geoJsonSubmitBox = await submit.boundingBox();
  expect(geoJsonSubmitBox).not.toBeNull();
  expect(
    await submit.evaluate((element) => getComputedStyle(element).whiteSpace),
  ).toBe("nowrap");
  await downloadDialog.locator('label[for="dashboard-download-csv"]').click();
  await expect(submit).toHaveText("Download CSV");
  const csvSubmitBox = await submit.boundingBox();
  expect(csvSubmitBox).not.toBeNull();
  expect(csvSubmitBox?.width).toBeCloseTo(geoJsonSubmitBox?.width ?? 0, 1);
  expect(csvSubmitBox?.height).toBeCloseTo(geoJsonSubmitBox?.height ?? 0, 1);

  await downloadDialog.getByRole("button", { name: "Cancel" }).click();
  await expect(downloadDialog).not.toBeVisible();

  const dayOfWeekPanel = sidebar
    .locator("details.civic-disclosure-panel")
    .nth(2);
  await dayOfWeekPanel.locator("summary").click();
  const dayRowGeometry = await dayOfWeekPanel
    .locator(".civic-dashboard-checkbox-filter__list li")
    .evaluateAll((rows) =>
      rows.map((row) => {
        const rowRect = row.getBoundingClientRect();
        const checkboxRect = row
          .querySelector(".usa-checkbox")!
          .getBoundingClientRect();
        const labelRect = row
          .querySelector(".usa-checkbox__label")!
          .getBoundingClientRect();
        return {
          checkboxLeft: checkboxRect.left,
          checkboxRight: checkboxRect.right,
          labelRight: labelRect.right,
          rowClientWidth: row.clientWidth,
          rowLeft: rowRect.left,
          rowRight: rowRect.right,
          rowScrollWidth: row.scrollWidth,
        };
      }),
    );
  expect(dayRowGeometry.length).toBeGreaterThan(0);
  for (const row of dayRowGeometry) {
    expect(row.rowScrollWidth).toBeLessThanOrEqual(row.rowClientWidth + 1);
    expect(row.checkboxLeft).toBeGreaterThanOrEqual(row.rowLeft - 0.5);
    expect(row.checkboxRight).toBeLessThanOrEqual(row.rowRight + 0.5);
    expect(row.labelRight).toBeLessThanOrEqual(row.rowRight + 0.5);
  }

  expect(categoryBoxes.length).toBeGreaterThan(1);
  for (let index = 1; index < categoryBoxes.length; index += 1) {
    expect(categoryBoxes[index].left).toBeCloseTo(categoryBoxes[0].left, 0);
    expect(categoryBoxes[index].right).toBeCloseTo(categoryBoxes[0].right, 0);
    expect(categoryBoxes[index].top).toBeGreaterThanOrEqual(
      categoryBoxes[index - 1].bottom,
    );
  }

  const categoryTitleStyle = await categoryCards
    .first()
    .locator("figcaption")
    .evaluate((element) => {
      const style = getComputedStyle(element);
      const rootFontSize = Number.parseFloat(
        getComputedStyle(document.documentElement).fontSize,
      );
      return {
        fontSizeInRem: Number.parseFloat(style.fontSize) / rootFontSize,
        marginTop: Number.parseFloat(style.marginTop),
      };
    });
  expect(categoryTitleStyle.fontSizeInRem).toBeCloseTo(1.3, 1);
  expect(categoryTitleStyle.marginTop).toBeCloseTo(16, 0);

  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
  ).toBe(false);
  expect(
    await page.locator(".civic-site-footer__inner").evaluate((element) =>
      getComputedStyle(element).textAlign,
    ),
  ).toBe("center");
  await expect(
    page.locator(".v-application, .v-overlay-container, .v-dialog, .v-btn, .v-select"),
  ).toHaveCount(0);
});
