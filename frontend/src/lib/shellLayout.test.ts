import { describe, expect, it } from "vitest";
import { SHARED_CONTENT_COLUMN } from "./shellLayout";

/**
 * Contract source: docs/FRONTEND_UI_SPEC.md, Section 1, "Shared content column".
 */
describe("shellLayout.SHARED_CONTENT_COLUMN", () => {
  it("caps the column at 48rem without ever overflowing its parent", () => {
    expect(SHARED_CONTENT_COLUMN).toContain("w-[min(100%,48rem)]");
  });

  it("centres the column", () => {
    expect(SHARED_CONTENT_COLUMN).toContain("mx-auto");
  });

  it("applies the small-viewport gutter clamp", () => {
    expect(SHARED_CONTENT_COLUMN).toContain("px-[clamp(0.75rem,2.5vw,1rem)]");
  });

  it("applies the large-viewport gutter clamp at the lg breakpoint", () => {
    expect(SHARED_CONTENT_COLUMN).toContain(
      "lg:px-[clamp(1rem,2.5vw,1.5rem)]",
    );
  });

  it("switches the gutter at lg (1024px) and never at md", () => {
    // md (768px) owns the sidebar/drawer switch; lg (1024px) owns the gutter switch.
    expect(SHARED_CONTENT_COLUMN).not.toContain("md:px-");
  });
});
