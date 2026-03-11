import { test, expect } from "@playwright/test";

test.describe("Dashboard E2E", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("page loads with correct title", async ({ page }) => {
    await expect(page).toHaveTitle(
      "Autoresearch Dashboard - Polymarket Calibration"
    );
  });

  test("header is visible", async ({ page }) => {
    await expect(page.locator("header")).toBeVisible();
    await expect(page.locator("header")).toContainText(
      "Autoresearch Dashboard"
    );
    await expect(page.locator("header")).toContainText("180K markets");
  });

  test("hero metrics section shows 4 stat cards", async ({ page }) => {
    // Composite Score
    await expect(page.getByRole("paragraph").filter({ hasText: /^Composite Score$/ })).toBeVisible();
    await expect(page.getByText("0.8018", { exact: false }).first()).toBeVisible();

    // ROI
    await expect(page.getByText("ROI", { exact: true })).toBeVisible();
    await expect(page.getByText("+24.0%")).toBeVisible();

    // PnL
    await expect(page.getByText("PnL", { exact: true })).toBeVisible();
    await expect(page.getByText("$387,809", { exact: false })).toBeVisible();

    // Win Rate card
    await expect(page.getByRole("paragraph").filter({ hasText: /^Win Rate$/ })).toBeVisible();
    await expect(page.getByText("94.7%")).toBeVisible();
  });

  test("hero metrics composite dropdown changes value", async ({ page }) => {
    // Default shows validation composite
    await expect(page.getByText("0.8018", { exact: false }).first()).toBeVisible();

    // Select crypto category
    const compositeDropdown = page.locator("select").first();
    await compositeDropdown.selectOption("crypto");
    await expect(page.getByText("0.8292", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("crypto best", { exact: false })).toBeVisible();
  });

  test("all sections are present", async ({ page }) => {
    const sections = [
      "Validation Results",
      "Methodology",
      "Learning Timeline",
      "Experiment Log",
      "Category Breakdown",
      "Composite Score Formula",
      "Calibration Curve",
      "Bucket Performance",
      "Strategy Logic",
    ];
    for (const section of sections) {
      await expect(page.getByText(section, { exact: false }).first()).toBeVisible();
    }
  });

  test("methodology section shows data pipeline", async ({ page }) => {
    await expect(page.getByText("180,607")).toBeVisible();
    await expect(page.getByText("Late-Stage VWAP", { exact: true })).toBeVisible();
    await expect(page.locator("p").filter({ hasText: /^Train$/ }).first()).toBeVisible();
  });

  test("learning timeline shows reading guide", async ({ page }) => {
    await expect(
      page.getByText("Reading this chart", { exact: false })
    ).toBeVisible();
  });

  test("experiment log table renders rows and filters work", async ({ page }) => {
    // Should show the experiment table with rows
    const table = page.locator("table").nth(0);
    await expect(table).toBeVisible();

    // Check baseline rows are present
    await expect(page.getByText("baseline").first()).toBeVisible();

    // Check experiment count reflects filtered data (no "other")
    await expect(page.getByText(/of 49 experiments/)).toBeVisible();

    // Filter to "Keep" only
    const statusSelect = page.locator("section").filter({ hasText: "Experiment Log" }).locator("select").nth(1);
    await statusSelect.selectOption("keep");
    const discardBadges = page.getByText("discard", { exact: true });
    await expect(discardBadges).toHaveCount(0);
  });

  test("category breakdown shows params table without OwnTable", async ({
    page,
  }) => {
    // Scroll to the section
    const heading = page.getByRole("heading", { name: "Optimized Parameters" });
    await heading.scrollIntoViewIfNeeded();
    await expect(heading).toBeVisible();
    await expect(page.getByText("Buckets").first()).toBeVisible();
    await expect(page.getByText("MinEdge").first()).toBeVisible();

    // OwnTable column should NOT exist
    const ownTableHeaders = page.getByText("OwnTable");
    await expect(ownTableHeaders).toHaveCount(0);

    // Category badges should be visible in the table
    await expect(page.locator("span").filter({ hasText: /^crypto$/ }).first()).toBeVisible();
    await expect(page.locator("span").filter({ hasText: /^politics$/ }).first()).toBeVisible();
  });

  test("composite score explainer shows formula", async ({ page }) => {
    await expect(
      page.getByText("0.30 x (1 - Brier)", { exact: false })
    ).toBeVisible();
    await expect(page.getByText("Brier Score").first()).toBeVisible();
    await expect(page.getByText("ROI Normalization").first()).toBeVisible();
    await expect(page.getByText("Bet Rate").first()).toBeVisible();
  });

  test("calibration curve section shows insight text", async ({ page }) => {
    await expect(
      page.getByText("Massive S-shaped Mispricing", { exact: false })
    ).toBeVisible();
    await expect(
      page.getByText("exploitable mispricing", { exact: false })
    ).toBeVisible();
  });

  test("bucket performance table with category selector", async ({ page }) => {
    // Scroll to bucket performance section
    const section = page.getByText("Bucket Performance").first();
    await section.scrollIntoViewIfNeeded();

    // Table should have bucket rows
    await expect(page.getByText("[0-10%)").first()).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Implied Prob" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Edge", exact: true })).toBeVisible();

    // Select dropdown should exist (even if option text is hidden)
    const selector = page.locator("section").filter({ hasText: "Bucket Performance" }).locator("select");
    await expect(selector).toBeVisible();
  });

  test("strategy code section shows 3 tabs", async ({ page }) => {
    const section = page.getByText("Strategy Logic").first();
    await section.scrollIntoViewIfNeeded();

    // Check the 3 tab buttons
    await expect(page.getByRole("button", { name: "strategy.py" })).toBeVisible();
    await expect(page.getByRole("button", { name: "h2_calibration.py" })).toBeVisible();
    await expect(page.getByRole("button", { name: "learning_loop.py" })).toBeVisible();

    // Check default tab content
    await expect(
      page.getByText("classify_category(question)", { exact: false }).first()
    ).toBeVisible();

    // Tunable parameters table
    await expect(
      page.getByRole("heading", { name: /Tunable Parameters/ })
    ).toBeVisible();
    await expect(page.getByText("num_buckets").first()).toBeVisible();
    await expect(page.getByText("min_edge").first()).toBeVisible();
  });

  test("static data files are served", async ({ page }) => {
    const resultsResp = await page.request.get("/data/results.json");
    expect(resultsResp.ok()).toBe(true);
    const results = await resultsResp.json();
    expect(results).toHaveLength(49);

    const learningResp = await page.request.get("/data/learning.json");
    expect(learningResp.ok()).toBe(true);
    const learning = await learningResp.json();
    expect(learning.total_iterations).toBe(50);
    expect(learning.validation.composite).toBeCloseTo(0.80185, 4);

    const calResp = await page.request.get("/data/calibration.json");
    expect(calResp.ok()).toBe(true);
    const cal = await calResp.json();
    expect(cal.total_markets).toBe(180607);
    expect(cal.buckets).toHaveLength(10);
    expect(cal.methodology).toBeDefined();
    expect(cal.methodology.window_blocks).toBe(5000);
  });

  test("page is scrollable and all sections reachable", async ({ page }) => {
    const strategyHeading = page.getByText("Strategy Logic").first();
    await strategyHeading.scrollIntoViewIfNeeded();
    await expect(strategyHeading).toBeInViewport();
  });
});
