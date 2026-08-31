import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Sidebar } from "./Sidebar";

/**
 * Contract source: docs/FRONTEND_UI_SPEC.md, Section 1.
 *
 * These assertions are structural: they pin the shell contract without pulling
 * in a DOM testing library, so the suite needs no dependencies beyond `vitest`
 * and the already-installed `react-dom/server`.
 */
const render = (open: boolean) =>
  renderToStaticMarkup(<Sidebar open={open} onClose={() => {}} />);

describe("Sidebar shell contract", () => {
  it("keeps the fluid desktop width (no px width, no resize handle)", () => {
    const html = render(true);
    expect(html).toContain("w-[clamp(14rem,18vw,18rem)]");
    expect(html).toContain("shrink-0");
    expect(html).not.toContain('role="separator"');
    expect(html).not.toContain("cursor-col-resize");
  });

  it("docks from md (768px) up and draws as an off-canvas panel below md", () => {
    const html = render(true);
    expect(html).toContain("max-md:fixed");
    expect(html).toContain("max-md:w-[min(85vw,20rem)]");
    // 1024px is only the content-column gutter breakpoint - never the drawer's.
    expect(html).not.toContain("max-lg:fixed");
  });

  it("removes the closed drawer from the tab order", () => {
    const html = render(false);
    expect(html).toContain("max-md:invisible");
    expect(html).toContain("max-md:-translate-x-full");
    // "max-md:invisible" must not be satisfied by the open-state class.
    expect(html).not.toContain("max-md:visible");
  });

  it("makes the open drawer visible and reachable", () => {
    const html = render(true);
    expect(html).toContain("max-md:visible");
    expect(html).toContain("max-md:translate-x-0");
  });

  it("keeps the slide animation but suppresses it under reduced motion", () => {
    const html = render(true);
    expect(html).toContain("max-md:transition-[transform,visibility]");
    expect(html).toContain("motion-reduce:transition-none");
  });

  it("gives interactive controls a 44x44px touch target below md", () => {
    const html = render(true);
    expect(html).toContain("max-md:h-11");
    expect(html).toContain("max-md:w-11");
  });

  it("renders a non-tabbable backdrop only while the drawer is open", () => {
    expect(render(true)).toContain('aria-hidden="true"');
    expect(render(false)).not.toContain("bg-foreground/50");
  });

  it("exposes the aside id the header menu button controls", () => {
    expect(render(true)).toContain('id="app-sidebar"');
  });
});
